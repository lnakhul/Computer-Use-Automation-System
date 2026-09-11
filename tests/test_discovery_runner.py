from pathlib import Path

import pytest

from automation.capabilities.models import (
    ActionType,
    ElementTarget,
    OutputDeclaration,
    StringParameter,
)
from automation.discovery.contracts import DecisionProviderError
from automation.discovery.models import (
    ClickDecision,
    DiscoveryArtifactDefinition,
    DiscoveryRequest,
    DiscoveryStopState,
    ExtractTextDecision,
    FillDecision,
    GoalAchievedDecision,
    HumanInterventionDecision,
    NavigateDecision,
    RuntimeParameter,
)
from automation.discovery.runner import DiscoveryRunner
from automation.policy import AllowedTarget, PolicyEnforcedSurfaceAdapter, SafetyPolicy, SafetyPolicyEvaluator
from automation.surface.contracts import ResolvedSurfaceTarget, SurfaceObservation
from automation.surface.errors import SurfaceAdapterError


class FakeDiscoverySurface:
    def __init__(self) -> None:
        self.current_location = "https://bank.example.test/members/search"
        self.executed_actions: list[str] = []

    def observe(self) -> SurfaceObservation:
        return SurfaceObservation("fake", self.current_location, "Member Console", "Member Search")

    def navigate(self, destination: str) -> None:
        self.current_location = destination
        self.executed_actions.append(f"navigate:{destination}")

    def resolve_recorded_target(self, target: ElementTarget) -> ResolvedSurfaceTarget:
        return ResolvedSurfaceTarget(target.description, 1, "role")

    def click(self, target: ElementTarget) -> ResolvedSurfaceTarget:
        self.executed_actions.append(f"click:{target.description}")
        return self.resolve_recorded_target(target)

    def enter_text(self, target: ElementTarget, text: str) -> ResolvedSurfaceTarget:
        self.executed_actions.append(f"fill:{target.description}:{text}")
        return self.resolve_recorded_target(target)

    def read_text_or_value(self, target: ElementTarget) -> str:
        self.executed_actions.append(f"extract:{target.description}")
        return "$1,240.50"

    def wait_for_state(self, condition: object, timeout_seconds: float) -> None:
        self.executed_actions.append("wait")

    def capture_evidence(self, destination: Path) -> Path:
        return destination

    def expose_live_session(self):
        raise NotImplementedError

    def resume_live_session(self, session_id: str):
        raise NotImplementedError


class FakeDecisionProvider:
    def __init__(self, decisions: list[object]) -> None:
        self._decisions = iter(decisions)

    def decide(self, goal: str, observation: SurfaceObservation) -> object:
        return next(self._decisions)


class InvalidDecisionProvider:
    def decide(self, goal: str, observation: SurfaceObservation) -> object:
        return {"decision_type": "fill", "reasoning_summary": "missing required target"}


class ErrorDecisionProvider:
    def decide(self, goal: str, observation: SurfaceObservation) -> object:
        raise DecisionProviderError("provider failed")


class FailingObservationSurface(FakeDiscoverySurface):
    def observe(self) -> SurfaceObservation:
        raise SurfaceAdapterError("surface stopped responding")


def target(description: str) -> ElementTarget:
    return ElementTarget(
        description=description,
        candidates=[
            {
                "priority": 1,
                "strategy": {"kind": "role", "role": "button", "accessible_name": description},
            }
        ],
    )


def request(maximum_steps: int = 8, timeout: float = 30) -> DiscoveryRequest:
    return DiscoveryRequest(
        goal="look up member 12345 and read the savings balance",
        artifact_definition=DiscoveryArtifactDefinition(
            capability_id="member.savings_balance.lookup",
            revision=1,
            name="Look up savings balance",
            description="Read a member's savings balance.",
            compatibility={
                "surface_kind": "web",
                "vendor_product": "demo",
                "vendor_version": "1",
                "application_name": "Member Console",
                "application_version": "1",
            },
            entry_point="https://bank.example.test/members/search",
            inputs=[
                StringParameter(
                    name="member_id",
                    description="Member identifier",
                )
            ],
            outputs=[
                OutputDeclaration(
                    name="savings_balance",
                    description="Current savings balance",
                    output_type="decimal",
                    source_action_id="placeholder",
                    parser="currency",
                )
            ],
            success_checkpoint={
                "description": "The balance is available.",
                "conditions":[{"condition_type": "element_visible", "target": target("Savings balance")}],
            },
            safety_profile={
                "permitted_action_types": ["navigate", "fill", "click", "extract_text"],
            },
        ),
        runtime_parameters=[RuntimeParameter(name="member_id", value="12345")],
        maximum_steps=maximum_steps,
        total_timeout_seconds=timeout,
    )


def runner(provider: object, surface: FakeDiscoverySurface) -> DiscoveryRunner:
    safety_policy = SafetyPolicy(
        allowed_targets=[AllowedTarget(origin="https://bank.example.test", route_prefixes=["/members"])],
        permitted_action_types=[ActionType.NAVIGATE, ActionType.FILL, ActionType.CLICK, ActionType.EXTRACT_TEXT],
    )
    return DiscoveryRunner(
        surface,
        provider,
        PolicyEnforcedSurfaceAdapter(surface, SafetyPolicyEvaluator(safety_policy)),
    )


def test_fake_provider_success_builds_symbolic_artifact() -> None:
    surface = FakeDiscoverySurface()
    provider = FakeDecisionProvider(
        [
            FillDecision(reasoning_summary="Enter the requested member identifier", target=target("Member ID"), text="12345", parameter_name="member_id"),
            ClickDecision(reasoning_summary="Submit the search", target=target("Search")),
            ExtractTextDecision(reasoning_summary="Read the balance", target=target("Savings balance"), output_name="savings_balance"),
            GoalAchievedDecision(reasoning_summary="The balance is visible and readable"),
        ]
    )

    result = runner(provider, surface).run(request())

    assert result.stop_state is DiscoveryStopState.GOAL_ACHIEVED
    assert result.artifact is not None
    assert any(action.value_template == "${member_id}" for action in result.artifact.actions if hasattr(action, "value_template"))
    assert "12345" not in result.artifact.model_dump_json()
    assert "extract:Savings balance" in surface.executed_actions


def test_policy_block_is_explicit_stop_state() -> None:
    surface = FakeDiscoverySurface()
    blocked_request = request()
    blocked_request.artifact_definition.entry_point = "https://outside.example.test/members/search"

    result = runner(FakeDecisionProvider([]), surface).run(blocked_request)

    assert result.stop_state is DiscoveryStopState.BLOCKED_BY_POLICY
    assert surface.executed_actions == []


def test_human_intervention_is_explicit_stop_state() -> None:
    surface = FakeDiscoverySurface()

    result = runner(
        FakeDecisionProvider([HumanInterventionDecision(reasoning_summary="A permission prompt needs a person", reason="Permission prompt")]),
        surface,
    ).run(request())

    assert result.stop_state is DiscoveryStopState.HUMAN_INTERVENTION_REQUIRED


def test_invalid_model_response_is_explicit_stop_state() -> None:
    result = runner(InvalidDecisionProvider(), FakeDiscoverySurface()).run(request())

    assert result.stop_state is DiscoveryStopState.MODEL_INVALID_RESPONSE


def test_provider_error_is_explicit_stop_state() -> None:
    result = runner(ErrorDecisionProvider(), FakeDiscoverySurface()).run(request())

    assert result.stop_state is DiscoveryStopState.MODEL_INVALID_RESPONSE


def test_surface_failure_is_explicit_stop_state() -> None:
    result = runner(FakeDecisionProvider([]), FailingObservationSurface()).run(request())

    assert result.stop_state is DiscoveryStopState.UNRECOVERABLE_SURFACE_FAILURE


def test_step_limit_is_explicit_stop_state() -> None:
    surface = FakeDiscoverySurface()
    repeated_provider = FakeDecisionProvider(
        [ClickDecision(reasoning_summary="Inspect the page", target=target("Search")) for _ in range(3)]
    )

    result = runner(repeated_provider, surface).run(request(maximum_steps=2))

    assert result.stop_state is DiscoveryStopState.STEP_LIMIT_REACHED
    assert result.steps_executed == 3