"""Build structured timeline.json from sampled frame analysis."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Sequence, Set

SCORE_HINT_RE = re.compile(r"\b(\d{1,2})\s*[-:]\s*(\d{1,2})\b")
SCORE_EVENT_RE = re.compile(r"^score\s+\d", re.I)
ECON_RE = re.compile(r"\$\d{1,5}")


def is_score_event(label: str) -> bool:
    """True when a timeline label is primarily a score readout."""

    t = str(label or "").strip().lower()
    if SCORE_EVENT_RE.match(t):
        return True
    if t.startswith("score "):
        return True
    if SCORE_HINT_RE.fullmatch(t.replace(" ", "")):
        return True
    if SCORE_HINT_RE.fullmatch(t):
        return True
    return False


def _confidence_label(score: float) -> str:
    if score >= 0.72:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _format_action_event(ev: Dict[str, Any]) -> str:
    killer = ev.get("killer")
    victim = ev.get("victim") or ev.get("text")
    weapon = ev.get("weapon")
    parts: List[str] = []
    if killer:
        parts.append(str(killer))
    if victim:
        if killer:
            parts.append(f"tags {victim}")
        else:
            parts.append(str(victim))
    if weapon:
        parts.append(f"with {weapon}")
    raw = str(ev.get("raw") or "")
    if "headshot" in raw.lower():
        parts.append("headshot")
    return " ".join(parts).strip() or str(victim or raw[:48])


def _events_from_raw(ev: Dict[str, Any]) -> List[str]:
    kind = str(ev.get("kind") or "")
    raw_lc = str(ev.get("raw") or ev.get("text") or "").lower()
    out: List[str] = []

    if kind == "kill":
        out.append(_format_action_event(ev))
    elif kind == "plant":
        out.append(str(ev.get("text") or "Objective planted"))
    elif kind == "defuse":
        out.append(str(ev.get("text") or "Objective defused"))
    elif kind == "round_end":
        out.append(str(ev.get("text") or "Round end"))
    elif kind == "score":
        out.append(f"Score {ev.get('text')}")
    elif kind in {"observation", "text", "scene"}:
        txt = str(ev.get("text") or ev.get("raw") or "").strip()
        if txt:
            if kind == "scene":
                out.append(txt)
            else:
                out.append(f"On-screen: {txt[:72]}")
    else:
        txt = str(ev.get("text") or "").strip()
        if txt:
            out.append(txt)

    # Do not attach incidental score digits from unrelated OCR blobs.

    for m in ECON_RE.findall(str(ev.get("raw") or "")):
        out.append(f"Label {m}")

    if any(k in raw_lc for k in ("mvp", "winner", "victory", "champion")):
        out.append("Win banner visible")
    if "clutch" in raw_lc or "final" in raw_lc:
        out.append("High-stakes moment")

    return out


def build_timeline(
    raw_events: Sequence[Dict[str, Any]],
    *,
    duration_sec: float,
    sample_fps: float = 1.0,
) -> List[Dict[str, Any]]:
    """Convert flat detected events into timeline.json entries grouped by second."""

    buckets: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for ev in raw_events:
        try:
            t = float(ev.get("t") or 0.0)
        except (TypeError, ValueError):
            continue
        sec = int(round(t))
        buckets[sec].append(ev)

    timeline: List[Dict[str, Any]] = []
    max_sec = max(int(duration_sec), max(buckets.keys(), default=0))

    for sec in range(0, max_sec + 1):
        frame_events = buckets.get(sec, [])
        if not frame_events:
            continue

        event_strings: List[str] = []
        confidences: List[float] = []
        notes: List[str] = []

        for ev in frame_events:
            event_strings.extend(_events_from_raw(ev))
            try:
                confidences.append(float(ev.get("confidence") or 0.5))
            except (TypeError, ValueError):
                confidences.append(0.5)
            kind = str(ev.get("kind") or "")
            if kind in {"observation", "text", "kill"}:
                notes.append("on-screen detail visible")
            elif kind == "scene":
                notes.append("scene beat")

        seen: Set[str] = set()
        deduped: List[str] = []
        for s in event_strings:
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(s)

        if not deduped:
            continue

        # Prefer non-score details first within each timestamp.
        deduped.sort(key=lambda s: (is_score_event(s), s.lower()))

        avg_conf = sum(confidences) / max(len(confidences), 1)
        timeline.append(
            {
                "timestamp_sec": float(sec),
                "events": deduped,
                "confidence": _confidence_label(avg_conf),
                "notes": ", ".join(sorted(set(notes))) if notes else "",
            }
        )

    return timeline


def prepare_timeline_for_script(timeline: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Down-rank persistent HUD scores so scripts focus on action and humor hooks."""

    score_mentions = 0
    max_score_mentions = 1
    prepared: List[Dict[str, Any]] = []

    for entry in timeline:
        events = list(entry.get("events") or [])
        filtered: List[str] = []
        for ev in events:
            if is_score_event(ev):
                if score_mentions >= max_score_mentions:
                    continue
                score_mentions += 1
            filtered.append(ev)

        if not filtered:
            continue

        non_score = [e for e in filtered if not is_score_event(e)]
        ordered = non_score + [e for e in filtered if is_score_event(e)]
        prepared.append({**entry, "events": ordered})

    return prepared


def pick_commentary_hook(events: Sequence[str]) -> str:
    """Best non-score hook for a commentary line."""

    for ev in events:
        if not is_score_event(ev):
            return str(ev)
    return str(events[0]) if events else "the moment"


def fill_scene_beats(
    timeline: List[Dict[str, Any]],
    *,
    duration_sec: float,
    target_entries: int = 8,
) -> List[Dict[str, Any]]:
    """Ensure non-empty timeline for videos with little or no on-screen text."""

    min_entries = max(3, min(target_entries, int(max(duration_sec, 1.0) // 5) + 1))
    if len(timeline) >= min_entries:
        return timeline

    existing_times = {int(entry.get("timestamp_sec", 0)) for entry in timeline}
    interval = max(3.0, duration_sec / min_entries)
    merged = list(timeline)

    for i in range(min_entries):
        ts = round(min(duration_sec - 1.0, i * interval + 0.5), 2)
        sec = int(round(ts))
        if sec in existing_times:
            continue
        label = "Opening beat" if i == 0 else f"Scene beat at {int(ts // 60)}:{int(ts % 60):02d}"
        merged.append(
            {
                "timestamp_sec": float(sec),
                "events": [label],
                "confidence": "low",
                "notes": "scene beat",
            }
        )
        existing_times.add(sec)

    merged.sort(key=lambda e: float(e.get("timestamp_sec") or 0.0))
    return merged


def extract_timeline_entities(timeline: Sequence[Dict[str, Any]]) -> Set[str]:
    """All reference tokens usable for script validation."""

    entities: Set[str] = set()
    for entry in timeline:
        for ev in entry.get("events") or []:
            text = str(ev)
            entities.add(text.lower())
            for token in re.findall(r"[A-Za-z0-9_\-\$:]+", text):
                if len(token) >= 2:
                    entities.add(token.lower())
    return entities
