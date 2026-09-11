"""Typed control-transfer and operator-action records."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import Field

from automation.capabilities.models import ContractModel
from automation.surface.contracts import HumanSurfaceActionType


class ControlOwner(StrEnum):
    AUTOMATION = "automation"
    HUMAN = "human"


class HumanInterventionRequest(ContractModel):
    request_id: str = Field(min_length=1)
    capability_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    current_step_id: str = Field(min_length=1)
    current_step_index: int = Field(ge=0)
    reason: str = Field(min_length=1)
    sanitized_current_state: dict[str, str | None]
    screenshot_evidence_reference: str | None = None
    session_id: str = Field(min_length=1)
    control_owner: ControlOwner = ControlOwner.HUMAN


class HumanActionRecord(ContractModel):
    request_id: str
    session_id: str
    action_type: HumanSurfaceActionType
    description: str
    result_summary: str
    evidence_reference: str | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ControlTransferEvent(ContractModel):
    session_id: str
    from_owner: ControlOwner
    to_owner: ControlOwner
    reason: str
    request_id: str | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))