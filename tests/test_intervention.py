from pathlib import Path

import pytest

from automation.intervention import ControlOwner, HumanInterventionCoordinator
from automation.surface.contracts import (
    HumanSurfaceAction,
    HumanSurfaceActionType,
    LiveInteractiveSession,
    SurfaceObservation,
)
from automation.surface.errors import SessionControlError


class HandoffSurface:
    def __init__(self) -> None:
        self.owner = "automation"
        self.session_id = "same-session"
        self.actions: list[str] = []

    def observe(self) -> SurfaceObservation:
        if self.owner != "automation":
            raise SessionControlError("automation does not own the live session")
        return SurfaceObservation("demo", "http://demo.test/members/12345", "Member Details", "Member Details")

    def expose_live_session(self) -> LiveInteractiveSession:
        if self.owner != "automation":
            raise SessionControlError("already human-owned")
        self.owner = "human"
        return LiveInteractiveSession(self.session_id, "http://demo.test/members/12345", "human")

    def resume_live_session(self, session_id: str) -> LiveInteractiveSession:
        if self.owner != "human" or session_id != self.session_id:
            raise SessionControlError("invalid resume")
        self.owner = "automation"
        return LiveInteractiveSession(self.session_id, "http://demo.test/members/12345", "automation")

    def perform_human_action(self, action: HumanSurfaceAction):
        if self.owner != "human":
            raise SessionControlError("human does not own session")
        self.actions.append(action.description)
        return None

    def capture_evidence(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"evidence")
        return destination


def test_handoff_transfers_same_session_and_records_operator_action(tmp_path: Path) -> None:
    surface = HandoffSurface()
    coordinator = HumanInterventionCoordinator(surface, evidence_directory=tmp_path)

    request = coordinator.request_intervention("member.lookup", "find member", "step-2", 1, "permission prompt")
    record = coordinator.perform_human_action(
        HumanSurfaceAction(HumanSurfaceActionType.CLICK, description="Dismiss permission prompt")
    )
    resume_event = coordinator.resume_automation()

    assert request.control_owner is ControlOwner.HUMAN
    assert request.session_id == "same-session"
    assert record.request_id == request.request_id
    assert resume_event.to_owner is ControlOwner.AUTOMATION
    assert coordinator.control_owner is ControlOwner.AUTOMATION
    assert surface.owner == "automation"


def test_invalid_control_transitions_are_rejected() -> None:
    surface = HandoffSurface()
    coordinator = HumanInterventionCoordinator(surface)

    with pytest.raises(SessionControlError):
        coordinator.resume_automation()

    coordinator.request_intervention("member.lookup", "find member", "step-2", 1, "stuck")
    with pytest.raises(SessionControlError):
        coordinator.request_intervention("member.lookup", "find member", "step-2", 1, "again")

    coordinator.resume_automation()
    with pytest.raises(SessionControlError):
        coordinator.perform_human_action(HumanSurfaceAction(HumanSurfaceActionType.CLICK, description="late action"))