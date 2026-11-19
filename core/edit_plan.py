"""
Strict validator for parsed edit plans.

The parser (``utils/prompt_parser.py``) returns an ``EditInstruction``. Before
any pixels move, the validator confirms:

- the operation is one we actually execute,
- required parameters for that operation are present and non-empty,
- color parameters reference known palette entries.

Today this is consumed inside ``parse_edit_command`` (it stamps a ``validation``
block on ``metadata`` so the UI can react). Later phases will gate execution on
``ValidationResult.ok``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set


SUPPORTED_OPERATIONS: Set[str] = {
    "text_replacement",
    "text_removal",
    "text_detection",
    "frame_extraction",
    "character_hair_recolor",
    "object_recolor",
    "object_remove",
    "object_replace_guided",
    "global_color_change",
    "atmosphere_overlay",
    "auto_commentary",
    "codegen_edit",
    "timeline_trim",
    "speed_change",
    "crop_resize",
    "volume_adjust",
    "fade_in_out",
    "rotate_flip",
    "brightness_contrast",
    "timeline_edit",
}

REQUIRED_PARAMETERS: Dict[str, List[str]] = {
    "text_replacement": ["old_text", "new_text"],
    "text_removal": [],
    "text_detection": [],
    "frame_extraction": [],
    "character_hair_recolor": ["target_color"],
    "object_recolor": ["target_object", "target_color"],
    "object_remove": ["target_object"],
    "object_replace_guided": ["target_object", "replacement_object"],
    "global_color_change": ["source_color", "target_color"],
    "atmosphere_overlay": [],
    "auto_commentary": [],
    "codegen_edit": ["original_prompt"],
    "timeline_trim": [],
    "speed_change": [],
    "crop_resize": [],
    "volume_adjust": [],
    "fade_in_out": [],
    "rotate_flip": [],
    "brightness_contrast": [],
    "timeline_edit": [],
}

COLOR_PARAM_NAMES: Set[str] = {"target_color", "source_color"}


@dataclass
class ValidationResult:
    ok: bool
    operation: str
    missing: List[str] = field(default_factory=list)
    invalid: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "operation": self.operation,
            "missing": list(self.missing),
            "invalid": list(self.invalid),
            "errors": list(self.errors),
        }


def _known_colors() -> Set[str]:
    """Avoid an import cycle with ``utils.prompt_parser`` at module load."""

    from utils.prompt_parser import KNOWN_COLORS

    return set(KNOWN_COLORS.keys())


def _color_resolves(value: str) -> bool:
    """True if a color spec resolves to a usable BGR triple.

    Accepts palette names, hex (#rrggbb / #rgb / 0xRRGGBB / bare hex),
    rgb()/rgba() — anything ``utils.prompt_parser.resolve_color`` understands.
    """

    from utils.prompt_parser import resolve_color

    return resolve_color(value) is not None


def _validate_operation_params(operation: str, parameters: Dict[str, Any]) -> List[str]:
    """Extra validation beyond required-parameter presence."""

    errors: List[str] = []

    if operation == "timeline_trim":
        if not any(
            parameters.get(k) is not None
            for k in ("start_sec", "end_sec", "start_time", "end_time", "start", "end", "duration_sec", "end_offset_sec")
        ):
            errors.append("timeline_trim needs start and/or end time (e.g. start_sec, end_sec)")

    elif operation == "crop_resize":
        if not (parameters.get("aspect_ratio") or parameters.get("aspect") or parameters.get("width")):
            errors.append("crop_resize needs aspect_ratio (e.g. 9:16) or width/height")

    elif operation == "volume_adjust":
        if not any(
            parameters.get(k) is not None
            for k in ("volume_factor", "volume", "mute", "mute_audio", "audio_fade_in_sec", "audio_fade_out_sec")
        ):
            errors.append("volume_adjust needs volume_factor, mute, or audio fade settings")

    elif operation == "fade_in_out":
        if not any(parameters.get(k) for k in ("fade_in_sec", "fade_out_sec", "video_fade_in_sec", "video_fade_out_sec")):
            errors.append("fade_in_out needs fade_in_sec and/or fade_out_sec")

    elif operation == "rotate_flip":
        if not (parameters.get("flip") or parameters.get("rotation") or parameters.get("rotation_degrees")):
            errors.append("rotate_flip needs rotation or flip")

    elif operation == "brightness_contrast":
        if not any(parameters.get(k) is not None for k in ("brightness", "contrast", "saturation", "preset")):
            errors.append("brightness_contrast needs brightness, contrast, saturation, or preset")

    elif operation == "timeline_edit":
        if not parameters.get("effects") and not any(
            parameters.get(k) is not None
            for k in ("start_sec", "end_sec", "speed_factor", "speed", "zoom_factor")
        ):
            errors.append("timeline_edit needs effects list or trim/speed/zoom parameters")

    elif operation == "speed_change":
        try:
            factor = float(parameters.get("speed_factor") or parameters.get("speed") or 0)
        except (TypeError, ValueError):
            factor = 0
        if factor <= 0:
            errors.append("speed_change needs a positive speed_factor")

    return errors


def validate_edit_instruction(instruction: Any) -> ValidationResult:
    """Validate an ``EditInstruction``-like object (or compatible dict)."""

    operation = getattr(instruction, "operation", None)
    if operation is None and isinstance(instruction, dict):
        operation = instruction.get("operation")

    parameters = getattr(instruction, "parameters", None)
    if parameters is None and isinstance(instruction, dict):
        parameters = instruction.get("parameters") or {}
    parameters = dict(parameters or {})

    if not operation:
        return ValidationResult(
            ok=False,
            operation="",
            errors=["instruction has no operation"],
        )

    if operation in {"unsupported", "unsupported_generative_edit", "unknown"}:
        return ValidationResult(
            ok=False,
            operation=operation,
            errors=[f"operation '{operation}' is not executable"],
        )

    if operation not in SUPPORTED_OPERATIONS:
        return ValidationResult(
            ok=False,
            operation=operation,
            errors=[f"unknown operation '{operation}'"],
        )

    required = REQUIRED_PARAMETERS.get(operation, [])
    missing = [name for name in required if not str(parameters.get(name) or "").strip()]

    invalid: List[str] = []
    for color_param in COLOR_PARAM_NAMES & set(required):
        value = str(parameters.get(color_param) or "").strip()
        if value and not _color_resolves(value):
            invalid.append(f"{color_param}='{value}' is not a recognizable color")

    param_errors = _validate_operation_params(operation, parameters)
    errors: List[str] = []
    if missing:
        errors.append(f"missing parameters: {', '.join(missing)}")
    errors.extend(invalid)
    errors.extend(param_errors)

    ok = not missing and not invalid and not param_errors

    return ValidationResult(
        ok=ok,
        operation=operation,
        missing=missing,
        invalid=invalid,
        errors=errors,
    )
