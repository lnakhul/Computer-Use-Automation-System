"""Minimal same-session human handoff coordinator."""

from __future__ import annotations

import uuid
from pathlib import Path

from automation.evidence.logging import JsonlEvidenceWriter
from automation.intervention.models import (
    ControlOwner,
    ControlTransferEvent,
    HumanActionRecord,
    HumanInterventionRequest,
)
from automation.surface.contracts import ComputerSurfaceAdapter, HumanSurfaceAction
from automation.surface.errors import SessionControlError


class HumanInterventionCoordinator:
    """Owns the exclusive automation/human lease around one live session."""

    def __init__(
        self,
        surface: ComputerSurfaceAdapter,
        evidence_writer: JsonlEvidenceWriter | None = None,
        evidence_directory: Path | None = None,
    ) -> None:
        self._surface = surface
        self._evidence_writer = evidence_writer
        self._evidence_directory = evidence_directory
        self._request: HumanInterventionRequest | None = None
        self._session_id: str | None = None

    @property
    def control_owner(self) -> ControlOwner:
        if self._request is not None:
            return ControlOwner.HUMAN
        return ControlOwner.AUTOMATION

    def request_intervention(
        self,
        capability_id: str,
        goal: str,
        current_step_id: str,
        current_step_index: int,
        reason: str,
    ) -> HumanInterventionRequest:
        if self.control_owner is not ControlOwner.AUTOMATION:
            raise SessionControlError("cannot request intervention while human already owns the session")
        observation = self._surface.observe()
        session = self._surface.expose_live_session()
        self._session_id = session.session_id
        screenshot_reference = self._capture_evidence("handoff")
        request = HumanInterventionRequest(
            request_id=str(uuid.uuid4()),
            capability_id=capability_id,
            goal=goal,
            current_step_id=current_step_id,
            current_step_index=current_step_index,
            reason=reason,
            sanitized_current_state={
                "surface_identifier": observation.surface_identifier,
                "current_location": observation.current_location,
                "title": observation.title,
                "visible_text": observation.visible_text[:1000],
                "dialog_text": observation.dialog_text,
            },
            screenshot_evidence_reference=screenshot_reference,
            session_id=session.session_id,
        )
        self._request = request
        self._write_event(ControlTransferEvent(
            session_id=session.session_id,
            from_owner=ControlOwner.AUTOMATION,
            to_owner=ControlOwner.HUMAN,
            reason=reason,
            request_id=request.request_id,
        ))
        return request

    def perform_human_action(self, action: HumanSurfaceAction) -> HumanActionRecord:
        request = self._require_human_owner()
        result = self._surface.perform_human_action(action)
        evidence_reference = self._capture_evidence("human-action")
        record = HumanActionRecord(
            request_id=request.request_id,
            session_id=request.session_id,
            action_type=action.action_type,
            description=action.description,
            result_summary="completed" if result is None else "target action completed",
            evidence_reference=evidence_reference,
        )
        self._write_event(record)
        return record

    def resume_automation(self) -> ControlTransferEvent:
        request = self._require_human_owner()
        self._surface.resume_live_session(request.session_id)
        event = ControlTransferEvent(
            session_id=request.session_id,
            from_owner=ControlOwner.HUMAN,
            to_owner=ControlOwner.AUTOMATION,
            reason="operator signalled resume",
            request_id=request.request_id,
        )
        self._request = None
        self._session_id = None
        self._write_event(event)
        return event

    def _require_human_owner(self) -> HumanInterventionRequest:
        if self._request is None or self.control_owner is not ControlOwner.HUMAN:
            raise SessionControlError("human does not own the live session")
        return self._request

    def _capture_evidence(self, label: str) -> str | None:
        if self._evidence_directory is None:
            return None
        path = self._surface.capture_evidence(self._evidence_directory / f"{label}-{uuid.uuid4()}.png")
        return str(path)

    def _write_event(self, event: ControlTransferEvent | HumanActionRecord) -> None:
        if self._evidence_writer is not None:
            self._evidence_writer.write_event(event.model_dump(mode="json"))