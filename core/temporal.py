"""
Phase 3: temporal mask stabilization.

Per-frame masks from SAM/GrabCut tend to flicker. Two cheap, deterministic
helpers without any extra model:

- ``smooth_mask_sequence``: morphological close + temporal box filter (rolling
  average across a small window) so a pixel must be "on" in most of the window
  to stay on. Removes 1-frame holes and 1-frame flickers.
- ``stabilize_bboxes``: rolling average of bounding boxes for cases where we
  prefer cropping over a binary mask.

Both functions accept and return numpy arrays; no torch dependency.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover - cv2 is in requirements but be defensive
    cv2 = None  # type: ignore


def smooth_mask_sequence(
    masks: Sequence[np.ndarray],
    *,
    window: int = 3,
    threshold: float = 0.5,
    morph_kernel: int = 3,
) -> List[np.ndarray]:
    """Return masks with morphological closing and temporal averaging.

    Inputs are uint8 masks (0 or 255). Output is the same shape and dtype.
    ``window`` is the temporal radius in frames (so window=3 means up to
    3 frames before and after are averaged in).
    """

    if not masks:
        return []
    arr = np.stack([(m > 0).astype(np.float32) for m in masks], axis=0)

    if cv2 is not None and morph_kernel and morph_kernel > 1:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_kernel, morph_kernel))
        for i in range(arr.shape[0]):
            closed = cv2.morphologyEx((arr[i] * 255).astype(np.uint8), cv2.MORPH_CLOSE, kernel)
            arr[i] = (closed > 0).astype(np.float32)

    if window <= 0:
        smoothed = arr
    else:
        n = arr.shape[0]
        smoothed = np.zeros_like(arr)
        for i in range(n):
            lo = max(0, i - window)
            hi = min(n, i + window + 1)
            smoothed[i] = arr[lo:hi].mean(axis=0)

    out = []
    for i in range(smoothed.shape[0]):
        out.append((smoothed[i] >= threshold).astype(np.uint8) * 255)
    return out


def stabilize_bboxes(
    bboxes: Sequence[Tuple[int, int, int, int]], *, window: int = 3
) -> List[Tuple[int, int, int, int]]:
    """Rolling average over (x1,y1,x2,y2) bboxes; rounds to ints."""

    if not bboxes:
        return []
    arr = np.array(bboxes, dtype=np.float32)
    n = arr.shape[0]
    out = np.zeros_like(arr)
    for i in range(n):
        lo = max(0, i - window)
        hi = min(n, i + window + 1)
        out[i] = arr[lo:hi].mean(axis=0)
    rounded = np.rint(out).astype(np.int32)
    return [tuple(int(v) for v in row) for row in rounded]
