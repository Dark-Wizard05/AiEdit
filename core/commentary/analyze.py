"""Stage 1: analyzeVideo — sample frames and build timeline.json."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.commentary.config import CommentaryJobConfig
from core.commentary.timeline import build_timeline, fill_scene_beats
from core.storage import StorageBackend
from utils.atmosphere_overlay import _ffprobe_exe
from utils.commentary_events import detect_events_from_frames
from utils.video_processor import extract_frames

try:
    from logging_config import get_logger

    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)

ProgressFn = Optional[Callable[[str, float, str], None]]


def probe_duration_sec(video_path: str) -> float:
    try:
        r = subprocess.run(
            [
                _ffprobe_exe(),
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return max(0.1, float(r.stdout.strip()))
    except Exception:
        return 60.0


def analyze_video(
    config: CommentaryJobConfig,
    storage: StorageBackend,
    work_dir: Path,
    *,
    progress: ProgressFn = None,
) -> Dict[str, Any]:
    """Extract ~1fps frames, OCR on-screen details, return timeline + metadata."""

    video_path = storage.local_path(config.video_storage_key)
    if not video_path.is_file():
        raise FileNotFoundError(f"video not found: {config.video_storage_key}")

    duration = probe_duration_sec(str(video_path))
    frames_key = storage.job_key(config.job_id, "frames")
    frames_dir = work_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    if progress:
        progress("analyzing", 0.08, f"Sampling frames at {config.sample_fps} fps")

    if not extract_frames(str(video_path), str(frames_dir), fps=config.sample_fps):
        raise RuntimeError("frame extraction failed during analyze")

    frame_files = sorted(frames_dir.glob("frame_*.png"))
    if not frame_files:
        raise RuntimeError("no frames extracted")

    if progress:
        progress("analyzing", 0.15, f"OCR on {len(frame_files)} sampled frames")

    raw_events = detect_events_from_frames(
        frame_files,
        sample_fps=config.sample_fps,
        device=config.device,
        progress=progress,
    )

    timeline = build_timeline(
        raw_events,
        duration_sec=duration,
        sample_fps=config.sample_fps,
    )
    timeline = fill_scene_beats(timeline, duration_sec=duration)

    timeline_payload = {
        "job_id": config.job_id,
        "duration_sec": duration,
        "sample_fps": config.sample_fps,
        "timeline": timeline,
        "raw_event_count": len(raw_events),
    }

    timeline_key = storage.job_key(config.job_id, "timeline.json")
    storage.write_json(timeline_key, timeline_payload)

    logger.info(
        "analyze_video job=%s duration=%.1fs timeline_entries=%s raw_events=%s",
        config.job_id,
        duration,
        len(timeline),
        len(raw_events),
    )

    return {
        "timeline_key": timeline_key,
        "timeline": timeline,
        "duration_sec": duration,
        "raw_events": raw_events,
        "video_path": str(video_path),
    }
