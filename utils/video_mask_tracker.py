from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from utils.model_manager import ModelManager

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


@dataclass
class TrackedFrame:
    frame_index: int
    frame_path: str
    bbox: Tuple[int, int, int, int]
    score: float
    source: str
    mask_path: Optional[str] = None


@dataclass
class TrackingResult:
    success: bool
    target_query: str
    frames: List[TrackedFrame] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    backend_info: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "target_query": self.target_query,
            "frames": [asdict(frame) for frame in self.frames],
            "warnings": self.warnings,
            "backend_info": self.backend_info,
            "error": self.error,
        }


class VideoMaskTracker:
    """Grounds an object from text and propagates masks across frames."""

    def __init__(self, device: str = "cpu", model_manager: Optional[ModelManager] = None):
        self.device = device
        self.model_manager = model_manager or ModelManager(device=device)

    @staticmethod
    def _clamp_box(box: Tuple[int, int, int, int], width: int, height: int) -> Tuple[int, int, int, int]:
        x1, y1, x2, y2 = box
        x1 = max(0, min(width - 1, int(x1)))
        y1 = max(0, min(height - 1, int(y1)))
        x2 = max(x1 + 1, min(width, int(x2)))
        y2 = max(y1 + 1, min(height, int(y2)))
        return (x1, y1, x2, y2)

    @staticmethod
    def _extract_template(frame_bgr: np.ndarray, bbox: Tuple[int, int, int, int]) -> np.ndarray:
        x1, y1, x2, y2 = bbox
        crop = frame_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            return np.empty((0, 0, 3), dtype=np.uint8)
        return crop.copy()

    @staticmethod
    def _candidate_labels(query: str) -> Sequence[str]:
        query = query.strip()
        variants = [query]
        if not query.startswith("a "):
            variants.append(f"a {query}")
        if " the " in query:
            variants.append(query.split(" the ")[-1])
        return list(dict.fromkeys(variants))

    def _detect_box(self, frame_bgr: np.ndarray, query: str) -> Optional[Dict[str, Any]]:
        detections = self.model_manager.detect_objects(
            frame_bgr,
            self._candidate_labels(query),
            threshold=0.22,
        )
        if not detections:
            return None

        detections.sort(key=lambda item: item["score"], reverse=True)
        return detections[0]

    def _template_track_box(
        self,
        prev_frame_bgr: np.ndarray,
        prev_box: Tuple[int, int, int, int],
        next_frame_bgr: np.ndarray,
    ) -> Tuple[Tuple[int, int, int, int], float]:
        height, width = next_frame_bgr.shape[:2]
        x1, y1, x2, y2 = prev_box
        box_w = x2 - x1
        box_h = y2 - y1

        template = self._extract_template(prev_frame_bgr, prev_box)
        if template.size == 0:
            return prev_box, 0.0

        pad_x = max(12, int(box_w * 0.75))
        pad_y = max(12, int(box_h * 0.75))
        sx1 = max(0, x1 - pad_x)
        sy1 = max(0, y1 - pad_y)
        sx2 = min(width, x2 + pad_x)
        sy2 = min(height, y2 + pad_y)
        search = next_frame_bgr[sy1:sy2, sx1:sx2]

        if (
            search.size == 0
            or search.shape[0] < template.shape[0]
            or search.shape[1] < template.shape[1]
        ):
            return prev_box, 0.0

        search_gray = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        result = cv2.matchTemplate(search_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        _, score, _, max_loc = cv2.minMaxLoc(result)
        nx1 = sx1 + max_loc[0]
        ny1 = sy1 + max_loc[1]
        nx2 = nx1 + template.shape[1]
        ny2 = ny1 + template.shape[0]
        return self._clamp_box((nx1, ny1, nx2, ny2), width, height), float(score)

    def track_target(
        self,
        frame_files: Sequence[Path],
        target_query: str,
        masks_dir: Optional[Path] = None,
        use_precise_masks: bool = True,
        redetect_interval: int = 8,
        update_callback=None,
    ) -> TrackingResult:
        backend_info = self.model_manager.describe_stack()
        result = TrackingResult(
            success=False,
            target_query=target_query,
            backend_info=backend_info,
        )

        if not frame_files:
            result.error = "No frames provided for tracking."
            return result

        if masks_dir is not None:
            masks_dir.mkdir(parents=True, exist_ok=True)

        initial_detection = None
        initial_idx = 0
        search_span = min(5, len(frame_files))
        for idx in range(search_span):
            frame = cv2.imread(str(frame_files[idx]))
            if frame is None:
                continue
            try:
                detection = self._detect_box(frame, target_query)
            except Exception as exc:
                result.error = str(exc)
                result.warnings.append(
                    "Object grounding failed. Install/download the grounding model or check internet access."
                )
                return result
            if detection:
                initial_detection = detection
                initial_idx = idx
                break

        if initial_detection is None:
            result.error = f"Could not find '{target_query}' in the first frames."
            result.warnings.append("Try a clearer prompt or start the clip closer to the target object.")
            return result

        previous_frame = cv2.imread(str(frame_files[initial_idx]))
        previous_box = self._clamp_box(initial_detection["bbox"], previous_frame.shape[1], previous_frame.shape[0])

        for idx, frame_path in enumerate(frame_files):
            frame = cv2.imread(str(frame_path))
            if frame is None:
                result.warnings.append(f"Skipped unreadable frame: {frame_path.name}")
                continue

            if idx < initial_idx:
                detection = self._detect_box(frame, target_query)
                if detection:
                    current_box = self._clamp_box(detection["bbox"], frame.shape[1], frame.shape[0])
                    current_score = float(detection["score"])
                    current_source = "grounding_dino"
                else:
                    current_box = previous_box
                    current_score = 0.0
                    current_source = "bootstrap"
            elif idx == initial_idx:
                current_box = previous_box
                current_score = float(initial_detection["score"])
                current_source = "grounding_dino"
            else:
                current_box, track_score = self._template_track_box(previous_frame, previous_box, frame)
                current_score = track_score
                current_source = "template_matching"

                if idx % max(1, redetect_interval) == 0:
                    detection = self._detect_box(frame, target_query)
                    if detection and float(detection["score"]) >= max(0.22, track_score):
                        current_box = self._clamp_box(detection["bbox"], frame.shape[1], frame.shape[0])
                        current_score = float(detection["score"])
                        current_source = "grounding_dino"

            mask = self.model_manager.segment_box(frame, current_box, use_precise_masks=use_precise_masks)
            mask_path = None
            if masks_dir is not None:
                mask_path = str(masks_dir / f"mask_{idx:04d}.png")
                cv2.imwrite(mask_path, mask)

            result.frames.append(
                TrackedFrame(
                    frame_index=idx,
                    frame_path=str(frame_path),
                    bbox=current_box,
                    score=current_score,
                    source=current_source,
                    mask_path=mask_path,
                )
            )

            if update_callback:
                update_callback(idx, len(frame_files), current_source, current_score)

            previous_frame = frame
            previous_box = current_box

        result.success = len(result.frames) > 0
        if backend_info["segmentation_backend"] == "grabcut":
            result.warnings.append("Using GrabCut masks because a Segment Anything backend is not configured.")
        return result
