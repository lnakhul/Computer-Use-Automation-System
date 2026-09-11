from pathlib import Path

from automation.capabilities.models import CapabilityArtifact
from automation.policy import AllowedTarget, PolicyEnforcedSurfaceAdapter, SafetyPolicy, SafetyPolicyEvaluator
from automation.replay import (
    CapabilityExecutionFailed,
    CapabilityExecutionSucceeded,
    CapabilityReplayRunner,
    KnownBusinessOutcome,
)
from automation.replay.models import ReplayFailureCategory
from automation.surface.contracts import ResolvedSurfaceTarget, SurfaceObservation
from automation.surface.errors import SurfaceAdapterError


class ReplaySurface:
    def __init__(self, mode: str = "success") -> None:
        self.mode = mode
        self.current_location = "https://bank.example.test/members/search"
        self.visible_text = "Member Search"
        self.action_order: list[str] = []
        self.transient_attempts = 0

    def observe(self) -> SurfaceObservation:
        return SurfaceObservation("fake-demo", self.current_location, "Member Console", self.visible_text)

    def navigate(self, destination: str) -> None:
        self.action_order.append("navigate")
        self.current_location = destination

    def resolve_recorded_target(self, target):
        if self.mode == "missing_target" and target.description == "Savings balance":
            raise SurfaceAdapterError("target could not be resolved")
        return ResolvedSurfaceTarget(target.description, 1, "role")

    def click(self, target):
        self.action_order.append("click")
        if self.mode == "transient" and self.transient_attempts == 0:
            self.transient_attempts += 1
            raise SurfaceAdapterError("transient loading delay")
        if self.mode == "validation":
            raise ValueError("Account type and a positive opening amount are required")
        if self.mode == "not_found":
            self.visible_text = "Member not found"
        else:
            self.visible_text = "Member Details"
        return ResolvedSurfaceTarget(target.description, 1, "role")

    def enter_text(self, target, text):
        self.action_order.append("fill")
        return ResolvedSurfaceTarget(target.description, 1, "label")

    def read_text_or_value(self, target):
        if self.mode == "missing_target" and target.description == "Savings balance":
            raise SurfaceAdapterError("target could not be resolved")
        if target.description == "Savings balance":
            return "$1,240.50"
        if target.description == "Member status":
            return self.visible_text
        return self.visible_text

    def wait_for_state(self, condition, timeout_seconds):
        self.action_order.append("wait")

    def capture_evidence(self, destination: Path) -> Path:
        destination.write_bytes(b"fake evidence")
        return destination

    def expose_live_session(self):
        raise NotImplementedError

    def resume_live_session(self, session_id: str):
        raise NotImplementedError


def target(description: str):
    return {
        "description": description,
        "candidates": [{
            "priority": 1,
            "strategy": {"kind": "role", "role": "button", "accessible_name": description},
        }],
    }


def artifact(mode: str = "success") -> CapabilityArtifact:
    success_conditions = [{
        "condition_type": "extracted_value_matches",
        "output_name": "savings_balance",
        "pattern": r"^\$[0-9,]+\.[0-9]{2}$",
    }]
    actions = [
        {
            "action_type": "navigate",
            "action_id": "open-search",
            "description": "Open member search",
            "route": "https://bank.example.test/members/search",
        },
        {
            "action_type": "fill",
            "action_id": "fill-member",
            "description": "Enter member ID",
            "target": target("Member ID"),
            "value_template": "${member_id}",
        },
        {
            "action_type": "click",
            "action_id": "submit-search",
            "description": "Submit member search",
            "target": target("Search"),
        },
        {
            "action_type": "extract_text",
            "action_id": "read-balance",
            "description": "Read savings balance",
            "target": target("Savings balance"),
            "output_name": "savings_balance",
        },
    ]
    if mode == "checkpoint_failure":
        success_conditions = [{
            "condition_type": "text_contains",
            "target": target("Member status"),
            "expected_text": "Confirmation state",
        }]
    return CapabilityArtifact(
        capability_id="member.savings_balance.lookup",
        revision=1,
        name="Look up savings balance",
        description="Read a synthetic member savings balance.",
        compatibility={
            "surface_kind": "web",
            "vendor_product": "local-member-servicing",
            "vendor_version": "demo-1",
            "application_name": "Member Console",
            "application_version": "demo-1",
        },
        entry_point="https://bank.example.test/members/search",
        inputs=[{
            "value_type": "string",
            "name": "member_id",
            "description": "Synthetic member identifier",
            "pattern": "^[0-9]{5}$",
        }],
        actions=actions,
        outputs=[{
            "name": "savings_balance",
            "description": "Current savings balance",
            "output_type": "decimal",
            "source_action_id": "read-balance",
            "parser": "currency",
        }],
        success_checkpoint={"description": "Balance is readable", "conditions": success_conditions},
        known_business_outcomes=[{
            "code": "MEMBER_NOT_FOUND",
            "description": "No member matches the requested identifier.",
            "detection": {
                "condition_type": "text_contains",
                "target": target("Member status"),
                "expected_text": "Member not found",
            },
        }],
        safety_profile={
            "permitted_action_types": ["navigate", "fill", "click", "extract_text"],
        },
    )


def runner(surface: ReplaySurface, permitted_action_types=None, evidence_directory=None):
    policy = SafetyPolicy(
        allowed_targets=[AllowedTarget(origin="https://bank.example.test", route_prefixes=["/members"])],
        permitted_action_types=permitted_action_types or ["navigate", "fill", "click", "extract_text"],
    )
    return CapabilityReplayRunner(
        surface,
        PolicyEnforcedSurfaceAdapter(surface, SafetyPolicyEvaluator(policy)),
        evidence_directory=evidence_directory,
    )


def test_successful_replay_returns_typed_outputs() -> None:
    surface = ReplaySurface()

    result = runner(surface).replay(artifact(), {"member_id": "12345"})

    assert isinstance(result, CapabilityExecutionSucceeded)
    assert result.outputs == {"savings_balance": "$1,240.50"}
    assert surface.action_order == ["navigate", "fill", "click"]


def test_member_not_found_is_a_business_outcome() -> None:
    result = runner(ReplaySurface("not_found")).replay(artifact(), {"member_id": "99999"})

    assert isinstance(result, KnownBusinessOutcome)
    assert result.outcome_code == "MEMBER_NOT_FOUND"


def test_transient_delay_is_retried_with_bounded_budget() -> None:
    surface = ReplaySurface("transient")

    result = runner(surface).replay(artifact(), {"member_id": "12345"})

    assert isinstance(result, CapabilityExecutionSucceeded)
    assert surface.transient_attempts == 1


def test_validation_error_is_structured_failure(tmp_path: Path) -> None:
    result = runner(ReplaySurface("validation"), evidence_directory=tmp_path).replay(artifact(), {"member_id": "12345"})

    assert isinstance(result, CapabilityExecutionFailed)
    assert result.failure_category is ReplayFailureCategory.VALIDATION_ERROR
    assert result.evidence_reference is not None


def test_missing_target_is_structured_failure(tmp_path: Path) -> None:
    result = runner(ReplaySurface("missing_target"), evidence_directory=tmp_path).replay(artifact(), {"member_id": "12345"})

    assert isinstance(result, CapabilityExecutionFailed)
    assert result.failure_category is ReplayFailureCategory.SURFACE_FAILURE
    assert result.step_id == "read-balance"


def test_checkpoint_failure_is_structured_failure() -> None:
    result = runner(ReplaySurface(),).replay(artifact("checkpoint_failure"), {"member_id": "12345"})

    assert isinstance(result, CapabilityExecutionFailed)
    assert result.failure_category is ReplayFailureCategory.CHECKPOINT_FAILURE


def test_policy_rejection_is_structured_failure() -> None:
    result = runner(ReplaySurface(), permitted_action_types=["fill", "click", "extract_text"]).replay(artifact(), {"member_id": "12345"})

    assert isinstance(result, CapabilityExecutionFailed)
    assert result.failure_category is ReplayFailureCategory.POLICY_REJECTION
    assert result.step_id == "open-search"