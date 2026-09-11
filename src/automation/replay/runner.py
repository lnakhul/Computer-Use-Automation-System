"""Ordered, LLM-free capability replay."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from automation.capabilities.models import (
    Action,
    CapabilityArtifact,
    CheckpointCondition,
    ElementVisibleCondition,
    ExtractedValueMatchesCondition,
    ExtractTextAction,
    TextContainsCondition,
    UrlMatchesCondition,
)
from automation.evidence.logging import JsonlEvidenceWriter
from automation.policy.enforced_surface import PolicyEnforcedSurfaceAdapter, PolicyViolationError
from automation.policy.models import PolicyDecisionKind
from automation.replay.models import (
    CapabilityExecutionFailed,
    CapabilityExecutionResult,
    CapabilityExecutionSucceeded,
    HumanInterventionRequired,
    KnownBusinessOutcome,
    ReplayFailureCategory,
)
from automation.surface.contracts import ComputerSurfaceAdapter, SurfaceObservation
from automation.surface.errors import SurfaceAdapterError


class CapabilityReplayRunner:
    def __init__(
        self,
        surface: ComputerSurfaceAdapter,
        policy_surface: PolicyEnforcedSurfaceAdapter,
        evidence_writer: JsonlEvidenceWriter | None = None,
        evidence_directory: Path | None = None,
        transient_retry_limit: int = 1,
    ) -> None:
        self._surface = surface
        self._policy_surface = policy_surface
        self._evidence_writer = evidence_writer
        self._evidence_directory = evidence_directory
        self._transient_retry_limit = transient_retry_limit

    def replay(
        self,
        artifact: CapabilityArtifact,
        invocation_parameters: Mapping[str, object],
    ) -> CapabilityExecutionResult:
        validation_error = self._validate_invocation(artifact, invocation_parameters)
        if validation_error is not None:
            return self._failure(artifact, 0, "invocation", 0, "valid invocation parameters", validation_error, ReplayFailureCategory.INVALID_INVOCATION)

        extracted_outputs: dict[str, object] = {}
        for action_index, action in enumerate(artifact.actions):
            for attempt in range(self._transient_retry_limit + 1):
                try:
                    action_result = self._policy_surface.execute_action(
                        action,
                        runtime_values=invocation_parameters,
                    )
                    if isinstance(action, ExtractTextAction):
                        extracted_outputs[action.output_name] = action_result
                    self._write_event(action_index, action, "completed")
                    postcondition_failure = self._verify_conditions(action.postconditions, extracted_outputs)
                    if postcondition_failure is not None:
                        return self._failure(
                            artifact,
                            action_index,
                            action.action_id,
                            action_index,
                            "declared action postcondition",
                            postcondition_failure,
                            ReplayFailureCategory.CHECKPOINT_FAILURE,
                        )
                    break
                except PolicyViolationError as error:
                    if error.decision is PolicyDecisionKind.REQUIRES_HUMAN_CONFIRMATION:
                        return HumanInterventionRequired(
                            capability_id=artifact.capability_id,
                            artifact_schema_version=artifact.artifact_schema_version,
                            steps_executed=action_index,
                            step_id=action.action_id,
                            step_index=action_index,
                            reason=str(error),
                        )
                    return self._failure(artifact, action_index, action.action_id, action_index, "policy allowlist", str(error), ReplayFailureCategory.POLICY_REJECTION)
                except SurfaceAdapterError as error:
                    if attempt < self._transient_retry_limit and self._is_transient_error(error):
                        self._write_event(action_index, action, "retrying transient condition")
                        continue
                    category = ReplayFailureCategory.TRANSIENT_CONDITION_EXHAUSTED if attempt else ReplayFailureCategory.SURFACE_FAILURE
                    return self._failure(artifact, action_index, action.action_id, action_index, "surface action succeeds", str(error), category)
                except ValueError as error:
                    return self._failure(artifact, action_index, action.action_id, action_index, "valid application state", str(error), ReplayFailureCategory.VALIDATION_ERROR)
            else:
                return self._failure(artifact, action_index, action.action_id, action_index, "surface action succeeds", "retry budget exhausted", ReplayFailureCategory.TRANSIENT_CONDITION_EXHAUSTED)

            business_outcome = self._detect_business_outcome(artifact, extracted_outputs)
            if business_outcome is not None:
                return KnownBusinessOutcome(
                    capability_id=artifact.capability_id,
                    artifact_schema_version=artifact.artifact_schema_version,
                    steps_executed=action_index + 1,
                    outcome_code=business_outcome.code,
                    description=business_outcome.description,
                )

        checkpoint_failure = self._verify_conditions(artifact.success_checkpoint.conditions, extracted_outputs)
        if checkpoint_failure is not None:
            return self._failure(
                artifact,
                len(artifact.actions) - 1,
                artifact.actions[-1].action_id,
                len(artifact.actions) - 1,
                artifact.success_checkpoint.description,
                checkpoint_failure,
                ReplayFailureCategory.CHECKPOINT_FAILURE,
            )
        return CapabilityExecutionSucceeded(
            capability_id=artifact.capability_id,
            artifact_schema_version=artifact.artifact_schema_version,
            steps_executed=len(artifact.actions),
            outputs=extracted_outputs,
        )

    def _validate_invocation(self, artifact: CapabilityArtifact, values: Mapping[str, object]) -> str | None:
        declared_parameters = {parameter.name: parameter for parameter in artifact.inputs}
        missing = [name for name, parameter in declared_parameters.items() if parameter.required and name not in values]
        unknown = [name for name in values if name not in declared_parameters]
        if missing:
            return f"missing required invocation parameters: {missing}"
        if unknown:
            return f"unknown invocation parameters: {unknown}"
        return None

    def _detect_business_outcome(self, artifact: CapabilityArtifact, outputs: Mapping[str, object]):
        for outcome in artifact.known_business_outcomes:
            if self._condition_matches(outcome.detection, outputs):
                return outcome
        return None

    def _verify_conditions(self, conditions: list[CheckpointCondition], outputs: Mapping[str, object]) -> str | None:
        for condition in conditions:
            if not self._condition_matches(condition, outputs):
                return f"condition was not met: {condition.condition_type.value}"
        return None

    def _condition_matches(self, condition: CheckpointCondition, outputs: Mapping[str, object]) -> bool:
        observation = self._policy_surface.observe()
        if isinstance(condition, ElementVisibleCondition):
            try:
                self._surface.resolve_recorded_target(condition.target)
                return True
            except SurfaceAdapterError:
                return False
        if isinstance(condition, TextContainsCondition):
            try:
                return condition.expected_text in self._surface.read_text_or_value(condition.target)
            except SurfaceAdapterError:
                return condition.expected_text in observation.visible_text
        if isinstance(condition, UrlMatchesCondition):
            return re.search(condition.pattern, observation.current_location) is not None
        if isinstance(condition, ExtractedValueMatchesCondition):
            value = outputs.get(condition.output_name)
            return value is not None and re.search(condition.pattern, str(value)) is not None
        return False

    @staticmethod
    def _is_transient_error(error: SurfaceAdapterError) -> bool:
        return any(marker in str(error).casefold() for marker in ("timeout", "slow", "transient", "loading"))

    def _failure(self, artifact: CapabilityArtifact, step_index: int, step_id: str, evidence_step: int, expected: str, summary: str, category: ReplayFailureCategory) -> CapabilityExecutionFailed:
        observed_state = self._sanitized_observed_state()
        evidence_reference = self._capture_failure_evidence(evidence_step)
        return CapabilityExecutionFailed(
            capability_id=artifact.capability_id,
            artifact_schema_version=artifact.artifact_schema_version,
            steps_executed=step_index,
            step_id=step_id,
            step_index=step_index,
            expected_state=expected,
            observed_state=observed_state,
            failure_category=category,
            debugging_summary=summary,
            evidence_reference=evidence_reference,
        )

    def _sanitized_observed_state(self) -> str:
        observation = self._surface.observe()
        return f"location={observation.current_location}; title={observation.title}; visible_text={observation.visible_text[:500]}"

    def _capture_failure_evidence(self, step_index: int) -> str | None:
        if self._evidence_directory is None:
            return None
        destination = self._evidence_directory / f"replay-failure-step-{step_index + 1}.png"
        return str(self._surface.capture_evidence(destination))

    def _write_event(self, step_index: int, action: Action, action_result: str) -> None:
        if self._evidence_writer is not None:
            self._evidence_writer.write_event({
                "event_type": "replay_action",
                "step_index": step_index,
                "action_id": action.action_id,
                "action_type": action.action_type.value,
                "action_result": action_result,
            })