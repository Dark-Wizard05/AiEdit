"""
Studio API for the SvelteKit frontend — local development only.

Upload videos, parse prompts, run jobs through core.engine, stream results.
"""

from __future__ import annotations

import shutil
import threading
import uuid
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

import cv2
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.auth_db import get_entitlements as db_get_entitlements
from backend.auth_db import record_edit
from backend.auth_routes import get_current_user

from core.clarification import clarification_question, needs_clarification
from core.engine import ExecutionContext, execute
from core.presets import detect_hardware, get_preset, recommend
from core.storage import get_storage
from core.tiers import (
    dev_premium_unlocked,
    enrich_plan_fields,
    instruction_for_execution,
    premium_required_for_instruction,
    user_has_premium,
)

router = APIRouter(prefix="/api", tags=["Studio"])

_VIDEOS: Dict[str, Dict[str, Any]] = {}
_REFERENCES: Dict[str, Dict[str, Any]] = {}
_JOBS: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()


class SystemStatus(BaseModel):
    parser: Dict[str, Any]
    hardware: Dict[str, Any]
    recommended_preset: str
    presets: List[str]
    default_features: List[str]
    premium_features: List[str]
    dev_premium_unlocked: bool


class VideoInfo(BaseModel):
    video_id: str
    filename: str
    duration_sec: Optional[float] = None
    fps: Optional[float] = None
    frame_count: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None


class ParseRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class ParseResponse(BaseModel):
    operation: str
    summary: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    supported: bool = True
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    needs_clarification: bool = False
    clarification_question: Optional[str] = None
    validation: Optional[Dict[str, Any]] = None
    tier: str = "default"
    premium_required: bool = False
    executable_default: bool = True
    user_message: str = ""
    premium_message: Optional[str] = None


class JobSubmitRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    video_id: str
    preset: Optional[Literal["fast", "balanced", "quality"]] = None
    reference_ids: List[str] = Field(default_factory=list)
    use_premium: bool = False


class JobStatusResponse(BaseModel):
    job_id: str
    state: Literal["queued", "running", "done", "error"]
    stage: str = "queued"
    progress: float = 0.0
    message: str = ""
    operation: Optional[str] = None
    summary: Optional[str] = None
    plan: Optional[Dict[str, Any]] = None
    output_video_path: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    validation: Optional[Dict[str, Any]] = None
    artifacts: Optional[Dict[str, Any]] = None
    premium_required: bool = False
    premium_message: Optional[str] = None


def _instruction_to_parse_response(instruction: Any) -> ParseResponse:
    from core.edit_plan import validate_edit_instruction

    validation = validate_edit_instruction(instruction)
    meta = getattr(instruction, "metadata", None) or {}
    tier_fields = enrich_plan_fields(instruction)
    return ParseResponse(
        operation=getattr(instruction, "operation", "unsupported"),
        summary=getattr(instruction, "summary", ""),
        parameters=dict(getattr(instruction, "parameters", {}) or {}),
        supported=bool(getattr(instruction, "supported", True)),
        warnings=list(getattr(instruction, "warnings", []) or []),
        metadata=dict(meta) if isinstance(meta, dict) else {},
        needs_clarification=needs_clarification(instruction),
        clarification_question=clarification_question(instruction) if needs_clarification(instruction) else None,
        validation=validation.to_dict(),
        tier=tier_fields["tier"],
        premium_required=tier_fields["premium_required"],
        executable_default=tier_fields["executable_default"],
        user_message=tier_fields["user_message"],
        premium_message=tier_fields["premium_message"],
    )


def _probe_video(path: Path) -> Dict[str, Any]:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return {}
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    duration = count / fps if fps > 0 else None
    return {
        "fps": float(fps),
        "frame_count": count,
        "width": width,
        "height": height,
        "duration_sec": duration,
    }


def _update_job(job_id: str, **fields: Any) -> None:
    with _LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(fields)


def _run_studio_job(job_id: str, body: JobSubmitRequest, user_id: str) -> None:
    from utils.prompt_parser import parse_edit_command

    try:
        from logging_config import log_event
    except Exception:
        def log_event(*_a, **_k):
            return None

    def progress(stage: str, prog: float, message: str) -> None:
        _update_job(job_id, stage=stage, progress=min(0.99, prog), message=message, state="running")

    log_event("job_start", job_id=job_id, prompt=body.prompt)
    _update_job(job_id, state="running", stage="parse", progress=0.05, message="Parsing prompt…")

    try:
        with _LOCK:
            video = _VIDEOS.get(body.video_id)
        if not video:
            raise ValueError(f"video '{body.video_id}' not found")

        ent = db_get_entitlements(user_id)
        if ent.subscription_status != "active":
            _update_job(
                job_id,
                state="error",
                stage="validate",
                error="Active subscription required. Choose a plan in Profile.",
                error_code="subscription_required",
            )
            log_event("job_finish", job_id=job_id, ok=False, error="subscription_required")
            return
        if ent.limit_reached:
            _update_job(
                job_id,
                state="error",
                stage="validate",
                error=f"Daily limit reached ({ent.daily_edit_limit} edits). See Profile for upgrades.",
                error_code="limit_reached",
            )
            log_event("job_finish", job_id=job_id, ok=False, error="limit_reached")
            return

        instruction = parse_edit_command(body.prompt)
        plan = _instruction_to_parse_response(instruction)
        _update_job(
            job_id,
            plan=plan.model_dump(),
            operation=plan.operation,
            summary=plan.summary,
            premium_required=plan.premium_required,
            premium_message=plan.premium_message,
        )

        if plan.needs_clarification:
            _update_job(
                job_id,
                state="error",
                stage="validate",
                progress=0.15,
                error=plan.clarification_question or "Clarification needed",
                error_code="clarification",
                validation=plan.validation,
            )
            log_event("job_finish", job_id=job_id, ok=False, error="clarification")
            return

        if plan.premium_required and not user_has_premium(use_premium_flag=body.use_premium, entitlements=ent):
            _update_job(
                job_id,
                state="error",
                stage="validate",
                progress=0.15,
                error=plan.premium_message or "Premium plan required for code-gen edits.",
                error_code="premium_required",
                validation=plan.validation,
            )
            log_event("job_finish", job_id=job_id, ok=False, error="premium_required")
            return

        instruction = instruction_for_execution(
            instruction,
            prompt=body.prompt,
            use_premium=body.use_premium,
            entitlements=ent,
        )

        _update_job(job_id, stage="validate", progress=0.12, message="Validating edit plan…")

        preset = get_preset(body.preset) if body.preset else recommend()
        ref_paths: List[str] = []
        with _LOCK:
            for rid in body.reference_ids:
                ref = _REFERENCES.get(rid)
                if ref:
                    ref_paths.append(ref["path"])

        storage = get_storage()
        out_dir = storage.local_path(storage.job_key(job_id, "output"))
        out_dir.mkdir(parents=True, exist_ok=True)

        ctx = ExecutionContext(
            video_path=video["path"],
            output_dir=str(out_dir),
            device=preset.device,
            fps=preset.fps,
            reference_image_paths=ref_paths,
            extra={
                "progress_callback": progress,
                "atmosphere": dict(instruction.parameters or {}),
            },
        )

        _update_job(job_id, stage="execute", progress=0.2, message="Running edit pipeline…")
        result = execute(instruction, ctx)

        if result.ok and result.output_video_path:
            record_edit(user_id)
            _update_job(
                job_id,
                state="done",
                stage="done",
                progress=1.0,
                message=result.summary or "Complete",
                output_video_path=result.output_video_path,
                validation=result.validation.to_dict() if result.validation else plan.validation,
                artifacts=result.artifacts,
            )
            log_event("job_finish", job_id=job_id, ok=True, operation=result.operation)
        else:
            _update_job(
                job_id,
                state="error",
                stage="execute",
                progress=0.5,
                error=result.error or "Edit failed",
                validation=result.validation.to_dict() if result.validation else plan.validation,
            )
            log_event("job_finish", job_id=job_id, ok=False, error=result.error)
    except Exception as exc:
        _update_job(job_id, state="error", error=str(exc), message=str(exc))
        log_event("job_finish", job_id=job_id, ok=False, error=str(exc))


@router.get("/health")
async def health():
    return {"ok": True, "service": "aiedit-studio"}


@router.get("/system/status", response_model=SystemStatus)
async def system_status():
    from utils.prompt_parser import get_prompt_parser_status

    from core.tiers import DEFAULT_FEATURES, PREMIUM_FEATURES

    hw = detect_hardware()
    rec = recommend()
    return SystemStatus(
        parser=get_prompt_parser_status(),
        hardware=hw,
        recommended_preset=rec.name,
        presets=["fast", "balanced", "quality"],
        default_features=DEFAULT_FEATURES,
        premium_features=PREMIUM_FEATURES,
        dev_premium_unlocked=dev_premium_unlocked(),
    )


@router.post("/videos/upload", response_model=VideoInfo)
async def upload_video(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    ent = db_get_entitlements(user["id"])
    if ent.subscription_status != "active":
        raise HTTPException(status_code=402, detail="Active subscription required")
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")

    ext = Path(file.filename).suffix.lower()
    if ext not in {".mp4", ".avi", ".mov", ".mkv", ".webm"}:
        raise HTTPException(status_code=400, detail="Unsupported video format")

    video_id = str(uuid.uuid4())
    storage = get_storage()
    key = storage.job_key("videos", video_id, f"source{ext}")
    dest = storage.local_path(key)
    dest.parent.mkdir(parents=True, exist_ok=True)

    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    meta = _probe_video(dest)
    record = {
        "video_id": video_id,
        "filename": file.filename,
        "path": str(dest.resolve()),
        "storage_key": key,
        **meta,
    }
    with _LOCK:
        _VIDEOS[video_id] = record

    return VideoInfo(
        video_id=video_id,
        filename=file.filename,
        duration_sec=meta.get("duration_sec"),
        fps=meta.get("fps"),
        frame_count=meta.get("frame_count"),
        width=meta.get("width"),
        height=meta.get("height"),
    )


@router.get("/videos/{video_id}", response_model=VideoInfo)
async def get_video(video_id: str):
    with _LOCK:
        record = _VIDEOS.get(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="video not found")
    return VideoInfo(
        video_id=record["video_id"],
        filename=record["filename"],
        duration_sec=record.get("duration_sec"),
        fps=record.get("fps"),
        frame_count=record.get("frame_count"),
        width=record.get("width"),
        height=record.get("height"),
    )


@router.get("/videos/{video_id}/stream")
async def stream_video(video_id: str):
    with _LOCK:
        record = _VIDEOS.get(video_id)
    if not record:
        raise HTTPException(status_code=404, detail="video not found")
    path = Path(record["path"])
    if not path.is_file():
        raise HTTPException(status_code=404, detail="video file missing")
    return FileResponse(path, media_type="video/mp4", filename=record["filename"])


@router.post("/references/upload")
async def upload_reference(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")

    ref_id = str(uuid.uuid4())
    storage = get_storage()
    ext = Path(file.filename).suffix.lower() or ".png"
    key = storage.job_key("references", ref_id, f"image{ext}")
    dest = storage.local_path(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    with _LOCK:
        _REFERENCES[ref_id] = {"ref_id": ref_id, "filename": file.filename, "path": str(dest.resolve())}
    return {"ref_id": ref_id, "filename": file.filename}


@router.post("/parse", response_model=ParseResponse)
async def parse_prompt(body: ParseRequest, user: dict = Depends(get_current_user)):
    from utils.prompt_parser import parse_edit_command

    instruction = parse_edit_command(body.prompt)
    return _instruction_to_parse_response(instruction)


@router.post("/jobs", response_model=JobStatusResponse)
async def submit_job(body: JobSubmitRequest, user: dict = Depends(get_current_user)):
    with _LOCK:
        if body.video_id not in _VIDEOS:
            raise HTTPException(status_code=404, detail="video not found")

    job_id = str(uuid.uuid4())
    with _LOCK:
        _JOBS[job_id] = {
            "job_id": job_id,
            "state": "queued",
            "stage": "queued",
            "progress": 0.0,
            "message": "Queued…",
        }
    threading.Thread(target=_run_studio_job, args=(job_id, body, user["id"]), daemon=True).start()
    with _LOCK:
        return JobStatusResponse(**_JOBS[job_id])


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(job_id: str):
    with _LOCK:
        record = _JOBS.get(job_id)
    if not record:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(**record)


@router.get("/jobs/{job_id}/video")
async def download_job_video(job_id: str):
    with _LOCK:
        record = _JOBS.get(job_id)
    if not record or record.get("state") != "done":
        raise HTTPException(status_code=404, detail="output not ready")
    path = record.get("output_video_path")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail="output file missing")
    return FileResponse(path, media_type="video/mp4", filename=f"aiedit_{job_id[:8]}.mp4")
