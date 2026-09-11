"""JSONL evidence writer with redaction at the persistence boundary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from automation.evidence.redaction import SensitiveDataRedactor


class JsonlEvidenceWriter:
    def __init__(self, destination: Path, redactor: SensitiveDataRedactor) -> None:
        self._destination = destination
        self._redactor = redactor

    def write_event(self, event: dict[str, Any]) -> None:
        sanitized_event = self._redactor.redact(event)
        self._destination.parent.mkdir(parents=True, exist_ok=True)
        with self._destination.open("a", encoding="utf-8") as evidence_file:
            evidence_file.write(json.dumps(sanitized_event, sort_keys=True, default=str))
            evidence_file.write("\n")