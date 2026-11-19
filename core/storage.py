"""Storage abstraction for web jobs — local disk or S3-compatible backends."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import quote


def storage_root() -> Path:
    root = os.getenv("AIEDIT_STORAGE_ROOT", "").strip()
    if root:
        return Path(root).resolve()
    import tempfile

    return Path(tempfile.gettempdir()).resolve() / "aiedit_storage"


class StorageBackend(ABC):
    @abstractmethod
    def write_bytes(self, key: str, data: bytes) -> str:
        """Persist bytes; return storage key."""

    @abstractmethod
    def write_text(self, key: str, text: str, encoding: str = "utf-8") -> str:
        """Persist text; return storage key."""

    @abstractmethod
    def read_bytes(self, key: str) -> bytes:
        ...

    @abstractmethod
    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        ...

    @abstractmethod
    def local_path(self, key: str) -> Path:
        """Resolved path for ffmpeg / local tools."""

    @abstractmethod
    def public_url(self, key: str) -> str:
        """URL for download (local file URL or CDN)."""

    def write_json(self, key: str, payload: Any) -> str:
        return self.write_text(key, json.dumps(payload, indent=2, ensure_ascii=False))

    def read_json(self, key: str) -> Any:
        return json.loads(self.read_text(key))

    def job_key(self, job_id: str, *parts: str) -> str:
        safe = [job_id] + [p.strip("/\\") for p in parts if p]
        return "/".join(safe)


class LocalStorageBackend(StorageBackend):
    def __init__(self, root: Optional[Union[str, Path]] = None) -> None:
        self.root = Path(root or storage_root()).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._public_base = os.getenv("AIEDIT_PUBLIC_URL_BASE", "").rstrip("/")

    def _path(self, key: str) -> Path:
        rel = key.replace("\\", "/").lstrip("/")
        path = (self.root / rel).resolve()
        if not str(path).startswith(str(self.root)):
            raise ValueError("invalid storage key")
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def write_bytes(self, key: str, data: bytes) -> str:
        p = self._path(key)
        p.write_bytes(data)
        return key

    def write_text(self, key: str, text: str, encoding: str = "utf-8") -> str:
        p = self._path(key)
        p.write_text(text, encoding=encoding)
        return key

    def read_bytes(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def read_text(self, key: str, encoding: str = "utf-8") -> str:
        return self._path(key).read_text(encoding=encoding)

    def local_path(self, key: str) -> Path:
        return self._path(key)

    def public_url(self, key: str) -> str:
        if self._public_base:
            return f"{self._public_base}/{quote(key.replace(chr(92), '/'))}"
        return self.local_path(key).as_uri()


def get_storage() -> StorageBackend:
    backend = os.getenv("AIEDIT_STORAGE_BACKEND", "local").strip().lower()
    if backend in {"local", "filesystem", ""}:
        return LocalStorageBackend()
    # Future: s3/r2 via env bucket + prefix
    return LocalStorageBackend()
