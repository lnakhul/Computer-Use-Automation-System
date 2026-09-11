"""Errors raised by surface adapters."""


class SurfaceAdapterError(RuntimeError):
    """Base error for surface interaction failures."""


class TargetResolutionError(SurfaceAdapterError):
    """A recorded target could not be resolved uniquely."""


class SessionControlError(SurfaceAdapterError):
    """A live-session control transfer was invalid."""

class SurfaceTimeoutError(TargetResolutionError):
    """A bounded wait expired; only read/wait operations may be retried."""


class AmbiguousTargetError(SurfaceAdapterError):
    """More than one control matches; fallback must not hide ambiguity."""
