"""Bounded observe-decide-act discovery loop."""

from __future__ import annotations

import time
import json
import uuid
from pathlib import Path
from collections.abc import Mapping

from pydantic import TypeAdapter, ValidationError


from automation.capabilities.models import (
    Action,
    CapabilityArtifact,
    ClickAction,
    ExtractTextAction,
    FillAction,
    NavigateAction,
    WaitForStateAction,
)
from automation.capabilities.runtime import validate_inputs, parse_outputs, condition_matches
from automation.discovery.contracts import AgentDecisionProvider, DecisionProviderError
from automation.discovery.models import (
    AgentDecision,
    ClickDecision,
    DiscoveryRequest,
    DiscoveryResult,
    DiscoveryStopState,
    ExtractTextDecision,
    FillDecision,
    GoalAchievedDecision,
    HumanInterventionDecision,
    NavigateDecision,
    WaitForStateDecision,
)
from automation.evidence.logging import JsonlEvidenceWriter
from automation.policy.enforced_surface import PolicyEnforcedSurfaceAdapter, PolicyViolationError
from automation.surface.contracts import ComputerSurfaceAdapter, SurfaceObservation
from automation.surface.errors import SurfaceAdapterError


class DiscoveryArtifactError(RuntimeError):
    """A successful path could not be represented safely as an artifact."""


class DiscoveryRunner:
    def __init__(
        self,
        surface: ComputerSurfaceAdapter,
        decision_provider: AgentDecisionProvider,
        policy_surface: PolicyEnforcedSurfaceAdapter,
        evidence_writer: JsonlEvidenceWriter | None = None,
        evidence_directory: Path | None = None,
        intervention_handler=None,
    ) -> None:
        self._surface = surface
        self._decision_provider = decision_provider
        self._policy_surface = policy_surface
        self._evidence_writer = evidence_writer
        self._evidence_directory = evidence_directory
        self._intervention_handler = intervention_handler

    def run(self, request: DiscoveryRequest) -> DiscoveryResult:
        started_at = time.monotonic()
        self._request = request
        self._run_id = self._evidence_writer.run_id if self._evidence_writer else str(uuid.uuid4())
        raw_outputs = {}
        intervention_used = False
        recorded_actions: list[Action] = []
        runtime_values = {parameter.name: parameter.value for parameter in request.runtime_parameters}

        try:
            runtime_values = validate_inputs(request.artifact_definition.inputs, runtime_values)
        except ValueError:
            return self._result(DiscoveryStopState.MODEL_INVALID_RESPONSE, 0, "invalid discovery inputs")
        try:
            initial_action = NavigateAction(
                action_id="step-001-open-entry-point",
                description="Open the capability entry point",
                route=request.artifact_definition.entry_point,
            )
            self._policy_surface.execute_action(initial_action, runtime_values=runtime_values)
            recorded_actions.append(initial_action)
            self._write_event("action_executed", 1, initial_action, "entry point opened", action_result="completed")
        except PolicyViolationError as error:
            return self._result(DiscoveryStopState.BLOCKED_BY_POLICY, 0, str(error))
        except SurfaceAdapterError as error:
            return self._result(DiscoveryStopState.UNRECOVERABLE_SURFACE_FAILURE, 0, str(error))

        for step_number in range(1, request.maximum_steps + 1):
            if time.monotonic() - started_at >= request.total_timeout_seconds:
                return self._result(DiscoveryStopState.TIMEOUT, len(recorded_actions), "discovery timeout reached")

            try:
                observation = self._policy_surface.observe()
                self._write_observation(step_number, observation)
                proposed_decision = self._decision_provider.decide(request.goal + "\nCapability contract: " + json.dumps({"inputs": runtime_values, "outputs": [o.name for o in request.artifact_definition.outputs]}), observation)
                decision = TypeAdapter(AgentDecision).validate_python(proposed_decision)
            except SurfaceAdapterError as error:
                return self._result(DiscoveryStopState.UNRECOVERABLE_SURFACE_FAILURE, len(recorded_actions), str(error))
            except DecisionProviderError as error:
                return self._result(DiscoveryStopState.MODEL_INVALID_RESPONSE, len(recorded_actions), str(error))
            except ValidationError as error:
                return self._result(DiscoveryStopState.MODEL_INVALID_RESPONSE, len(recorded_actions), "model response failed schema validation")
            except Exception as error:
                return self._result(DiscoveryStopState.MODEL_INVALID_RESPONSE, len(recorded_actions), str(error))

            if time.monotonic() - started_at >= request.total_timeout_seconds:
                return self._result(DiscoveryStopState.TIMEOUT, len(recorded_actions), "discovery timeout reached")

            if isinstance(decision, GoalAchievedDecision):
                try:
                    artifact = self._build_artifact(request, recorded_actions)
                    parse_outputs(artifact.outputs, raw_outputs)
                    if observation.dialog_text or any(not condition_matches(self._surface, c, raw_outputs, runtime_values) for c in artifact.success_checkpoint.conditions):
                        raise DiscoveryArtifactError("declared success checkpoint was not met")
                except (DiscoveryArtifactError, ValueError, SurfaceAdapterError) as error:
                    return self._result(DiscoveryStopState.MODEL_INVALID_RESPONSE, len(recorded_actions), str(error))
                self._write_event("goal_achieved", step_number, None, "declared checkpoint verified")
                return DiscoveryResult(
                    stop_state=DiscoveryStopState.GOAL_ACHIEVED,
                    steps_executed=len(recorded_actions),
                    artifact=artifact,
                )
            if isinstance(decision, HumanInterventionDecision):
                if not intervention_used and self._intervention_handler is not None:
                    intervention_used = True
                    if self._intervention_handler(request.artifact_definition.capability_id, request.goal, "discovery", len(recorded_actions), "model requested human intervention"):
                        continue
                return self._result(DiscoveryStopState.HUMAN_INTERVENTION_REQUIRED, len(recorded_actions), decision.reason)

            try:
                recorded_action = self._record_decision(decision, request, runtime_values, len(recorded_actions) + 1)
                action_result = self._policy_surface.execute_action(
                    recorded_action,
                    runtime_values=runtime_values,
                )
                recorded_actions.append(recorded_action)
                result_summary = "text extracted" if isinstance(recorded_action, ExtractTextAction) else "action completed"
                self._write_event(
                    "action_executed",
                    step_number,
                    recorded_action,
                    recorded_action.description,
                    action_result=result_summary,
                )
                if action_result is not None and isinstance(recorded_action, ExtractTextAction):
                    raw_outputs[recorded_action.output_name] = action_result
                    self._write_event(
                        "extraction_completed",
                        step_number,
                        recorded_action,
                        "declared output captured",
                        action_result="value captured in memory",
                    )
            except (DiscoveryArtifactError, ValueError) as error:
                return self._result(DiscoveryStopState.MODEL_INVALID_RESPONSE, len(recorded_actions), str(error))
            except PolicyViolationError as error:
                return self._result(DiscoveryStopState.BLOCKED_BY_POLICY, len(recorded_actions), str(error))
            except SurfaceAdapterError as error:
                return self._result(DiscoveryStopState.UNRECOVERABLE_SURFACE_FAILURE, len(recorded_actions), str(error))

        return self._result(DiscoveryStopState.STEP_LIMIT_REACHED, len(recorded_actions), "maximum discovery steps reached")

    def _record_decision(
        self,
        decision: AgentDecision,
        request: DiscoveryRequest,
        runtime_values: Mapping[str, str],
        action_number: int,
    ) -> Action:
        action_id = f"step-{action_number:03d}-{decision.decision_type}"
        common = {"action_id": action_id, "description": f"Recorded {decision.decision_type} action"}
        if isinstance(decision, NavigateDecision):
            route = decision.destination
            for name, value in runtime_values.items():
                route = route.replace(str(value), "${" + name + "}")
            return NavigateAction(**common, route=route, risk=decision.risk)
        if isinstance(decision, ClickDecision):
            return ClickAction(**common, target=decision.target, risk=decision.risk)
        if isinstance(decision, FillDecision):
            value_template = self._parameterize_fill_value(decision, request, runtime_values)
            return FillAction(
                **common,
                target=decision.target,
                value_template=value_template,
                sensitive_value=any(
                    parameter.name == decision.parameter_name and parameter.sensitive
                    for parameter in request.runtime_parameters
                ),
                risk=decision.risk,
            )
        if isinstance(decision, WaitForStateDecision):
            return WaitForStateAction(
                **common,
                condition=decision.condition,
                timeout_seconds=decision.timeout_seconds,
                risk=decision.risk,
            )
        if isinstance(decision, ExtractTextDecision):
            return ExtractTextAction(
                **common,
                target=decision.target,
                output_name=decision.output_name,
                risk=decision.risk,
            )
        raise DiscoveryArtifactError(f"unsupported decision type: {decision.decision_type}")

    @staticmethod
    def _parameterize_fill_value(
        decision: FillDecision,
        request: DiscoveryRequest,
        runtime_values: Mapping[str, str],
    ) -> str:
        if decision.parameter_name is not None:
            if decision.parameter_name not in runtime_values:
                raise DiscoveryArtifactError(f"unknown runtime parameter: {decision.parameter_name}")
            if str(runtime_values[decision.parameter_name]) != decision.text:
                raise DiscoveryArtifactError("model fill value does not match its declared runtime parameter")
            return f"${{{decision.parameter_name}}}"
        for parameter in request.runtime_parameters:
            if parameter.value == decision.text:
                return f"${{{parameter.name}}}"
        raise DiscoveryArtifactError("fill value has no declared runtime parameter and cannot be persisted")

    def _build_artifact(self, request: DiscoveryRequest, recorded_actions: list[Action]) -> CapabilityArtifact:
        action_ids = {action.action_id for action in recorded_actions}
        outputs = [
            output.model_copy(update={"source_action_id": self._find_output_action_id(output, recorded_actions)})
            for output in request.artifact_definition.outputs
        ]
        invalid_output_sources = [output.source_action_id for output in outputs if output.source_action_id not in action_ids]
        if invalid_output_sources:
            raise DiscoveryArtifactError(f"declared outputs were not extracted: {invalid_output_sources}")
        artifact = CapabilityArtifact(
            capability_id=request.artifact_definition.capability_id,
            revision=request.artifact_definition.revision,
            name=request.artifact_definition.name,
            description=request.artifact_definition.description,
            compatibility=request.artifact_definition.compatibility,
            entry_point=request.artifact_definition.entry_point,
            inputs=request.artifact_definition.inputs,
            actions=recorded_actions,
            outputs=outputs,
            success_checkpoint=request.artifact_definition.success_checkpoint,
            known_business_outcomes=request.artifact_definition.known_business_outcomes,
            safety_profile=request.artifact_definition.safety_profile,
        )

        serialized = artifact.model_dump_json()
        for parameter in request.runtime_parameters:
            if parameter.value in serialized:
                raise DiscoveryArtifactError("artifact contains a literal invocation value; use symbolic references")
        return artifact

    @staticmethod
    def _find_output_action_id(output: object, recorded_actions: list[Action]) -> str:
        output_name = output.name
        matching_actions = [
            action.action_id
            for action in recorded_actions
            if isinstance(action, ExtractTextAction) and action.output_name == output_name
        ]
        if len(matching_actions) != 1:
            raise DiscoveryArtifactError(f"expected exactly one extraction for output: {output_name}")
        return matching_actions[0]

    def _write_observation(self, step_number: int, observation: SurfaceObservation) -> None:
        self._write_event(
            "observation",
            step_number,
            None,
            "surface observed",
            {
                "location": "[WITHHELD]",
                "title": "[WITHHELD]",
                "visible_text": "[WITHHELD]",
                "dialog_present": bool(observation.dialog_text),
            },
        )

    def _write_event(
        self,
        event_type: str,
        step_number: int,
        action: Action | None,
        reasoning_summary: str,
        extra: dict[str, object] | None = None,
        action_result: str | None = None,
    ) -> None:
        if self._evidence_writer is None:
            return
        event: dict[str, object] = {
            "event_type": event_type,
            "run_id": self._run_id,
            "capability_id": self._request.artifact_definition.capability_id,
            "revision": self._request.artifact_definition.revision,
            "step_number": step_number,
            "reasoning_summary": reasoning_summary,
        }
        if action is not None:
            event["action_type"] = action.action_type.value
            event["action_id"] = action.action_id
        if extra is not None:
            event["state"] = extra
        if action_result is not None:
            event["action_result"] = action_result
        self._evidence_writer.write_event(event)

    def _result(self, stop_state, steps_executed, reason):
        evidence_reference = None
        if self._evidence_directory is not None:
            try:
                evidence_reference = str(self._surface.capture_evidence(Path(self._evidence_directory) / f"{self._run_id}-discovery-failure.png"))
            except Exception:
                pass
        self._write_event("discovery_stopped", steps_executed, None, stop_state.value, {"evidence_reference": evidence_reference})
        return DiscoveryResult(stop_state=stop_state, steps_executed=steps_executed, reason=stop_state.value,
                               evidence_reference=evidence_reference)
