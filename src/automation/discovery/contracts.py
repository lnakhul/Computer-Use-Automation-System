"""Provider interface for structured model decisions."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from automation.discovery.models import AgentDecision
from automation.surface.contracts import SurfaceObservation


class DecisionProviderError(RuntimeError):
    """The configured provider could not return a valid structured decision."""


@runtime_checkable
class AgentDecisionProvider(Protocol):
    def decide(self, goal: str, observation: SurfaceObservation) -> AgentDecision:
        """Return one validated next decision from the observable state."""