from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import urllib.request

import cv2
import numpy as np
import torch
from PIL import Image

try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


SAM_CHECKPOINTS = {
    "vit_b": "sam_vit_b_01ec64.pth",
    "vit_l": "sam_vit_l_0b3195.pth",
    "vit_h": "sam_vit_h_4b8939.pth",
}


@dataclass
class ModelAvailability:
    device: str
    grounding_backend: str = "unavailable"
    segmentation_backend: str = "grabcut"
    tracking_backend: str = "template_matching"
    inpainting_backend: str = "opencv"
    warnings: List[str] = field(default_factory=list)


class ModelManager:
    """Lazy-loads optional detection and segmentation backends."""

    def __init__(self, device: Optional[str] = None):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._grounding_pipe = None
        self._grounding_model_id = None
        self._sam_predictor = None
        self._sam_model_type = None

    @staticmethod
    def _has_module(module_name: str) -> bool:
        return importlib.util.find_spec(module_name) is not None

    def get_availability(self) -> ModelAvailability:
        availability = ModelAvailability(device=self.device)

        if self._has_module("transformers"):
            availability.grounding_backend = "grounding_dino"
        else:
            availability.warnings.append("Transformers is unavailable, so prompt grounding will be disabled.")

        if self._has_module("segment_anything"):
            availability.segmentation_backend = "segment_anything"
        else:
            availability.warnings.append("Segment Anything is unavailable; GrabCut masks will be used.")

        if self._has_module("sam2"):
            availability.tracking_backend = "sam2_or_template_matching"

        if self._has_module("diffusers"):
            availability.inpainting_backend = "opencv_or_diffusion"

        return availability

    def describe_stack(self) -> Dict[str, Any]:
        availability = self.get_availability()
        return {
            "device": availability.device,
            "grounding_backend": availability.grounding_backend,
            "segmentation_backend": availability.segmentation_backend,
            "tracking_backend": availability.tracking_backend,
            "inpainting_backend": availability.inpainting_backend,
            "warnings": availability.warnings,
        }

    def load_grounding_detector(self, model_id: Optional[str] = None):
        if self._grounding_pipe is not None:
            return self._grounding_pipe

        if not self._has_module("transformers"):
            raise RuntimeError("Transformers is not installed.")

        from transformers import pipeline

        model_id = model_id or "IDEA-Research/grounding-dino-tiny"
        logger.info("Loading grounding detector: %s", model_id)
        self._grounding_pipe = pipeline(
            "zero-shot-object-detection",
            model=model_id,
            device=0 if self.device == "cuda" else -1,
        )
        self._grounding_model_id = model_id
        return self._grounding_pipe

    def detect_objects(
        self,
        image_bgr: np.ndarray,
        candidate_labels: Sequence[str],
        threshold: float = 0.25,
    ) -> List[Dict[str, Any]]:
        pipe = self.load_grounding_detector()
        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
        image_pil = Image.fromarray(image_rgb)
        results = pipe(image_pil, candidate_labels=list(candidate_labels), threshold=threshold)

        normalized: List[Dict[str, Any]] = []
        for item in results:
            box = item.get("box", {})
            xmin = int(box.get("xmin", 0))
            ymin = int(box.get("ymin", 0))
            xmax = int(box.get("xmax", 0))
            ymax = int(box.get("ymax", 0))
            normalized.append(
                {
                    "label": item.get("label", candidate_labels[0] if candidate_labels else "object"),
                    "score": float(item.get("score", 0.0)),
                    "bbox": (xmin, ymin, xmax, ymax),
                    "backend": self._grounding_model_id or "grounding_dino",
                }
            )

        return normalized

    def _download_sam_checkpoint(self, model_type: str = "vit_b") -> str:
        checkpoint_dir = Path.home() / ".cache" / "sam_checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_file = checkpoint_dir / SAM_CHECKPOINTS.get(model_type, SAM_CHECKPOINTS["vit_b"])
        if not checkpoint_file.exists():
            url = f"https://dl.fbaipublicfiles.com/segment_anything/{checkpoint_file.name}"
            logger.info("Downloading SAM checkpoint: %s", checkpoint_file.name)
            urllib.request.urlretrieve(url, checkpoint_file)
        return str(checkpoint_file)

    def load_sam_predictor(self, model_type: str = "vit_b"):
        if self._sam_predictor is not None and self._sam_model_type == model_type:
            return self._sam_predictor

        if not self._has_module("segment_anything"):
            raise RuntimeError("segment_anything is not installed.")

        from segment_anything import SamPredictor, sam_model_registry

        checkpoint_path = self._download_sam_checkpoint(model_type)
        logger.info("Loading SAM predictor: %s", model_type)
        sam_model = sam_model_registry[model_type](checkpoint=checkpoint_path)
        sam_model.to(device=self.device)
        self._sam_predictor = SamPredictor(sam_model)
        self._sam_model_type = model_type
        return self._sam_predictor

    def segment_box(
        self,
        image_bgr: np.ndarray,
        bbox: Tuple[int, int, int, int],
        use_precise_masks: bool = True,
    ) -> np.ndarray:
        if use_precise_masks and self._has_module("segment_anything"):
            try:
                predictor = self.load_sam_predictor()
                image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
                predictor.set_image(image_rgb)
                input_box = np.array([bbox[0], bbox[1], bbox[2], bbox[3]])
                masks, _, _ = predictor.predict(box=input_box, multimask_output=False)
                mask = masks[0].astype(np.uint8) * 255
                if int(mask.sum()) > 0:
                    return mask
            except Exception as exc:
                logger.warning("SAM mask generation failed, falling back to GrabCut: %s", exc)

        return self.grabcut_mask(image_bgr, bbox)

    @staticmethod
    def grabcut_mask(image_bgr: np.ndarray, bbox: Tuple[int, int, int, int]) -> np.ndarray:
        x1, y1, x2, y2 = bbox
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        rect = (x1, y1, width, height)

        mask = np.zeros(image_bgr.shape[:2], np.uint8)
        bgd_model = np.zeros((1, 65), np.float64)
        fgd_model = np.zeros((1, 65), np.float64)

        try:
            cv2.grabCut(image_bgr, mask, rect, bgd_model, fgd_model, 3, cv2.GC_INIT_WITH_RECT)
            output_mask = np.where(
                (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD),
                255,
                0,
            ).astype(np.uint8)
            if int(output_mask.sum()) > 0:
                return output_mask
        except Exception:
            pass

        fallback = np.zeros(image_bgr.shape[:2], dtype=np.uint8)
        fallback[y1:y2, x1:x2] = 255
        return fallback
