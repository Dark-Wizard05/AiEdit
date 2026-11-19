"""
Frame-based visual edit runners (object, hair, global color).

Shared by core.engine and the studio API — logic extracted from app.py without Streamlit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2

from core.engine import ExecutionContext, ExecutionResult


ProgressCallback = Callable[[str, float, str], None]


def _noop_progress(stage: str, progress: float, message: str) -> None:
    del stage, progress, message


def _get_video_fps(video_path: str, fallback: int) -> float:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return float(fallback)
    fps = cap.get(cv2.CAP_PROP_FPS) or fallback
    cap.release()
    return float(fps) if fps > 0 else float(fallback)


def _extract_and_get_frames(
    video_path: str,
    out_root: Path,
    fps: int,
    progress: ProgressCallback,
) -> Tuple[List[Path], float]:
    from utils.video_processor import extract_frames

    frames_dir = out_root / "extracted_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    export_fps = _get_video_fps(video_path, fps)
    progress("extract", 0.1, f"Extracting frames at {export_fps:.1f} FPS…")
    if not extract_frames(video_path, str(frames_dir), fps=int(export_fps)):
        raise RuntimeError("Frame extraction failed")
    frame_files = sorted(frames_dir.glob("frame_*.png"))
    if not frame_files:
        raise RuntimeError("No frames extracted from video")
    progress("extract", 0.2, f"Extracted {len(frame_files)} frames")
    return frame_files, export_fps


def _reassemble_output(
    processed_dir: Path,
    video_path: str,
    out_root: Path,
    export_fps: float,
    progress: ProgressCallback,
) -> str:
    from utils.video_processor import reassemble_frames

    source = Path(video_path)
    output_path = out_root / f"{source.stem}_edited.mp4"
    progress("export", 0.92, "Assembling MP4…")
    if not reassemble_frames(
        str(processed_dir),
        str(output_path),
        fps=export_fps,
        codec="libx264",
        audio_source=video_path,
    ):
        raise RuntimeError("Video reassembly failed")
    progress("export", 1.0, "Export complete")
    return str(output_path.resolve())


def run_object_edit(
    frame_files: List[Path],
    temp_dir: Path,
    instruction: Any,
    device: str,
    progress: ProgressCallback,
    reference_image_paths: Optional[List[str]] = None,
) -> Tuple[List[Path], List[Path], Dict[str, Any]]:
    from utils.model_manager import ModelManager
    from utils.object_editor import ObjectEditOutcome, ObjectEditor, create_mask_overlay, load_reference_images
    from utils.video_mask_tracker import VideoMaskTracker

    processed_dir = temp_dir / "processed_frames"
    processed_dir.mkdir(exist_ok=True)
    masks_dir = temp_dir / "tracked_masks"
    masks_dir.mkdir(exist_ok=True)
    overlay_dir = temp_dir / "mask_previews"
    overlay_dir.mkdir(exist_ok=True)

    tracker = VideoMaskTracker(device=device, model_manager=ModelManager(device=device))
    editor = ObjectEditor(device=device)
    target_query = instruction.parameters["target_object"]

    def tracking_update(frame_idx: int, total_frames: int, source: str, score: float) -> None:
        p = 0.28 + (0.26 * (frame_idx + 1) / total_frames)
        progress("execute", p, f"Tracking frame {frame_idx + 1}/{total_frames} ({source} {score:.2f})")

    tracking_result = tracker.track_target(
        frame_files,
        target_query=target_query,
        masks_dir=masks_dir,
        use_precise_masks=True,
        redetect_interval=8,
        update_callback=tracking_update,
    )
    if not tracking_result.success:
        raise RuntimeError(tracking_result.error or "Object tracking failed")

    mask_preview_frames: List[Path] = []
    processed_frames: List[Path] = []
    notes = list(tracking_result.warnings)
    reference_images = load_reference_images(reference_image_paths)
    changed_frame_count = 0
    total_frames = max(1, len(tracking_result.frames))

    for idx, tracked in enumerate(tracking_result.frames):
        frame = cv2.imread(tracked.frame_path)
        mask = cv2.imread(tracked.mask_path, cv2.IMREAD_GRAYSCALE) if tracked.mask_path else None
        if frame is None or mask is None:
            continue

        if instruction.operation == "object_recolor":
            edited_frame, outcome = editor.recolor_object(
                frame, mask, instruction.parameters["target_color"]
            )
        elif instruction.operation == "object_remove":
            edited_frame, outcome = editor.remove_object(frame, mask, removal_mode="opencv")
        elif instruction.operation == "object_replace_guided":
            edited_frame, outcome = editor.replace_object(
                frame,
                mask,
                instruction.parameters["replacement_object"],
                reference_images=reference_images,
                removal_mode="opencv",
            )
        else:
            raise ValueError(f"Unsupported object operation: {instruction.operation}")

        notes.extend(outcome.warnings)
        if outcome.changed_pixels > 0:
            changed_frame_count += 1

        processed_path = processed_dir / Path(tracked.frame_path).name
        overlay_path = overlay_dir / f"overlay_{idx:04d}.png"
        cv2.imwrite(str(processed_path), edited_frame)
        cv2.imwrite(str(overlay_path), create_mask_overlay(frame, mask))
        processed_frames.append(processed_path)
        mask_preview_frames.append(overlay_path)

        p = 0.55 + (0.35 * (idx + 1) / total_frames)
        progress("execute", p, f"Applying edit {idx + 1}/{total_frames}")

    payload = tracking_result.to_dict()
    payload["changed_frame_count"] = changed_frame_count
    payload["operation"] = instruction.operation
    payload["notes"] = list(dict.fromkeys(n for n in notes if n))
    return processed_frames, mask_preview_frames, payload


def run_hair_recolor(
    frame_files: List[Path],
    processed_dir: Path,
    target_color: str,
    progress: ProgressCallback,
) -> Tuple[List[Path], int]:
    from utils.color_editor import change_hair_color

    processed_dir.mkdir(exist_ok=True)
    processed_frames: List[Path] = []
    changed_frames = 0
    total = len(frame_files)

    for idx, frame_path in enumerate(frame_files):
        image = cv2.imread(str(frame_path))
        result, _, stats = change_hair_color(image, target_color)
        if stats["changed_pixels"] > 0:
            changed_frames += 1
        output_path = processed_dir / frame_path.name
        cv2.imwrite(str(output_path), result)
        processed_frames.append(output_path)
        p = 0.3 + (0.6 * (idx + 1) / max(1, total))
        progress("execute", p, f"Hair recolor {idx + 1}/{total}")

    return processed_frames, changed_frames


def run_global_color_change(
    frame_files: List[Path],
    processed_dir: Path,
    source_color: str,
    target_color: str,
    tolerance: Any,
    progress: ProgressCallback,
) -> Tuple[List[Path], int]:
    from utils.color_editor import change_selected_color

    processed_dir.mkdir(exist_ok=True)
    processed_frames: List[Path] = []
    changed_frames = 0
    total = len(frame_files)

    for idx, frame_path in enumerate(frame_files):
        image = cv2.imread(str(frame_path))
        result, _, stats = change_selected_color(
            image, source_color, target_color, tolerance=tolerance
        )
        if stats["changed_pixels"] > 0:
            changed_frames += 1
        output_path = processed_dir / frame_path.name
        cv2.imwrite(str(output_path), result)
        processed_frames.append(output_path)
        p = 0.3 + (0.6 * (idx + 1) / max(1, total))
        progress("execute", p, f"Color change {idx + 1}/{total}")

    return processed_frames, changed_frames


def visual_frame_runner(instruction: Any, context: ExecutionContext) -> ExecutionResult:
    """Runner for object / hair / global_color operations."""

    video_path = context.video_path
    if not video_path or not Path(video_path).is_file():
        return ExecutionResult(
            ok=False,
            operation=getattr(instruction, "operation", ""),
            error="video_path must point to an existing file",
        )

    op = instruction.operation
    out_root = Path(context.output_dir).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    progress = context.extra.get("progress_callback") or _noop_progress
    device = context.device or "cpu"
    params = getattr(instruction, "parameters", {}) or {}

    try:
        frame_files, export_fps = _extract_and_get_frames(
            video_path, out_root, context.fps, progress
        )
        processed_dir = out_root / "processed_frames"
        artifacts: Dict[str, Any] = {"frames_extracted": len(frame_files)}

        if op in {"object_recolor", "object_remove", "object_replace_guided"}:
            _, mask_previews, tracking = run_object_edit(
                frame_files,
                out_root,
                instruction,
                device,
                progress,
                reference_image_paths=context.reference_image_paths or None,
            )
            artifacts["tracking"] = tracking
            artifacts["mask_preview_dir"] = str(out_root / "mask_previews")
            artifacts["mask_preview_count"] = len(mask_previews)
        elif op == "character_hair_recolor":
            _, changed = run_hair_recolor(
                frame_files, processed_dir, params["target_color"], progress
            )
            artifacts["changed_frames"] = changed
        elif op == "global_color_change":
            _, changed = run_global_color_change(
                frame_files,
                processed_dir,
                params["source_color"],
                params["target_color"],
                params.get("tolerance", "normal"),
                progress,
            )
            artifacts["changed_frames"] = changed
        else:
            return ExecutionResult(ok=False, operation=op, error=f"visual runner cannot handle '{op}'")

        output_video = _reassemble_output(
            processed_dir, video_path, out_root, export_fps, progress
        )
        return ExecutionResult(
            ok=True,
            operation=op,
            summary=getattr(instruction, "summary", op),
            output_video_path=output_video,
            artifacts=artifacts,
        )
    except Exception as exc:  # noqa: BLE001
        return ExecutionResult(
            ok=False,
            operation=op,
            summary="Visual edit failed",
            error=str(exc),
        )
