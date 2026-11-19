"""Final mux — mute game audio, burn ASS, mix VO + optional music."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from utils.atmosphere_overlay import _ffmpeg_exe, _ffprobe_exe

try:
    from logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            [
                _ffprobe_exe(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return max(0.1, float(r.stdout.strip()))
    except Exception:
        return 60.0


def _speed_filter(stream_idx: int, idx: int, speed: float) -> tuple[str, str]:
    """Return (filter_fragment, audio_label) for one voice line."""

    speed = max(1.0, min(float(speed), 2.0))
    if speed <= 1.001:
        return "", f"{stream_idx}:a"
    label = f"spd{idx}"
    return f"[{stream_idx}:a]atempo={speed:.3f}[{label}]", label


def mux_export(
    video_in: str,
    audio_lines: Sequence[Dict[str, Any]],
    video_out: str,
    *,
    ass_path: Optional[str] = None,
    music_path: Optional[str] = None,
    music_volume: float = 0.12,
    mute_game_audio: bool = True,
    voice_volume: float = 1.0,
    pad_video_to_voice: bool = True,
) -> bool:
    """Mux commentary export with optional subs burn and background music."""

    inp = Path(video_in)
    if not inp.is_file():
        return False

    valid = [
        ln
        for ln in audio_lines
        if Path(str(ln.get("path") or "")).is_file()
        and float(ln.get("duration") or ln.get("audio_duration") or 0.0) > 0.05
    ]
    if not valid:
        logger.warning("mux_export: no valid audio lines")
        return False

    video_duration = _probe_duration(str(inp))
    last_end = max(
        float(ln.get("start_sec") or ln.get("start") or 0.0)
        + float(ln.get("duration") or ln.get("audio_duration") or 0.0)
        / max(float(ln.get("speed_factor") or 1.0), 1.0)
        for ln in valid
    )
    needs_pad = pad_video_to_voice and video_duration > 0 and last_end > video_duration + 0.05
    export_duration = max(video_duration, last_end) + (0.5 if needs_pad else 0.0)

    inputs: List[str] = ["-i", str(inp)]
    stream_idx = 1
    filters: List[str] = []
    mix_inputs: List[str] = []

    if mute_game_audio:
        filters.append(
            f"anullsrc=channel_layout=stereo:sample_rate=48000:duration={export_duration:.3f}[base]"
        )
    else:
        filters.append(f"[0:a]volume=0.25[base]")
    mix_inputs.append("[base]")

    for idx, ln in enumerate(valid):
        inputs.extend(["-i", str(ln["path"])])
        delay_ms = max(0, int(round(float(ln.get("start_sec") or ln.get("start") or 0.0) * 1000)))
        speed = float(ln.get("speed_factor") or 1.0)
        spd_filter, audio_src = _speed_filter(stream_idx, idx, speed)
        if spd_filter:
            filters.append(spd_filter)
        filters.append(
            f"[{audio_src}]aresample=48000,adelay={delay_ms}|{delay_ms},volume={voice_volume:.3f}[v{idx}]"
        )
        mix_inputs.append(f"[v{idx}]")
        stream_idx += 1

    if music_path and Path(music_path).is_file():
        inputs.extend(["-stream_loop", "-1", "-i", music_path])
        mv = max(0.08, min(0.18, float(music_volume)))
        filters.append(
            f"[{stream_idx}:a]atrim=0:{export_duration:.3f},asetpts=PTS-STARTPTS,"
            f"volume={mv:.3f}[music]"
        )
        mix_inputs.append("[music]")
        stream_idx += 1

    filters.append(
        "".join(mix_inputs)
        + f"amix=inputs={len(mix_inputs)}:duration=longest:dropout_transition=2,"
        + "alimiter=limit=0.95[aout]"
    )

    ass_escaped = ""
    if ass_path and Path(ass_path).is_file():
        ass_escaped = str(Path(ass_path).resolve()).replace("\\", "/").replace(":", "\\:")

    if needs_pad:
        pad_seconds = max(0.0, last_end - video_duration) + 0.5
        if ass_escaped:
            filters.append(
                f"[0:v]tpad=stop_mode=clone:stop_duration={pad_seconds:.3f},ass='{ass_escaped}'[vout]"
            )
        else:
            filters.append(f"[0:v]tpad=stop_mode=clone:stop_duration={pad_seconds:.3f}[vout]")
        v_map = "[vout]"
        v_codec = "libx264"
    elif ass_escaped:
        filters.append(f"[0:v]ass='{ass_escaped}'[vout]")
        v_map = "[vout]"
        v_codec = "libx264"
    else:
        v_map = "0:v"
        v_codec = "copy"

    cmd: List[str] = [_ffmpeg_exe(), "-y", *inputs, "-filter_complex", ";".join(filters)]
    cmd.extend(
        [
            "-map",
            v_map,
            "-map",
            "[aout]",
            "-c:v",
            v_codec,
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
        ]
    )
    if not needs_pad and not ass_escaped:
        cmd.append("-shortest")
    cmd.append(str(video_out))

    logger.info("commentary mux_export cmd: %s", " ".join(cmd[:12]) + " ...")
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=max(300, int(inp.stat().st_size / (512 * 1024)) * 60),
        )
        return Path(video_out).is_file()
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "mux_export failed: %s",
            (exc.stderr or b"").decode(errors="ignore")[:800],
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("mux_export failed: %s", exc)
        return False
