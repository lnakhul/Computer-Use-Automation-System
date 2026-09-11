"""Pure policy evaluation with no surface or browser dependencies."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit, unquote

from automation.capabilities.models import ActionType, ActionRisk

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

        if request.destination is None and (not current_location or not self._is_allowed_destination(current_location)):
            return PolicyDecision(decision=PolicyDecisionKind.DENIED, reason="current location is outside the configured allowlist")
        effective_risk = request.risk
        if request.action_type in {ActionType.CLICK, ActionType.FILL}:
            # The deployment policy, never the model, approves control semantics.
            matches = [rule for rule in self._policy.approved_interactions
                       if rule.action_type == request.action_type and request.target is not None
                       and all(candidate.strategy in [c.strategy for c in rule.target.candidates] for candidate in request.target.candidates)]
            if not matches:
                return PolicyDecision(decision=PolicyDecisionKind.DENIED, reason="control is not approved by deployment policy")
            order = {ActionRisk.READ_ONLY: 0, ActionRisk.REVERSIBLE: 1, ActionRisk.IRREVERSIBLE: 2}
            effective_risk = max([request.risk] + [rule.risk for rule in matches], key=order.get)
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

        if effective_risk in self._policy.denied_risks:
            return PolicyDecision(
                decision=PolicyDecisionKind.DENIED,
                reason=f"risk category is denied: {effective_risk.value}",
                normalized_destination=normalized_destination,
            )

        if effective_risk in self._policy.confirmation_required_risks and not request.human_confirmation:
            return PolicyDecision(
                decision=PolicyDecisionKind.REQUIRES_HUMAN_CONFIRMATION,
                reason=f"human confirmation is required for risk: {effective_risk.value}",
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
            path = unquote(parsed_destination.path)
            if any(segment in {".", ".."} for segment in path.split("/")) or "\\" in path:
                return False
            if any(path == route.rstrip("/") or path.startswith(route.rstrip("/") + "/") for route in allowed_target.route_prefixes):
                return True
        return False

    def allows_request(self, destination: str, method: str = "GET") -> bool:
        if not self._is_allowed_destination(destination):
            return False
        if method in {"GET", "HEAD"}:
            return True
        return method == "POST" and unquote(urlsplit(destination).path) in self._policy.allowed_post_routes
