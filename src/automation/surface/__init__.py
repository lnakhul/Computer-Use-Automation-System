"""Surface-independent computer interaction contracts and implementations."""

from .contracts import (
    ComputerSurfaceAdapter,
    LiveInteractiveSession,
    ResolvedSurfaceTarget,
    SurfaceObservation,
)

__all__ = [
    "ComputerSurfaceAdapter",
    "LiveInteractiveSession",
    "ResolvedSurfaceTarget",
    "SurfaceObservation",
]