"""
Append-only local prompt memory.

Each successful or failed parse is recorded as one JSON line in
``logs/prompt_history.jsonl``. This is the bootstrap for Phase 2's
"prompt -> plan -> outcome -> correction" memory: pure local file, no DB,
safe to delete.

API kept tiny on purpose:

- ``log_parse(...)``: write one record (best-effort; never raises).
- ``recent_examples(limit=...)``: read last N records for future few-shot.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_LOG_DIR = Path(os.getenv("AIEDIT_LOG_DIR", "logs"))
_HISTORY_PATH = _LOG_DIR / "prompt_history.jsonl"
_LOCK = threading.Lock()


def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if is_dataclass(value):
        return _serialize(asdict(value))
    if isinstance(value, dict):
        return {str(k): _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize(v) for v in value]
    return str(value)


def log_parse(
    *,
    prompt: str,
    instruction: Any,
    validation: Any = None,
    outcome: Optional[str] = None,
    correction: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Best-effort append of one parse record. Never raises."""

    record = {
        "ts": time.time(),
        "prompt": prompt,
        "instruction": _serialize(instruction),
        "validation": _serialize(validation),
        "outcome": outcome,
        "correction": correction,
    }
    if extra:
        record["extra"] = _serialize(extra)

    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with _LOCK:
            with _HISTORY_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        # Memory is a nice-to-have; never block parsing if disk is unhappy.
        return


def log_correction(
    *,
    prompt: str,
    correction: str,
    instruction: Any = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a user-supplied correction so we can few-shot or analyze later.

    A correction is what the user *meant* the parser to do for this prompt
    (free text, or a structured plan). Stored as a separate entry tagged
    ``kind = correction`` so it doesn't pollute parse stats.
    """

    record_extra = {"kind": "correction"}
    if extra:
        record_extra.update(extra)
    log_parse(
        prompt=prompt,
        instruction=instruction,
        outcome="user_correction",
        correction=correction,
        extra=record_extra,
    )


def _iter_records() -> Iterable[Dict[str, Any]]:
    if not _HISTORY_PATH.exists():
        return []
    try:
        with _HISTORY_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []


def recent_examples(limit: int = 20) -> List[Dict[str, Any]]:
    """Return the last ``limit`` records (oldest -> newest)."""

    records = list(_iter_records())
    if limit <= 0:
        return []
    return records[-limit:]


def history_path() -> Path:
    return _HISTORY_PATH
