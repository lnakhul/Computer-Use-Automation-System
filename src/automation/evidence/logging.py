"""JSONL evidence writer with redaction at the persistence boundary."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation.evidence.redaction import SensitiveDataRedactor


class JsonlEvidenceWriter:
    def __init__(
        self,
        destination: Path,
        redactor: SensitiveDataRedactor,
        run_id: str | None = None,
        capability_id: str | None = None,
        artifact_schema_version: str | None = None,
    ) -> None:
        self._destination = destination
        self._redactor = redactor
        self._run_id = run_id or str(uuid.uuid4())
        self._capability_id = capability_id
        self._artifact_schema_version = artifact_schema_version

    @property
    def run_id(self) -> str:
        return self._run_id

    def write_event(self, event: dict[str, Any]) -> None:
        event_with_context = {
            "run_id": self._run_id,
            "capability_id": self._capability_id,
            "artifact_schema_version": self._artifact_schema_version,
            "event_timestamp": datetime.now(timezone.utc).isoformat(),
            **event,
        }
        sanitized_event = self._redactor.redact(event_with_context)
        self._destination.parent.mkdir(parents=True, exist_ok=True)
        with self._destination.open("a", encoding="utf-8") as evidence_file:
            evidence_file.write(json.dumps(sanitized_event, sort_keys=True, default=str))
            evidence_file.write("\n")