"""
Tiny helper around clarification questions.

UIs (Streamlit, FastAPI, future job runner) all need the same logic:
"is this plan ready, or should we ask the user one focused question first?"

Two pure functions, no UI dependencies:

- ``needs_clarification(instruction)`` -> bool
- ``clarification_question(instruction)`` -> str
"""

from __future__ import annotations

from typing import Any

from core.edit_plan import REQUIRED_PARAMETERS, validate_edit_instruction


def _meta(instruction: Any) -> dict:
    meta = getattr(instruction, "metadata", None) or {}
    return meta if isinstance(meta, dict) else {}


def needs_clarification(instruction: Any) -> bool:
    meta = _meta(instruction)
    if meta.get("needs_clarification"):
        return True
    validation = validate_edit_instruction(instruction)
    return not validation.ok and bool(getattr(instruction, "supported", True))


def clarification_question(instruction: Any) -> str:
    meta = _meta(instruction)
    explicit = meta.get("clarification_question")
    if explicit:
        return str(explicit)

    validation = validate_edit_instruction(instruction)
    op = validation.operation or getattr(instruction, "operation", "")

    if validation.missing:
        names = ", ".join(validation.missing)
        if op == "text_replacement":
            return "What text should I look for, and what should it become?"
        if op in {"object_recolor", "global_color_change", "character_hair_recolor"}:
            return "Which color should it become? (e.g. pink, blue, gold)"
        if op == "object_remove":
            return "Which object exactly should I remove?"
        if op == "object_replace_guided":
            return "What should I replace it with? A reference image helps."
        return f"I need a bit more info: {names}."

    if validation.invalid:
        return ", ".join(validation.invalid) + ". Could you pick a known color?"

    needed = REQUIRED_PARAMETERS.get(op, [])
    if needed:
        return f"To run '{op}', please confirm: {', '.join(needed)}."
    return "Could you rephrase the request?"
