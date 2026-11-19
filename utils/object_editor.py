from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from utils.color_editor import shift_masked_region_color
from utils.text_removal_overlay import TextRemovalAndOverlay

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


@dataclass
class ObjectEditOutcome:
    changed_pixels: int
    warnings: List[str] = field(default_factory=list)


def mask_bounds(mask: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    ys, xs = np.where(mask > 0)
    if len(xs) == 0 or len(ys) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def create_mask_overlay(frame: np.ndarray, mask: np.ndarray, color: Tuple[int, int, int] = (0, 255, 0)) -> np.ndarray:
    overlay = frame.copy()
    binary = mask > 0
    overlay[binary] = (overlay[binary] * 0.55 + np.array(color) * 0.45).astype(np.uint8)
    return overlay


def select_best_reference_image(reference_images: List[np.ndarray], target_size: Tuple[int, int]) -> Optional[np.ndarray]:
    if not reference_images:
        return None
    target_w, target_h = target_size
    target_ratio = target_w / max(1, target_h)
    return min(
        reference_images,
        key=lambda img: abs((img.shape[1] / max(1, img.shape[0])) - target_ratio),
    )


class ObjectEditor:
    def __init__(self, device: str = "cpu"):
        self.device = device
        self.processor = TextRemovalAndOverlay(device=device)

    def recolor_object(self, frame: np.ndarray, mask: np.ndarray, target_color: str) -> Tuple[np.ndarray, ObjectEditOutcome]:
        changed_pixels = int(np.count_nonzero(mask))
        if changed_pixels == 0:
            return frame.copy(), ObjectEditOutcome(changed_pixels=0, warnings=["No object pixels were selected for recolor."])
        result = shift_masked_region_color(frame, mask, target_color)
        return result, ObjectEditOutcome(changed_pixels=changed_pixels)

    def remove_object(
        self,
        frame: np.ndarray,
        mask: np.ndarray,
        removal_mode: str = "opencv",
    ) -> Tuple[np.ndarray, ObjectEditOutcome]:
        changed_pixels = int(np.count_nonzero(mask))
        if changed_pixels == 0:
            return frame.copy(), ObjectEditOutcome(changed_pixels=0, warnings=["No object pixels were selected for removal."])

        if removal_mode == "diffusion":
            cleaned = self.processor.remove_text_inpainting(frame, mask, prompt="clean background after object removal")
        else:
            cleaned = self.processor.remove_text_opencv(frame, mask)
        return cleaned, ObjectEditOutcome(changed_pixels=changed_pixels)

    def replace_object(
        self,
        frame: np.ndarray,
        mask: np.ndarray,
        replacement_prompt: str,
        reference_images: Optional[List[np.ndarray]] = None,
        removal_mode: str = "opencv",
    ) -> Tuple[np.ndarray, ObjectEditOutcome]:
        cleaned, removal_outcome = self.remove_object(frame, mask, removal_mode=removal_mode)
        reference_images = reference_images or []
        if not reference_images:
            removal_outcome.warnings.append(
                "No reference image was provided, so this replacement only removed the original object."
            )
            return cleaned, removal_outcome

        bounds = mask_bounds(mask)
        if bounds is None:
            removal_outcome.warnings.append("Replacement mask was empty.")
            return cleaned, removal_outcome

        x1, y1, x2, y2 = bounds
        target_w = max(1, x2 - x1)
        target_h = max(1, y2 - y1)
        reference_image = select_best_reference_image(reference_images, (target_w, target_h))
        if reference_image is None:
            removal_outcome.warnings.append("Reference images could not be loaded.")
            return cleaned, removal_outcome
        resized_reference = cv2.resize(reference_image, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

        ref_mask = np.zeros((target_h, target_w), dtype=np.uint8)
        ref_mask[:] = 255

        composed = cleaned.copy()
        roi = composed[y1:y2, x1:x2]
        local_mask = (mask[y1:y2, x1:x2] > 0).astype(np.uint8) * 255
        if local_mask.shape[:2] != resized_reference.shape[:2]:
            local_mask = cv2.resize(local_mask, (target_w, target_h), interpolation=cv2.INTER_NEAREST)

        blended = roi.copy()
        binary_mask = local_mask > 0
        blended[binary_mask] = resized_reference[binary_mask]
        composed[y1:y2, x1:x2] = blended

        outcome = ObjectEditOutcome(
            changed_pixels=removal_outcome.changed_pixels,
            warnings=removal_outcome.warnings,
        )
        if replacement_prompt:
            outcome.warnings.append(
                f"Used the reference image for replacement. Prompt guidance '{replacement_prompt}' is only advisory in this mode."
            )
        return composed, outcome


def load_reference_image(reference_path: Optional[str]) -> Optional[np.ndarray]:
    if not reference_path:
        return None
    path = Path(reference_path)
    if not path.exists():
        return None
    return cv2.imread(str(path))


def load_reference_images(reference_paths: Optional[List[str]]) -> List[np.ndarray]:
    images: List[np.ndarray] = []
    for reference_path in reference_paths or []:
        image = load_reference_image(reference_path)
        if image is not None:
            images.append(image)
    return images
