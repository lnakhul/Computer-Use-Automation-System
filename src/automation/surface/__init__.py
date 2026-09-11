"""Surface-independent computer interaction contracts and implementations."""

from .contracts import (
    ComputerSurfaceAdapter,
    HumanSurfaceAction,
    HumanSurfaceActionType,
    LiveInteractiveSession,
    ResolvedSurfaceTarget,
    SurfaceObservation,
)

__all__ = [
    "ComputerSurfaceAdapter",
    "HumanSurfaceAction",
    "HumanSurfaceActionType",
    "LiveInteractiveSession",
    "ResolvedSurfaceTarget",
    "SurfaceObservation",
]