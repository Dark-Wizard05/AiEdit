"""
Product tiers: default (structured edits) vs premium (AI code-gen fallback).

Default tier covers all operations in ``core.edit_plan.SUPPORTED_OPERATIONS``.
When a prompt maps to ``unsupported`` (or fails default validation), premium is
required — the upsell path for open-ended edits via sandboxed script generation.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from core.edit_plan import SUPPORTED_OPERATIONS, ValidationResult, validate_edit_instruction

TIER_DEFAULT = "default"
TIER_PREMIUM = "premium"

PREMIUM_OPERATION = "codegen_edit"

# Human-readable list for UI / docs (default pack).
DEFAULT_FEATURES: List[str] = [
    "Text detect, remove, and replace",
    "Trim, cut, and clip (timeline)",
    "Speed change — slow-mo and timelapse",
    "Crop and resize — 9:16, 16:9, square",
    "Volume, mute, and audio fade",
    "Video fade in / fade out",
    "Rotate and flip",
    "Brightness, contrast, and color presets",
    "Timeline montage — zoom + speed segments",
    "Object recolor, remove, and reference-guided replace",
    "Character hair recolor",
    "Global color change with tolerance",
    "Atmosphere / weather / mood overlays",
    "Auto play-by-play commentary",
    "Frame extraction",
]

PREMIUM_FEATURES: List[str] = [
    "Custom edits via AI-generated FFmpeg / MoviePy scripts",
    "Open-ended prompts not covered by the default pack",
]

PREMIUM_UPSELL_TITLE = "Premium required for this edit"

PREMIUM_UPSELL_BODY = (
    "This request goes beyond the default editor (text, objects, colors, atmosphere, "
    "timeline, commentary). Premium runs a sandboxed AI script tailored to your prompt — "
    "for unusual compositing or edits not covered by built-in operations."
)


def dev_premium_unlocked() -> bool:
    """Local testing: set ``AIEDIT_DEV_PREMIUM=1`` to exercise the premium path."""
    return os.getenv("AIEDIT_DEV_PREMIUM", "").strip().lower() in {"1", "true", "yes"}


def user_has_premium(*, use_premium_flag: bool = False, entitlements: Any = None) -> bool:
    """True when the caller is allowed to run premium/code-gen jobs."""
    if entitlements is not None:
        status = getattr(entitlements, "subscription_status", None) or (
            entitlements.get("subscription_status") if isinstance(entitlements, dict) else None
        )
        codegen = getattr(entitlements, "codegen_enabled", None)
        if codegen is None and isinstance(entitlements, dict):
            codegen = entitlements.get("permissions", {}).get("codegen_enabled")
        if status == "active" and codegen:
            return True
    if use_premium_flag and dev_premium_unlocked():
        return True
    return False


def is_default_executable(operation: str, validation: ValidationResult) -> bool:
    return validation.ok and operation in SUPPORTED_OPERATIONS


def premium_required_for_instruction(instruction: Any) -> bool:
    """True when default tier cannot run this plan and premium/code-gen is the path."""
    operation = getattr(instruction, "operation", "") or ""
    supported = bool(getattr(instruction, "supported", True))
    validation = validate_edit_instruction(instruction)

    if operation in {"unsupported", "unsupported_generative_edit"}:
        return True
    if not supported and not validation.ok:
        return True
    if not validation.ok and operation not in SUPPORTED_OPERATIONS:
        return True
    return False


def friendly_user_message(instruction: Any, validation: ValidationResult) -> str:
    summary = getattr(instruction, "summary", "") or ""
    operation = getattr(instruction, "operation", "") or ""

    if premium_required_for_instruction(instruction):
        if summary:
            return summary
        return (
            "This edit is not included in the default pack. "
            "Upgrade to Premium for custom timeline and open-ended edits."
        )

    if validation.missing:
        return f"Missing details: {', '.join(validation.missing)}."
    if validation.errors:
        return validation.errors[0]
    return summary or f"Ready to run {operation}."


def premium_upsell_message(instruction: Any) -> str:
    summary = getattr(instruction, "summary", "") or ""
    base = PREMIUM_UPSELL_BODY
    if summary:
        return f"{summary}\n\n{base}"
    return base


def enrich_plan_fields(instruction: Any) -> Dict[str, Any]:
    """Extra fields merged into parse/job API responses."""
    validation = validate_edit_instruction(instruction)
    operation = getattr(instruction, "operation", "") or ""
    needs_premium = premium_required_for_instruction(instruction)
    executable_default = is_default_executable(operation, validation)

    return {
        "tier": TIER_PREMIUM if needs_premium else TIER_DEFAULT,
        "premium_required": needs_premium,
        "executable_default": executable_default,
        "user_message": friendly_user_message(instruction, validation),
        "premium_message": premium_upsell_message(instruction) if needs_premium else None,
        "default_features": DEFAULT_FEATURES,
        "premium_features": PREMIUM_FEATURES,
    }


def instruction_for_execution(
    instruction: Any,
    *,
    prompt: str,
    use_premium: bool,
    entitlements: Any = None,
) -> Any:
    """
    If premium is active and the plan is unsupported, rewrite to ``codegen_edit``
    so ``core.engine`` can dispatch the premium runner.
    """
    if not premium_required_for_instruction(instruction):
        return instruction
    if not user_has_premium(use_premium_flag=use_premium, entitlements=entitlements):
        return instruction

    from utils.prompt_parser import EditInstruction

    return EditInstruction(
        operation=PREMIUM_OPERATION,
        summary="Premium: generate and run a custom edit script for your prompt.",
        parameters={
            "original_prompt": prompt,
            "original_operation": getattr(instruction, "operation", "unsupported"),
            "original_summary": getattr(instruction, "summary", ""),
        },
        supported=True,
        warnings=list(getattr(instruction, "warnings", []) or []),
        metadata={
            **dict(getattr(instruction, "metadata", None) or {}),
            "tier": TIER_PREMIUM,
            "routed_from_default": True,
        },
    )
