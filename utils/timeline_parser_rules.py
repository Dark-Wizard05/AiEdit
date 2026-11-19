"""Rule-based parsing for timeline / FFmpeg Normal-plan edits."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from utils.time_parse import parse_time_to_seconds


def _edit_instruction(**kwargs):
    from utils.prompt_parser import EditInstruction

    return EditInstruction(**kwargs)


def _extract_time_range(command: str) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    command_lower = command.lower()

    between = re.search(
        r"(?:from|between)\s+(\d[\d:.,]*(?:\s*(?:sec|second|s|min|m))?)\s+(?:to|and|-)\s+(\d[\d:.,]*(?:\s*(?:sec|second|s|min|m))?)",
        command_lower,
    )
    if between:
        start = parse_time_to_seconds(between.group(1))
        end = parse_time_to_seconds(between.group(2))
        if start is not None:
            params["start_sec"] = start
        if end is not None:
            params["end_sec"] = end
        return params

    from_match = re.search(
        r"(?:from|starting at|start at)\s+(\d[\d:.,]*(?:\s*(?:sec|second|s|min|m))?)",
        command_lower,
    )
    if from_match:
        start = parse_time_to_seconds(from_match.group(1))
        if start is not None:
            params["start_sec"] = start

    to_match = re.search(
        r"(?:to|until|up to|ending at|end at)\s+(\d[\d:.,]*(?:\s*(?:sec|second|s|min|m))?)",
        command_lower,
    )
    if to_match:
        end = parse_time_to_seconds(to_match.group(1))
        if end is not None:
            params["end_sec"] = end

    remove_start = re.search(
        r"(?:remove|cut|trim)\s+(?:the\s+)?(?:first|initial)\s+(\d+(?:\.\d+)?)\s*(?:sec|second|s)?",
        command_lower,
    )
    if remove_start:
        sec = parse_time_to_seconds(remove_start.group(1))
        if sec is not None:
            params["start_sec"] = sec

    remove_end = re.search(
        r"(?:remove|cut|trim)\s+(?:the\s+)?(?:last|final)\s+(\d+(?:\.\d+)?)\s*(?:sec|second|s)?",
        command_lower,
    )
    if remove_end and "duration_sec" not in params:
        sec = parse_time_to_seconds(remove_end.group(1))
        if sec is not None:
            params["trim_last_sec"] = sec

    return params


def _parse_speed_factor(command_lower: str) -> Optional[float]:
    if "half speed" in command_lower or "0.5x" in command_lower:
        return 0.5
    if "double speed" in command_lower or "2x speed" in command_lower:
        return 2.0
    match = re.search(r"(\d+(?:\.\d+)?)\s*x\s*(?:speed|faster|slower)?", command_lower)
    if match:
        return float(match.group(1))
    match = re.search(r"(?:speed|at)\s+(\d+(?:\.\d+)?)\s*x", command_lower)
    if match:
        return float(match.group(1))
    if "slow motion" in command_lower or "slow-mo" in command_lower or "slo-mo" in command_lower:
        pct = re.search(r"(\d+)\s*%", command_lower)
        if pct:
            return max(0.1, float(pct.group(1)) / 100.0)
        return 0.5
    if "timelapse" in command_lower or "time lapse" in command_lower or "fast forward" in command_lower:
        return 2.0
    return None


def parse_timeline_command(command: str) -> Optional[Any]:
    command = (command or "").strip()
    if not command:
        return None
    command_lower = command.lower()
    meta = {"parser_backend": "rule_based", "confidence": 0.84}
    time_range = _extract_time_range(command)

    # --- Trim / cut ---
    if any(
        kw in command_lower
        for kw in ["trim", " cut ", "cut the", "clip to", "keep only", "remove first", "remove last"]
    ) or re.search(r"\bcut\b", command_lower):
        if "text" not in command_lower and "caption" not in command_lower:
            params = dict(time_range)
            if params.get("trim_last_sec") and "end_sec" not in params:
                params["duration_hint_trim_last"] = params.pop("trim_last_sec")
            if params or "trim" in command_lower or re.search(r"\bcut\b", command_lower):
                if "duration_hint_trim_last" in params:
                    # end = duration - last; runner resolves if only start given
                    params["end_offset_sec"] = params.pop("duration_hint_trim_last")
                summary_bits = []
                if params.get("start_sec") is not None:
                    summary_bits.append(f"from {params['start_sec']}s")
                if params.get("end_sec") is not None:
                    summary_bits.append(f"to {params['end_sec']}s")
                return _edit_instruction(
                    operation="timeline_trim",
                    summary="Trim video " + " ".join(summary_bits) if summary_bits else "Trim video clip.",
                    parameters=params,
                    metadata=meta,
                )

    # --- Speed ---
    speed = _parse_speed_factor(command_lower)
    if speed and any(k in command_lower for k in ["speed", "slow", "fast", "timelapse", "time lapse", "x"]):
        params: Dict[str, Any] = {"speed_factor": speed}
        params.update(time_range)
        return _edit_instruction(
            operation="speed_change",
            summary=f"Change speed to {speed}x.",
            parameters=params,
            metadata=meta,
        )

    # --- Crop / aspect ---
    aspect = None
    if any(k in command_lower for k in ["9:16", "vertical", "tiktok", "reel", "shorts", "portrait"]):
        aspect = "9:16"
    elif "16:9" in command_lower or "landscape" in command_lower or "youtube" in command_lower:
        aspect = "16:9"
    elif "1:1" in command_lower or "square" in command_lower:
        aspect = "1:1"
    elif "4:5" in command_lower or "instagram" in command_lower:
        aspect = "4:5"
    if aspect or ("crop" in command_lower and "text" not in command_lower):
        return _edit_instruction(
            operation="crop_resize",
            summary=f"Crop to {aspect or 'center frame'}.",
            parameters={"aspect_ratio": aspect or "16:9"},
            metadata=meta,
        )

    # --- Volume ---
    if any(k in command_lower for k in ["mute", "silence audio", "no audio", "remove audio"]):
        return _edit_instruction(
            operation="volume_adjust",
            summary="Mute audio.",
            parameters={"mute": True},
            metadata=meta,
        )
    vol_match = re.search(r"(?:volume|audio)\s+(?:to\s+)?(\d+(?:\.\d+)?)\s*%", command_lower)
    if vol_match:
        pct = float(vol_match.group(1))
        return _edit_instruction(
            operation="volume_adjust",
            summary=f"Set volume to {pct}%.",
            parameters={"volume_factor": pct / 100.0},
            metadata=meta,
        )
    if "louder" in command_lower or "boost volume" in command_lower:
        return _edit_instruction(
            operation="volume_adjust",
            summary="Boost volume.",
            parameters={"volume_factor": 1.5},
            metadata=meta,
        )
    if "quieter" in command_lower or "lower volume" in command_lower:
        return _edit_instruction(
            operation="volume_adjust",
            summary="Lower volume.",
            parameters={"volume_factor": 0.5},
            metadata=meta,
        )

    # --- Video fade ---
    if "fade in" in command_lower or "fade out" in command_lower:
        params: Dict[str, Any] = {}
        fin = re.search(r"fade\s+in\s+(?:over\s+)?(\d+(?:\.\d+)?)\s*(?:sec|second|s)?", command_lower)
        fout = re.search(r"fade\s+out\s+(?:over\s+)?(\d+(?:\.\d+)?)\s*(?:sec|second|s)?", command_lower)
        if fin:
            params["fade_in_sec"] = float(fin.group(1))
        if fout:
            params["fade_out_sec"] = float(fout.group(1))
        if "fade in" in command_lower and "fade_in_sec" not in params:
            params["fade_in_sec"] = 1.0
        if "fade out" in command_lower and "fade_out_sec" not in params:
            params["fade_out_sec"] = 1.0
        if params:
            return _edit_instruction(
                operation="fade_in_out",
                summary="Apply video fade.",
                parameters=params,
                metadata=meta,
            )

    # --- Rotate / flip ---
    if "flip horizontal" in command_lower or "mirror" in command_lower:
        return _edit_instruction(
            operation="rotate_flip",
            summary="Flip video horizontally.",
            parameters={"flip": "horizontal"},
            metadata=meta,
        )
    if "flip vertical" in command_lower:
        return _edit_instruction(
            operation="rotate_flip",
            summary="Flip video vertically.",
            parameters={"flip": "vertical"},
            metadata=meta,
        )
    rot = re.search(r"rotate\s+(90|180|270)", command_lower)
    if rot:
        return _edit_instruction(
            operation="rotate_flip",
            summary=f"Rotate video {rot.group(1)}°.",
            parameters={"rotation": int(rot.group(1))},
            metadata=meta,
        )

    # --- Brightness / contrast ---
    if any(k in command_lower for k in ["brighter", "brightness", "contrast", "saturation", "cinematic look", "vivid"]):
        params: Dict[str, Any] = {}
        if "cinematic" in command_lower:
            params["preset"] = "cinematic"
        elif "vivid" in command_lower:
            params["preset"] = "vivid"
        elif "muted" in command_lower:
            params["preset"] = "muted"
        elif "brighter" in command_lower:
            params["preset"] = "bright"
        else:
            params["brightness"] = 0.08
        return _edit_instruction(
            operation="brightness_contrast",
            summary="Adjust brightness and color.",
            parameters=params,
            metadata=meta,
        )

    # --- Combined timeline (zoom + slow-mo) ---
    zoom_match = re.search(r"zoom\s+(?:to\s+)?(\d+(?:\.\d+)?)\s*%", command_lower)
    if not zoom_match:
        zoom_match = re.search(r"(\d+(?:\.\d+)?)\s*%\s*zoom", command_lower)
    zoom_factor = None
    if zoom_match:
        zoom_factor = float(zoom_match.group(1)) / 100.0
    elif "zoom in" in command_lower:
        zoom_factor = 1.5

    speed = _parse_speed_factor(command_lower)
    if zoom_factor or (speed and time_range):
        effects: list = []
        if time_range.get("start_sec") is not None or time_range.get("end_sec") is not None:
            effects.append({"type": "trim", **time_range})
        if zoom_factor:
            effects.append(
                {
                    "type": "zoom",
                    "zoom_factor": zoom_factor,
                    "start_sec": time_range.get("start_sec"),
                    "end_sec": time_range.get("end_sec"),
                }
            )
        if speed:
            effects.append(
                {
                    "type": "speed",
                    "speed_factor": speed,
                    "start_sec": time_range.get("start_sec"),
                    "end_sec": time_range.get("end_sec"),
                }
            )
        if effects:
            return _edit_instruction(
                operation="timeline_edit",
                summary="Apply timeline montage edit.",
                parameters={"effects": effects},
                metadata={**meta, "confidence": 0.8},
            )

    return None
