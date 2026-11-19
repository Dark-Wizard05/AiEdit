"""
Premium tier: LLM-generated edit scripts executed in a sandbox (future).

Today this is a scaffold — registers with ``core.engine`` and returns a clear
status until sandbox execution is implemented.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.engine import ExecutionContext, ExecutionResult, register_runner
from core.tiers import PREMIUM_OPERATION


def execute_codegen_edit(instruction: Any, context: ExecutionContext) -> ExecutionResult:
    """
    Premium code-gen runner (stub).

    Planned flow:
    1. LLM writes FFmpeg/MoviePy script from ``original_prompt``
    2. Static validation + allowlisted imports
    3. Sandboxed subprocess with timeouts
    4. Export MP4 to ``context.output_dir``
    """
    params = getattr(instruction, "parameters", {}) or {}
    prompt = params.get("original_prompt") or ""

    if not context.video_path or not Path(context.video_path).is_file():
        return ExecutionResult(
            ok=False,
            operation=PREMIUM_OPERATION,
            error="video_path is required for premium code-gen edits",
        )

    return ExecutionResult(
        ok=False,
        operation=PREMIUM_OPERATION,
        summary="Premium code-gen pipeline is not enabled yet.",
        error=(
            "Premium code-gen is scaffolded but not fully implemented. "
            f"Your prompt was accepted for tier routing ({len(prompt)} chars). "
            "Sandbox script generation and execution will ship in a follow-up."
        ),
        artifacts={
            "status": "scaffold",
            "original_prompt_preview": prompt[:500],
            "video_path": context.video_path,
        },
    )


register_runner(PREMIUM_OPERATION, execute_codegen_edit)
