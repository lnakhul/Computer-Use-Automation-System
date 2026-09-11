"""Typed discovery requests, decisions, and run results."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Union

from pydantic import Field, PositiveInt

from automation.capabilities.models import (
    ActionRisk,
    CheckpointCondition,
    CompatibilityMetadata,
    CapabilityArtifact,
    ElementTarget,
    InputParameter,
    OutputDeclaration,
    SafetyProfile,
    BusinessOutcome,
    SuccessCheckpoint,
)
from automation.capabilities.models import ContractModel


class DiscoveryStopState(StrEnum):
    GOAL_ACHIEVED = "goal_achieved"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    STEP_LIMIT_REACHED = "step_limit_reached"
    TIMEOUT = "timeout"
    MODEL_INVALID_RESPONSE = "model_invalid_response"
    UNRECOVERABLE_SURFACE_FAILURE = "unrecoverable_surface_failure"
    HUMAN_INTERVENTION_REQUIRED = "human_intervention_required"


class RuntimeParameter(ContractModel):
    name: str = Field(min_length=1)
    value: str = Field(min_length=1)
    sensitive: bool = False


class DiscoveryArtifactDefinition(ContractModel):
    capability_id: str = Field(min_length=1)
    revision: PositiveInt
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    compatibility: CompatibilityMetadata
    entry_point: str = Field(min_length=1)
    inputs: list[InputParameter] = Field(default_factory=list)
    outputs: list[OutputDeclaration] = Field(default_factory=list)
    success_checkpoint: SuccessCheckpoint
    known_business_outcomes: list[BusinessOutcome] = Field(default_factory=list)
    safety_profile: SafetyProfile


class DiscoveryRequest(ContractModel):
    goal: str = Field(min_length=1)
    artifact_definition: DiscoveryArtifactDefinition
    runtime_parameters: list[RuntimeParameter] = Field(default_factory=list)
    maximum_steps: PositiveInt = 12
    total_timeout_seconds: float = Field(gt=0, le=3600)


class DecisionBase(ContractModel):
    reasoning_summary: str = Field(min_length=1, max_length=500)


class NavigateDecision(DecisionBase):
    decision_type: Literal["navigate"] = "navigate"
    destination: str = Field(min_length=1)
    risk: ActionRisk = ActionRisk.READ_ONLY


class ClickDecision(DecisionBase):
    decision_type: Literal["click"] = "click"
    target: ElementTarget
    risk: ActionRisk = ActionRisk.READ_ONLY


class FillDecision(DecisionBase):
    decision_type: Literal["fill"] = "fill"
    target: ElementTarget
    text: str = Field(min_length=1, max_length=500)
    parameter_name: str | None = None
    risk: ActionRisk = ActionRisk.REVERSIBLE


class WaitForStateDecision(DecisionBase):
    decision_type: Literal["wait_for_state"] = "wait_for_state"
    condition: CheckpointCondition
    timeout_seconds: float = Field(gt=0, le=120)
    risk: ActionRisk = ActionRisk.READ_ONLY


class ExtractTextDecision(DecisionBase):
    decision_type: Literal["extract_text"] = "extract_text"
    target: ElementTarget
    output_name: str = Field(min_length=1)
    risk: ActionRisk = ActionRisk.READ_ONLY


class GoalAchievedDecision(DecisionBase):
    decision_type: Literal["goal_achieved"] = "goal_achieved"


class HumanInterventionDecision(DecisionBase):
    decision_type: Literal["human_intervention_required"] = "human_intervention_required"
    reason: str = Field(min_length=1, max_length=500)


AgentDecision = Annotated[
    Union[
        NavigateDecision,
        ClickDecision,
        FillDecision,
        WaitForStateDecision,
        ExtractTextDecision,
        GoalAchievedDecision,
        HumanInterventionDecision,
    ],
    Field(discriminator="decision_type"),
]


class DiscoveryResult(ContractModel):
    stop_state: DiscoveryStopState
    steps_executed: int = Field(ge=0)
    artifact: CapabilityArtifact | None = None
    reason: str | None = None
    evidence_reference: str | None = None

