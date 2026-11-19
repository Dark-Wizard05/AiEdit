"""Persistent commentary job state via storage abstraction."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

from core.commentary.config import CommentaryJobState
from core.storage import StorageBackend, get_storage

_LOCK = threading.Lock()
_MEMORY: Dict[str, CommentaryJobState] = {}


def _state_key(job_id: str) -> str:
    return f"commentary/jobs/{job_id}/state.json"


def save_job_state(state: CommentaryJobState, storage: Optional[StorageBackend] = None) -> None:
    st = storage or get_storage()
    payload = state.to_dict()
    payload["output_video_key"] = state.output_video_key
    payload["subtitles_key"] = state.subtitles_key
    payload["script_key"] = state.script_key
    payload["timeline_key"] = state.timeline_key
    st.write_json(_state_key(state.job_id), payload)
    with _LOCK:
        _MEMORY[state.job_id] = state


def load_job_state(job_id: str, storage: Optional[StorageBackend] = None) -> Optional[CommentaryJobState]:
    with _LOCK:
        if job_id in _MEMORY:
            return _MEMORY[job_id]
    st = storage or get_storage()
    key = _state_key(job_id)
    try:
        data = st.read_json(key)
    except Exception:
        return None
    state = CommentaryJobState(
        job_id=job_id,
        stage=data.get("stage", "queued"),
        progress=float(data.get("progress") or 0.0),
        message=str(data.get("message") or ""),
        error=data.get("error"),
        output_video_key=data.get("output_video_key"),
        subtitles_key=data.get("subtitles_key"),
        script_key=data.get("script_key"),
        timeline_key=data.get("timeline_key"),
        music_credit=data.get("musicCredit") or data.get("music_credit"),
        artifacts=dict(data.get("artifacts") or {}),
    )
    for k in ("outputVideoUrl", "subtitlesUrl", "scriptJson"):
        if k in data:
            state.artifacts[k] = data[k]
    with _LOCK:
        _MEMORY[job_id] = state
    return state


def update_job(
    job_id: str,
    *,
    storage: Optional[StorageBackend] = None,
    **kwargs: Any,
) -> CommentaryJobState:
    state = load_job_state(job_id, storage) or CommentaryJobState(job_id=job_id)
    for key, val in kwargs.items():
        if hasattr(state, key):
            setattr(state, key, val)
        elif key in state.artifacts or key.endswith("Url") or key == "scriptJson":
            state.artifacts[key] = val
    save_job_state(state, storage)
    return state
