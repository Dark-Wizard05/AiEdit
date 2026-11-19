"""Expressive TTS — sports commentator delivery with emotion-driven prosody."""

from __future__ import annotations

import asyncio
import logging
import re
import struct
import wave
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    from logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)

ProgressFn = Optional[Callable[[str, float, str], None]]

# Aggressive prosody — neural voices respond well to rate/pitch/volume swings.
_EMOTION_PARAMS = {
    "hype": {"rate": "+38%", "pitch": "+12Hz", "volume": "+22%"},
    "dry": {"rate": "-8%", "pitch": "-2Hz", "volume": "+0%"},
    "neutral": {"rate": "+12%", "pitch": "+4Hz", "volume": "+8%"},
}

_VOICE_BY_EMOTION = {
    "hype": "en-US-GuyNeural",
    "dry": "en-US-AndrewNeural",
    "neutral": "en-US-GuyNeural",
}

_TONE_RATE_BOOST = {
    "hype": "+8%",
    "roast": "+5%",
    "dry": "+0%",
}

_STOPWORDS = frozenset(
    "a an the and or but in on at to for of is are was were with that this it".split()
)


def _estimate_duration_from_text(text: str) -> float:
    words = max(1, len(text.split()))
    return max(1.2, words / 2.4)


def _write_silence_wav(path: Path, duration_sec: float, sample_rate: int = 24000) -> None:
    n_frames = max(1, int(duration_sec * sample_rate))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(struct.pack("<h", 0) * n_frames)


def _probe_audio_duration(path: Path) -> Optional[float]:
    try:
        from utils.atmosphere_overlay import _ffprobe_exe
        import subprocess

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
    except Exception:
        return None


def _pick_stress_word(text: str) -> Optional[str]:
    words = re.findall(r"[A-Za-z']{4,}", text)
    candidates = [w for w in words if w.lower() not in _STOPWORDS]
    if not candidates:
        return None
    return max(candidates, key=len)


def style_commentary_text(text: str, emotion: str, tone: str = "hype") -> str:
    """Light touch-up so Edge TTS reads with broadcaster energy."""

    t = text.strip()
    if not t:
        return t

    if emotion == "hype" or tone in {"hype", "roast"}:
        if not t.endswith(("!", "?", "!!")):
            t = t.rstrip(".") + "!"
        stress = _pick_stress_word(t)
        if stress and stress.upper() not in t and len(t) < 120:
            t = t.replace(stress, stress.upper(), 1)
        if emotion == "hype" and not t.upper().startswith(("OH", "BOOM", "AND", "STOP", "WAIT")):
            if "!" in t and len(t) > 20:
                parts = t.split("!", 1)
                t = parts[0].strip() + "!" + parts[1]

    if emotion == "dry":
        if t.endswith("!!"):
            t = t[:-1]

    return t


def _combine_rate(base: str, extra: str) -> str:
    if not extra or extra == "+0%":
        return base
    try:
        base_val = int(base.replace("%", "").replace("+", ""))
        extra_val = int(extra.replace("%", "").replace("+", ""))
        return f"+{base_val + extra_val}%"
    except ValueError:
        return base


def _emotion_params(emotion: str, tone: str, base_voice: str) -> Dict[str, str]:
    key = str(emotion or "neutral").lower()
    params = dict(_EMOTION_PARAMS.get(key, _EMOTION_PARAMS["neutral"]))
    params["rate"] = _combine_rate(params["rate"], _TONE_RATE_BOOST.get(tone, "+0%"))
    voice = base_voice
    if base_voice in {"en-US-AndrewNeural", "en-US-GuyNeural"}:
        voice = _VOICE_BY_EMOTION.get(key, base_voice)
    params["voice"] = voice
    return params


async def _edge_stream_save(
    text: str,
    voice: str,
    rate: str,
    pitch: str,
    volume: str,
    out_path: Path,
) -> List[Dict[str, Any]]:
    import edge_tts  # type: ignore

    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
        volume=volume,
    )
    boundaries: List[Dict[str, Any]] = []
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                boundaries.append(
                    {
                        "text": str(chunk.get("text") or ""),
                        "offset_ms": float(chunk.get("offset") or 0) / 10000.0,
                        "duration_ms": float(chunk.get("duration") or 0) / 10000.0,
                    }
                )
    return boundaries


def render_line_tts(
    line: Dict[str, Any],
    out_path: Path,
    *,
    voice: str,
    tone: str = "hype",
) -> Tuple[Path, float, List[Dict[str, Any]], str]:
    raw_text = str(line.get("text") or "").strip()
    emotion = str(line.get("emotion") or "neutral")
    spoken_text = style_commentary_text(raw_text, emotion, tone=tone)
    params = _emotion_params(emotion, tone, voice)
    use_voice = params.pop("voice", voice)
    mp3_path = out_path.with_suffix(".mp3")

    try:
        boundaries = asyncio.run(
            _edge_stream_save(
                text=spoken_text,
                voice=use_voice,
                rate=params["rate"],
                pitch=params["pitch"],
                volume=params["volume"],
                out_path=mp3_path,
            )
        )
        if mp3_path.exists() and mp3_path.stat().st_size > 256:
            duration = _probe_audio_duration(mp3_path) or _estimate_duration_from_text(spoken_text)
            return mp3_path, duration, boundaries, spoken_text
    except Exception as exc:  # noqa: BLE001
        logger.warning("edge-tts failed: %s", exc)

    wav_path = out_path.with_suffix(".wav")
    duration = _estimate_duration_from_text(spoken_text)
    _write_silence_wav(wav_path, duration)
    words = spoken_text.split()
    boundaries = []
    if words:
        per_word = (duration * 1000.0) / len(words)
        for i, w in enumerate(words):
            boundaries.append(
                {"text": w, "offset_ms": i * per_word, "duration_ms": per_word}
            )
    return wav_path, duration, boundaries, spoken_text


def render_tts(
    lines: Sequence[Dict[str, Any]],
    audio_dir: Path,
    *,
    voice: str,
    tone: str = "hype",
    progress: ProgressFn = None,
) -> List[Dict[str, Any]]:
    """Render each scheduled line with commentator-style expressiveness."""

    audio_dir = Path(audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)
    rendered: List[Dict[str, Any]] = []
    n = max(1, len(lines))

    for idx, ln in enumerate(lines):
        text = str(ln.get("text") or "").strip()
        if not text:
            continue
        stem = audio_dir / f"line_{idx:03d}"
        audio_path, duration, boundaries, spoken_text = render_line_tts(
            ln, stem, voice=voice, tone=tone
        )
        out = dict(ln)
        out["path"] = str(audio_path)
        out["audio_duration"] = round(duration, 3)
        out["duration"] = round(duration, 3)
        out["word_boundaries"] = boundaries
        out["spoken_text"] = spoken_text
        rendered.append(out)

        if progress:
            progress(
                "rendering_tts",
                0.55 + 0.15 * (idx + 1) / n,
                f"Voicing line {idx + 1}/{len(lines)} ({ln.get('emotion', 'neutral')})",
            )

    return rendered
