"""
Phase 3: multi-frame OCR consensus.

EasyOCR runs per-frame and disagrees across frames on the same overlay. This
helper takes per-frame detections, groups them by spatial bucket, and votes
the most common (cleaned) text per bucket weighted by detector confidence.

Input shape (matches what TextDetectionSAM.detect_text_regions returns):

    [
      [{"bbox": (x1,y1,x2,y2), "text": str, "confidence": float}, ...],   # frame 0
      ...
    ]

Output: list of consensus regions::

    [
      {
        "bbox": (x1,y1,x2,y2),
        "text": "WINNER",
        "confidence": float,
        "votes": int,
        "candidates": {"WINNER": 5, "WiNNER": 1},
      },
      ...
    ]
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List, Sequence, Tuple

import numpy as np


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _bucket(bbox: Tuple[int, int, int, int], grid: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    return (x1 // grid, y1 // grid, x2 // grid, y2 // grid)


def _avg_bbox(bboxes: Sequence[Tuple[int, int, int, int]]) -> Tuple[int, int, int, int]:
    arr = np.array(bboxes, dtype=np.float32).mean(axis=0)
    return tuple(int(round(v)) for v in arr)


def consensus_text_regions(
    per_frame_detections: Sequence[Sequence[Dict]],
    *,
    grid: int = 16,
    min_confidence: float = 0.0,
    min_votes: int = 1,
) -> List[Dict]:
    """Vote OCR strings across frames to one consensus region.

    Args:
        per_frame_detections: Per-frame list of detection dicts.
        grid: Spatial bucket size in pixels for grouping (smaller = stricter).
        min_confidence: Discard detections under this confidence.
        min_votes: Drop buckets with fewer total votes than this.
    """

    buckets: Dict[Tuple[int, int, int, int], Dict] = defaultdict(
        lambda: {"bboxes": [], "texts": [], "confidences": []}
    )
    for frame in per_frame_detections:
        for det in frame:
            conf = float(det.get("confidence", 0.0))
            if conf < min_confidence:
                continue
            bbox = tuple(int(v) for v in det.get("bbox", (0, 0, 0, 0)))
            text = _clean(det.get("text", ""))
            if not text:
                continue
            key = _bucket(bbox, grid)
            buckets[key]["bboxes"].append(bbox)
            buckets[key]["texts"].append(text)
            buckets[key]["confidences"].append(conf)

    out: List[Dict] = []
    for entry in buckets.values():
        if len(entry["texts"]) < min_votes:
            continue

        weights: Dict[str, float] = defaultdict(float)
        counts: Dict[str, int] = defaultdict(int)
        for text, conf in zip(entry["texts"], entry["confidences"]):
            weights[text] += conf
            counts[text] += 1
        winner = max(weights.items(), key=lambda kv: kv[1])[0]

        out.append(
            {
                "bbox": _avg_bbox(entry["bboxes"]),
                "text": winner,
                "confidence": weights[winner] / max(1, counts[winner]),
                "votes": sum(counts.values()),
                "candidates": dict(counts),
            }
        )
    return out
