"""Recursive redaction for structured evidence."""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field

from automation.capabilities.models import ContractModel


class RedactionPolicy(ContractModel):
    sensitive_field_names: list[str] = Field(default_factory=list)
    sensitive_value_patterns: list[str] = Field(default_factory=list)
    replacement: str = "[REDACTED]"


class SensitiveDataRedactor:
    def __init__(self, policy: RedactionPolicy) -> None:
        self._policy = policy
        self._field_names = {field_name.casefold() for field_name in policy.sensitive_field_names}
        self._patterns = [re.compile(pattern, re.IGNORECASE) for pattern in policy.sensitive_value_patterns]

    def redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: self._policy.replacement
                if key.casefold() in self._field_names
                else self.redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact(item) for item in value)
        if isinstance(value, str):
            redacted_value = value
            for pattern in self._patterns:
                redacted_value = pattern.sub(self._policy.replacement, redacted_value)
            return redacted_value
        return value