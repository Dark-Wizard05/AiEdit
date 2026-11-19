"""FastAPI routes for Commentary v2 web jobs."""

from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from core.commentary.config import CommentaryJobConfig, CommentaryJobState
from core.commentary.job_store import load_job_state, save_job_state, update_job
from core.commentary.music import list_music_tracks
from core.commentary.pipeline import run_commentary_job
from core.storage import get_storage

router = APIRouter(prefix="/api/commentary", tags=["Commentary"])


class CommentaryJobCreate(BaseModel):
    videoId: Optional[str] = Field(None, description="Storage key from prior upload")
    playerName: Optional[str] = None
    videoContext: Optional[str] = Field(None, description="Optional hint: sports match, cooking vlog, gameplay, etc.")
    tone: Optional[Literal["hype", "dry", "balanced", "roast"]] = "hype"
    musicTrackId: Optional[str] = None
    musicEnabled: bool = False
    mustIncludeJoke: Optional[str] = None
    mustSyncTimestamp: Optional[float] = None
    allowFastForward: bool = False
    voice: Optional[str] = None


class CommentaryJobStatus(BaseModel):
    job_id: str
    stage: str
    progress: float
    message: str = ""
    error: Optional[str] = None


class CommentaryJobResult(BaseModel):
    job_id: str
    outputVideoUrl: Optional[str] = None
    subtitlesUrl: Optional[str] = None
    scriptJson: Optional[Dict[str, Any]] = None
    musicCredit: Optional[str] = None


def _ingest_upload(job_id: str, upload: UploadFile) -> str:
    storage = get_storage()
    ext = Path(upload.filename or "video.mp4").suffix or ".mp4"
    key = storage.job_key(job_id, f"source{ext}")
    dest = storage.local_path(key)
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return key


def _run_commentary_async(job_id: str, video_key: str, body: CommentaryJobCreate) -> None:
    storage = get_storage()
    config = CommentaryJobConfig.from_dict(
        job_id,
        video_key,
        {
            "player_name": body.playerName,
            "video_context": body.videoContext,
            "tone": body.tone,
            "music_track_id": body.musicTrackId,
            "music_enabled": body.musicEnabled,
            "must_include_joke": body.mustIncludeJoke,
            "must_sync_timestamp": body.mustSyncTimestamp,
            "allow_fast_forward": body.allowFastForward,
            "voice": body.voice,
        },
    )
    try:
        run_commentary_job(config, storage=storage)
    except Exception as exc:  # noqa: BLE001 — worker boundary
        update_job(job_id, storage=storage, stage="error", error=str(exc), message="Failed")


@router.post("/upload")
async def upload_commentary_video(file: UploadFile = File(...)) -> Dict[str, str]:
    """Upload video clip; returns videoId storage key for job creation."""

    job_id = str(uuid.uuid4())
    video_key = _ingest_upload(job_id, file)
    save_job_state(CommentaryJobState(job_id=job_id, stage="ingesting", message="Upload complete"))
    return {"videoId": video_key, "uploadJobId": job_id}


@router.post("/jobs", response_model=CommentaryJobStatus)
async def create_commentary_job(body: CommentaryJobCreate) -> CommentaryJobStatus:
    if not body.videoId:
        raise HTTPException(status_code=400, detail="videoId is required (upload first or pass storage key)")

    storage = get_storage()
    if not storage.local_path(body.videoId).is_file():
        raise HTTPException(status_code=404, detail=f"video not found: {body.videoId}")

    job_id = str(uuid.uuid4())
    state = CommentaryJobState(job_id=job_id, stage="queued", message="Queued")
    save_job_state(state, storage)
    threading.Thread(
        target=_run_commentary_async,
        args=(job_id, body.videoId, body),
        daemon=True,
    ).start()
    return CommentaryJobStatus(job_id=job_id, stage="queued", progress=0.0, message="Queued")


@router.get("/jobs/{job_id}", response_model=CommentaryJobStatus)
async def get_commentary_job(job_id: str) -> CommentaryJobStatus:
    state = load_job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
    return CommentaryJobStatus(
        job_id=state.job_id,
        stage=state.stage,
        progress=state.progress,
        message=state.message,
        error=state.error,
    )


@router.get("/jobs/{job_id}/result", response_model=CommentaryJobResult)
async def get_commentary_result(job_id: str) -> CommentaryJobResult:
    state = load_job_state(job_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"job '{job_id}' not found")
    if state.stage != "done":
        raise HTTPException(status_code=409, detail=f"job not complete (stage={state.stage})")
    return CommentaryJobResult(
        job_id=job_id,
        outputVideoUrl=state.artifacts.get("outputVideoUrl"),
        subtitlesUrl=state.artifacts.get("subtitlesUrl"),
        scriptJson=state.artifacts.get("scriptJson"),
        musicCredit=state.music_credit,
    )


@router.get("/music-tracks")
async def get_music_tracks() -> List[Dict[str, Any]]:
    return [{"id": t.get("id"), "title": t.get("title"), "composer": t.get("composer")} for t in list_music_tracks()]
