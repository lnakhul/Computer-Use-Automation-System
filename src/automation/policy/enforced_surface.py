"""Policy-enforcing facade for surface actions."""

from __future__ import annotations

from automation.capabilities.models import (
    Action,
    ActionRisk,
    ClickAction,
    ExtractTextAction,
    FillAction,
    NavigateAction,
    WaitForStateAction,
)
from automation.policy.evaluator import SafetyPolicyEvaluator
from automation.policy.models import PolicyActionRequest, PolicyDecisionKind
from automation.surface.contracts import (
    ComputerSurfaceAdapter,
    ResolvedSurfaceTarget,
    SurfaceObservation,
)


class PolicyViolationError(RuntimeError):
    """Raised when policy does not allow an action to execute."""


class PolicyEnforcedSurfaceAdapter:
    """Authorizes a recorded action before delegating it to a surface."""

    def __init__(self, surface: ComputerSurfaceAdapter, evaluator: SafetyPolicyEvaluator) -> None:
        self._surface = surface
        self._evaluator = evaluator

    def execute_action(self, action: Action, human_confirmation: bool = False) -> str | ResolvedSurfaceTarget | None:
        current_location = self._surface.observe().current_location
        destination = action.route if isinstance(action, NavigateAction) else None
        decision = self._evaluator.evaluate(
            PolicyActionRequest(
                action_type=action.action_type,
                risk=action.risk,
                destination=destination,
                human_confirmation=human_confirmation,
            ),
            current_location=current_location,
        )
        if decision.decision is not PolicyDecisionKind.ALLOWED:
            raise PolicyViolationError(f"{decision.decision.value}: {decision.reason}")

        if isinstance(action, NavigateAction):
            self._surface.navigate(decision.normalized_destination or action.route)
            return None
        if isinstance(action, ClickAction):
            return self._surface.click(action.target)
        if isinstance(action, FillAction):
            return self._surface.enter_text(action.target, action.value_template)
        if isinstance(action, WaitForStateAction):
            self._surface.wait_for_state(action.condition, action.timeout_seconds)
            return None
        if isinstance(action, ExtractTextAction):
            return self._surface.read_text_or_value(action.target)
        raise TypeError(f"unsupported action model: {type(action).__name__}")

    def observe(self) -> SurfaceObservation:
        return self._surface.observe()