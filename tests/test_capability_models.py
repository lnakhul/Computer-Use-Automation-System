import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from automation.capabilities.models import CapabilityArtifact


def example_artifact_payload() -> dict:
    return {
        "artifact_schema_version": "1.0",
        "capability_id": "member.savings_balance.lookup",
        "revision": 1,
        "name": "Look up member savings balance",
        "description": "Find a member and read the current savings balance.",
        "compatibility": {
            "surface_kind": "web",
            "vendor_product": "local-member-servicing",
            "vendor_version": "demo-1",
            "application_name": "Member Servicing Console",
            "application_version": "demo-1",
        },
        "entry_point": "/members/search",
        "inputs": [
            {
                "value_type": "string",
                "name": "member_id",
                "description": "Five-digit synthetic member identifier.",
                "pattern": "^[0-9]{5}$",
            }
        ],
        "actions": [
            {
                "action_type": "navigate",
                "action_id": "open-search",
                "description": "Open member search.",
                "route": "/members/search",
            },
            {
                "action_type": "fill",
                "action_id": "enter-member-id",
                "description": "Enter the requested member ID.",
                "target": {
                    "description": "Member ID field",
                    "candidates": [
                        {
                            "priority": 1,
                            "strategy": {"kind": "label", "label": "Member ID"},
                        },
                        {
                            "priority": 2,
                            "strategy": {
                                "kind": "attribute",
                                "attribute_name": "name",
                                "attribute_value": "member_id",
                            },
                        },
                    ],
                },
                "value_template": "${inputs.member_id}",
            },
            {
                "action_type": "click",
                "action_id": "submit-search",
                "description": "Submit the member search.",
                "target": {
                    "description": "Search button",
                    "candidates": [
                        {
                            "priority": 1,
                            "strategy": {
                                "kind": "role",
                                "role": "button",
                                "accessible_name": "Search",
                            },
                        }
                    ],
                },
            },
            {
                "action_type": "wait_for_state",
                "action_id": "wait-for-member-detail",
                "description": "Wait for the member detail heading.",
                "condition": {
                    "condition_type": "element_visible",
                    "target": {
                        "description": "Member detail heading",
                        "candidates": [
                            {
                                "priority": 1,
                                "strategy": {
                                    "kind": "role",
                                    "role": "heading",
                                    "accessible_name": "Member Details",
                                },
                            }
                        ],
                    },
                },
                "timeout_seconds": 10,
            },
            {
                "action_type": "extract_text",
                "action_id": "read-savings-balance",
                "description": "Read the savings balance.",
                "target": {
                    "description": "Savings balance value",
                    "candidates": [
                        {
                            "priority": 1,
                            "strategy": {
                                "kind": "label",
                                "label": "Savings balance",
                            },
                        }
                    ],
                },
                "output_name": "savings_balance",
            },
        ],
        "outputs": [
            {
                "name": "savings_balance",
                "description": "Current savings balance.",
                "output_type": "decimal",
                "source_action_id": "read-savings-balance",
                "parser": "currency",
                "sensitive": True,
            }
        ],
        "success_checkpoint": {
            "description": "Member detail and a parseable savings balance are visible.",
            "conditions": [
                {
                    "condition_type": "extracted_value_matches",
                    "output_name": "savings_balance",
                    "pattern": r"^\$?[0-9,]+\.[0-9]{2}$",
                }
            ],
        },
        "known_business_outcomes": [
            {
                "code": "MEMBER_NOT_FOUND",
                "description": "No member exists for the requested identifier.",
                "detection": {
                    "condition_type": "text_contains",
                    "target": {
                        "description": "Search result status",
                        "candidates": [
                            {
                                "priority": 1,
                                "strategy": {
                                    "kind": "text",
                                    "text": "Member not found",
                                },
                            }
                        ],
                    },
                    "expected_text": "Member not found",
                },
            }
        ],
        "safety_profile": {
            "permitted_action_types": [
                "navigate",
                "fill",
                "click",
                "wait_for_state",
                "extract_text",
            ],
            "maximum_risk": "reversible",
            "risky_action_policy": "block",
        },
    }


def test_valid_artifact_serializes_and_deserializes() -> None:
    artifact = CapabilityArtifact.model_validate(example_artifact_payload())

    serialized_artifact = artifact.model_dump_json()
    restored_artifact = CapabilityArtifact.model_validate_json(serialized_artifact)

    assert json.loads(serialized_artifact)["artifact_schema_version"] == "1.0"
    assert restored_artifact == artifact
    assert restored_artifact.inputs[0].name == "member_id"
    assert restored_artifact.outputs[0].sensitive is True


def test_required_fields_are_enforced() -> None:
    payload = example_artifact_payload()
    del payload["success_checkpoint"]

    with pytest.raises(ValidationError):
        CapabilityArtifact.model_validate(payload)


def test_only_supported_schema_version_is_accepted() -> None:
    payload = example_artifact_payload()
    payload["artifact_schema_version"] = "2.0"

    with pytest.raises(ValidationError):
        CapabilityArtifact.model_validate(payload)


def test_typed_parameters_preserve_declared_types() -> None:
    payload = example_artifact_payload()
    payload["inputs"] = [
        {
            "value_type": "integer",
            "name": "attempt_count",
            "description": "Maximum retry attempts.",
            "minimum": 1,
            "maximum": 3,
            "default": 2,
        },
        {
            "value_type": "decimal",
            "name": "threshold",
            "description": "Balance threshold.",
            "default": "12.50",
        },
    ]

    payload["actions"][1]["value_template"] = "${attempt_count}"
    artifact = CapabilityArtifact.model_validate(payload)

    assert artifact.inputs[0].value_type == "integer"
    assert artifact.inputs[0].default == 2
    assert artifact.inputs[1].default == Decimal("12.50")


def test_malformed_action_is_rejected() -> None:
    payload = example_artifact_payload()
    payload["actions"][0] = {
        "action_type": "unsupported_action",
        "action_id": "bad-action",
        "description": "Malformed action.",
    }

    with pytest.raises(ValidationError):
        CapabilityArtifact.model_validate(payload)


def test_locator_candidates_require_unique_ascending_priorities() -> None:
    payload = example_artifact_payload()
    payload["actions"][1]["target"]["candidates"][1]["priority"] = 1

    with pytest.raises(ValidationError, match="priorities"):
        CapabilityArtifact.model_validate(payload)


def test_locator_strategy_requires_its_discriminator_fields() -> None:
    payload = example_artifact_payload()
    payload["actions"][2]["target"]["candidates"][0]["strategy"] = {
        "kind": "role",
        "accessible_name": "Search",
    }

    with pytest.raises(ValidationError):
        CapabilityArtifact.model_validate(payload)


def test_irreversible_action_requires_conservative_safety_metadata() -> None:
    payload = example_artifact_payload()
    payload["actions"].append(
        {
            "action_type": "click",
            "action_id": "submit-transaction",
            "description": "Submit a transaction.",
            "risk": "irreversible",
            "target": payload["actions"][2]["target"],
        }
    )

    with pytest.raises(ValidationError, match="irreversible"):
        CapabilityArtifact.model_validate(payload)

    payload["safety_profile"]["maximum_risk"] = "irreversible"
    payload["safety_profile"]["risky_action_policy"] = "require_human_confirmation"
    artifact = CapabilityArtifact.model_validate(payload)

    assert artifact.safety_profile.risky_action_policy == "require_human_confirmation"