"""
AiEdit shared core (Phase 1 seed).

This package will gradually become the single execution layer that both the
Streamlit UI (``app.py``) and any future API or job runner share. Today it
hosts the strict edit-plan validator and the local prompt-memory store so the
parser, UI, and tests can agree on what a valid edit looks like without
touching the video utilities.

See ``docs/CURRENT_STATE_AND_ROADMAP.md`` for phase context.
"""

from core.edit_plan import (
    REQUIRED_PARAMETERS,
    SUPPORTED_OPERATIONS,
    ValidationResult,
    validate_edit_instruction,
)
from core.prompt_memory import log_correction, log_parse, recent_examples
from core.clarification import clarification_question, needs_clarification
from core.engine import (
    ExecutionContext,
    ExecutionResult,
    execute,
    get_runner,
    register_runner,
)
from core.presets import PRESETS, Preset, detect_hardware, get_preset, recommend
from core.temporal import smooth_mask_sequence, stabilize_bboxes
from core.ocr_consensus import consensus_text_regions

__all__ = [
    "REQUIRED_PARAMETERS",
    "SUPPORTED_OPERATIONS",
    "ValidationResult",
    "validate_edit_instruction",
    "log_parse",
    "log_correction",
    "recent_examples",
    "needs_clarification",
    "clarification_question",
    "ExecutionContext",
    "ExecutionResult",
    "execute",
    "register_runner",
    "get_runner",
    "PRESETS",
    "Preset",
    "detect_hardware",
    "get_preset",
    "recommend",
    "smooth_mask_sequence",
    "stabilize_bboxes",
    "consensus_text_regions",
]
