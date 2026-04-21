"""Execution audit trail persistence."""

from __future__ import annotations

import json
import threading
from pathlib import Path

_DEFAULT_AUDIT_PATH = Path(__file__).resolve().parents[4] / ".data" / "execution_audit.jsonl"


class ExecutionAuditStore:
    """Append-only JSONL audit log for live execution attempts."""

    def __init__(self, path: Path = _DEFAULT_AUDIT_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()

    def append(self, event: dict) -> None:
        """Persist one audit event."""

        self._path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, sort_keys=True)
        with self._lock, self._path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
