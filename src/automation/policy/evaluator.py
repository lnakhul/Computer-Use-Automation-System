"""Pure policy evaluation with no surface or browser dependencies."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from automation.policy.models import (
    PolicyActionRequest,
    PolicyDecision,
    PolicyDecisionKind,
    SafetyPolicy,
)


class SafetyPolicyEvaluator:
    def __init__(self, policy: SafetyPolicy) -> None:
        self._policy = policy

    def evaluate(
        self,
        request: PolicyActionRequest,
        current_location: str | None = None,
    ) -> PolicyDecision:
        if request.action_type not in self._policy.permitted_action_types:
            return PolicyDecision(
                decision=PolicyDecisionKind.DENIED,
                reason=f"action type is not permitted: {request.action_type.value}",
            )

        normalized_destination = None
        if request.destination is not None:
            if current_location is None and not urlsplit(request.destination).netloc:
                return PolicyDecision(
                    decision=PolicyDecisionKind.DENIED,
                    reason="relative destination requires a current location",
                )
            normalized_destination = urljoin(current_location or "", request.destination)
            if not self._is_allowed_destination(normalized_destination):
                return PolicyDecision(
                    decision=PolicyDecisionKind.DENIED,
                    reason="destination is outside the configured origin and route allowlist",
                    normalized_destination=normalized_destination,
                )

        if request.risk in self._policy.denied_risks:
            return PolicyDecision(
                decision=PolicyDecisionKind.DENIED,
                reason=f"risk category is denied: {request.risk.value}",
                normalized_destination=normalized_destination,
            )

        if request.risk in self._policy.confirmation_required_risks and not request.human_confirmation:
            return PolicyDecision(
                decision=PolicyDecisionKind.REQUIRES_HUMAN_CONFIRMATION,
                reason=f"human confirmation is required for risk: {request.risk.value}",
                normalized_destination=normalized_destination,
            )

        return PolicyDecision(
            decision=PolicyDecisionKind.ALLOWED,
            reason="action is permitted by policy",
            normalized_destination=normalized_destination,
        )

    def _is_allowed_destination(self, destination: str) -> bool:
        parsed_destination = urlsplit(destination)
        destination_origin = f"{parsed_destination.scheme}://{parsed_destination.netloc}".rstrip("/")
        for allowed_target in self._policy.allowed_targets:
            if destination_origin != allowed_target.origin:
                continue
            if any(parsed_destination.path.startswith(route) for route in allowed_target.route_prefixes):
                return True
        return False