"""Trusted deployment policy for the synthetic member lookup only."""
from automation.policy.models import ApprovedInteraction


def approved_interactions():
    return [ApprovedInteraction(action_type="fill", risk="reversible", target={
        "description": "Member ID field", "candidates": [
            {"priority": 1, "strategy": {"kind": "label", "label": "Member ID"}},
            {"priority": 2, "strategy": {"kind": "attribute", "attribute_name": "name", "attribute_value": "member_id"}},
        ]}), ApprovedInteraction(action_type="click", risk="read_only", target={
        "description": "Search", "candidates": [
            {"priority": 1, "strategy": {"kind": "role", "role": "button", "accessible_name": "Search"}},
        ]})]
