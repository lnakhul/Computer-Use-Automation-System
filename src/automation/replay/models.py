"""Typed replay results and failure taxonomy."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import Field

from automation.capabilities.models import ContractModel


class ReplayFailureCategory(StrEnum):
    INVALID_INVOCATION = "invalid_invocation"
    POLICY_REJECTION = "policy_rejection"
    MISSING_TARGET = "missing_target"
    VALIDATION_ERROR = "validation_error"
    CHECKPOINT_FAILURE = "checkpoint_failure"
    TRANSIENT_CONDITION_EXHAUSTED = "transient_condition_exhausted"
    SURFACE_FAILURE = "surface_failure"
    ARTIFACT_FAILURE = "artifact_failure"


class ReplayResultBase(ContractModel):
    capability_id: str
    artifact_schema_version: str
    steps_executed: int = Field(ge=0)


class CapabilityExecutionSucceeded(ReplayResultBase):
    result_type: Literal["succeeded"] = "succeeded"
    outputs: dict[str, object] = Field(default_factory=dict)


class KnownBusinessOutcome(ReplayResultBase):
    result_type: Literal["business_outcome"] = "business_outcome"
    outcome_code: str
    description: str


class CapabilityExecutionFailed(ReplayResultBase):
    result_type: Literal["failed"] = "failed"
    step_id: str
    step_index: int = Field(ge=0)
    expected_state: str
    observed_state: str
    failure_category: ReplayFailureCategory
    debugging_summary: str
    evidence_reference: str | None = None


class HumanInterventionRequired(ReplayResultBase):
    result_type: Literal["human_intervention_required"] = "human_intervention_required"
    step_id: str
    step_index: int = Field(ge=0)
    reason: str
    evidence_reference: str | None = None


CapabilityExecutionResult = Annotated[
    Union[
        CapabilityExecutionSucceeded,
        KnownBusinessOutcome,
        CapabilityExecutionFailed,
        HumanInterventionRequired,
    ],
    Field(discriminator="result_type"),
]