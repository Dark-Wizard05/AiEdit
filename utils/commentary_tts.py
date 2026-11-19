"""Text-to-speech rendering for commentary lines.

Default backend is ``edge-tts`` (no API key, requires internet). If the
package or the network is unavailable, falls back to a silent placeholder
audio file so the rest of the pipeline still produces a valid MP4.

Public entry point::

    render_lines_to_audio(lines, out_dir, voice="en-US-AndrewNeural", rate="+0%")

Returns ``[{"start": float, "text": str, "path": str, "duration": float}, ...]``.
The ``path`` is always populated with a file ffmpeg can read — silent WAV is
used when TTS is not available.
"""

from __future__ import annotations

import asyncio
import logging
import math
import struct
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

try:
    from logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


def _estimate_duration_from_text(text: str) -> float:
    words = max(1, len(text.split()))
    return max(1.5, words / 2.7)  # ~165 wpm


def _write_silence_wav(path: Path, duration_sec: float, sample_rate: int = 24000) -> None:
    n_frames = max(1, int(duration_sec * sample_rate))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack("<h", 0) * n_frames)


def _probe_audio_duration(path: Path) -> Optional[float]:
    """Best-effort duration probe via ffprobe; ``None`` if it can't be read."""

    try:
        from utils.atmosphere_overlay import _ffprobe_exe
    except Exception:
        return None

    import subprocess

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
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return float(r.stdout.strip()) if r.stdout.strip() else None
    except Exception as exc:  # noqa: BLE001
        logger.info("ffprobe duration failed for %s: %s", path, exc)
        return None


async def _edge_tts_save(text: str, voice: str, rate: str, out_path: Path) -> None:
    import edge_tts  # type: ignore

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    await communicate.save(str(out_path))


def _render_one(text: str, voice: str, rate: str, out_path: Path) -> bool:
    try:
        asyncio.run(_edge_tts_save(text=text, voice=voice, rate=rate, out_path=out_path))
        return out_path.exists() and out_path.stat().st_size > 256
    except Exception as exc:  # noqa: BLE001 - TTS is best-effort
        logger.warning("edge-tts failed for line '%s...': %s", (text or "")[:24], exc)
        return False


def render_lines_to_audio(
    lines: Sequence[Dict[str, Any]],
    out_dir: Path,
    *,
    voice: str = "en-US-AndrewNeural",
    rate: str = "+0%",
    progress: Optional[Callable[[str, float, str], None]] = None,
) -> List[Dict[str, Any]]:
    """Render each line to its own audio file. Returns the enriched line list."""

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rendered: List[Dict[str, Any]] = []
    n = max(1, len(lines))
    for idx, ln in enumerate(lines):
        text = str(ln.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(ln.get("start") or 0.0)
        except (TypeError, ValueError):
            start = 0.0

        mp3_path = out_dir / f"line_{idx:03d}.mp3"
        ok = _render_one(text=text, voice=voice, rate=rate, out_path=mp3_path)
        audio_path: Path
        duration: float
        if ok:
            audio_path = mp3_path
            duration = _probe_audio_duration(mp3_path) or _estimate_duration_from_text(text)
        else:
            wav_path = out_dir / f"line_{idx:03d}.wav"
            duration = _estimate_duration_from_text(text)
            _write_silence_wav(wav_path, duration_sec=duration)
            audio_path = wav_path

        rendered.append(
            {
                "start": round(max(0.0, start), 2),
                "text": text,
                "path": str(audio_path),
                "duration": round(float(duration), 2),
            }
        )

        if progress:
            progress(
                "Voicing commentary",
                0.70 + 0.18 * (idx + 1) / n,
                f"Voice line {idx + 1}/{len(lines)}",
            )

    rendered.sort(key=lambda r: r["start"])
    return rendered


SUGGESTED_VOICES = [
    "en-US-AndrewNeural",
    "en-US-GuyNeural",
    "en-US-AriaNeural",
    "en-US-JennyNeural",
    "en-GB-RyanNeural",
    "en-AU-WilliamNeural",
]
