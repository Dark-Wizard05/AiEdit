"""Commentary job configuration — no hardcoded paths or clip-specific values."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional


ToneKind = Literal["hype", "dry", "balanced", "roast"]
CommentaryStage = Literal[
    "queued",
    "ingesting",
    "analyzing",
    "writing_script",
    "validating_script",
    "rendering_tts",
    "scheduling",
    "building_subtitles",
    "muxing",
    "done",
    "error",
]


@dataclass
class CommentaryJobConfig:
    job_id: str
    video_storage_key: str
    player_name: Optional[str] = None
    game_title: str = ""
    video_context: Optional[str] = None
    tone: ToneKind = "hype"
    voice: str = "en-US-GuyNeural"
    music_track_id: Optional[str] = None
    music_enabled: bool = False
    music_volume: float = 0.12
    must_include_joke: Optional[str] = None
    must_sync_timestamp: Optional[float] = None
    allow_fast_forward: bool = False
    sample_fps: float = 1.0
    mute_game_audio: bool = True
    device: str = "cpu"
    seed: int = 42

    @classmethod
    def from_dict(cls, job_id: str, video_key: str, data: Optional[Dict[str, Any]] = None) -> "CommentaryJobConfig":
        d = dict(data or {})
        tone = str(d.get("tone") or "hype").lower()
        if tone == "balanced":
            tone = "hype"
        if tone not in {"hype", "dry", "roast"}:
            tone = "hype"
        music_vol = float(d.get("music_volume", os.getenv("AIEDIT_COMMENTARY_MUSIC_VOLUME", "0.12")))
        music_vol = max(0.08, min(0.18, music_vol))
        return cls(
            job_id=job_id,
            video_storage_key=video_key,
            player_name=(d.get("player_name") or d.get("playerName") or None),
            game_title=str(d.get("game_title") or d.get("gameTitle") or d.get("video_context") or d.get("videoContext") or ""),
            video_context=(d.get("video_context") or d.get("videoContext") or d.get("game_title") or d.get("gameTitle") or None),
            tone=tone,  # type: ignore[arg-type]
            voice=str(d.get("voice") or os.getenv("AIEDIT_COMMENTARY_VOICE", "en-US-GuyNeural")),
            music_track_id=d.get("music_track_id") or d.get("musicTrackId"),
            music_enabled=bool(d.get("music_enabled", d.get("musicEnabled", False))),
            music_volume=music_vol,
            must_include_joke=d.get("must_include_joke") or d.get("mustIncludeJoke"),
            must_sync_timestamp=_float_or_none(d.get("must_sync_timestamp") or d.get("mustSyncTimestamp")),
            allow_fast_forward=bool(d.get("allow_fast_forward", d.get("allowFastForward", False))),
            sample_fps=float(d.get("sample_fps") or os.getenv("AIEDIT_COMMENTARY_SAMPLE_FPS", "1.0")),
            mute_game_audio=bool(d.get("mute_game_audio", d.get("muteGameAudio", True))),
            device=str(d.get("device") or "cpu"),
            seed=int(d.get("seed") or 42),
        )


def _float_or_none(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class CommentaryJobState:
    job_id: str
    stage: CommentaryStage = "queued"
    progress: float = 0.0
    message: str = ""
    error: Optional[str] = None
    output_video_key: Optional[str] = None
    subtitles_key: Optional[str] = None
    script_key: Optional[str] = None
    timeline_key: Optional[str] = None
    music_credit: Optional[str] = None
    artifacts: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "stage": self.stage,
            "progress": round(self.progress, 3),
            "message": self.message,
            "error": self.error,
            "outputVideoUrl": self.artifacts.get("outputVideoUrl"),
            "subtitlesUrl": self.artifacts.get("subtitlesUrl"),
            "scriptJson": self.artifacts.get("scriptJson"),
            "musicCredit": self.music_credit,
            "timeline_key": self.timeline_key,
        }
