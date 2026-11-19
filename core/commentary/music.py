"""Royalty-free music track metadata — keys from env/storage, not hardcoded paths."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.storage import StorageBackend, get_storage


def _manifest_path() -> Optional[Path]:
    env = os.getenv("AIEDIT_MUSIC_MANIFEST", "").strip()
    if env:
        return Path(env)
    return None


def _default_tracks() -> List[Dict[str, Any]]:
    prefix = os.getenv("AIEDIT_MUSIC_LIBRARY_PREFIX", "assets/music").strip("/")
    return [
        {
            "id": "ambient-drive",
            "title": "Ambient Drive",
            "composer": "AiEdit Library",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "storage_key": f"{prefix}/ambient_drive.mp3",
        },
        {
            "id": "pulse-bed",
            "title": "Pulse Bed",
            "composer": "AiEdit Library",
            "license_url": "https://creativecommons.org/licenses/by/4.0/",
            "storage_key": f"{prefix}/pulse_bed.mp3",
        },
    ]


def list_music_tracks() -> List[Dict[str, Any]]:
    manifest = _manifest_path()
    if manifest and manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            tracks = data.get("tracks") if isinstance(data, dict) else data
            if isinstance(tracks, list):
                return tracks
        except Exception:
            pass
    return _default_tracks()


def resolve_music_track(
    track_id: Optional[str],
    storage: Optional[StorageBackend] = None,
) -> Optional[Dict[str, Any]]:
    if not track_id:
        return None
    for track in list_music_tracks():
        if str(track.get("id")) == track_id:
            st = storage or get_storage()
            key = str(track.get("storage_key") or "")
            if key and st.local_path(key).is_file():
                return track
            return track  # caller may skip if file missing
    return None


def music_credit_string(track: Dict[str, Any]) -> str:
    title = track.get("title") or "Background music"
    composer = track.get("composer") or "Unknown"
    license_url = track.get("license_url") or ""
    if license_url:
        return f'Music: "{title}" by {composer} — {license_url}'
    return f'Music: "{title}" by {composer}'
