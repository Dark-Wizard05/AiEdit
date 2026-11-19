"""OCR-driven on-screen detail extraction for auto-commentary.

This module converts a sampled set of frames from any video clip into a
timestamped list of events. It uses EasyOCR via the existing ``TextDetectionSAM``
wrapper — no cloud vision API required for the MVP.

Detected moments include scores, action labels, and generic on-screen text
observations. Game-specific patterns (kills, plants, etc.) are recognized when
present but are not required.

Event payload shape (one dict per detected moment)::

    {
        "t": 19.0,                    # seconds from clip start
        "kind": "kill" | "plant" | "round_end" | "score" | "raw_text",
        "text": "Yoda III",          # short label / tag
        "raw": "PLAYER killed Yoda III with AK-47",
        "weapon": "ak-47" | None,
        "victim": "yoda iii" | None,
        "killer": "dark wizard" | None,
        "confidence": 0.78,
    }

The detection rules are intentionally lightweight: a small lexicon plus a
few regex shapes. The goal is "good enough to drive a script", not perfect
match parsing — anything subtler should plug into a real game-replay parser.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    from logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


WEAPONS = {
    "ak-47", "ak47", "m4a4", "m4a1", "m4a1-s", "awp", "deagle", "desert eagle",
    "glock", "usp", "usp-s", "p250", "tec-9", "five-seven", "cz75", "mac-10",
    "mp9", "mp7", "mp5", "ump-45", "p90", "bizon", "famas", "galil", "aug",
    "sg 553", "ssg 08", "g3sg1", "scar-20", "negev", "m249", "nova",
    "xm1014", "mag-7", "sawed-off", "knife", "grenade", "he", "smoke",
    "molotov", "incendiary", "flash", "decoy", "zeus", "taser",
}

KILL_HINTS = ("killed", "eliminated", "headshot", "ace", "double kill", "triple kill")
PLANT_HINTS = ("planted the bomb", "bomb planted", "planted", "c4 planted")
DEFUSE_HINTS = ("defused", "bomb defused")
ROUND_END_HINTS = ("round won", "round over", "victory", "defeat", "match point", "mvp")
SCORE_HINT_RE = re.compile(r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b")
SCORE_CONTEXT = ("score", "round", "match", "vs", "halftime", "period")


def _is_noise(text: str) -> bool:
    t = _norm(text)
    if len(t) < 4:
        return True
    if re.fullmatch(r"[\W\d_]+", t):
        return True
    return False



def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _frame_index_to_time(frame_index: int, sample_fps: float) -> float:
    if sample_fps <= 1e-6:
        return float(frame_index)
    return float(frame_index) / float(sample_fps)


def _detect_weapon(text_lc: str) -> Optional[str]:
    for w in WEAPONS:
        if w in text_lc:
            return w
    return None


def _detect_kill(text_lc: str) -> Optional[Tuple[Optional[str], Optional[str], Optional[str]]]:
    """Return ``(killer, victim, weapon)`` if ``text_lc`` looks like a kill row."""

    if not any(h in text_lc for h in KILL_HINTS):
        return None

    weapon = _detect_weapon(text_lc)

    m = re.search(r"^(?P<killer>[a-z0-9_\-\. ]{2,24})\s+(?:killed|eliminated|headshot)\s+(?P<victim>[a-z0-9_\-\. ]{2,24})", text_lc)
    if m:
        return (m.group("killer").strip(), m.group("victim").strip(), weapon)

    m = re.search(r"\b(?:killed|eliminated|headshot)\s+(?P<victim>[a-z0-9_\-\. ]{2,24})", text_lc)
    if m:
        return (None, m.group("victim").strip(), weapon)

    return (None, None, weapon)


def _classify_line(text: str) -> Optional[Dict[str, Any]]:
    text_lc = _norm(text)
    if not text_lc:
        return None

    kill = _detect_kill(text_lc)
    if kill is not None:
        killer, victim, weapon = kill
        return {
            "kind": "kill",
            "text": victim or weapon or text_lc[:32],
            "raw": text,
            "killer": killer,
            "victim": victim,
            "weapon": weapon,
        }

    if any(h in text_lc for h in PLANT_HINTS):
        return {"kind": "plant", "text": "bomb planted", "raw": text}
    if any(h in text_lc for h in DEFUSE_HINTS):
        return {"kind": "defuse", "text": "bomb defused", "raw": text}
    if any(h in text_lc for h in ROUND_END_HINTS):
        return {"kind": "round_end", "text": text_lc[:48], "raw": text}

    score = SCORE_HINT_RE.search(text_lc)
    if score:
        has_context = any(c in text_lc for c in SCORE_CONTEXT)
        a, b = int(score.group(1)), int(score.group(2))
        plausible = a <= 30 and b <= 30
        if has_context or plausible:
            return {
                "kind": "score",
                "text": f"{score.group(1)}-{score.group(2)}",
                "raw": text,
            }

    return None


def _dedupe_close_events(events: List[Dict[str, Any]], min_gap: float = 1.5) -> List[Dict[str, Any]]:
    """Suppress duplicate events of the same kind that fire within ``min_gap`` seconds."""

    out: List[Dict[str, Any]] = []
    last_seen: Dict[Tuple[str, str], float] = {}
    for ev in sorted(events, key=lambda e: float(e.get("t") or 0.0)):
        key = (str(ev.get("kind")), str(ev.get("text")).strip())
        t = float(ev.get("t") or 0.0)
        prev = last_seen.get(key)
        if prev is not None and t - prev < min_gap:
            continue
        last_seen[key] = t
        out.append(ev)
    return out


def detect_events_from_frames(
    frame_files: Sequence[Path],
    *,
    sample_fps: float,
    device: str = "cpu",
    progress: Optional[Callable[[str, float, str], None]] = None,
    max_frames: Optional[int] = None,
    confidence_floor: float = 0.45,
) -> List[Dict[str, Any]]:
    """Run OCR on each frame and emit timestamped events.

    ``sample_fps`` is the rate at which ``frame_files`` were sampled from the
    source video (so frame index ``i`` maps to ``i / sample_fps`` seconds).
    """

    from utils.text_detection_sam import TextDetectionSAM

    if not frame_files:
        return []

    files = list(frame_files)
    if max_frames is not None:
        files = files[: int(max_frames)]

    detector = TextDetectionSAM(device=device)

    raw_events: List[Dict[str, Any]] = []
    last_score_value: Optional[str] = None
    n = len(files)
    for idx, fp in enumerate(files):
        try:
            import cv2

            img = cv2.imread(str(fp))
            if img is None:
                continue
            detections = detector.detect_text_regions(img) or []
        except Exception as exc:  # noqa: BLE001 - OCR can fail per-frame; never abort the run
            logger.warning("OCR failed on frame %s: %s", fp, exc)
            detections = []

        t = _frame_index_to_time(idx, sample_fps)
        for det in detections:
            if not isinstance(det, dict):
                continue
            conf = float(det.get("confidence") or 0.0)
            if conf < confidence_floor:
                continue
            text = str(det.get("text") or "").strip()
            if not text:
                continue
            classified = _classify_line(text)
            if classified is None:
                if len(text) >= 4 and not _is_noise(text):
                    classified = {
                        "kind": "observation",
                        "text": text[:72],
                        "raw": text,
                    }
                else:
                    continue
            if classified.get("kind") == "score":
                score_val = str(classified.get("text") or "")
                if score_val == last_score_value:
                    continue
                last_score_value = score_val
            classified["t"] = round(t, 2)
            classified["confidence"] = conf
            raw_events.append(classified)

        if progress and (idx + 1) % max(1, n // 12) == 0:
            progress(
                "Reading on-screen details",
                0.30 + 0.40 * (idx + 1) / max(n, 1),
                f"OCR frame {idx + 1}/{n} - {len(raw_events)} events",
            )

    deduped = _dedupe_close_events(raw_events, min_gap=1.5)
    logger.info(
        "commentary_events: %s raw -> %s deduped from %s frames",
        len(raw_events),
        len(deduped),
        len(files),
    )
    return deduped
