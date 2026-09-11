import json
from pathlib import Path

import pytest

from automation.capabilities.models import (
    ActionRisk,
    ActionType,
    CapabilityArtifact,
    ClickAction,
    ElementTarget,
    FillAction,
    NavigateAction,
)
from automation.evidence import JsonlEvidenceWriter, RedactionPolicy, SensitiveDataRedactor
from automation.policy import (
    AllowedTarget,
    PolicyActionRequest,
    PolicyDecisionKind,
    PolicyEnforcedSurfaceAdapter,
    SafetyPolicy,
    SafetyPolicyEvaluator,
)
from automation.surface.contracts import ResolvedSurfaceTarget, SurfaceObservation


class RecordingSurface:
    def __init__(self) -> None:
        self.actions: list[str] = []
        self.current_location = "https://bank.example.test/members/search"

    def observe(self) -> SurfaceObservation:
        return SurfaceObservation("fake", self.current_location, "Demo", "Ready")

    def navigate(self, destination: str) -> None:
        self.actions.append(f"navigate:{destination}")
        self.current_location = destination

    def resolve_recorded_target(self, target: ElementTarget) -> ResolvedSurfaceTarget:
        return ResolvedSurfaceTarget(target.description, 1, "role")

    def click(self, target: ElementTarget) -> ResolvedSurfaceTarget:
        self.actions.append(f"click:{target.description}")
        return self.resolve_recorded_target(target)

    def enter_text(self, target: ElementTarget, text: str) -> ResolvedSurfaceTarget:
        self.actions.append(f"fill:{target.description}:{text}")
        return self.resolve_recorded_target(target)

    def read_text_or_value(self, target: ElementTarget) -> str:
        self.actions.append(f"read:{target.description}")
        return "value"

    def wait_for_state(self, condition: object, timeout_seconds: float) -> None:
        self.actions.append("wait")

    def capture_evidence(self, destination: Path) -> Path:
        return destination

    def expose_live_session(self):
        raise NotImplementedError

    def resume_live_session(self, session_id: str):
        raise NotImplementedError


def policy() -> SafetyPolicy:
    return SafetyPolicy(
        allowed_targets=[
            AllowedTarget(
                origin="https://bank.example.test",
                route_prefixes=["/members", "/accounts"],
            )
        ],
        permitted_action_types=[
            ActionType.NAVIGATE,
            ActionType.CLICK,
            ActionType.FILL,
        ],
    )


def target() -> ElementTarget:
    return ElementTarget(
        description="Search button",
        candidates=[
            {
                "priority": 1,
                "strategy": {
                    "kind": "role",
                    "role": "button",
                    "accessible_name": "Search",
                },
            }
        ],
    )


def test_blocked_domain_is_denied() -> None:
    evaluator = SafetyPolicyEvaluator(policy())

    decision = evaluator.evaluate(
        PolicyActionRequest(
            action_type=ActionType.NAVIGATE,
            risk=ActionRisk.READ_ONLY,
            destination="https://outside.example.test/members/search",
        )
    )

    assert decision.decision is PolicyDecisionKind.DENIED


def test_blocked_action_type_is_denied() -> None:
    evaluator = SafetyPolicyEvaluator(policy())

    decision = evaluator.evaluate(
        PolicyActionRequest(
            action_type=ActionType.EXTRACT_TEXT,
            risk=ActionRisk.READ_ONLY,
            destination="https://bank.example.test/members/12345",
        )
    )

    assert decision.decision is PolicyDecisionKind.DENIED


def test_consequential_action_requires_human_confirmation() -> None:
    evaluator = SafetyPolicyEvaluator(policy())

    decision = evaluator.evaluate(
        PolicyActionRequest(
            action_type=ActionType.CLICK,
            risk=ActionRisk.IRREVERSIBLE,
            destination="https://bank.example.test/accounts/submit",
        )
    )

    assert decision.decision is PolicyDecisionKind.REQUIRES_HUMAN_CONFIRMATION


def test_allowed_safe_action_is_allowed() -> None:
    evaluator = SafetyPolicyEvaluator(policy())

    decision = evaluator.evaluate(
        PolicyActionRequest(
            action_type=ActionType.NAVIGATE,
            risk=ActionRisk.READ_ONLY,
            destination="https://bank.example.test/members/search",
        )
    )

    assert decision.decision is PolicyDecisionKind.ALLOWED


def test_enforced_surface_blocks_before_underlying_action() -> None:
    surface = RecordingSurface()
    guarded_surface = PolicyEnforcedSurfaceAdapter(surface, SafetyPolicyEvaluator(policy()))
    action = NavigateAction(
        action_id="blocked-navigation",
        description="Navigate outside bank",
        route="https://outside.example.test/members",
    )

    with pytest.raises(RuntimeError, match="outside the configured"):
        guarded_surface.execute_action(action)

    assert surface.actions == []


def test_enforced_surface_requires_confirmation_before_irreversible_action() -> None:
    surface = RecordingSurface()
    guarded_surface = PolicyEnforcedSurfaceAdapter(surface, SafetyPolicyEvaluator(policy()))
    action = ClickAction(
        action_id="submit-account",
        description="Submit account",
        risk=ActionRisk.IRREVERSIBLE,
        target=target(),
    )

    with pytest.raises(RuntimeError, match="requires_human_confirmation"):
        guarded_surface.execute_action(action)
    assert surface.actions == []

    guarded_surface.execute_action(action, human_confirmation=True)
    assert surface.actions == ["click:Search button"]


def test_sensitive_values_are_redacted_from_structured_logs(tmp_path: Path) -> None:
    redactor = SensitiveDataRedactor(
        RedactionPolicy(
            sensitive_field_names=["member_id", "authorization"],
            sensitive_value_patterns=[r"Bearer\s+\S+", r"token=[^\s&]+"],
        )
    )
    destination = tmp_path / "run.jsonl"
    JsonlEvidenceWriter(destination, redactor).write_event(
        {
            "member_id": "12345",
            "message": "Authorization: Bearer secret-token token=runtime-secret",
            "nested": {"authorization": "Bearer another-secret"},
        }
    )

    persisted_log = destination.read_text(encoding="utf-8")
    assert "12345" not in persisted_log
    assert "secret-token" not in persisted_log
    assert "another-secret" not in persisted_log
    assert "[REDACTED]" in persisted_log


def test_artifact_persists_symbolic_parameter_reference_not_invocation_value() -> None:
    artifact = CapabilityArtifact(
        capability_id="member.lookup",
        revision=1,
        name="Member lookup",
        description="Read a member record.",
        compatibility={
            "surface_kind": "web",
            "vendor_product": "demo",
            "vendor_version": "1",
            "application_name": "Demo",
            "application_version": "1",
        },
        entry_point="/members/search",
        inputs=[
            {
                "value_type": "string",
                "name": "member_id",
                "description": "Member identifier",
                "sensitive": True,
            }
        ],
        actions=[
            FillAction(
                action_id="fill-member",
                description="Enter member ID",
                target=target(),
                value_template="${member_id}",
                sensitive_value=True,
            )
        ],
        success_checkpoint={
            "description": "Member is selected",
            "conditions":[
                {
                    "condition_type": "element_visible",
                    "target": target(),
                }
            ],
        },
        safety_profile={
            "permitted_action_types": ["fill"],
            "maximum_risk": "reversible",
        },
    )

    serialized_artifact = artifact.model_dump_json()

    assert "12345" not in serialized_artifact
    assert "${member_id}" in serialized_artifact
    assert json.loads(serialized_artifact)["inputs"][0]["default"] is None


def test_sensitive_parameter_default_is_rejected() -> None:
    with pytest.raises(ValueError, match="sensitive parameters"):
        CapabilityArtifact(
            capability_id="member.lookup",
            revision=1,
            name="Member lookup",
            description="Read a member record.",
            compatibility={
                "surface_kind": "web",
                "vendor_product": "demo",
                "vendor_version": "1",
                "application_name": "Demo",
                "application_version": "1",
            },
            entry_point="/members/search",
            inputs=[
                {
                    "value_type": "string",
                    "name": "token",
                    "description": "Secret token",
                    "sensitive": True,
                    "default": "secret-value",
                }
            ],
            actions=[
                FillAction(
                    action_id="fill-token",
                    description="Enter token",
                    target=target(),
                    value_template="${token}",
                )
            ],
            success_checkpoint={"description": "Done", "conditions": [{"condition_type": "element_visible", "target": target()}]},
            safety_profile={"permitted_action_types": ["fill"]},
        )