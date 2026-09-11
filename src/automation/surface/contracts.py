"""Generic contracts for operating a computer surface."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from automation.capabilities.models import ElementTarget
from automation.capabilities.models import CheckpointCondition


@dataclass(frozen=True)
class SurfaceObservation:
    """A sanitized snapshot that discovery or replay can reason about."""

    surface_identifier: str
    current_location: str
    title: str
    visible_text: str
    dialog_text: str | None = None


@dataclass(frozen=True)
class ResolvedSurfaceTarget:
    """Adapter-owned evidence that a semantic target was resolved."""

    target_description: str
    selected_priority: int
    strategy_kind: str


@dataclass(frozen=True)
class LiveInteractiveSession:
    """Handle used to transfer control without creating a new session."""

    session_id: str
    current_location: str
    control_owner: str


@runtime_checkable
class ComputerSurfaceAdapter(Protocol):
    """Operations required by discovery and deterministic replay."""

    def observe(self) -> SurfaceObservation:
        """Return the current sanitized surface state."""

    def navigate(self, destination: str) -> None:
        """Navigate to an approved surface destination."""

    def resolve_recorded_target(self, target: ElementTarget) -> ResolvedSurfaceTarget:
        """Resolve a semantic recorded target using adapter-specific mechanics."""

    def click(self, target: ElementTarget) -> ResolvedSurfaceTarget:
        """Click one uniquely resolved target."""

    def enter_text(self, target: ElementTarget, text: str) -> ResolvedSurfaceTarget:
        """Enter text into one uniquely resolved target."""

    def read_text_or_value(self, target: ElementTarget) -> str:
        """Read visible text or a form control value."""

    def wait_for_state(self, condition: CheckpointCondition, timeout_seconds: float) -> None:
        """Wait for a declared surface state."""

    def capture_evidence(self, destination: Path) -> Path:
        """Capture evidence for the current state and return its path."""

    def expose_live_session(self) -> LiveInteractiveSession:
        """Pause automation ownership and expose the current live session."""

    def resume_live_session(self, session_id: str) -> LiveInteractiveSession:
        """Resume automation ownership for the same live session."""