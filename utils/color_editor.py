from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import cv2
import numpy as np

from utils.prompt_parser import KNOWN_COLORS, resolve_color


def _build_face_detector() -> cv2.CascadeClassifier:
    return cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )


def _skin_mask(hsv_image: np.ndarray) -> np.ndarray:
    lower = np.array([0, 20, 50], dtype=np.uint8)
    upper = np.array([25, 220, 255], dtype=np.uint8)
    return cv2.inRange(hsv_image, lower, upper) > 0


def _bgr_for(color_value: Any) -> Tuple[int, int, int]:
    """Resolve any color spec (name / hex / rgb()/ tuple) to a BGR tuple."""

    bgr = resolve_color(color_value)
    if bgr is None:
        # Last-ditch: keep legacy behavior on unknown names by routing through
        # the palette dict if the caller really did pass a name we know.
        if isinstance(color_value, str) and color_value.lower() in KNOWN_COLORS:
            bgr = tuple(int(c) for c in KNOWN_COLORS[color_value.lower()])
        else:
            raise ValueError(f"unrecognized color spec: {color_value!r}")
    return tuple(int(c) for c in bgr)


def _target_hsv(color_value: Any) -> np.ndarray:
    bgr = np.uint8([[list(_bgr_for(color_value))]])
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[0, 0]


def shift_masked_region_color(
    frame: np.ndarray,
    mask: np.ndarray,
    target_color: Any,
    saturation_floor: int = 90,
) -> np.ndarray:
    if mask is None or not np.any(mask):
        return frame.copy()

    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    target_hsv = _target_hsv(target_color)
    binary_mask = mask.astype(bool)

    hsv[..., 0][binary_mask] = target_hsv[0]
    hsv[..., 1][binary_mask] = np.clip(
        np.maximum(hsv[..., 1][binary_mask], saturation_floor),
        0,
        255,
    )
    hsv[..., 2][binary_mask] = np.clip(hsv[..., 2][binary_mask] * 1.02, 0, 255)

    recolored = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    result = frame.copy()
    result[binary_mask] = recolored[binary_mask]
    return result


def estimate_hair_mask(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    face_detector = _build_face_detector()
    faces = face_detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(40, 40))

    mask = np.zeros((height, width), dtype=np.uint8)
    if len(faces) == 0:
        return mask

    skin = _skin_mask(hsv)

    for (x, y, w, h) in faces:
        x0 = max(0, int(x - 0.35 * w))
        x1 = min(width, int(x + 1.35 * w))
        y0 = max(0, int(y - 0.90 * h))
        y1 = min(height, int(y + 0.30 * h))

        roi_mask = np.zeros((height, width), dtype=np.uint8)
        center = (int(x + w / 2), int(y + h * 0.35))
        axes = (max(10, int(w * 0.85)), max(10, int(h * 0.95)))
        cv2.ellipse(roi_mask, center, axes, 0, 180, 360, 255, -1)

        face_rect = np.zeros((height, width), dtype=np.uint8)
        cv2.rectangle(face_rect, (x, y), (x + w, y + h), 255, -1)
        upper_roi = np.zeros((height, width), dtype=np.uint8)
        cv2.rectangle(upper_roi, (x0, y0), (x1, y1), 255, -1)

        candidate = (
            (upper_roi > 0)
            & (roi_mask > 0)
            & (face_rect == 0)
            & (~skin)
            & (hsv[..., 1] > 25)
            & (hsv[..., 2] > 20)
        )

        local_mask = np.zeros((height, width), dtype=np.uint8)
        local_mask[candidate] = 255
        local_mask = cv2.medianBlur(local_mask, 5)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        local_mask = cv2.morphologyEx(local_mask, cv2.MORPH_CLOSE, kernel)
        local_mask = cv2.morphologyEx(local_mask, cv2.MORPH_OPEN, kernel)
        mask = cv2.bitwise_or(mask, local_mask)

    return mask


def change_hair_color(
    frame: np.ndarray,
    target_color: Any,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, int]]:
    mask = estimate_hair_mask(frame)
    changed_pixels = int(np.count_nonzero(mask))
    if changed_pixels == 0:
        return frame.copy(), mask, {"changed_pixels": 0}

    return shift_masked_region_color(frame, mask, target_color), mask, {"changed_pixels": changed_pixels}


_TOLERANCE_PROFILES: Dict[str, Dict[str, int]] = {
    "narrow": {"hue": 6, "sat": 60, "val": 30},
    "normal": {"hue": 12, "sat": 40, "val": 25},
    "wide":   {"hue": 22, "sat": 25, "val": 15},
    "very_wide": {"hue": 32, "sat": 15, "val": 10},
}


def _resolve_tolerance(tolerance: Any) -> Dict[str, int]:
    """Map a user-facing strictness to (hue/sat/val) thresholds."""

    if isinstance(tolerance, dict):
        out = dict(_TOLERANCE_PROFILES["normal"])
        out.update({k: int(v) for k, v in tolerance.items() if k in out})
        return out
    if isinstance(tolerance, (int, float)):
        hue = max(1, min(45, int(tolerance)))
        return {"hue": hue, "sat": 40, "val": 25}
    if isinstance(tolerance, str):
        key = tolerance.strip().lower().replace("-", "_").replace(" ", "_")
        if key in _TOLERANCE_PROFILES:
            return dict(_TOLERANCE_PROFILES[key])
    return dict(_TOLERANCE_PROFILES["normal"])


def change_selected_color(
    frame: np.ndarray,
    source_color: Any,
    target_color: Any,
    tolerance: Any = "normal",
) -> Tuple[np.ndarray, np.ndarray, Dict[str, int]]:
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    source_hsv = _target_hsv(source_color)
    hue = hsv[..., 0].astype(np.int16)
    distance = np.abs(hue - int(source_hsv[0]))
    distance = np.minimum(distance, 180 - distance)

    tol = _resolve_tolerance(tolerance)
    mask = (
        (distance <= tol["hue"])
        & (hsv[..., 1] > tol["sat"])
        & (hsv[..., 2] > tol["val"])
    ).astype(np.uint8) * 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    changed_pixels = int(np.count_nonzero(mask))
    if changed_pixels == 0:
        return frame.copy(), mask, {"changed_pixels": 0}

    return (
        shift_masked_region_color(frame, mask, target_color),
        mask,
        {"changed_pixels": changed_pixels, "tolerance": tol},
    )
