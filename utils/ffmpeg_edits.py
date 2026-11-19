"""FFmpeg-based timeline edits for the Normal plan (trim, speed, crop, audio, fades)."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ffmpeg

from utils.time_parse import coerce_time_param

try:
    from logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


def _ffmpeg_cmd() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _ffprobe_cmd() -> str:
    cmd = _ffmpeg_cmd()
    return cmd.replace("ffmpeg", "ffprobe") if "ffmpeg" in cmd.lower() else "ffprobe"


def probe_video(path: str) -> Dict[str, Any]:
    info: Dict[str, Any] = {"duration_sec": None, "width": None, "height": None}
    try:
        out = subprocess.run(
            [
                _ffprobe_cmd(),
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(out.stdout or "{}")
        fmt = payload.get("format") or {}
        if fmt.get("duration"):
            info["duration_sec"] = float(fmt["duration"])
        for stream in payload.get("streams") or []:
            if stream.get("codec_type") == "video":
                info["width"] = stream.get("width")
                info["height"] = stream.get("height")
                break
    except Exception as exc:
        logger.warning("ffprobe failed for %s: %s", path, exc)
    return info


def _has_audio(path: str) -> bool:
    try:
        out = subprocess.run(
            [
                _ffprobe_cmd(),
                "-v",
                "quiet",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=index",
                "-of",
                "csv=p=0",
                path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return bool((out.stdout or "").strip())
    except Exception:
        return False


def _run(output_path: str, *streams, **kwargs) -> None:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    (
        ffmpeg.output(*streams, output_path, **kwargs).run(
            cmd=_ffmpeg_cmd(),
            overwrite_output=True,
            capture_stdout=True,
            capture_stderr=True,
            quiet=True,
        )
    )


def _atempo_chain(factor: float) -> str:
    if factor <= 0:
        return "volume=0"
    filters: List[str] = []
    remaining = factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return ",".join(filters)


def _aspect_crop_size(aspect: str, width: int, height: int) -> Tuple[int, int]:
    mapping = {
        "9:16": (9, 16),
        "16:9": (16, 9),
        "1:1": (1, 1),
        "4:5": (4, 5),
        "4:3": (4, 3),
        "3:4": (3, 4),
    }
    aw, ah = mapping.get(aspect.strip().lower().replace(" ", ""), (16, 9))
    target_ratio = aw / ah
    src_ratio = width / height
    if src_ratio > target_ratio:
        crop_w = int(height * target_ratio)
        crop_h = height
    else:
        crop_w = width
        crop_h = int(width / target_ratio)
    crop_w -= crop_w % 2
    crop_h -= crop_h % 2
    return max(2, crop_w), max(2, crop_h)


def apply_timeline_trim(input_path: str, output_path: str, params: Dict[str, Any]) -> str:
    probe = probe_video(input_path)
    duration = probe.get("duration_sec")

    start = coerce_time_param(params, "start_sec", "start_time", "start") or 0.0
    end = coerce_time_param(params, "end_sec", "end_time", "end")
    if end is None and params.get("duration_sec") is not None:
        end = start + float(params["duration_sec"])
    if end is None and params.get("end_offset_sec") is not None and duration is not None:
        end = max(start, duration - float(params["end_offset_sec"]))
    if end is None and duration is not None:
        end = duration
    if end is None:
        raise ValueError("trim requires end_sec, end_time, or a probeable video duration")
    if end <= start:
        raise ValueError("trim end must be after start")

    inp = ffmpeg.input(input_path, ss=start, to=end)
    kwargs = {"vcodec": "libx264", "pix_fmt": "yuv420p", "movflags": "+faststart"}
    if _has_audio(input_path):
        _run(output_path, inp.video, inp.audio, acodec="aac", **kwargs)
    else:
        _run(output_path, inp.video, **kwargs)
    return str(Path(output_path).resolve())


def apply_speed_change(input_path: str, output_path: str, params: Dict[str, Any]) -> str:
    factor = float(params.get("speed_factor") or params.get("speed") or 1.0)
    if factor <= 0:
        raise ValueError("speed_factor must be positive")

    start = coerce_time_param(params, "start_sec", "start_time", "start")
    end = coerce_time_param(params, "end_sec", "end_time", "end")
    probe = probe_video(input_path)
    duration = probe.get("duration_sec") or 0.0

    if start is None and end is None:
        inp = ffmpeg.input(input_path)
        vfilter = f"setpts=PTS/{factor}"
        if _has_audio(input_path):
            _run(
                output_path,
                inp,
                vcodec="libx264",
                acodec="aac",
                pix_fmt="yuv420p",
                vf=vfilter,
                af=_atempo_chain(factor),
            )
        else:
            _run(output_path, inp.video, vcodec="libx264", pix_fmt="yuv420p", vf=vfilter)
        return str(Path(output_path).resolve())

    seg_start = start or 0.0
    seg_end = end if end is not None else duration
    if seg_end <= seg_start:
        raise ValueError("speed segment end must be after start")

    has_audio = _has_audio(input_path)
    v_filters: List[str] = []
    a_filters: List[str] = []
    n = 0

    if seg_start > 0.01:
        v_filters.append(f"[0:v]trim=0:{seg_start},setpts=PTS-STARTPTS[v{n}]")
        if has_audio:
            a_filters.append(f"[0:a]atrim=0:{seg_start},asetpts=PTS-STARTPTS[a{n}]")
        n += 1

    mid = n
    v_filters.append(
        f"[0:v]trim={seg_start}:{seg_end},setpts=(PTS-STARTPTS)/{factor}[v{mid}]"
    )
    if has_audio:
        a_filters.append(
            f"[0:a]atrim={seg_start}:{seg_end},asetpts=PTS-STARTPTS,{_atempo_chain(factor)}[a{mid}]"
        )
    n += 1

    if duration and seg_end < duration - 0.01:
        v_filters.append(f"[0:v]trim={seg_end},setpts=PTS-STARTPTS[v{n}]")
        if has_audio:
            a_filters.append(f"[0:a]atrim={seg_end},asetpts=PTS-STARTPTS[a{n}]")

    v_labels = [f"[v{i}]" for i in range(len(v_filters))]
    graph_parts = v_filters + a_filters
    if has_audio:
        a_labels = [f"[a{i}]" for i in range(len(a_filters))]
        graph_parts.append(
            f"{''.join(v_labels)}{''.join(a_labels)}concat=n={len(v_filters)}:v=1:a=1[vout][aout]"
        )
        subprocess.run(
            [
                _ffmpeg_cmd(),
                "-y",
                "-i",
                input_path,
                "-filter_complex",
                ";".join(graph_parts),
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    else:
        graph_parts.append(f"{''.join(v_labels)}concat=n={len(v_filters)}:v=1:a=0[vout]")
        subprocess.run(
            [
                _ffmpeg_cmd(),
                "-y",
                "-i",
                input_path,
                "-filter_complex",
                ";".join(graph_parts),
                "-map",
                "[vout]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    return str(Path(output_path).resolve())


def apply_crop_resize(input_path: str, output_path: str, params: Dict[str, Any]) -> str:
    probe = probe_video(input_path)
    width = int(params.get("width") or probe.get("width") or 1920)
    height = int(params.get("height") or probe.get("height") or 1080)
    aspect = (params.get("aspect_ratio") or params.get("aspect") or "").strip()
    if aspect:
        crop_w, crop_h = _aspect_crop_size(aspect, width, height)
    else:
        crop_w, crop_h = width, height

    target_w = int(params.get("output_width") or crop_w)
    target_h = int(params.get("output_height") or crop_h)
    target_w -= target_w % 2
    target_h -= target_h % 2
    vf = f"crop={crop_w}:{crop_h}:(iw-{crop_w})/2:(ih-{crop_h})/2,scale={target_w}:{target_h}"
    inp = ffmpeg.input(input_path)
    if _has_audio(input_path):
        _run(output_path, inp, vcodec="libx264", acodec="aac", pix_fmt="yuv420p", vf=vf)
    else:
        _run(output_path, inp.video, vcodec="libx264", pix_fmt="yuv420p", vf=vf)
    return str(Path(output_path).resolve())


def apply_volume_adjust(input_path: str, output_path: str, params: Dict[str, Any]) -> str:
    mute = bool(params.get("mute") or params.get("mute_audio"))
    factor = 0.0 if mute else float(params.get("volume_factor") or params.get("volume") or 1.0)
    fade_in = float(params.get("audio_fade_in_sec") or 0)
    fade_out = float(params.get("audio_fade_out_sec") or 0)
    duration = probe_video(input_path).get("duration_sec") or 0.0

    inp = ffmpeg.input(input_path)
    if not _has_audio(input_path):
        shutil.copy2(input_path, output_path)
        return str(Path(output_path).resolve())

    parts: List[str] = []
    if factor != 1.0:
        parts.append(f"volume={factor}")
    if fade_in > 0:
        parts.append(f"afade=t=in:st=0:d={fade_in}")
    if fade_out > 0 and duration > fade_out:
        parts.append(f"afade=t=out:st={max(0.0, duration - fade_out)}:d={fade_out}")
    af = ",".join(parts) if parts else "anull"
    _run(output_path, inp, vcodec="copy", acodec="aac", af=af)
    return str(Path(output_path).resolve())


def apply_fade_in_out(input_path: str, output_path: str, params: Dict[str, Any]) -> str:
    fade_in = float(params.get("fade_in_sec") or params.get("video_fade_in_sec") or 0)
    fade_out = float(params.get("fade_out_sec") or params.get("video_fade_out_sec") or 0)
    duration = probe_video(input_path).get("duration_sec") or 0.0
    parts: List[str] = []
    if fade_in > 0:
        parts.append(f"fade=t=in:st=0:d={fade_in}")
    if fade_out > 0 and duration > fade_out:
        parts.append(f"fade=t=out:st={max(0.0, duration - fade_out)}:d={fade_out}")
    if not parts:
        raise ValueError("fade_in_out requires fade_in_sec and/or fade_out_sec")
    vf = ",".join(parts)
    inp = ffmpeg.input(input_path)
    if _has_audio(input_path):
        _run(output_path, inp, vcodec="libx264", acodec="copy", pix_fmt="yuv420p", vf=vf)
    else:
        _run(output_path, inp.video, vcodec="libx264", pix_fmt="yuv420p", vf=vf)
    return str(Path(output_path).resolve())


def apply_rotate_flip(input_path: str, output_path: str, params: Dict[str, Any]) -> str:
    flip = str(params.get("flip") or "").lower()
    rotation = int(params.get("rotation") or params.get("rotation_degrees") or 0)
    vf: Optional[str] = None
    if flip == "horizontal":
        vf = "hflip"
    elif flip == "vertical":
        vf = "vflip"
    elif rotation in {90, -270}:
        vf = "transpose=1"
    elif rotation in {180, -180}:
        vf = "hflip,vflip"
    elif rotation in {270, -90}:
        vf = "transpose=2"
    if not vf:
        raise ValueError("rotate_flip requires rotation (90/180/270) or flip (horizontal/vertical)")

    inp = ffmpeg.input(input_path)
    if _has_audio(input_path):
        _run(output_path, inp, vcodec="libx264", acodec="copy", pix_fmt="yuv420p", vf=vf)
    else:
        _run(output_path, inp.video, vcodec="libx264", pix_fmt="yuv420p", vf=vf)
    return str(Path(output_path).resolve())


def apply_brightness_contrast(input_path: str, output_path: str, params: Dict[str, Any]) -> str:
    preset = str(params.get("preset") or "").lower()
    brightness = params.get("brightness")
    contrast = params.get("contrast")
    saturation = params.get("saturation")
    if preset == "cinematic":
        brightness, contrast, saturation = -0.05, 1.1, 0.85
    elif preset == "vivid":
        brightness, contrast, saturation = 0.05, 1.15, 1.35
    elif preset == "muted":
        brightness, contrast, saturation = 0.0, 0.95, 0.75
    elif preset == "bright":
        brightness, contrast, saturation = 0.12, 1.0, 1.05

    eq: List[str] = []
    if brightness is not None:
        eq.append(f"brightness={float(brightness)}")
    if contrast is not None:
        eq.append(f"contrast={float(contrast)}")
    if saturation is not None:
        eq.append(f"saturation={float(saturation)}")
    if not eq:
        raise ValueError("brightness_contrast requires brightness, contrast, saturation, or preset")

    vf = "eq=" + ":".join(eq)
    inp = ffmpeg.input(input_path)
    if _has_audio(input_path):
        _run(output_path, inp, vcodec="libx264", acodec="copy", pix_fmt="yuv420p", vf=vf)
    else:
        _run(output_path, inp.video, vcodec="libx264", pix_fmt="yuv420p", vf=vf)
    return str(Path(output_path).resolve())


def apply_zoom_segment(input_path: str, output_path: str, params: Dict[str, Any]) -> str:
    zoom = float(params.get("zoom_factor") or params.get("zoom") or 1.5)
    start = coerce_time_param(params, "start_sec", "start_time", "start") or 0.0
    end = coerce_time_param(params, "end_sec", "end_time", "end")
    duration = probe_video(input_path).get("duration_sec") or 0.0
    if end is None:
        end = min(duration, start + 2.0) if duration else start + 2.0

    crop_scale = (
        f"scale=iw*{zoom}:ih*{zoom},"
        f"crop=iw/{zoom}:ih/{zoom}:(iw-iw/{zoom})/2:(ih-ih/{zoom})/2"
    )
    has_audio = _has_audio(input_path)

    if start <= 0.01 and (not duration or end >= duration - 0.01):
        inp = ffmpeg.input(input_path)
        if has_audio:
            _run(output_path, inp, vcodec="libx264", acodec="copy", pix_fmt="yuv420p", vf=crop_scale)
        else:
            _run(output_path, inp.video, vcodec="libx264", pix_fmt="yuv420p", vf=crop_scale)
        return str(Path(output_path).resolve())

    v_filters: List[str] = []
    a_filters: List[str] = []
    n = 0
    if start > 0.01:
        v_filters.append(f"[0:v]trim=0:{start},setpts=PTS-STARTPTS[v{n}]")
        if has_audio:
            a_filters.append(f"[0:a]atrim=0:{start},asetpts=PTS-STARTPTS[a{n}]")
        n += 1

    v_filters.append(
        f"[0:v]trim={start}:{end},setpts=PTS-STARTPTS,{crop_scale},setpts=PTS-STARTPTS[v{n}]"
    )
    if has_audio:
        a_filters.append(f"[0:a]atrim={start}:{end},asetpts=PTS-STARTPTS[a{n}]")
    n += 1

    if duration and end < duration - 0.01:
        v_filters.append(f"[0:v]trim={end},setpts=PTS-STARTPTS[v{n}]")
        if has_audio:
            a_filters.append(f"[0:a]atrim={end},asetpts=PTS-STARTPTS[a{n}]")

    v_labels = [f"[v{i}]" for i in range(len(v_filters))]
    graph = v_filters + a_filters
    if has_audio:
        a_labels = [f"[a{i}]" for i in range(len(a_filters))]
        graph.append(f"{''.join(v_labels)}{''.join(a_labels)}concat=n={len(v_filters)}:v=1:a=1[vout][aout]")
        subprocess.run(
            [
                _ffmpeg_cmd(),
                "-y",
                "-i",
                input_path,
                "-filter_complex",
                ";".join(graph),
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    else:
        graph.append(f"{''.join(v_labels)}concat=n={len(v_filters)}:v=1:a=0[vout]")
        subprocess.run(
            [
                _ffmpeg_cmd(),
                "-y",
                "-i",
                input_path,
                "-filter_complex",
                ";".join(graph),
                "-map",
                "[vout]",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                output_path,
            ],
            check=True,
            capture_output=True,
        )
    return str(Path(output_path).resolve())


def apply_timeline_edit(input_path: str, output_path: str, params: Dict[str, Any]) -> str:
    effects = params.get("effects")
    if not isinstance(effects, list) or not effects:
        built: List[Dict[str, Any]] = []
        if any(k in params for k in ("start_sec", "end_sec", "start_time", "end_time")):
            built.append(
                {
                    "type": "trim",
                    "start_sec": params.get("start_sec"),
                    "end_sec": params.get("end_sec"),
                    "start_time": params.get("start_time"),
                    "end_time": params.get("end_time"),
                }
            )
        if params.get("speed_factor") or params.get("speed"):
            built.append(
                {
                    "type": "speed",
                    "speed_factor": params.get("speed_factor") or params.get("speed"),
                    "start_sec": params.get("speed_start_sec"),
                    "end_sec": params.get("speed_end_sec"),
                }
            )
        if params.get("zoom_factor"):
            built.append(
                {
                    "type": "zoom",
                    "zoom_factor": params.get("zoom_factor"),
                    "start_sec": params.get("zoom_start_sec"),
                    "end_sec": params.get("zoom_end_sec"),
                }
            )
        effects = built

    if not effects:
        raise ValueError("timeline_edit requires effects list or trim/speed/zoom parameters")

    temp_dir = Path(output_path).parent / "_timeline_chain"
    temp_dir.mkdir(parents=True, exist_ok=True)
    current = input_path
    handlers = {
        "trim": apply_timeline_trim,
        "speed": apply_speed_change,
        "zoom": apply_zoom_segment,
        "crop": apply_crop_resize,
        "fade": apply_fade_in_out,
    }

    for idx, effect in enumerate(effects):
        if not isinstance(effect, dict):
            continue
        etype = str(effect.get("type") or "").lower()
        handler = handlers.get(etype)
        if handler is None:
            raise ValueError(f"unknown timeline effect type '{etype}'")
        step_out = str(temp_dir / f"step_{idx:02d}.mp4")
        current = handler(current, step_out, effect)

    shutil.copy2(current, output_path)
    return str(Path(output_path).resolve())


_DISPATCH = {
    "timeline_trim": apply_timeline_trim,
    "speed_change": apply_speed_change,
    "crop_resize": apply_crop_resize,
    "volume_adjust": apply_volume_adjust,
    "fade_in_out": apply_fade_in_out,
    "rotate_flip": apply_rotate_flip,
    "brightness_contrast": apply_brightness_contrast,
    "timeline_edit": apply_timeline_edit,
}


def run_timeline_operation(operation: str, input_path: str, output_path: str, params: Dict[str, Any]) -> str:
    fn = _DISPATCH.get(operation)
    if fn is None:
        raise ValueError(f"unsupported timeline operation '{operation}'")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    result = fn(input_path, output_path, params)
    if not Path(result).is_file():
        raise RuntimeError(f"{operation} did not produce output")
    return result
