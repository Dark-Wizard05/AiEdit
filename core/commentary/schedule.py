"""Audio scheduling — fit commentary lines to timeline without overlaps."""

from __future__ import annotations

from typing import Any, Dict, List, Sequence


DEFAULT_GAP_SEC = 0.35
MAX_SPEEDUP = 1.22
MAX_SPEEDUP_EARLY = 1.28
EARLY_LINE_COUNT = 3


def fit_schedule(
    lines: Sequence[Dict[str, Any]],
    *,
    duration_sec: float,
    default_gap: float = DEFAULT_GAP_SEC,
) -> List[Dict[str, Any]]:
    """Assign start_sec / end_sec / speed_factor per rendered line."""

    scheduled: List[Dict[str, Any]] = []
    prev_end = 0.0

    sorted_lines = sorted(lines, key=lambda l: float(l.get("target_start_sec") or 0.0))

    for idx, ln in enumerate(sorted_lines):
        target = float(ln.get("target_start_sec") or 0.0)
        must_sync = bool(ln.get("must_sync", False))
        audio_dur = float(ln.get("audio_duration") or ln.get("duration") or 2.5)
        max_speed = MAX_SPEEDUP_EARLY if idx < EARLY_LINE_COUNT else MAX_SPEEDUP

        if must_sync:
            start = max(target, prev_end + default_gap)
            speed = 1.0
        else:
            start = max(target, prev_end + default_gap)
            speed = 1.0
            slot = max(0.5, target + 2.5 - start) if idx + 1 < len(sorted_lines) else max(
                0.5, duration_sec - start
            )
            if audio_dur > slot and not must_sync:
                speed = min(max_speed, audio_dur / max(slot, 0.1))
                speed = max(1.0, speed)

        effective_dur = audio_dur / speed
        end = start + effective_dur

        out = dict(ln)
        out["start_sec"] = round(start, 3)
        out["end_sec"] = round(end, 3)
        out["speed_factor"] = round(speed, 3)
        scheduled.append(out)
        prev_end = end

    return scheduled
