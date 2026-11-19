"""CommentaryScriptService — humor-first sports-style lines for any video."""

from __future__ import annotations

import json
import logging
import os
import random
import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import requests

from core.commentary.timeline import extract_timeline_entities, is_score_event, pick_commentary_hook

try:
    from logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """You are an OVER-THE-TOP humorous sports broadcaster covering ANY video. Your job is to ENTERTAIN — witty, loud, crowd-hyping commentary that makes people laugh.

You receive a timestamped timeline from sampled frames. Write lines synced to on-screen moments.

PRIORITY ORDER (strict):
1. HUMOR and personality — jokes, absurd comparisons, crowd reactions, broadcaster banter.
2. Specific visual/action hooks from the timeline (names, on-screen text, scene beats, wins, objects).
3. Score/timer — mention AT MOST ONCE in the entire script, only if it actually changed something. Never narrate the score every line.

FORBIDDEN:
- Lines that mainly restate score/timer ("Score is 4-5", "still 3-2", "clock ticking").
- Generic filler with no timeline anchor ("what a play", "insane moment").
- Monotone stat reading — you are a comedian with a mic, not a spreadsheet.

REQUIRED:
- At least 60% of lines should feel funny or hype (exclamations, jokes, crowd calls).
- At least 3 different comedic angles across the clip (surprise, exaggeration, dry aside, mock drama).
- Vary emotion: hype for peaks, dry for jokes, neutral only for quick setup lines.

Return JSON only:
{"lines":[{"text":"...","target_start_sec":12.0,"emotion":"hype|dry|neutral","must_sync":false,"references":["observable detail"]}]}
"""

FORBIDDEN_GENERIC = re.compile(
    r"^(what a play|insane moment|wow|unbelievable|incredible|let's go guys?|"
    r"what a moment|amazing stuff|great play)\.?$",
    re.I,
)
SCORE_ONLY = re.compile(
    r"^(score\s*(is|now|sits at|reads|shows)?\s*\d+\s*[-:]\s*\d+|"
    r"\d+\s*[-:]\s*\d+\s*on the board|"
    r"(still|remains)\s+\d+\s*[-:]\s*\d+|"
    r"\d+\s*seconds?\s*left)\.?$",
    re.I,
)
TIMER_ONLY = re.compile(r"^\d+\s*seconds?\s*(left|remaining)\.?$", re.I)
SCORE_MENTION = re.compile(r"\bscore\b|\b\d{1,2}\s*[-:]\s*\d{1,2}\b", re.I)
HUMOR_MARKERS = re.compile(
    r"!|\?|—|lol|haha|crowd|booth|broadcast|clip|replay|therapy|chaos|"
    r"dimension|spiraling|bingo|plot twist|didn't|wait |stop |boom|folks|"
    r"unbeliev|ridiculous|absurd|classic|nervous|coffee|truck|highlight",
    re.I,
)

_HYPE_TEMPLATES = [
    "STOP EVERYTHING — {hook}! The booth is SCREAMING!",
    "Did we just witness {hook}? Somebody save that clip!",
    "{hook} — the crowd has LEFT THE BUILDING!",
    "I need a replay! {hook}! WHAT was that!",
    "{hook}! My co-commentator just fell out of his chair!",
]

_DRY_TEMPLATES = [
    "{hook}. Sure. Totally normal. Nothing to see here.",
    "Ah yes, {hook} — my therapist is going to love this segment.",
    "{hook}? That's going straight on the blooper reel, folks.",
    "Classic. {hook}. I pretend to understand and move on.",
]

_NEUTRAL_SETUP = [
    "We're live and {hook} already has the room buzzing.",
    "Keep your eyes here — {hook} is about to steal the show.",
]


def build_system_prompt(*, video_context: Optional[str] = None, tone: str = "hype") -> str:
    extra = ""
    if video_context:
        extra = f"\nVideo context: {video_context}\n"
    return SYSTEM_PROMPT + extra + f"\nDelivery tone: {tone} — lean into hype and jokes.\n"


def _ollama_generate(prompt: str, *, timeout: float = 90.0) -> Optional[str]:
    base = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
    try:
        r = requests.post(
            f"{base}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False, "format": "json"},
            timeout=timeout,
        )
        if not r.ok:
            return None
        return (r.json().get("response") or "").strip()
    except Exception as exc:  # noqa: BLE001
        logger.info("CommentaryScriptService LLM failed: %s", exc)
        return None


def _parse_llm_lines(raw: str) -> List[Dict[str, Any]]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return []
        try:
            parsed = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    lines = parsed.get("lines") if isinstance(parsed, dict) else parsed
    if not isinstance(lines, list):
        return []
    out: List[Dict[str, Any]] = []
    for ln in lines:
        if not isinstance(ln, dict):
            continue
        text = str(ln.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(ln.get("target_start_sec", ln.get("start", 0.0)))
        except (TypeError, ValueError):
            start = 0.0
        emotion = str(ln.get("emotion") or "neutral").lower()
        if emotion not in {"hype", "dry", "neutral"}:
            emotion = "neutral"
        refs = ln.get("references") or []
        if not isinstance(refs, list):
            refs = []
        out.append(
            {
                "text": text,
                "target_start_sec": round(max(0.0, start), 2),
                "emotion": emotion,
                "must_sync": bool(ln.get("must_sync", False)),
                "references": [str(r) for r in refs if r],
            }
        )
    return out


def line_references_timeline(line: Dict[str, Any], entities: Set[str]) -> bool:
    text_lc = str(line.get("text") or "").lower()
    refs = [str(r).lower() for r in (line.get("references") or [])]
    if refs and any(r in text_lc or any(r in e for e in entities) for r in refs):
        return True
    for ent in entities:
        if len(ent) < 3:
            continue
        if ent in text_lc:
            return True
    return False


def is_score_or_timer_only(text: str) -> bool:
    t = text.strip()
    if SCORE_ONLY.match(t) or TIMER_ONLY.match(t):
        return True
    if FORBIDDEN_GENERIC.match(t):
        return True
    if re.fullmatch(r"score\s+\d+\s*[-:]\s*\d+", t, re.I):
        return True
    # Line that's mostly just digits/score words
    stripped = re.sub(r"[^a-z0-9\s]", "", t.lower())
    words = stripped.split()
    if words and sum(1 for w in words if w in {"score", "board", "still", "remains"}) >= 2:
        if SCORE_MENTION.search(t) and len(words) <= 8:
            return True
    return False


def line_has_humor(text: str, emotion: str) -> bool:
    if emotion in {"hype", "dry"}:
        return True
    return bool(HUMOR_MARKERS.search(text))


def validate_script(
    lines: Sequence[Dict[str, Any]],
    timeline: Sequence[Dict[str, Any]],
    *,
    duration_sec: float,
    extra_entities: Optional[Sequence[str]] = None,
    tone: str = "hype",
) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if not lines:
        return False, ["empty script"]

    entities = extract_timeline_entities(timeline)
    for ent in extra_entities or []:
        if ent:
            entities.add(str(ent).lower())
            for token in re.findall(r"[A-Za-z0-9_\-\$]+", str(ent)):
                if len(token) >= 2:
                    entities.add(token.lower())

    score_only_count = 0
    score_mention_count = 0
    missing_ref = 0
    humor_count = 0

    for i, ln in enumerate(lines):
        text = str(ln.get("text") or "").strip()
        emotion = str(ln.get("emotion") or "neutral").lower()
        if not text:
            errors.append(f"line {i}: empty text")
            continue
        if is_score_or_timer_only(text):
            score_only_count += 1
        if SCORE_MENTION.search(text):
            score_mention_count += 1
        if not line_references_timeline(ln, entities):
            missing_ref += 1
            errors.append(f"line {i}: no timeline reference in '{text[:40]}'")
        if line_has_humor(text, emotion):
            humor_count += 1

    if missing_ref > len(lines) * 0.5:
        errors.append(f"{missing_ref}/{len(lines)} lines lack timeline references")

    if score_only_count / max(len(lines), 1) > 0.15:
        errors.append(f"{score_only_count}/{len(lines)} lines are score/timer-only")

    max_score_mentions = max(1, len(lines) // 8)
    if score_mention_count > max_score_mentions:
        errors.append(
            f"{score_mention_count}/{len(lines)} lines mention score (max {max_score_mentions})"
        )

    min_humor = max(2, int(len(lines) * 0.5))
    if humor_count < min_humor and tone in {"hype", "roast"}:
        errors.append(f"only {humor_count}/{len(lines)} lines feel humorous (need {min_humor}+)")

    starts = sorted(float(ln.get("target_start_sec") or 0.0) for ln in lines)
    if starts:
        if starts[0] > 2.0:
            errors.append("late start — gap at beginning")
        for a, b in zip(starts, starts[1:]):
            if b - a > 8.0:
                errors.append(f"gap {b - a:.1f}s between lines (max 8s allowed)")

    if starts and duration_sec - starts[-1] > 6.0:
        errors.append("commentary ends too early vs clip duration")

    return len(errors) == 0, errors


def _humorous_line(hook: str, rng: random.Random, tone: str, *, slot: int) -> tuple[str, str]:
    hook_clean = hook.replace("On-screen: ", "").strip()
    if is_score_event(hook_clean):
        hook_clean = "the chaos on screen"

    if tone == "dry" or slot % 4 == 3:
        return rng.choice(_DRY_TEMPLATES).format(hook=hook_clean), "dry"
    if slot % 2 == 0:
        return rng.choice(_HYPE_TEMPLATES).format(hook=hook_clean), "hype"
    return rng.choice(_NEUTRAL_SETUP).format(hook=hook_clean), "neutral"


def _templated_script(
    timeline: Sequence[Dict[str, Any]],
    *,
    duration_sec: float,
    player_name: Optional[str],
    tone: str,
    must_joke: Optional[str],
    must_sync_ts: Optional[float],
    seed: int,
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    lines: List[Dict[str, Any]] = []
    subject = player_name or "our star"

    first_hook = subject
    if timeline:
        first_events = timeline[0].get("events") or []
        if first_events:
            first_hook = pick_commentary_hook(first_events)

    lines.append(
        {
            "text": f"Ladies and gentlemen, we're LIVE! {first_hook} — and the crowd is already losing it!",
            "target_start_sec": 0.5,
            "emotion": "hype",
            "must_sync": False,
            "references": [first_hook],
        }
    )

    slot = 0
    for entry in timeline:
        ts = float(entry.get("timestamp_sec") or 0.0)
        events = entry.get("events") or []
        if not events:
            continue
        hook = pick_commentary_hook(events)
        refs = [e for e in events[:3] if not is_score_event(e)] or list(events[:3])
        line, emotion = _humorous_line(hook, rng, tone, slot=slot)
        slot += 1

        lines.append(
            {
                "text": line,
                "target_start_sec": max(0.5, ts - 0.5),
                "emotion": emotion,
                "must_sync": False,
                "references": refs,
            }
        )

    if must_joke:
        sync_ts = must_sync_ts if must_sync_ts is not None else duration_sec * 0.5
        lines.append(
            {
                "text": must_joke,
                "target_start_sec": round(float(sync_ts), 2),
                "emotion": "dry",
                "must_sync": True,
                "references": ["callback"],
            }
        )

    lines.append(
        {
            "text": f"That's a WRAP! {subject} gave us a highlight reel the booth won't forget!",
            "target_start_sec": round(max(0.0, duration_sec - 3.5), 2),
            "emotion": "hype",
            "must_sync": False,
            "references": [subject],
        }
    )

    return lines


def boost_emotions(lines: List[Dict[str, Any]], tone: str) -> List[Dict[str, Any]]:
    """When tone is hype/roast, default more lines to hype delivery for TTS."""

    if tone not in {"hype", "roast"}:
        return lines
    out: List[Dict[str, Any]] = []
    for i, ln in enumerate(lines):
        row = dict(ln)
        if row.get("must_sync"):
            out.append(row)
            continue
        em = str(row.get("emotion") or "neutral")
        if em == "neutral" and i % 2 == 0:
            row["emotion"] = "hype"
        out.append(row)
    return out


class CommentaryScriptService:
    """Generate and validate commentary scripts from timeline.json."""

    def generate(
        self,
        timeline: Sequence[Dict[str, Any]],
        *,
        duration_sec: float,
        player_name: Optional[str] = None,
        video_context: Optional[str] = None,
        tone: str = "hype",
        must_include_joke: Optional[str] = None,
        must_sync_timestamp: Optional[float] = None,
        seed: int = 42,
        max_retries: int = 2,
    ) -> List[Dict[str, Any]]:
        user_payload = {
            "duration_sec": duration_sec,
            "subject_name": player_name,
            "video_context": video_context,
            "tone": tone,
            "must_include_joke": must_include_joke,
            "must_sync_timestamp": must_sync_timestamp,
            "timeline": timeline,
        }
        system = build_system_prompt(video_context=video_context, tone=tone)
        prompt = system + "\n\nINPUT:\n" + json.dumps(user_payload, ensure_ascii=False)

        for _attempt in range(max_retries + 1):
            raw = _ollama_generate(prompt)
            if raw:
                lines = _parse_llm_lines(raw)
                lines = boost_emotions(lines, tone)
                ok, errs = validate_script(
                    lines,
                    timeline,
                    duration_sec=duration_sec,
                    extra_entities=[player_name] if player_name else None,
                    tone=tone,
                )
                if ok:
                    logger.info("CommentaryScriptService: LLM script accepted (%s lines)", len(lines))
                    return lines
                logger.warning("CommentaryScriptService LLM validation failed: %s", errs)
                prompt = (
                    system
                    + "\n\nPREVIOUS OUTPUT REJECTED:\n"
                    + json.dumps(errs)
                    + "\n\nINPUT:\n"
                    + json.dumps(user_payload, ensure_ascii=False)
                )

        logger.info("CommentaryScriptService: falling back to templated script")
        lines = _templated_script(
            timeline,
            duration_sec=duration_sec,
            player_name=player_name,
            tone=tone,
            must_joke=must_include_joke,
            must_sync_ts=must_sync_timestamp,
            seed=seed,
        )
        lines = boost_emotions(lines, tone)
        ok, errs = validate_script(
            lines,
            timeline,
            duration_sec=duration_sec,
            extra_entities=[player_name] if player_name else None,
            tone=tone,
        )
        if not ok:
            logger.warning("Templated script validation warnings: %s", errs)
        return lines
