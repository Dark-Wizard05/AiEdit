"""Parse human time expressions into seconds for timeline edits."""

from __future__ import annotations

import re
from typing import Any, Optional, Union


def parse_time_to_seconds(value: Any) -> Optional[float]:
    """Convert ``90``, ``90s``, ``1:30``, or ``0:01:30`` to seconds."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value).strip().lower()
    if not text:
        return None

    text = re.sub(r"\s*(seconds?|secs?|s)\s*$", "", text, flags=re.IGNORECASE).strip()

    if re.fullmatch(r"\d+(\.\d+)?", text):
        return float(text)

    if ":" in text:
        parts = [p.strip() for p in text.split(":")]
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        if len(nums) == 2:
            minutes, seconds = nums
            return max(0.0, minutes * 60.0 + seconds)
        if len(nums) == 3:
            hours, minutes, seconds = nums
            return max(0.0, hours * 3600.0 + minutes * 60.0 + seconds)
        return None

    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:sec|second|s)\b", text)
    if match:
        return float(match.group(1))

    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:min|minute|m)\b", text)
    if match:
        return float(match.group(1)) * 60.0

    return None


def coerce_time_param(params: dict, *keys: str) -> Optional[float]:
    for key in keys:
        if key in params and params[key] is not None:
            parsed = parse_time_to_seconds(params[key])
            if parsed is not None:
                return parsed
    return None
