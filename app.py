"""
AiEdit Streamlit App - Interactive Video Editing Interface
"""

import streamlit as st
import cv2
import numpy as np
from pathlib import Path
import tempfile
import shutil
import difflib
import base64
import os
import hmac
from typing import Any, Dict, List, Optional, Tuple
import time
from logging_config import get_logger, log_session
from utils.prompt_parser import get_prompt_parser_status, normalize_text_for_matching, parse_edit_command

from ui.theme import inject_aiedit_theme, render_hero, render_card_open, render_card_close
from ui.atmosphere_panel import render_atmosphere_tab
from ui.commentary_panel import render_commentary_tab
from ui.prompt_queue import apply_pending_command, queue_command_prompt

# Initialize logger
logger = get_logger(__name__)

# Page configuration
st.set_page_config(
    page_title="AiEdit - AI Video Editor",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded"
)

inject_aiedit_theme()

# Initialize session state
if "video_uploaded" not in st.session_state:
    st.session_state.video_uploaded = False
if "processed_frames" not in st.session_state:
    st.session_state.processed_frames = None
if "detections" not in st.session_state:
    st.session_state.detections = None
if "processing_active" not in st.session_state:
    st.session_state.processing_active = False
if "should_cancel" not in st.session_state:
    st.session_state.should_cancel = False
if "command_input" not in st.session_state:
    st.session_state.command_input = ""
if "pending_command_input" not in st.session_state:
    st.session_state.pending_command_input = None
if "mask_preview_frames" not in st.session_state:
    st.session_state.mask_preview_frames = None
if "object_tracking" not in st.session_state:
    st.session_state.object_tracking = None
if "processing_notes" not in st.session_state:
    st.session_state.processing_notes = []
if "reference_image_path" not in st.session_state:
    st.session_state.reference_image_path = None
if "reference_image_paths" not in st.session_state:
    st.session_state.reference_image_paths = []
if "export_video_bytes" not in st.session_state:
    st.session_state.export_video_bytes = None
if "export_video_filename" not in st.session_state:
    st.session_state.export_video_filename = None
if "export_video_path" not in st.session_state:
    st.session_state.export_video_path = None
if "original_video_fps" not in st.session_state:
    st.session_state.original_video_fps = None
if "original_video_frame_count" not in st.session_state:
    st.session_state.original_video_frame_count = None
if "additional_guidance" not in st.session_state:
    st.session_state.additional_guidance = ""
if "preserve_original_style" not in st.session_state:
    st.session_state.preserve_original_style = True
if "apply_to_whole_clip" not in st.session_state:
    st.session_state.apply_to_whole_clip = True
if "preview_text_match_hint" not in st.session_state:
    st.session_state.preview_text_match_hint = None
if "upload_signature" not in st.session_state:
    st.session_state.upload_signature = None
if "aiedit_logged_in" not in st.session_state:
    st.session_state.aiedit_logged_in = False
# Atmosphere overrides: when empty the parser-inferred params are used as-is.
# UI writes user-tweaked knobs here; processing merges with parsed instruction.
if "atmosphere_overrides" not in st.session_state:
    st.session_state.atmosphere_overrides = {}
if "atmosphere_inferred_summary" not in st.session_state:
    st.session_state.atmosphere_inferred_summary = ""
if "atmosphere_tab_visible" not in st.session_state:
    st.session_state.atmosphere_tab_visible = False
if "atmosphere_last_inferred" not in st.session_state:
    st.session_state.atmosphere_last_inferred = {}
if "commentary_overrides" not in st.session_state:
    st.session_state.commentary_overrides = {}
if "commentary_inferred_summary" not in st.session_state:
    st.session_state.commentary_inferred_summary = ""
if "commentary_tab_visible" not in st.session_state:
    st.session_state.commentary_tab_visible = False
if "commentary_last_inferred" not in st.session_state:
    st.session_state.commentary_last_inferred = {}
if "commentary_last_artifacts" not in st.session_state:
    st.session_state.commentary_last_artifacts = {}


def _login_required() -> bool:
    return bool(os.getenv("AIEDIT_AUTH_PASSWORD", "").strip())


def _verify_login(username: str, password: str) -> bool:
    expected_user = os.getenv("AIEDIT_AUTH_USERNAME", "").strip()
    expected_pw = os.getenv("AIEDIT_AUTH_PASSWORD", "").strip()
    if not expected_pw:
        return True
    if expected_user and not hmac.compare_digest(username.strip(), expected_user):
        return False
    return hmac.compare_digest(password, expected_pw)


def _clear_session_job_state():
    """Clear video job data (e.g. logout or new upload)."""
    st.session_state.video_uploaded = False
    st.session_state.video_path = None
    st.session_state.temp_dir = None
    st.session_state.upload_signature = None
    st.session_state.processed_frames = None
    st.session_state.detections = None
    st.session_state.mask_preview_frames = None
    st.session_state.object_tracking = None
    st.session_state.processing_notes = []
    st.session_state.reference_image_path = None
    st.session_state.reference_image_paths = []
    st.session_state.export_video_bytes = None
    st.session_state.export_video_filename = None
    st.session_state.export_video_path = None
    st.session_state.original_video_fps = None
    st.session_state.original_video_frame_count = None
    st.session_state.preview_text_match_hint = None
    st.session_state.processing_active = False
    st.session_state.should_cancel = False
    st.session_state.atmosphere_overrides = {}
    st.session_state.atmosphere_inferred_summary = ""
    st.session_state.atmosphere_tab_visible = False
    st.session_state.atmosphere_last_inferred = {}
    st.session_state.commentary_overrides = {}
    st.session_state.commentary_inferred_summary = ""
    st.session_state.commentary_tab_visible = False
    st.session_state.commentary_last_inferred = {}
    st.session_state.commentary_last_artifacts = {}


def _export_download_payload() -> Tuple[Optional[bytes], Optional[str]]:
    """Prefer on-disk export so reruns and repeat downloads stay reliable."""
    path_str = st.session_state.get("export_video_path")
    name = st.session_state.get("export_video_filename") or "edited_video.mp4"
    if path_str:
        p = Path(path_str)
        if p.is_file():
            try:
                return p.read_bytes(), name
            except OSError:
                pass
    data = st.session_state.get("export_video_bytes")
    if data:
        return data, name
    return None, None


def clear_generated_files(directory: Path):
    if not directory.exists():
        return
    for pattern in ("frame_*.png", "mask_*.png", "overlay_*.png"):
        for path in directory.glob(pattern):
            path.unlink(missing_ok=True)


def format_unsupported_instruction_message(instruction: Any) -> str:
    """Human-readable explanation when the parsed edit cannot run (supported=False)."""

    if instruction is None:
        return "Unsupported command."

    lines: List[str] = []
    warns = list(getattr(instruction, "warnings", None) or [])
    if warns:
        lines.append(warns[0])
        if len(warns) > 1:
            lines.append("")
            lines.append("More detail:")
            for w in warns[1:]:
                lines.append(f"- {w}")

    meta = getattr(instruction, "metadata", None) or {}
    if isinstance(meta, dict):
        cq = meta.get("clarification_question")
        if cq:
            lines.append("")
            lines.append(f"Parser note: {cq}")

    lines.append("")
    lines.append(
        "AiEdit handles **local edits** (text, objects, hair, colors) and **atmosphere overlays** (grading + rain + lightning flashes) "
        "that keep your original motion and layout. "
        "It does **not** fully regenerate a scene as new video (that needs a different pipeline)."
    )
    lines.append("")
    lines.append("Try prompts like:")
    lines.append("- **Atmosphere / rain / thunder** (keeps gameplay geometry): e.g. “Add rain and battlefield grading without changing gameplay”")
    lines.append('- Replace "Hello" with "Goodbye"')
    lines.append("- Remove text from the video")
    lines.append("- Change Rapunzel's hair color to pink")
    lines.append("- Remove the fireworks behind the character")
    lines.append("- Replace the crown with a flower (upload a reference image first)")
    return "\n".join(lines)


def create_downloadable_video(temp_dir: Path, source_video_path: str, export_fps: float) -> Tuple[bytes, str, Path]:
    from utils.video_processor import reassemble_frames

    frames_dir = temp_dir / "processed_frames"
    if not frames_dir.exists() or not list(frames_dir.glob("frame_*.png")):
        frames_dir = temp_dir / "extracted_frames"

    source_path = Path(source_video_path)
    output_filename = f"{source_path.stem}_edited.mp4"
    output_path = temp_dir / output_filename

    success = reassemble_frames(
        str(frames_dir),
        str(output_path),
        fps=export_fps,
        codec="libx264",
        audio_source=source_video_path,
    )
    if not success or not output_path.exists():
        raise RuntimeError("Failed to assemble the edited video for download.")

    with open(output_path, "rb") as file_obj:
        return file_obj.read(), output_filename, output_path


PREVIEW_MAX_FRAMES = 15
PREVIEW_FRACTION = 0.05
PREVIEW_MAX_WIDTH = 380
PREVIEW_JPEG_QUALITY = 62


def _build_preview_quality_scores(num_frames: int) -> Optional[List[float]]:
    """Per-frame scores for picking representative previews (higher = better)."""
    if num_frames <= 0:
        return None
    scores = [0.0] * num_frames
    filled = False

    tracking = st.session_state.get("object_tracking") or {}
    t_frames = tracking.get("frames") or []
    if isinstance(t_frames, list) and len(t_frames) == num_frames:
        for i, fr in enumerate(t_frames):
            if isinstance(fr, dict):
                scores[i] = float(fr.get("score") or 0.0)
        filled = True

    if not filled:
        dets = st.session_state.get("detections")
        if isinstance(dets, list) and len(dets) == num_frames:
            hint = (st.session_state.get("preview_text_match_hint") or "").strip()
            hint_norm = normalize_text_for_matching(hint) if hint else ""
            for i, item in enumerate(dets):
                det_list = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else []
                if not isinstance(det_list, list):
                    continue
                if hint_norm:
                    best = 0.0
                    for d in det_list:
                        if not isinstance(d, dict):
                            continue
                        nt = normalize_text_for_matching(d.get("text") or "")
                        conf = float(d.get("confidence") or 0.0)
                        ratio = difflib.SequenceMatcher(None, hint_norm, nt).ratio()
                        best = max(best, ratio * conf + ratio * 0.25)
                    scores[i] = best
                else:
                    scores[i] = sum(
                        float(d.get("confidence") or 0.0) for d in det_list if isinstance(d, dict)
                    )
            filled = True

    return scores if filled else None


def select_preview_frame_indices(
    total_frames: int,
    max_frames: int = PREVIEW_MAX_FRAMES,
    fraction: float = PREVIEW_FRACTION,
    scores: Optional[List[float]] = None,
) -> List[int]:
    """~fraction of frames, capped at max_frames; prefer high-score segments when scores align."""
    if total_frames <= 0:
        return []
    n = min(max_frames, max(1, int(round(total_frames * fraction))))
    n = min(n, total_frames)
    if scores is None or len(scores) != total_frames:
        if n == 1:
            return [total_frames // 2]
        return sorted({int(round(i * (total_frames - 1) / (n - 1))) for i in range(n)})

    indices: List[int] = []
    seg_size = total_frames / n
    for k in range(n):
        start = int(k * seg_size)
        end = total_frames if k == n - 1 else min(total_frames, int((k + 1) * seg_size))
        if start >= end:
            continue
        best_i = max(range(start, end), key=lambda i: scores[i])
        indices.append(best_i)
    return sorted(set(indices))


def render_edited_frames_preview(processed_frames: List[Path]) -> None:
    """Low-res teaser grid; full quality only via download."""
    paths = [Path(p) for p in processed_frames if p is not None]
    if not paths:
        return

    n = len(paths)
    scores = _build_preview_quality_scores(n)
    idxs = select_preview_frame_indices(n, scores=scores)

    st.markdown("### Edited output preview")
    st.caption(
        f"Showing {len(idxs)} sample frame(s) from {n} total (~{100 * len(idxs) / n:.0f}% of this run). "
        "Preview is compressed and not full resolution — download the MP4 for the real output."
    )
    parts: List[str] = [
        '<div class="aiedit-preview-strip" style="display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start;">'
    ]
    for fi in idxs:
        img_bgr = cv2.imread(str(paths[fi]))
        if img_bgr is None:
            continue
        h, w = img_bgr.shape[:2]
        if w > PREVIEW_MAX_WIDTH:
            scale = PREVIEW_MAX_WIDTH / float(w)
            img_bgr = cv2.resize(
                img_bgr,
                (int(w * scale), int(h * scale)),
                interpolation=cv2.INTER_AREA,
            )
        ok, buf = cv2.imencode(
            ".jpg",
            img_bgr,
            [int(cv2.IMWRITE_JPEG_QUALITY), PREVIEW_JPEG_QUALITY],
        )
        if not ok:
            continue
        b64 = base64.b64encode(buf.tobytes()).decode("ascii")
        parts.append(
            f'<figure style="margin:0;max-width:{PREVIEW_MAX_WIDTH}px;">'
            f'<img src="data:image/jpeg;base64,{b64}" width="{PREVIEW_MAX_WIDTH}" '
            'draggable="false" alt="" '
            'style="display:block;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,0.12);"/>'
            f'<figcaption style="font-size:0.8rem;color:#a1a1aa;margin-top:6px;">Frame {fi + 1} of {n}</figcaption>'
            "</figure>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def create_precise_text_mask(image: np.ndarray, detection: Dict[str, Any]) -> np.ndarray:
    height, width = image.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)

    polygon = detection.get("polygon")
    if polygon is not None and len(polygon) >= 3:
        polygon_np = np.array(polygon, dtype=np.int32)
        cv2.fillPoly(mask, [polygon_np], 255)
    else:
        x1, y1, x2, y2 = detection["bbox"]
        mask[y1:y2, x1:x2] = 255

    x1, y1, x2, y2 = detection["bbox"]
    roi = image[max(0, y1):max(y1 + 1, y2), max(0, x1):max(x1 + 1, x2)]
    roi_mask = mask[max(0, y1):max(y1 + 1, y2), max(0, x1):max(x1 + 1, x2)]
    if roi.size == 0:
        return mask

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    value_channel = hsv[..., 2]
    saturation_channel = hsv[..., 1]
    bright_threshold = np.percentile(value_channel, 72)
    saturation_threshold = np.percentile(saturation_channel, 55)

    refined = (
        (value_channel >= bright_threshold)
        & (saturation_channel <= max(90, saturation_threshold + 10))
        & (roi_mask > 0)
    ).astype(np.uint8) * 255

    if int(np.count_nonzero(refined)) < 20:
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        refined = cv2.bitwise_and(otsu, roi_mask)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    refined = cv2.morphologyEx(refined, cv2.MORPH_CLOSE, kernel)
    refined = cv2.dilate(refined, kernel, iterations=1)

    full_mask = np.zeros((height, width), dtype=np.uint8)
    full_mask[y1:y2, x1:x2] = refined
    if int(np.count_nonzero(full_mask)) == 0:
        return mask
    return full_mask


def estimate_text_style(image: np.ndarray, bbox: Tuple[int, int, int, int], replacement_text: str) -> Dict[str, Any]:
    x1, y1, x2, y2 = bbox
    roi = image[max(0, y1):max(y1 + 1, y2), max(0, x1):max(x1 + 1, x2)]
    if roi.size == 0:
        return {
            "color": (255, 255, 255),
            "stroke_color": (0, 0, 0),
            "stroke_width": 2,
            "shadow_offset": (1, 1),
            "shadow_color": (0, 0, 0),
            "font_size": max(18, int((y2 - y1) * 0.9)),
        }

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    bright_mask = gray >= np.percentile(gray, 88)
    if int(np.count_nonzero(bright_mask)) > 0:
        bright_pixels = roi[bright_mask]
        mean_color = bright_pixels.mean(axis=0)
    else:
        mean_color = np.array([255, 255, 255], dtype=np.float32)

    color = tuple(int(np.clip(channel, 180, 255)) for channel in mean_color.tolist())
    stroke_color = (0, 0, 0)
    font_size = max(18, int((y2 - y1) * 0.88))
    if len(replacement_text) <= 4:
        font_size = int(font_size * 0.96)

    return {
        "color": color,
        "stroke_color": stroke_color,
        "stroke_width": max(1, int((y2 - y1) * 0.05)),
        "shadow_offset": (1, 1),
        "shadow_color": (15, 15, 15),
        "font_size": font_size,
        "width_scale": 0.82,
        "height_scale": 0.74,
    }


def replace_text_in_frames(frame_files, processed_dir: Path, old_text: str, new_text: str,
                           device: str, update_display,
                           preserve_style: bool = True,
                           apply_to_whole_clip: bool = True,
                           style_overrides: Optional[Dict[str, Any]] = None) -> Tuple[list, list, int]:
    from utils.text_detection_sam import TextDetectionSAM
    from utils.text_removal_overlay import TextRemovalAndOverlay

    detector = TextDetectionSAM(device=device)
    processor = TextRemovalAndOverlay(device=device)

    processed_frames = []
    all_detections = []
    replaced_regions = 0
    target_normalized = normalize_text_for_matching(old_text)

    total_frames = len(frame_files)
    for idx, frame_path in enumerate(frame_files):
        image = cv2.imread(str(frame_path))
        detections = detector.detect_text_regions(image)
        matched_detections = []
        result = image.copy()

        if not apply_to_whole_clip and replaced_regions > 0:
            output_path = processed_dir / frame_path.name
            cv2.imwrite(str(output_path), result)
            processed_frames.append(output_path)
            all_detections.append((output_path, matched_detections))
            progress = 0.35 + (0.60 * (idx + 1) / total_frames)
            update_display(
                "Step 2: Replacing Text",
                progress,
                f"Frame {idx + 1}/{total_frames} - keeping original frame after first edit",
            )
            continue

        for det in detections:
            detected_text = det["text"]
            detected_normalized = normalize_text_for_matching(detected_text)
            if not detected_normalized:
                continue
            similarity = difflib.SequenceMatcher(None, target_normalized, detected_normalized).ratio()
            token_subset_match = (
                target_normalized and detected_normalized
                and all(token in detected_normalized.split() for token in target_normalized.split())
            )
            if (
                target_normalized != detected_normalized
                and target_normalized not in detected_normalized
                and detected_normalized not in target_normalized
                and not token_subset_match
                and similarity < 0.72
            ):
                continue

            x1, y1, x2, y2 = det["bbox"]
            mask = create_precise_text_mask(image, det)

            ov = dict(style_overrides or {})
            effective_preserve = ov.get("preserve_style", preserve_style)
            if effective_preserve:
                style = estimate_text_style(image, det["bbox"], new_text)
            else:
                style = {
                    "color": (255, 255, 255),
                    "stroke_color": (0, 0, 0),
                    "stroke_width": 1,
                    "shadow_offset": (0, 0),
                    "shadow_color": None,
                    "font_size": max(18, int((y2 - y1) * 0.75)),
                    "width_scale": 0.88,
                    "height_scale": 0.82,
                }

            if "color" in ov:
                style["color"] = tuple(int(c) for c in ov["color"])
            if "stroke_color" in ov:
                style["stroke_color"] = tuple(int(c) for c in ov["stroke_color"])
            if "font_size" in ov:
                try:
                    style["font_size"] = max(6, int(ov["font_size"]))
                except (TypeError, ValueError):
                    pass
            if ov.get("font_weight") == "bold":
                style["stroke_width"] = max(int(style.get("stroke_width", 1)), 2)
            align = str(ov.get("align") or "center").lower()
            if align not in ("left", "center", "right"):
                align = "center"
            font_path = ov.get("font_path") or ov.get("font_family")

            result = processor.remove_text_opencv(result, mask)
            result = processor.overlay_text(
                result,
                new_text,
                det["bbox"],
                color=style["color"],
                font_size=style["font_size"],
                stroke_width=style["stroke_width"],
                stroke_color=style["stroke_color"],
                shadow_offset=style["shadow_offset"],
                shadow_color=style["shadow_color"],
                align=align,
                width_scale=style["width_scale"],
                height_scale=style["height_scale"],
                font_path=font_path if isinstance(font_path, str) else None,
            )
            matched_detections.append(det)
            replaced_regions += 1

        output_path = processed_dir / frame_path.name
        cv2.imwrite(str(output_path), result)
        processed_frames.append(output_path)
        all_detections.append((output_path, matched_detections))

        progress = 0.35 + (0.60 * (idx + 1) / total_frames)
        update_display(
            "Step 2: Replacing Text",
            progress,
            f"Frame {idx + 1}/{total_frames} - {len(matched_detections)} matching regions",
        )

    return processed_frames, all_detections, replaced_regions


def remove_text_from_frames(frame_files, processed_dir: Path, device: str, update_display) -> Tuple[list, list]:
    from utils.text_detection_sam import TextDetectionSAM
    from utils.text_removal_overlay import TextRemovalAndOverlay

    detector = TextDetectionSAM(device=device)
    processor = TextRemovalAndOverlay(device=device)

    processed_frames = []
    all_detections = []
    total_frames = len(frame_files)

    for idx, frame_path in enumerate(frame_files):
        image = cv2.imread(str(frame_path))
        detections = detector.detect_text_regions(image)
        mask = np.zeros((image.shape[0], image.shape[1]), dtype=np.uint8)
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            mask[y1:y2, x1:x2] = 255

        cleaned = processor.remove_text_opencv(image, mask) if mask.sum() > 0 else image
        output_path = processed_dir / frame_path.name
        cv2.imwrite(str(output_path), cleaned)
        processed_frames.append(output_path)
        all_detections.append((output_path, detections))

        progress = 0.40 + (0.55 * (idx + 1) / total_frames)
        update_display(
            "Step 3: Text Removal",
            progress,
            f"Frame {idx + 1}/{total_frames} - removed {len(detections)} text regions",
        )

    return processed_frames, all_detections


def recolor_hair_in_frames(frame_files, processed_dir: Path, target_color: str, update_display) -> Tuple[list, int]:
    from utils.color_editor import change_hair_color

    processed_frames = []
    changed_frames = 0
    total_frames = len(frame_files)

    for idx, frame_path in enumerate(frame_files):
        image = cv2.imread(str(frame_path))
        result, _, stats = change_hair_color(image, target_color)
        if stats["changed_pixels"] > 0:
            changed_frames += 1

        output_path = processed_dir / frame_path.name
        cv2.imwrite(str(output_path), result)
        processed_frames.append(output_path)

        progress = 0.30 + (0.65 * (idx + 1) / total_frames)
        update_display(
            "Step 2: Hair Color Change",
            progress,
            f"Frame {idx + 1}/{total_frames} - recolored {stats['changed_pixels']} pixels",
        )

    return processed_frames, changed_frames


def recolor_selected_color_in_frames(
    frame_files,
    processed_dir: Path,
    source_color: str,
    target_color: str,
    update_display,
    tolerance: Any = "normal",
) -> Tuple[list, int]:
    from utils.color_editor import change_selected_color

    processed_frames = []
    changed_frames = 0
    total_frames = len(frame_files)

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

        progress = 0.30 + (0.65 * (idx + 1) / total_frames)
        update_display(
            "Step 2: Color Change",
            progress,
            f"Frame {idx + 1}/{total_frames} - recolored {stats['changed_pixels']} pixels",
        )

    return processed_frames, changed_frames


def run_object_edit_pipeline(
    frame_files,
    temp_dir: Path,
    instruction,
    device: str,
    update_display,
    reference_image_paths: Optional[List[str]] = None,
    apply_to_whole_clip: bool = True,
) -> Tuple[list, list, Dict]:
    from utils.model_manager import ModelManager
    from utils.object_editor import ObjectEditOutcome, ObjectEditor, create_mask_overlay, load_reference_images
    from utils.video_mask_tracker import VideoMaskTracker

    processed_dir = temp_dir / "processed_frames"
    processed_dir.mkdir(exist_ok=True)
    masks_dir = temp_dir / "tracked_masks"
    masks_dir.mkdir(exist_ok=True)
    overlay_dir = temp_dir / "mask_previews"
    overlay_dir.mkdir(exist_ok=True)

    model_manager = ModelManager(device=device)
    tracker = VideoMaskTracker(device=device, model_manager=model_manager)
    editor = ObjectEditor(device=device)
    target_query = instruction.parameters["target_object"]

    def tracking_update(frame_idx: int, total_frames: int, source: str, score: float):
        progress = 0.28 + (0.26 * (frame_idx + 1) / total_frames)
        update_display(
            "Step 2: Tracking Target",
            progress,
            f"Frame {frame_idx + 1}/{total_frames} - {source} score {score:.2f}",
        )

    tracking_result = tracker.track_target(
        frame_files,
        target_query=target_query,
        masks_dir=masks_dir,
        use_precise_masks=True,
        redetect_interval=8,
        update_callback=tracking_update,
    )
    if not tracking_result.success:
        raise ValueError(tracking_result.error or "Object tracking failed.")

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

        should_edit_this_frame = apply_to_whole_clip or changed_frame_count == 0
        if not should_edit_this_frame:
            edited_frame = frame.copy()
            outcome = ObjectEditOutcome(changed_pixels=0, warnings=[])
        else:
            if instruction.operation == "object_recolor":
                edited_frame, outcome = editor.recolor_object(
                    frame,
                    mask,
                    instruction.parameters["target_color"],
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
                raise ValueError(f"Unsupported object edit operation: {instruction.operation}")

        notes.extend(outcome.warnings)
        if outcome.changed_pixels > 0:
            changed_frame_count += 1

        processed_path = processed_dir / Path(tracked.frame_path).name
        overlay_path = overlay_dir / f"overlay_{idx:04d}.png"
        cv2.imwrite(str(processed_path), edited_frame)
        cv2.imwrite(str(overlay_path), create_mask_overlay(frame, mask))
        processed_frames.append(processed_path)
        mask_preview_frames.append(overlay_path)

        progress = 0.55 + (0.40 * (idx + 1) / total_frames)
        update_display(
            "Step 3: Applying Edit",
            progress,
            f"Frame {idx + 1}/{total_frames} - edited {outcome.changed_pixels} masked pixels",
        )

    tracking_payload = tracking_result.to_dict()
    tracking_payload["changed_frame_count"] = changed_frame_count
    tracking_payload["operation"] = instruction.operation
    tracking_payload["notes"] = list(dict.fromkeys(note for note in notes if note))
    return processed_frames, mask_preview_frames, tracking_payload

# ==================== Login (optional) ====================
if _login_required() and not st.session_state.aiedit_logged_in:
    render_hero("Sign in to start editing with prompts, atmosphere tabs, and local AI tools.")
    with st.container():
        render_card_open("Sign in")
        with st.form("aiedit_login_form"):
            lu = os.getenv("AIEDIT_AUTH_USERNAME", "").strip()
            if lu:
                username = st.text_input("Username")
            else:
                username = ""
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary")
            if submitted:
                u = (username or "").strip() if lu else ""
                if _verify_login(u, password):
                    st.session_state.aiedit_logged_in = True
                    st.rerun()
                else:
                    st.error("Invalid username or password.")
        render_card_close()
    st.caption(
        "Login is enforced when the environment variable `AIEDIT_AUTH_PASSWORD` is set. "
        "Optional: `AIEDIT_AUTH_USERNAME` for username + password."
    )
    st.stop()

# ==================== Sidebar ====================
st.sidebar.markdown("## Studio")

if _login_required():
    if st.sidebar.button("Sign out", use_container_width=True, key="aiedit_sign_out"):
        st.session_state.aiedit_logged_in = False
        _clear_session_job_state()
        st.rerun()
    st.sidebar.caption("Signed in. Export files stay available until you upload a new video or sign out.")
else:
    st.sidebar.caption("Auth is off (set `AIEDIT_AUTH_PASSWORD` to require sign-in).")

# Stop/Cancel Controls
if st.session_state.processing_active:
    st.sidebar.warning("⏳ **Processing in Progress**")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        if st.button("⏹️ Stop Processing", use_container_width=True, key="stop_btn"):
            st.session_state.should_cancel = True
            st.info("⏹️ Stopping processing... Please wait for current operation to finish.")
    with col2:
        if st.button("🔄 Hard Reset", use_container_width=True, key="reset_btn"):
            st.session_state.processing_active = False
            st.session_state.should_cancel = False
            st.rerun()

# Add processing info banner
st.sidebar.info("""
### ⏳ About Processing

The app processes videos step-by-step:
1. **Extract Frames** (~1s)
2. **Load ML Models** (~30-60s first run)
3. **Detect/Process Text** (varies)
4. **Reassemble Video** (~10-30s)

**Watch the progress bar and logs below** - you'll see real-time updates!

**To Stop:**
- Click ⏹️ **Stop Processing** button (above)
- Or press **Ctrl+C** in terminal
- Or close the browser tab

*First run will be slower due to model downloads.*
""")

st.sidebar.markdown("### Processing Options")
device = st.sidebar.radio(
    "Processing Device:",
    options=["CPU", "GPU"],
    help="CPU is slower but works everywhere. GPU requires CUDA."
)
device = device.lower()

processing_mode = st.sidebar.selectbox(
    "Processing Mode:",
    options=["Frame Extraction", "Text Detection", "Text Removal & Overlay", "Full Pipeline"],
    help="Choose what processing to apply to the video"
)

st.sidebar.markdown("### Advanced Settings")
fps = st.sidebar.slider("Target FPS:", 1, 60, 30, help="Frames per second for extraction")
confidence_threshold = st.sidebar.slider("Confidence Threshold:", 0.0, 1.0, 0.5, 
                                        help="Minimum confidence for text detection")

st.sidebar.markdown("---")
st.sidebar.markdown("### About")
st.sidebar.info("""
**AiEdit** - AI-Powered Video Editing

**Features:**
- 🎥 Extract frames from videos
- 📝 Detect text with OCR & SAM
- 🗑️ Remove text intelligently
- ✍️ Overlay new text
- 🎨 Prompt-driven hair and object edits

**Supported Formats:**
- MP4, AVI, MOV, MKV

**Models Used:**
- EasyOCR for text detection
- Grounding DINO for object prompts
- Segment Anything or GrabCut for masks
- OpenCV + local heuristics for free edits
""")

# ==================== Main Content ====================
show_atmosphere_tab = bool(st.session_state.get("atmosphere_tab_visible"))
show_commentary_tab = bool(st.session_state.get("commentary_tab_visible"))
render_hero(
    show_atmosphere_tab=show_atmosphere_tab,
    show_commentary_tab=show_commentary_tab,
)

atm_inferred: Optional[Dict[str, Any]] = None
atm_active = False
atm_summary = ""
commentary_inferred: Optional[Dict[str, Any]] = None
commentary_active = False
commentary_summary = ""
instruction = None
effective_command = ""
has_prompt = False

tab_labels = ["✨ Edit"]
if show_atmosphere_tab:
    tab_labels.append("🌦️ Atmosphere")
if show_commentary_tab:
    tab_labels.append("🎙️ Commentary")
tab_labels.append("📦 Output")

_tabs = st.tabs(tab_labels)
_tab_iter = iter(_tabs)
tab_edit = next(_tab_iter)
tab_atmosphere = next(_tab_iter) if show_atmosphere_tab else None
tab_commentary = next(_tab_iter) if show_commentary_tab else None
tab_output = next(_tab_iter)

with tab_edit:
    col1, col2 = st.columns([2, 3])

    with col1:
        render_card_open("Upload")
        uploaded_file = st.file_uploader(
            "Choose a video file",
            type=["mp4", "avi", "mov", "mkv"],
            help="Upload a video file to process",
            label_visibility="collapsed",
        )

        if uploaded_file is not None:
            sig = (uploaded_file.name, uploaded_file.size)
            if st.session_state.get("upload_signature") != sig:
                st.session_state.upload_signature = sig
                temp_dir = tempfile.mkdtemp()
                video_path = Path(temp_dir) / uploaded_file.name
                with open(video_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                st.session_state.video_uploaded = True
                st.session_state.video_path = str(video_path)
                st.session_state.temp_dir = temp_dir
                st.session_state.original_video_fps = None
                st.session_state.original_video_frame_count = None
                st.session_state.processed_frames = None
                st.session_state.detections = None
                st.session_state.mask_preview_frames = None
                st.session_state.object_tracking = None
                st.session_state.processing_notes = []
                st.session_state.reference_image_path = None
                st.session_state.reference_image_paths = []
                st.session_state.export_video_bytes = None
                st.session_state.export_video_filename = None
                st.session_state.export_video_path = None
                st.session_state.additional_guidance = ""
                st.session_state.preserve_original_style = True
                st.session_state.apply_to_whole_clip = True
                st.session_state.preview_text_match_hint = None
                st.session_state.atmosphere_overrides = {}
                st.session_state.atmosphere_inferred_summary = ""
                st.session_state.atmosphere_tab_visible = False
                st.session_state.atmosphere_last_inferred = {}
                st.session_state.commentary_overrides = {}
                st.session_state.commentary_inferred_summary = ""
                st.session_state.commentary_tab_visible = False
                st.session_state.commentary_last_inferred = {}
                st.session_state.commentary_last_artifacts = {}

                with st.spinner("Reading video information..."):
                    cap = cv2.VideoCapture(str(video_path))
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    video_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()
                    st.session_state.original_video_fps = video_fps
                    st.session_state.original_video_frame_count = total_frames
                    st.session_state.video_display_width = frame_width
                    st.session_state.video_display_height = frame_height

                st.success("Video uploaded")
                st.markdown(
                    f"**{total_frames / max(video_fps, 1e-6):.1f}s** · "
                    f"**{frame_width}×{frame_height}** · "
                    f"**{video_fps:.1f} fps** · "
                    f"**{uploaded_file.size / (1024 * 1024):.1f} MB**"
                )
            else:
                vp = st.session_state.get("video_path")
                if vp and Path(vp).exists():
                    tf = int(st.session_state.get("original_video_frame_count") or 0)
                    vf = float(st.session_state.get("original_video_fps") or 30.0)
                    fw = int(st.session_state.get("video_display_width") or 0)
                    fh = int(st.session_state.get("video_display_height") or 0)
                    dur = tf / max(vf, 1e-6) if tf else 0.0
                    res = f"{fw}×{fh}" if fw and fh else "—"
                    st.success("Video ready — export stays on the Output tab.")
                    st.markdown(
                        f"**{uploaded_file.name}** · **{dur:.1f}s** · **{res}** · **{vf:.1f} fps**"
                    )
                else:
                    st.session_state.upload_signature = None
                    st.warning("Previous file missing from disk. Upload again.")
                    st.rerun()
        else:
            if st.session_state.upload_signature is not None:
                st.session_state.upload_signature = None
                _clear_session_job_state()
            st.caption("MP4, AVI, MOV, or MKV")
        render_card_close()

    with col2:
        render_card_open("Prompt")
        st.caption("Describe your edit in natural language — the parser plans the operation.")
        apply_pending_command()
        st.text_area(
            "Enter your editing command:",
            placeholder="e.g. Change hair to pink · Remove all text · Heavy thunderstorm with rain",
            height=100,
            label_visibility="collapsed",
            key="command_input",
        )

        _guidance_raw = st.text_area(
            "Clarify (optional)",
            value=st.session_state.additional_guidance,
            placeholder="Extra details: match original font, whole clip, keep centered…",
            height=72,
            label_visibility="visible",
            key="additional_guidance_widget",
        )
        st.session_state.additional_guidance = _guidance_raw
        additional_guidance = _guidance_raw.strip()

        clarify_col1, clarify_col2 = st.columns(2)
        with clarify_col1:
            st.session_state.preserve_original_style = st.checkbox(
                "Match original style",
                value=st.session_state.preserve_original_style,
            )
        with clarify_col2:
            st.session_state.apply_to_whole_clip = st.checkbox(
                "Whole clip",
                value=st.session_state.apply_to_whole_clip,
            )

        st.markdown("**Quick start**")
        q1, q2, q3, q4, q5 = st.columns(5)
        with q1:
            if st.button("Extract", use_container_width=True, key="qc_extract"):
                queue_command_prompt("Extract frames")
        with q2:
            if st.button("Detect text", use_container_width=True, key="qc_detect"):
                queue_command_prompt("Detect text in video")
        with q3:
            if st.button("Remove text", use_container_width=True, key="qc_remove"):
                queue_command_prompt("Remove text from video")
        with q4:
            if st.button("Storm", use_container_width=True, key="qc_storm"):
                queue_command_prompt(
                    "Heavy thunderstorm with lightning and rain audio. "
                    "Atmosphere overlay only — keep gameplay geometry unchanged."
                )
        with q5:
            if st.button("Commentary", use_container_width=True, key="qc_commentary"):
                queue_command_prompt(
                    "Add funny hype sports commentary over this clip — focus on the action, not the scoreboard. "
                    "Mute the original audio."
                )

        command_input = st.session_state.command_input.strip()
        if command_input and additional_guidance:
            effective_command = f"{command_input}\nAdditional guidance: {additional_guidance}"
        elif command_input:
            effective_command = command_input
        elif additional_guidance:
            effective_command = additional_guidance
        else:
            effective_command = ""

        has_prompt = bool(command_input) or bool(additional_guidance)
        instruction = parse_edit_command(effective_command) if effective_command else None

        if instruction:
            if instruction.supported:
                st.markdown(
                    f'<span class="aiedit-status-ok">✓ {instruction.summary}</span>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<span class="aiedit-status-warn">⚠ {instruction.summary}</span>',
                    unsafe_allow_html=True,
                )
            parser_backend = instruction.metadata.get("parser_backend")
            parser_confidence = instruction.metadata.get("confidence")
            if parser_backend:
                st.caption(
                    f"Parser: `{parser_backend}`"
                    + (
                        f" · confidence `{parser_confidence:.2f}`"
                        if isinstance(parser_confidence, (int, float))
                        else ""
                    )
                )
            for warning in instruction.warnings:
                st.caption(f"· {warning}")
            with st.expander("Parser status"):
                st.json(get_prompt_parser_status())
            if instruction.operation in {
                "object_recolor",
                "object_remove",
                "object_replace_guided",
                "character_hair_recolor",
            }:
                from utils.model_manager import ModelManager

                with st.expander("Object backend"):
                    st.json(ModelManager(device=device).describe_stack())

            if instruction.operation == "atmosphere_overlay":
                atm_inferred = dict(instruction.parameters or {})
                atm_active = True
                atm_summary = instruction.summary
                st.session_state.atmosphere_inferred_summary = instruction.summary
                if show_atmosphere_tab:
                    st.caption("Fine-tune on the **Atmosphere** tab, then re-process if needed.")
                else:
                    st.caption(
                        "Atmosphere edit planned — run **Process video**. "
                        "The **Atmosphere** tab unlocks after your first atmosphere export."
                    )

            elif instruction.operation == "auto_commentary":
                commentary_inferred = dict(instruction.parameters or {})
                commentary_active = True
                commentary_summary = instruction.summary
                st.session_state.commentary_inferred_summary = instruction.summary
                if show_commentary_tab:
                    st.caption("Tweak voice / tone on the **Commentary** tab, then re-process if needed.")
                else:
                    st.caption(
                        "Commentary edit planned — run **Process video**. "
                        "The **Commentary** tab unlocks after your first commentary export."
                    )

        render_card_close()

        render_card_open("Reference images")
        reference_files = st.file_uploader(
            "Add up to 5 reference images",
            type=["png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            label_visibility="collapsed",
        )
        if reference_files and st.session_state.video_uploaded:
            saved_paths: List[str] = []
            references_dir = Path(st.session_state.temp_dir) / "references"
            references_dir.mkdir(parents=True, exist_ok=True)
            for index, reference_file in enumerate(reference_files[:5]):
                reference_path = references_dir / f"reference_{index+1}_{reference_file.name}"
                with open(reference_path, "wb") as file_obj:
                    file_obj.write(reference_file.getbuffer())
                saved_paths.append(str(reference_path))
            st.session_state.reference_image_paths = saved_paths
            st.session_state.reference_image_path = saved_paths[0] if saved_paths else None
            st.caption(f"{len(saved_paths)} reference image(s) loaded.")
        elif not reference_files:
            st.session_state.reference_image_paths = []
            st.session_state.reference_image_path = None
        render_card_close()

        with st.expander("Processing timeline"):
            st.markdown(
                "| Step | Typical time |\n|------|-------------|\n"
                "| Extract | ~1–3 s |\n| Atmosphere | ~2–12 min |\n"
                "| Text / object ML | ~1–5 min |\n| Reassemble | ~10–30 s |"
            )

        st.markdown("---")
        if st.session_state.video_uploaded and has_prompt:
            if show_atmosphere_tab:
                st.caption("Adjust atmosphere on its tab if needed, then re-process.")
            else:
                st.caption("Ready when you are — click below to start.")
            if st.button("⚡ Process video", use_container_width=True, type="primary", key="process_video_go"):
                # Mark processing as active
                st.session_state.processing_active = True
                st.session_state.should_cancel = False
            
                # Log session start
                log_session(
                    st.session_state.video_path,
                    effective_command,
                    "started",
                    {
                        "device": device,
                        "preserve_original_style": st.session_state.preserve_original_style,
                        "apply_to_whole_clip": st.session_state.apply_to_whole_clip,
                        "reference_images": len(st.session_state.reference_image_paths),
                    }
                )
                logger.info(f"Processing started: {effective_command}")
            
                # Create a status container with real-time updates
                with st.status("Processing video...", expanded=True) as status:
                    import time as time_module
                    start_time = time_module.time()
                
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    log_container = st.empty()
                    time_display = st.empty()
                
                    def update_display(step: str, progress: float, log_msg: str = ""):
                        """Update the display with current step and elapsed time"""
                        # Check if user requested cancellation
                        if st.session_state.should_cancel:
                            raise KeyboardInterrupt("[User cancelled processing]")
                    
                        elapsed = time_module.time() - start_time
                        mins, secs = int(elapsed) // 60, int(elapsed) % 60
                    
                        status_text.markdown(f"**{step}** ⏱️ {mins}m {secs}s elapsed")
                        progress_bar.progress(min(progress, 1.0))
                    
                        if log_msg:
                            log_container.info(f"📋 {log_msg}")
                
                    try:
                        if not instruction or not instruction.supported:
                            st.session_state.processing_active = False
                            msg = (
                                format_unsupported_instruction_message(instruction)
                                if instruction
                                else "No valid edit plan for this prompt."
                            )
                            status.update(label="⚠️ Prompt not supported", state="error")
                            st.error(msg)
                            log_session(
                                st.session_state.video_path,
                                effective_command,
                                "error",
                                {"error": "unsupported_instruction", "detail": msg[:500]},
                            )
                            st.stop()

                        if instruction.operation == "auto_commentary":
                            from core.engine import ExecutionContext, execute as engine_execute

                            update_display(
                                "Step 1/4: Sampling clip for commentary",
                                0.10,
                                "Extracting low-fps frames for visual analysis...",
                            )

                            commentary_extras = dict(st.session_state.get("commentary_overrides") or {})

                            ctx = ExecutionContext(
                                video_path=st.session_state.video_path,
                                output_dir=str(Path(st.session_state.temp_dir) / "commentary_run"),
                                device=device,
                                fps=int(st.session_state.get("original_video_fps") or fps),
                                extra={"commentary": commentary_extras},
                            )
                            update_display("Step 2/4: Reading on-screen details", 0.40, "OCR over sampled frames...")
                            result = engine_execute(instruction, ctx)
                            if not result.ok or not result.output_video_path:
                                err = result.error or "commentary pipeline failed"
                                st.session_state.processing_active = False
                                status.update(label="❌ Commentary failed", state="error")
                                st.error(f"❌ {err}")
                                log_session(
                                    st.session_state.video_path,
                                    effective_command,
                                    "error",
                                    {"error": err},
                                )
                                st.stop()

                            update_display(
                                "Step 3/4: Voicing & mixing",
                                0.85,
                                "TTS rendered, ffmpeg mux complete.",
                            )

                            artifacts = dict(result.artifacts or {})
                            st.session_state.commentary_last_artifacts = artifacts
                            st.session_state.commentary_last_inferred = dict(instruction.parameters or {})
                            st.session_state.commentary_inferred_summary = instruction.summary
                            st.session_state.commentary_tab_visible = True
                            if not show_commentary_tab:
                                st.session_state["_pending_commentary_tab_rerun"] = True

                            export_path = Path(result.output_video_path)
                            export_filename = export_path.name
                            st.session_state.export_video_path = str(export_path)
                            st.session_state.export_video_filename = export_filename
                            st.session_state.export_video_bytes = None
                            st.session_state.processed_frames = None
                            st.session_state.processing_notes = [
                                {
                                    "events_detected": len(artifacts.get("events") or []),
                                    "lines_generated": len(artifacts.get("lines") or []),
                                    "duration": artifacts.get("duration"),
                                    "sample_fps": artifacts.get("sample_fps"),
                                }
                            ]

                            update_display(
                                "Complete ✅",
                                1.0,
                                f"[OK] Commentary ready - {len(artifacts.get('lines') or [])} lines",
                            )
                            status.update(label="✅ Commentary complete", state="complete")

                            logger.info(
                                "Auto-commentary completed: %s lines from %s events",
                                len(artifacts.get("lines") or []),
                                len(artifacts.get("events") or []),
                            )
                            log_session(
                                st.session_state.video_path,
                                effective_command,
                                "completed",
                                {
                                    "operation": "auto_commentary",
                                    "lines": len(artifacts.get("lines") or []),
                                    "events": len(artifacts.get("events") or []),
                                },
                            )
                            st.session_state.processing_active = False
                            if st.session_state.pop("_pending_commentary_tab_rerun", False):
                                st.rerun()
                            st.stop()

                        # Import modules
                        update_display("Step 0: Loading modules", 0.05, "Importing video processing utilities...")
                        from utils.video_processor import extract_frames
                    
                        frames_dir = Path(st.session_state.temp_dir) / "extracted_frames"
                        frames_dir.mkdir(exist_ok=True)
                        processed_dir = Path(st.session_state.temp_dir) / "processed_frames"
                        processed_dir.mkdir(exist_ok=True)
                        clear_generated_files(frames_dir)
                        clear_generated_files(processed_dir)
                        clear_generated_files(Path(st.session_state.temp_dir) / "tracked_masks")
                        clear_generated_files(Path(st.session_state.temp_dir) / "mask_previews")
                    
                        # Step 1: Extract frames
                        extraction_fps = st.session_state.get("original_video_fps") or fps
                        update_display("Step 1/4: Extracting frames", 0.1, f"Reading {extraction_fps:.2f} FPS from video...")
                        success = extract_frames(st.session_state.video_path, str(frames_dir), fps=extraction_fps)
                        if not success:
                            st.error("❌ Failed to extract frames. Check video format and file integrity.")
                            st.info("Supported formats: MP4, AVI, MOV, MKV")
                            st.stop()
                    
                        update_display("Step 1: Frame Extraction", 0.25, f"Extracted frames")
                    
                        # Get frame list
                        frame_files = sorted(frames_dir.glob("frame_*.png"))
                        if not frame_files:
                            st.error("❌ No frames extracted. Video may be invalid or corrupted.")
                            st.stop()
                    
                        update_display("Step 1: Frame Extraction", 0.25, f"[OK] {len(frame_files)} frames ready for processing")
                        st.session_state.frame_files = frame_files
                        st.session_state.detections = None
                        st.session_state.mask_preview_frames = None
                        st.session_state.object_tracking = None
                        st.session_state.processing_notes = []
                        st.session_state.preview_text_match_hint = None
                        st.session_state.export_video_bytes = None
                        st.session_state.export_video_filename = None
                        st.session_state.export_video_path = None
                    
                        # Step 2: Process based on parsed instruction
                        if instruction.operation == "frame_extraction":
                            update_display("Complete ✅", 1.0, "Frame extraction finished!")
                            st.session_state.processed_frames = frame_files
                            status.update(label="✅ Processing Complete", state="complete")
                        
                        elif instruction.operation == "text_replacement":
                            update_display("Step 2: Loading Model", 0.30, "Loading EasyOCR (may take 30-60s on first run)...")
                            processed_frames, all_detections, replaced_regions = replace_text_in_frames(
                                frame_files,
                                processed_dir,
                                instruction.parameters["old_text"],
                                instruction.parameters["new_text"],
                                device,
                                update_display,
                                preserve_style=st.session_state.preserve_original_style,
                                apply_to_whole_clip=st.session_state.apply_to_whole_clip,
                                style_overrides=instruction.parameters.get("style_overrides"),
                            )
                            st.session_state.detections = all_detections
                            st.session_state.preview_text_match_hint = instruction.parameters.get("old_text")
                            st.session_state.processed_frames = processed_frames
                            if replaced_regions == 0:
                                st.warning("No matching text was found, so the output frames are unchanged.")
                            update_display("Complete ✅", 1.0, f"[OK] Text replacement finished - {replaced_regions} regions updated")
                            status.update(label="✅ Processing Complete", state="complete")
                        
                        elif instruction.operation == "text_detection":
                            update_display("Step 2: Loading Model", 0.30, "Loading EasyOCR (may take 30-60s on first run)...")
                            try:
                                from utils.text_detection_sam import TextDetectionSAM
                                detector = TextDetectionSAM(device=device)
                                update_display("Step 2: Model Ready", 0.35, "EasyOCR loaded - starting text detection...")
                            except Exception as e:
                                st.error(f"Failed to load text detection model: {str(e)}")
                                st.info("Note: EasyOCR model downloads automatically on first run (~100MB)")
                                st.stop()
                        
                            all_detections = []
                            num_frames = len(frame_files)
                            frames_to_process = min(10, num_frames)
                        
                            for idx, frame_path in enumerate(frame_files[:frames_to_process]):
                                # Check if user requested cancellation
                                if st.session_state.should_cancel:
                                    st.warning("⏹️ Processing stopped by user")
                                    st.session_state.processing_active = False
                                    st.stop()
                            
                                try:
                                    image = cv2.imread(str(frame_path))
                                    detections = detector.detect_text_regions(image)
                                    all_detections.append((frame_path, detections))
                                
                                    progress = 0.35 + (0.40 * (idx + 1) / frames_to_process)
                                    update_display(
                                        f"Step 2: Text Detection",
                                        progress,
                                        f"Frame {idx+1}/{frames_to_process} - {len(detections)} text regions found"
                                    )
                                except Exception as e:
                                    st.warning(f"Error processing frame {idx}: {str(e)}")
                        
                            st.session_state.detections = all_detections
                            st.session_state.processed_frames = frame_files
                            update_display("Complete ✅", 1.0, f"[OK] Text detection finished - {len(all_detections)} regions detected")
                            status.update(label="✅ Processing Complete", state="complete")
                        
                        elif instruction.operation == "text_removal":
                            update_display("Step 2: Loading Models", 0.30, "Loading OCR and text removal models...")
                            processed_frames, all_detections = remove_text_from_frames(
                                frame_files,
                                processed_dir,
                                device,
                                update_display,
                            )
                            st.session_state.detections = all_detections
                            st.session_state.processed_frames = processed_frames
                            update_display("Complete ✅", 1.0, f"[OK] Text removal finished - {len(processed_frames)} frames processed")
                            status.update(label="✅ Processing Complete", state="complete")

                        elif instruction.operation == "character_hair_recolor":
                            target_color = instruction.parameters["target_color"]
                            update_display("Step 2: Hair Color Change", 0.30, f"Changing hair color to {target_color}...")
                            processed_frames, changed_frames = recolor_hair_in_frames(
                                frame_files,
                                processed_dir,
                                target_color,
                                update_display,
                            )
                            st.session_state.processed_frames = processed_frames
                            if changed_frames == 0:
                                st.warning("No hair region was confidently detected in these frames. Try a closer shot or a clip with a clear face.")
                            update_display("Complete ✅", 1.0, f"[OK] Hair color edit finished - {changed_frames}/{len(frame_files)} frames changed")
                            status.update(label="✅ Processing Complete", state="complete")

                        elif instruction.operation in {"object_recolor", "object_remove", "object_replace_guided"}:
                            if (
                                instruction.operation == "object_replace_guided"
                                and not st.session_state.get("reference_image_paths")
                            ):
                                st.warning("No reference image was provided. The object will be removed, but replacement quality will be limited.")
                            update_display("Step 2: Loading Object Models", 0.28, "Loading grounding, mask, and edit backends...")
                            processed_frames, mask_preview_frames, tracking_payload = run_object_edit_pipeline(
                                frame_files,
                                Path(st.session_state.temp_dir),
                                instruction,
                                device,
                                update_display,
                                reference_image_paths=st.session_state.get("reference_image_paths"),
                                apply_to_whole_clip=st.session_state.apply_to_whole_clip,
                            )
                            st.session_state.processed_frames = processed_frames
                            st.session_state.mask_preview_frames = mask_preview_frames
                            st.session_state.object_tracking = tracking_payload
                            st.session_state.processing_notes = tracking_payload.get("notes", [])
                            if tracking_payload.get("changed_frame_count", 0) == 0:
                                st.warning("The target was tracked, but no visible pixels were changed in the edited frames.")
                            update_display(
                                "Complete ✅",
                                1.0,
                                f"[OK] Object edit finished - {tracking_payload.get('changed_frame_count', 0)}/{len(frame_files)} frames changed",
                            )
                            status.update(label="✅ Processing Complete", state="complete")

                        elif instruction.operation == "global_color_change":
                            update_display(
                                "Step 2: Color Change",
                                0.30,
                                f"Changing {instruction.parameters['source_color']} to {instruction.parameters['target_color']}...",
                            )
                            processed_frames, changed_frames = recolor_selected_color_in_frames(
                                frame_files,
                                processed_dir,
                                instruction.parameters["source_color"],
                                instruction.parameters["target_color"],
                                update_display,
                                tolerance=instruction.parameters.get("tolerance", "normal"),
                            )
                            st.session_state.processed_frames = processed_frames
                            if changed_frames == 0:
                                st.warning("No matching color region was found in these frames.")
                            update_display("Complete ✅", 1.0, f"[OK] Color edit finished - {changed_frames}/{len(frame_files)} frames changed")
                            status.update(label="✅ Processing Complete", state="complete")

                        elif instruction.operation == "atmosphere_overlay":
                            from utils.atmosphere_overlay import apply_atmosphere_to_frames

                            params = dict(instruction.parameters or {})
                            for k, v in (st.session_state.get("atmosphere_overrides") or {}).items():
                                if k.startswith("_"):
                                    continue
                                params[k] = v

                            update_display(
                                "Step 2: Atmosphere overlays",
                                0.28,
                                f"Applying: {instruction.summary} (geometry unchanged)...",
                            )
                            _, atm_notes = apply_atmosphere_to_frames(
                                frame_files,
                                processed_dir,
                                params,
                                float(extraction_fps),
                                update_display,
                                seed=42,
                            )
                            st.session_state.processed_frames = sorted(processed_dir.glob("frame_*.png"))
                            st.session_state.processing_notes = [atm_notes]
                            st.session_state.atmosphere_tab_visible = True
                            st.session_state.atmosphere_last_inferred = dict(params)
                            st.session_state.atmosphere_inferred_summary = instruction.summary
                            if not show_atmosphere_tab:
                                st.session_state["_pending_atmosphere_tab_rerun"] = True
                            st.caption(
                                "Atmosphere export complete — open the **Atmosphere** tab to tweak and re-run."
                            )
                            update_display("Complete ✅", 1.0, "[OK] Atmosphere overlay finished")
                            status.update(label="✅ Processing Complete", state="complete")

                        else:
                            raise ValueError(f"Unsupported operation: {instruction.operation}")

                        update_display("Step 4: Preparing Download", 0.97, "Creating downloadable MP4...")
                        _, output_filename, output_path = create_downloadable_video(
                            Path(st.session_state.temp_dir),
                            st.session_state.video_path,
                            st.session_state.get("original_video_fps") or fps,
                        )
                        st.session_state.export_video_filename = output_filename
                        st.session_state.export_video_path = str(output_path)
                        st.session_state.export_video_bytes = None

                        if instruction.operation == "atmosphere_overlay":
                            from utils.atmosphere_overlay import (
                                mix_rain_under_original_audio,
                                video_has_audio_stream,
                            )

                            _pn = st.session_state.get("processing_notes") or []
                            atm_notes_mux: Dict[str, Any] = (
                                _pn[0] if _pn and isinstance(_pn[0], dict) else {}
                            )

                            merged_params = dict(instruction.parameters or {})
                            for k, v in (st.session_state.get("atmosphere_overrides") or {}).items():
                                if k.startswith("_"):
                                    continue
                                merged_params[k] = v
                            bed_kind = str(
                                atm_notes_mux.get("audio_bed")
                                or merged_params.get("audio_bed")
                                or "none"
                            ).lower()
                            mix_on = bool(merged_params.get("mix_rain_audio", bed_kind != "none"))
                            outp = Path(st.session_state.export_video_path)
                            if (
                                mix_on
                                and bed_kind in {"rain", "wind"}
                                and video_has_audio_stream(st.session_state.video_path)
                                and outp.is_file()
                            ):
                                muxed = outp.parent / f"{outp.stem}.__atmosbed__.mp4"
                                mix_thunder = bool(
                                    atm_notes_mux.get("mix_thunder_audio")
                                    and str(atm_notes_mux.get("flash_kind") or "").lower() == "lightning"
                                )
                                burst_frames = atm_notes_mux.get("lightning_burst_frames") or []
                                fps_mux = float(
                                    atm_notes_mux.get("atmosphere_fps")
                                    or st.session_state.get("original_video_fps")
                                    or extraction_fps
                                    or 30.0
                                )
                                seed_mux = int(atm_notes_mux.get("atmosphere_seed", 42))
                                if mix_rain_under_original_audio(
                                    str(outp),
                                    str(muxed),
                                    bed_kind=bed_kind,
                                    mix_thunder=mix_thunder,
                                    lightning_burst_frames=burst_frames,
                                    fps=fps_mux,
                                    thunder_rng_seed=seed_mux + 913,
                                ):
                                    try:
                                        outp.unlink(missing_ok=True)
                                    except OSError:
                                        pass
                                    muxed.rename(outp)

                        update_display("Complete ✅", 1.0, f"[OK] Download ready - {output_filename}")
                    
                        logger.info(f"Processing completed successfully: {effective_command}")
                        log_session(
                            st.session_state.video_path,
                            effective_command,
                            "completed",
                            {
                                "frames_processed": len(st.session_state.processed_frames) if st.session_state.processed_frames else 0,
                                "reference_images": len(st.session_state.reference_image_paths),
                            }
                        )
                        st.session_state.processing_active = False
                        if st.session_state.pop("_pending_atmosphere_tab_rerun", False):
                            st.rerun()
                    
                    except KeyboardInterrupt as e:
                        # User cancelled processing
                        logger.info(f"Processing cancelled by user: {str(e)}")
                        st.session_state.processing_active = False
                        st.warning("⏹️ Processing was stopped by user")
                        log_session(
                            st.session_state.video_path,
                            effective_command,
                            "cancelled",
                            {"reason": "User cancelled processing"}
                        )
                    
                    except Exception as e:
                        logger.error(f"Processing error: {str(e)}", exc_info=True)
                        st.session_state.processing_active = False
                        log_session(
                            st.session_state.video_path,
                            effective_command,
                            "error",
                            {"error": str(e)}
                        )
                        status.update(label="❌ Processing Failed", state="error")
                        st.error(f"❌ Error processing video: {str(e)}")
                        import traceback

                        # Cannot nest st.expander inside st.status (StreamlitAPIException).
                        st.code(traceback.format_exc(), language="python")

        elif st.session_state.video_uploaded and not has_prompt:
            st.info("Enter a prompt above, then click **Process video**.")

if show_atmosphere_tab and not atm_active:
    last_inferred = st.session_state.get("atmosphere_last_inferred")
    if isinstance(last_inferred, dict) and last_inferred:
        atm_inferred = last_inferred
        atm_active = True
        atm_summary = str(st.session_state.get("atmosphere_inferred_summary") or "")

if show_commentary_tab and not commentary_active:
    last_inferred = st.session_state.get("commentary_last_inferred")
    if isinstance(last_inferred, dict) and last_inferred:
        commentary_inferred = last_inferred
        commentary_active = True
        commentary_summary = str(st.session_state.get("commentary_inferred_summary") or "")

if tab_atmosphere is not None:
    with tab_atmosphere:
        render_atmosphere_tab(
            inferred=atm_inferred,
            instruction_summary=atm_summary or st.session_state.get("atmosphere_inferred_summary", ""),
            active=atm_active,
        )

if tab_commentary is not None:
    with tab_commentary:
        render_commentary_tab(
            inferred=commentary_inferred,
            instruction_summary=commentary_summary or st.session_state.get("commentary_inferred_summary", ""),
            active=commentary_active,
            last_artifacts=st.session_state.get("commentary_last_artifacts") or {},
        )

with tab_output:
    render_card_open("Results")
    if st.session_state.get("processed_frames"):
        render_edited_frames_preview(list(st.session_state.processed_frames))
    else:
        st.caption("Processed frame previews appear here after a successful run.")

    _dl_data, _dl_fname = _export_download_payload()
    if _dl_data:
        st.success("Export ready — download while this upload is loaded.")
        st.download_button(
            label="Download edited MP4",
            data=_dl_data,
            file_name=_dl_fname or "edited_video.mp4",
            mime="video/mp4",
            use_container_width=True,
            key="aiedit_download_edited_mp4",
        )
        if st.session_state.get("export_video_path"):
            st.caption(f"Temp file: `{Path(st.session_state['export_video_path']).name}`")
    elif not st.session_state.get("processed_frames"):
        st.info("Run processing on the **Edit** tab to generate output.")
    render_card_close()


# ==================== Footer ====================
st.markdown("---")
f1, f2, f3 = st.columns(3)
with f1:
    st.markdown("**Features** · text · objects · atmosphere · color")
with f2:
    st.markdown("**Stack** · Streamlit · OpenCV · PyTorch")
with f3:
    st.markdown("**Export** · MP4 · optional rain/thunder beds")

st.markdown(
    '<div class="aiedit-footer"><strong>AiEdit</strong> · prompt-first video editing</div>',
    unsafe_allow_html=True,
)
