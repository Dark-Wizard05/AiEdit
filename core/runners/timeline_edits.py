"""Runners for FFmpeg timeline operations (Normal plan)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.engine import ExecutionContext, ExecutionResult
from utils.ffmpeg_edits import run_timeline_operation

_TIMELINE_OPS = {
    "timeline_trim",
    "speed_change",
    "crop_resize",
    "volume_adjust",
    "fade_in_out",
    "rotate_flip",
    "brightness_contrast",
    "timeline_edit",
}


def timeline_runner(instruction: Any, context: ExecutionContext) -> ExecutionResult:
    op = getattr(instruction, "operation", "")
    if op not in _TIMELINE_OPS:
        return ExecutionResult(ok=False, operation=op, error=f"unknown timeline op '{op}'")

    video_path = context.video_path
    if not video_path or not Path(video_path).is_file():
        return ExecutionResult(
            ok=False,
            operation=op,
            error="ExecutionContext.video_path must point to an existing video file",
        )

    params = dict(getattr(instruction, "parameters", {}) or {})
    out_root = Path(context.output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    output_video = out_root / f"{op}_output.mp4"

    try:
        result_path = run_timeline_operation(op, str(video_path), str(output_video), params)
    except Exception as exc:  # noqa: BLE001
        return ExecutionResult(
            ok=False,
            operation=op,
            summary=getattr(instruction, "summary", op),
            error=str(exc),
        )

    return ExecutionResult(
        ok=True,
        operation=op,
        summary=getattr(instruction, "summary", op),
        output_video_path=result_path,
        artifacts={"parameters": params},
    )


def register_timeline_runners(register) -> None:
    for op in _TIMELINE_OPS:
        register(op, timeline_runner)
