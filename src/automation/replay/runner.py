"""Ordered, LLM-free replay with bounded read recovery and same-session handoff."""
from pathlib import Path
import uuid

from automation.capabilities.models import ExtractTextAction, WaitForStateAction, ActionRisk
from automation.capabilities.runtime import validate_inputs, parse_outputs, condition_matches
from automation.policy.enforced_surface import PolicyViolationError
from automation.policy.models import PolicyDecisionKind
from automation.replay.models import (
    CapabilityExecutionFailed, CapabilityExecutionSucceeded, HumanInterventionRequired,
    KnownBusinessOutcome, ReplayFailureCategory,
)
from automation.surface.contracts import ResolvedSurfaceTarget
from automation.surface.errors import SurfaceAdapterError, SurfaceTimeoutError


class CapabilityReplayRunner:
    def __init__(self, surface, policy_surface, evidence_writer=None, evidence_directory=None,
                 transient_retry_limit=1, intervention_handler=None):
        if not 0 <= transient_retry_limit <= 3:
            raise ValueError("transient retry limit must be between zero and three")
        self._surface = surface
        self._policy_surface = policy_surface
        self._evidence_writer = evidence_writer
        self._evidence_directory = evidence_directory
        self._transient_retry_limit = transient_retry_limit
        self._intervention_handler = intervention_handler

    def replay(self, artifact, invocation_parameters):
        self._run_id = self._evidence_writer.run_id if self._evidence_writer else str(uuid.uuid4())
        self._artifact = artifact
        self._step_index = 0
        self._steps_executed = 0
        self._action = artifact.actions[0]
        raw = {}
        self._event("replay_started")
        try:
            values = validate_inputs(artifact.inputs, invocation_parameters)
        except ValueError as error:
            return self._finish(self._failure("invocation", ReplayFailureCategory.INVALID_INVOCATION, str(error)))
        # A single operator callback may repair a failed step; replay never skips it.
        for index, action in enumerate(artifact.actions):
            self._step_index, self._action = index, action
            handed_off = False
            retries = 0
            while True:
                action_started = False
                try:
                    observation = self._policy_surface.observe()
                    if observation.dialog_text:
                        raise SurfaceAdapterError("unexpected dialog requires human intervention")
                    action_started = True
                    result = self._policy_surface.execute_action(action, runtime_values=values)
                    self._steps_executed = index + 1
                    if isinstance(action, ExtractTextAction):
                        raw[action.output_name] = result
                    resolution = result if isinstance(result, ResolvedSurfaceTarget) else (
                        getattr(self._surface, "last_resolution", None) if isinstance(action, ExtractTextAction) else None)
                    self._event("replay_action", action_result="completed",
                                resolution={"selected_priority": resolution.selected_priority, "strategy_kind": resolution.strategy_kind} if resolution is not None else None)
                    # A valid domain outcome takes precedence over the happy-path postcondition.
                    outcome = self._outcome(artifact, raw, values)
                    if outcome is not None:
                        return self._finish(KnownBusinessOutcome(**self._base(), outcome_code=outcome.code, description=outcome.description))
                    self._verify(action.postconditions, raw, values)
                    break
                except (PolicyViolationError, SurfaceAdapterError, ValueError) as error:
                    if (isinstance(error, SurfaceTimeoutError) and isinstance(action, (WaitForStateAction, ExtractTextAction))
                            and action.risk == ActionRisk.READ_ONLY and retries < self._transient_retry_limit):
                        retries += 1
                        self._event("recovery_attempt", attempt=retries, condition="surface_timeout")
                        continue
                    blocked = isinstance(error, PolicyViolationError)
                    # Denied actions cannot be approved by this operator seam.
                    if not blocked and not handed_off and self._intervention_handler is not None:
                        handed_off = True
                        try:
                            resumed = self._intervention_handler(artifact.capability_id, artifact.description, action.action_id, index, "surface or checkpoint requires review")
                            if resumed and (not action_started or isinstance(action, (WaitForStateAction, ExtractTextAction))):
                                self._policy_surface.observe()
                                continue
                        except SurfaceAdapterError:
                            self._event("intervention_unavailable")
                        # An uncertain click may have taken effect. Human review never
                        # grants permission to repeat it; preserve the original failure.
                    if blocked and error.decision == PolicyDecisionKind.REQUIRES_HUMAN_CONFIRMATION:
                        if self._intervention_handler is not None:
                            self._intervention_handler(artifact.capability_id, artifact.description, action.action_id, index, "policy requires human review; action remains blocked")
                        return self._finish(HumanInterventionRequired(**self._base(), step_id=action.action_id, step_index=index,
                                                                    reason="deployment policy requires confirmation",
                                                                    evidence_reference=self._capture()))
                    category = (ReplayFailureCategory.POLICY_REJECTION if blocked else
                                ReplayFailureCategory.TRANSIENT_CONDITION_EXHAUSTED if retries else
                                ReplayFailureCategory.VALIDATION_ERROR if isinstance(error, ValueError) else
                                ReplayFailureCategory.CHECKPOINT_FAILURE if isinstance(error, CheckpointError) else
                                ReplayFailureCategory.SURFACE_FAILURE)
                    return self._finish(self._failure("declared action and postconditions", category, str(error) if blocked else type(error).__name__))
        try:
            if self._policy_surface.observe().dialog_text:
                raise CheckpointError("unexpected dialog")
            self._verify(artifact.success_checkpoint.conditions, raw, values)
            outputs = parse_outputs(artifact.outputs, raw)
        except (SurfaceAdapterError, PolicyViolationError, ValueError) as error:
            return self._finish(self._failure(artifact.success_checkpoint.description, ReplayFailureCategory.CHECKPOINT_FAILURE, type(error).__name__))
        return self._finish(CapabilityExecutionSucceeded(**self._base(), outputs=outputs))

    def _base(self):
        return dict(capability_id=self._artifact.capability_id,
                    artifact_schema_version=self._artifact.artifact_schema_version,
                    steps_executed=self._steps_executed)

    def _outcome(self, artifact, raw, values):
        for outcome in artifact.known_business_outcomes:
            if condition_matches(self._surface, outcome.detection, raw, values):
                return outcome
        return None

    def _verify(self, conditions, raw, values):
        for condition in conditions:
            matched = condition_matches(self._surface, condition, raw, values)
            self._event("checkpoint", condition_type=condition.condition_type.value, matched=matched)
            if not matched:
                raise CheckpointError("declared checkpoint was not met")

    def _capture(self):
        if self._evidence_directory is None:
            return None
        try:
            destination = Path(self._evidence_directory) / f"{self._run_id}-step-{self._step_index}.png"
            destination.parent.mkdir(parents=True, exist_ok=True)
            return str(self._surface.capture_evidence(destination))
        except Exception:
            self._event("evidence_unavailable")
            return None

    def _failure(self, expected, category, summary):
        try:
            observation = self._surface.observe()
            state = f"surface={observation.surface_identifier}; dialog_present={bool(observation.dialog_text)}; page content withheld"
        except Exception:
            state = "surface unavailable"
        return CapabilityExecutionFailed(**self._base(), step_id=self._action.action_id,
            step_index=self._step_index, expected_state=expected, observed_state=state,
            failure_category=category, debugging_summary=summary, evidence_reference=self._capture())

    def _finish(self, result):
        self._event("replay_result", result_type=result.result_type,
                    outcome_code=getattr(result, "outcome_code", None),
                    failure_category=getattr(result, "failure_category", None),
                    evidence_reference=getattr(result, "evidence_reference", None))
        return result

    def _event(self, event_type, **details):
        if self._evidence_writer:
            self._evidence_writer.write_event(dict(event_type=event_type, run_id=self._run_id,
                capability_id=self._artifact.capability_id, artifact_schema_version=self._artifact.artifact_schema_version,
                revision=self._artifact.revision, step_index=self._step_index, action_id=self._action.action_id, **details))


class CheckpointError(SurfaceAdapterError):
    """The declared semantic result was not observed."""
