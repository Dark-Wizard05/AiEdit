"""Turn an event timeline into timed commentary lines.

Two backends:

1. **Templated** (default; zero external deps): hand-written quips per event
   ``kind`` with light tone variation. Good enough for an MVP demo.
2. **LLM** (optional): if ``OPENAI_API_KEY`` / ``OLLAMA_URL`` is configured,
   we re-use the same outbound style as ``utils.prompt_parser`` (HTTP) and
   ask for ``[{"start": float, "text": str}]`` JSON. Falls back to templated
   on any failure so the pipeline is always offline-safe.

Output schema (per line)::

    {"start": 19.0, "text": "Tap! Yoda III is gone — AK-47 from Dark Wizard."}
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from typing import Any, Dict, List, Optional, Sequence

import requests

try:
    from logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Templated backend
# --------------------------------------------------------------------------- #

_TONE_OPENERS = {
    "hype": [
        "Let's go!",
        "Oh that's clean!",
        "Tap! Tap!",
        "Are you kidding me?",
        "Massive!",
    ],
    "dry": [
        "Right.",
        "Well then.",
        "Hm.",
        "Sure, why not.",
        "Of course.",
    ],
    "roast": [
        "And of course,",
        "Predictable.",
        "Don't blink,",
        "What a flex,",
        "Comedy hour,",
    ],
}

_KILL_LINES = [
    "{victim} folds — {weapon} from {killer}.",
    "{killer} clips {victim} clean. {weapon}, no doubt.",
    "{victim} is gone. {weapon} did the talking.",
    "Sharp tap from {killer}. {victim} was never going to make it.",
]
_KILL_LINES_NO_KILLER = [
    "{victim} just got tapped — {weapon}.",
    "{victim} is gone. {weapon}, lights out.",
    "Frag picked up — {victim} folded fast.",
]
_PLANT_LINES = [
    "Bomb is down. Now we play defense.",
    "Plant goes through. Forty seconds on the clock.",
    "C4 is set — let's see who keeps their nerve.",
]
_DEFUSE_LINES = [
    "Defuse! Massive hold from CT.",
    "Wire snipped — the round flips.",
    "Defuse on time. Round saved.",
]
_ROUND_END_LINES = [
    "Round closed out. Onto the next.",
    "And that's the round. Reset and reload.",
    "Closer than the score made it look.",
]
_SCORE_LINES = [
    "Scoreboard now sits at {score}.",
    "{score} on the board — close one.",
    "We're at {score} — momentum shifting.",
]


def _pick(seq: Sequence[str], rng: random.Random) -> str:
    return seq[rng.randrange(len(seq))]


def _format_kill(ev: Dict[str, Any], rng: random.Random) -> str:
    victim = (ev.get("victim") or "they").strip().title() or "they"
    killer = (ev.get("killer") or "").strip().title()
    weapon = (ev.get("weapon") or "rifle").strip().upper()
    if killer:
        return _pick(_KILL_LINES, rng).format(victim=victim, weapon=weapon, killer=killer)
    return _pick(_KILL_LINES_NO_KILLER, rng).format(victim=victim, weapon=weapon)


def _intro_line(player_name: Optional[str], tone: str, rng: random.Random) -> str:
    base = f"Round on. {player_name.title()} on the rifle." if player_name else "Round on."
    flair = {
        "hype": " Lock in.",
        "dry": " Try not to die.",
        "roast": " Try to make me look good.",
    }.get(tone, "")
    return base + flair


def _outro_line(tone: str, rng: random.Random) -> str:
    if tone == "hype":
        return "Massive round. That's the highlight reel."
    if tone == "roast":
        return "Don't worry, we'll edit out the bad bits."
    return "And that's a clip."


def _line_for(event: Dict[str, Any], tone: str, rng: random.Random) -> Optional[str]:
    kind = str(event.get("kind") or "").lower()
    opener = _pick(_TONE_OPENERS.get(tone, _TONE_OPENERS["hype"]), rng)

    if kind == "kill":
        return f"{opener} {_format_kill(event, rng)}"
    if kind == "plant":
        return f"{opener} {_pick(_PLANT_LINES, rng)}"
    if kind == "defuse":
        return f"{opener} {_pick(_DEFUSE_LINES, rng)}"
    if kind == "round_end":
        return f"{opener} {_pick(_ROUND_END_LINES, rng)}"
    if kind == "score":
        return _pick(_SCORE_LINES, rng).format(score=event.get("text") or "neck-and-neck")
    return None


def _build_templated_lines(
    events: Sequence[Dict[str, Any]],
    *,
    duration: float,
    player_name: Optional[str],
    tone: str,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    lines: List[Dict[str, Any]] = []

    if duration > 1.0:
        lines.append({"start": 0.0, "text": _intro_line(player_name, tone, rng)})

    for ev in events:
        try:
            t = float(ev.get("t") or 0.0)
        except (TypeError, ValueError):
            continue
        text = _line_for(ev, tone, rng)
        if text:
            lines.append({"start": round(max(0.5, t), 2), "text": text})

    if duration > 6.0:
        lines.append({"start": round(max(0.0, duration - 4.0), 2), "text": _outro_line(tone, rng)})

    return _enforce_min_gap(lines, min_gap=2.5, hard_cutoff=duration)


def _enforce_min_gap(
    lines: List[Dict[str, Any]],
    *,
    min_gap: float,
    hard_cutoff: float,
) -> List[Dict[str, Any]]:
    """Push later lines forward so neighbours don't overlap; drop overflow."""

    if not lines:
        return []
    lines = sorted(lines, key=lambda l: float(l.get("start") or 0.0))
    fixed: List[Dict[str, Any]] = []
    last_end = -1.0
    for ln in lines:
        try:
            start = float(ln.get("start") or 0.0)
        except (TypeError, ValueError):
            continue
        if start < last_end + min_gap:
            start = last_end + min_gap
        if hard_cutoff > 0 and start >= hard_cutoff - 0.5:
            break
        fixed.append({"start": round(start, 2), "text": str(ln.get("text") or "").strip()})
        last_end = start + min_gap
    return [ln for ln in fixed if ln["text"]]


# --------------------------------------------------------------------------- #
# Optional LLM backend
# --------------------------------------------------------------------------- #

def _try_llm_lines(
    events: Sequence[Dict[str, Any]],
    *,
    duration: float,
    player_name: Optional[str],
    tone: str,
    timeout_sec: float = 15.0,
) -> Optional[List[Dict[str, Any]]]:
    """Attempt to produce lines via Ollama; return None on any failure."""

    base = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

    prompt = _build_llm_prompt(events, duration=duration, player_name=player_name, tone=tone)

    try:
        resp = requests.post(
            f"{base}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=timeout_sec,
        )
        if not resp.ok:
            return None
        body = resp.json().get("response") or ""
    except Exception as exc:  # noqa: BLE001 - LLM is best-effort
        logger.info("commentary_script LLM call failed: %s", exc)
        return None

    body = body.strip()
    if not body:
        return None

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}|\[.*\]", body, re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    raw_lines = parsed.get("lines") if isinstance(parsed, dict) else parsed
    if not isinstance(raw_lines, list):
        return None

    cleaned: List[Dict[str, Any]] = []
    for ln in raw_lines:
        if not isinstance(ln, dict):
            continue
        try:
            start = float(ln.get("start") or 0.0)
        except (TypeError, ValueError):
            continue
        text = str(ln.get("text") or "").strip()
        if not text:
            continue
        cleaned.append({"start": round(max(0.0, start), 2), "text": text})

    return _enforce_min_gap(cleaned, min_gap=2.5, hard_cutoff=duration) or None


def _build_llm_prompt(
    events: Sequence[Dict[str, Any]],
    *,
    duration: float,
    player_name: Optional[str],
    tone: str,
) -> str:
    summarized = [
        {k: ev.get(k) for k in ("t", "kind", "text", "killer", "victim", "weapon") if ev.get(k) is not None}
        for ev in events
    ]
    return json.dumps(
        {
            "task": "Write timed esports-style commentary for a short gameplay clip.",
            "rules": [
                "Output JSON: {\"lines\": [{\"start\": <seconds>, \"text\": <string>}, ...]}",
                f"Tone: {tone}.",
                "Each line should be ~5-10 words and reference the specific event when possible.",
                "Keep at least 2.5 seconds between line starts; never go past clip duration.",
                "Stay grounded — never invent facts that are not in the event list.",
            ],
            "duration_sec": round(float(duration), 2),
            "player_name": player_name,
            "events": summarized,
        }
    )


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def build_commentary_lines(
    events: Sequence[Dict[str, Any]],
    *,
    duration: float,
    player_name: Optional[str] = None,
    tone: str = "hype",
    seed: int = 42,
    use_llm: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Return ``[{start, text}, ...]`` covering ``duration`` seconds."""

    tone = (tone or "hype").lower()
    if tone not in _TONE_OPENERS:
        tone = "hype"

    duration = max(float(duration or 0.0), 1.0)

    want_llm = bool(use_llm) if use_llm is not None else bool(os.getenv("AIEDIT_COMMENTARY_LLM"))
    if want_llm:
        llm_lines = _try_llm_lines(
            events, duration=duration, player_name=player_name, tone=tone
        )
        if llm_lines:
            logger.info("commentary_script: using LLM lines (%s)", len(llm_lines))
            return llm_lines

    return _build_templated_lines(
        events,
        duration=duration,
        player_name=player_name,
        tone=tone,
        seed=seed,
    )
