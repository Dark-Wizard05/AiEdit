"""
Phase 1 unified execution facade.

Goal: every editor (Streamlit ``app.py``, ``backend/api.py``, ``pipeline.py``,
future job runner) goes through one validate-then-execute funnel.

Today this module:

- validates an ``EditInstruction`` via ``core.edit_plan``,
- if invalid, returns an ``ExecutionResult(ok=False)`` with the validator's
  errors (no pixels touched),
- otherwise dispatches to a registered runner for the operation.

Runners are kept thin: they wrap existing utilities (``pipeline.VideoPipeline``,
``utils.video_mask_tracker``, ``utils.object_editor``) so we don't fork the
editing logic. Streamlit can adopt this funnel incrementally; ``backend/api.py``
already uses it for its ``/jobs`` endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import shutil
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.edit_plan import ValidationResult, validate_edit_instruction


@dataclass
class ExecutionContext:
    video_path: Optional[str] = None
    output_dir: str = "output"
    device: str = "cpu"
    fps: int = 30
    max_frames: Optional[int] = None
    reference_image_paths: list = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    ok: bool
    operation: str
    summary: str = ""
    output_video_path: Optional[str] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)
    validation: Optional[ValidationResult] = None
    error: Optional[str] = None


Runner = Callable[[Any, ExecutionContext], ExecutionResult]
_RUNNERS: Dict[str, Runner] = {}


def register_runner(operation: str, runner: Runner) -> None:
    """Wire a callable to handle one operation. Last registration wins."""

    _RUNNERS[operation] = runner


def get_runner(operation: str) -> Optional[Runner]:
    return _RUNNERS.get(operation)


def execute(instruction: Any, context: ExecutionContext) -> ExecutionResult:
    """Validate then dispatch. Never lets an invalid plan touch pixels."""

    validation = validate_edit_instruction(instruction)
    operation = validation.operation or getattr(instruction, "operation", "") or ""

    if not validation.ok:
        return ExecutionResult(
            ok=False,
            operation=operation,
            summary="Edit plan failed validation; nothing was rendered.",
            validation=validation,
            error="; ".join(validation.errors) or "validation failed",
        )

    runner = _RUNNERS.get(operation)
    if runner is None:
        return ExecutionResult(
            ok=False,
            operation=operation,
            summary=f"No runner registered for '{operation}'.",
            validation=validation,
            error=f"no runner for '{operation}'",
        )

    try:
        result = runner(instruction, context)
        if result.validation is None:
            result.validation = validation
        return result
    except Exception as exc:  # noqa: BLE001 - runners must never crash callers
        return ExecutionResult(
            ok=False,
            operation=operation,
            summary="Runner raised; see error.",
            validation=validation,
            error=str(exc),
        )


# --------------------------------------------------------------------------- #
# Default runner: text-focused operations through pipeline.VideoPipeline.
# --------------------------------------------------------------------------- #

def _text_pipeline_runner(instruction: Any, context: ExecutionContext) -> ExecutionResult:
    if not context.video_path:
        return ExecutionResult(
            ok=False,
            operation=getattr(instruction, "operation", ""),
            error="ExecutionContext.video_path is required",
        )

    from pipeline import VideoPipeline, PipelineConfig

    cfg = PipelineConfig(device=context.device, fps=context.fps, max_frames=context.max_frames)
    pipe = VideoPipeline(cfg)
    out_dir = str(Path(context.output_dir))
    op = instruction.operation
    params = getattr(instruction, "parameters", {}) or {}

    if op == "text_replacement":
        result = pipe.run_text_replacement(
            context.video_path,
            params.get("new_text", ""),
            out_dir,
            style_overrides=params.get("style_overrides"),
        )
    elif op == "text_removal":
        result = pipe.run_text_removal(context.video_path, out_dir)
    elif op in {"text_detection", "frame_extraction"}:
        result = pipe.run_text_extraction(context.video_path, out_dir)
    else:
        return ExecutionResult(
            ok=False,
            operation=op,
            error=f"text runner cannot handle '{op}'",
        )

    return ExecutionResult(
        ok=bool(result.success),
        operation=op,
        summary=getattr(instruction, "summary", op),
        output_video_path=result.output_video_path,
        artifacts={
            "frames_dir": result.frames_dir,
            "frames_processed": result.frames_processed,
            "processing_time": result.processing_time,
            "detections": len(result.detections or []),
        },
        error=result.error_message,
    )


for _op in ("text_replacement", "text_removal", "text_detection", "frame_extraction"):
    register_runner(_op, _text_pipeline_runner)


def _atmosphere_overlay_runner(instruction: Any, context: ExecutionContext) -> ExecutionResult:
    """Extract frames → grade/rain/lightning → MP4; optional rain bed under source audio."""

    video_path = context.video_path
    if not video_path or not Path(video_path).is_file():
        return ExecutionResult(
            ok=False,
            operation=getattr(instruction, "operation", "atmosphere_overlay"),
            error="ExecutionContext.video_path must point to an existing video file",
        )

    from utils.atmosphere_overlay import (
        apply_atmosphere_to_frames,
        mix_rain_under_original_audio,
        video_has_audio_stream,
    )
    from utils.video_processor import extract_frames, reassemble_frames

    params = dict(getattr(instruction, "parameters", {}) or {})
    params.update(dict(context.extra.get("atmosphere") or {}))

    out_root = Path(context.output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    frames_raw = out_root / "_atmosphere_extract"
    frames_out = out_root / "_atmosphere_frames"

    shutil.rmtree(frames_raw, ignore_errors=True)
    shutil.rmtree(frames_out, ignore_errors=True)

    fps = max(1, int(context.fps))
    if not extract_frames(str(video_path), str(frames_raw), fps=fps):
        return ExecutionResult(
            ok=False,
            operation="atmosphere_overlay",
            error="frame extraction failed",
        )

    frame_files = sorted(frames_raw.glob("frame_*.png"))
    if context.max_frames is not None:
        frame_files = frame_files[: int(context.max_frames)]
    if not frame_files:
        return ExecutionResult(
            ok=False,
            operation="atmosphere_overlay",
            error="no frames extracted",
        )

    seed = context.extra.get("atmosphere_seed", 42)
    try:
        seed_int = int(seed)
    except (TypeError, ValueError):
        seed_int = 42

    _, atm_notes = apply_atmosphere_to_frames(
        frame_files,
        frames_out,
        params,
        float(fps),
        seed=seed_int,
    )

    output_video = out_root / "atmosphere_output.mp4"
    if not reassemble_frames(str(frames_out), str(output_video), fps=fps):
        return ExecutionResult(
            ok=False,
            operation="atmosphere_overlay",
            error="video reassembly failed",
        )

    outp_str = str(output_video.resolve())
    bed_kind = str(atm_notes.get("audio_bed") or params.get("audio_bed") or "none").lower()
    mix_on = bool(params.get("mix_rain_audio", True)) and bed_kind in {"rain", "wind"}
    if mix_on and video_has_audio_stream(str(video_path)):
        muxed = out_root / "atmosphere_output.__rainbed__.mp4"
        mix_thunder = bool(
            atm_notes.get("mix_thunder_audio")
            and str(atm_notes.get("flash_kind") or "").lower() == "lightning"
        )
        burst_frames = atm_notes.get("lightning_burst_frames") or []
        fps_mux = float(atm_notes.get("atmosphere_fps") or fps)
        seed_mux = int(atm_notes.get("atmosphere_seed", seed_int))
        if mix_rain_under_original_audio(
            outp_str,
            str(muxed),
            bed_kind=bed_kind,
            mix_thunder=mix_thunder,
            lightning_burst_frames=burst_frames,
            fps=fps_mux,
            thunder_rng_seed=seed_mux + 913,
        ):
            try:
                Path(outp_str).unlink(missing_ok=True)
            except OSError:
                pass
            muxed.rename(outp_str)

    return ExecutionResult(
        ok=True,
        operation="atmosphere_overlay",
        summary=getattr(instruction, "summary", "Atmosphere overlay complete"),
        output_video_path=outp_str,
        artifacts={
            "frames_extracted": len(frame_files),
            "frames_written": len(list(frames_out.glob("frame_*.png"))),
            "notes": atm_notes,
            "extract_dir": str(frames_raw),
            "processed_dir": str(frames_out),
        },
    )


register_runner("atmosphere_overlay", _atmosphere_overlay_runner)


def _auto_commentary_runner(instruction: Any, context: ExecutionContext) -> ExecutionResult:
    """Sports-style commentary pipeline: analyze -> timeline -> script -> TTS -> ASS -> mux."""

    video_path = context.video_path
    if not video_path or not Path(video_path).is_file():
        return ExecutionResult(
            ok=False,
            operation="auto_commentary",
            error="ExecutionContext.video_path must point to an existing video file",
        )

    import uuid

    from core.commentary.config import CommentaryJobConfig
    from core.commentary.pipeline import run_commentary_job
    from core.storage import get_storage

    params = dict(getattr(instruction, "parameters", {}) or {})
    extras = dict(context.extra.get("commentary") or {})
    params.update(extras)

    out_root = Path(context.output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    storage = get_storage()
    job_id = str(uuid.uuid4())
    video_key = storage.job_key(job_id, Path(video_path).name or "source.mp4")
    dest = storage.local_path(video_key)
    if not dest.is_file():
        shutil.copy2(video_path, dest)

    keep_source = params.get("keep_source_audio")
    mute_game = True if keep_source is False else bool(params.get("mute_game_audio", True))

    config = CommentaryJobConfig.from_dict(
        job_id,
        video_key,
        {
            **params,
            "mute_game_audio": mute_game,
            "music_enabled": bool(params.get("music_enabled", False)),
            "music_track_id": params.get("music_track_id"),
            "must_include_joke": params.get("must_include_joke"),
            "must_sync_timestamp": params.get("must_sync_timestamp"),
            "device": context.device or "cpu",
        },
    )

    try:
        state = run_commentary_job(config, storage=storage)
    except Exception as exc:  # noqa: BLE001
        return ExecutionResult(
            ok=False,
            operation="auto_commentary",
            error=str(exc),
        )

    if state.stage != "done" or not state.output_video_key:
        return ExecutionResult(
            ok=False,
            operation="auto_commentary",
            error=state.error or "commentary pipeline failed",
        )

    output_src = storage.local_path(state.output_video_key)
    output_video = out_root / "commentary_output.mp4"
    shutil.copy2(output_src, output_video)

    script_payload = state.artifacts.get("scriptJson") or {}
    timeline_payload = {}
    if state.timeline_key:
        try:
            timeline_payload = storage.read_json(state.timeline_key)
        except Exception:
            timeline_payload = {}

    return ExecutionResult(
        ok=True,
        operation="auto_commentary",
        summary=getattr(instruction, "summary", "Auto-commentary complete"),
        output_video_path=str(output_video.resolve()),
        artifacts={
            "job_id": job_id,
            "timeline": timeline_payload.get("timeline", []),
            "lines": script_payload.get("lines", []),
            "script_validation": script_payload.get("validation_errors", []),
            "outputVideoUrl": state.artifacts.get("outputVideoUrl"),
            "subtitlesUrl": state.artifacts.get("subtitlesUrl"),
            "musicCredit": state.music_credit,
        },
    )


register_runner("auto_commentary", _auto_commentary_runner)


# Object, hair, and global color — frame pipeline (studio UI + API).
from core.runners.visual_edits import visual_frame_runner  # noqa: E402

for _visual_op in (
    "object_recolor",
    "object_remove",
    "object_replace_guided",
    "character_hair_recolor",
    "global_color_change",
):
    register_runner(_visual_op, visual_frame_runner)

# Premium code-gen runner (registers ``codegen_edit``; stub until sandbox ships).
import core.codegen  # noqa: E402, F401

from core.runners.timeline_edits import register_timeline_runners  # noqa: E402

register_timeline_runners(register_runner)
