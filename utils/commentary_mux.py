"""Mux per-line voice clips on top of a video, with optional duck of source.

Builds a single ffmpeg ``filter_complex`` graph that:

- Optionally lowers the original audio volume (duck) and mixes per-line
  voice clips in via ``adelay`` + ``amix`` + ``alimiter``.
- Optionally pads the video with ``tpad`` (cloning the last frame) when
  the final voice line ends past the source duration so we never cut VO.

When the source has no audio stream we synthesise a silent base via
``anullsrc`` so ``amix`` always has at least two inputs.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Sequence

from utils.atmosphere_overlay import _ffmpeg_exe, _ffprobe_exe, video_has_audio_stream

try:
    from logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


def _probe_video_duration(video_path: str) -> float:
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
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return float(r.stdout.strip()) if r.stdout.strip() else 0.0
    except Exception as exc:  # noqa: BLE001
        logger.info("probe duration failed: %s", exc)
        return 0.0


def mux_commentary_over_video(
    video_in: str,
    audio_lines: Sequence[Dict[str, Any]],
    video_out: str,
    *,
    keep_source_audio: bool = True,
    source_audio_volume: float = 0.25,
    voice_volume: float = 1.0,
    pad_video_to_voice: bool = True,
) -> bool:
    """Render ``video_in`` + commentary lines into ``video_out``."""

    inp = Path(video_in)
    if not inp.exists():
        return False

    valid_lines = [
        ln
        for ln in audio_lines
        if Path(str(ln.get("path") or "")).is_file()
        and float(ln.get("duration") or 0.0) > 0.05
    ]
    if not valid_lines:
        logger.warning("mux_commentary_over_video: no valid audio lines")
        return False

    video_duration = _probe_video_duration(str(inp))
    last_end = max(
        float(ln.get("start") or 0.0) + float(ln.get("duration") or 0.0)
        for ln in valid_lines
    )
    needs_pad = pad_video_to_voice and video_duration > 0.0 and last_end > video_duration + 0.05

    has_src_audio = video_has_audio_stream(str(inp))
    use_src_audio = bool(keep_source_audio and has_src_audio)

    inputs: List[str] = ["-i", str(inp)]
    audio_input_offset = 1
    filters: List[str] = []
    mix_inputs: List[str] = []

    base_duration = max(video_duration, last_end, 1.0)

    if use_src_audio:
        vol = max(0.0, min(2.0, float(source_audio_volume)))
        filters.append(f"[0:a]volume={vol:.3f}[base]")
    else:
        filters.append(
            f"anullsrc=channel_layout=stereo:sample_rate=48000:duration={base_duration:.3f}[base]"
        )
    mix_inputs.append("[base]")

    for idx, ln in enumerate(valid_lines):
        inputs.extend(["-i", str(ln["path"])])
        delay_ms = max(0, int(round(float(ln["start"]) * 1000.0)))
        label = f"v{idx}"
        stream_idx = audio_input_offset + idx
        filters.append(
            f"[{stream_idx}:a]aresample=48000,adelay={delay_ms}|{delay_ms},volume={voice_volume:.3f}[{label}]"
        )
        mix_inputs.append(f"[{label}]")

    filters.append(
        "".join(mix_inputs)
        + f"amix=inputs={len(mix_inputs)}:duration=longest:dropout_transition=2,"
        + "alimiter=limit=0.95[aout]"
    )

    if needs_pad:
        pad_seconds = max(0.0, last_end - video_duration) + 0.5
        filters.append(f"[0:v]tpad=stop_mode=clone:stop_duration={pad_seconds:.3f}[vout]")
        v_map = "[vout]"
    else:
        v_map = "0:v"

    cmd: List[str] = [_ffmpeg_exe(), "-y", *inputs, "-filter_complex", ";".join(filters)]
    cmd.extend(
        [
            "-map",
            v_map,
            "-map",
            "[aout]",
            "-c:v",
            "libx264" if needs_pad else "copy",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
        ]
    )
    if not needs_pad:
        cmd.append("-shortest")
    cmd.append(str(video_out))

    logger.info("commentary mux cmd: %s", " ".join(cmd))
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=max(180, int(inp.stat().st_size / (1024 * 1024)) * 30),
        )
        return Path(video_out).exists()
    except subprocess.CalledProcessError as exc:
        logger.warning(
            "commentary mux failed: returncode=%s stderr=%s",
            exc.returncode,
            (exc.stderr or b"").decode(errors="ignore")[:600],
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("commentary mux failed: %s", exc)
        return False
