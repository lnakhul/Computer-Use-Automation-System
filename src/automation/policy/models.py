"""Typed safety policy contracts."""

from __future__ import annotations

from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from automation.capabilities.models import ActionRisk, ActionType, ContractModel


class PolicyDecisionKind(StrEnum):
    ALLOWED = "allowed"
    REQUIRES_HUMAN_CONFIRMATION = "requires_human_confirmation"
    DENIED = "denied"


class AllowedTarget(ContractModel):
    origin: str = Field(min_length=1)
    route_prefixes: list[str] = Field(min_length=1)

    @field_validator("origin")
    @classmethod
    def validate_origin(cls, origin: str) -> str:
        parsed_origin = urlsplit(origin)
        if not parsed_origin.scheme or not parsed_origin.netloc or parsed_origin.path not in {"", "/"}:
            raise ValueError("origin must include scheme and host without a route")
        return origin.rstrip("/")

    @field_validator("route_prefixes")
    @classmethod
    def validate_route_prefixes(cls, route_prefixes: list[str]) -> list[str]:
        if any(not route.startswith("/") for route in route_prefixes):
            raise ValueError("route prefixes must start with '/'")
        return route_prefixes


class SafetyPolicy(ContractModel):
    allowed_targets: list[AllowedTarget] = Field(min_length=1)
    permitted_action_types: list[ActionType] = Field(min_length=1)
    confirmation_required_risks: list[ActionRisk] = Field(
        default_factory=lambda: [ActionRisk.IRREVERSIBLE]
    )
    denied_risks: list[ActionRisk] = Field(default_factory=list)


class PolicyActionRequest(ContractModel):
    action_type: ActionType
    risk: ActionRisk
    destination: str | None = None
    human_confirmation: bool = False


class PolicyDecision(ContractModel):
    decision: PolicyDecisionKind
    reason: str = Field(min_length=1)
    normalized_destination: str | None = None
