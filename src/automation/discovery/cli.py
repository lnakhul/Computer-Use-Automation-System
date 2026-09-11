"""Manual entry point for a configured OpenAI-compatible discovery run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from automation.capabilities.models import CapabilityArtifact
from automation.discovery.models import DiscoveryArtifactDefinition, DiscoveryRequest, RuntimeParameter
from automation.discovery.openai_provider import OpenAICompatibleDecisionProvider
from automation.discovery.runner import DiscoveryRunner
from automation.evidence import JsonlEvidenceWriter, RedactionPolicy, SensitiveDataRedactor
from automation.policy import PolicyEnforcedSurfaceAdapter, SafetyPolicy, SafetyPolicyEvaluator
from automation.surface.playwright_adapter import PlaywrightBrowserSurfaceAdapter


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one LLM-driven discovery session against the demo app.")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--target", required=True, help="Absolute demo-app entry URL.")
    parser.add_argument("--member-id", required=True)
    parser.add_argument("--artifact", default="examples/member_savings_balance.json")
    parser.add_argument("--output", default="evidence/discovery-artifact.json")
    parser.add_argument("--evidence", default="evidence/discovery-run.jsonl")
    arguments = parser.parse_args()

    artifact_template = CapabilityArtifact.model_validate_json(Path(arguments.artifact).read_text(encoding="utf-8"))
    definition = DiscoveryArtifactDefinition(
        capability_id=artifact_template.capability_id,
        revision=artifact_template.revision,
        name=artifact_template.name,
        description=artifact_template.description,
        compatibility=artifact_template.compatibility,
        entry_point=arguments.target,
        inputs=artifact_template.inputs,
        outputs=artifact_template.outputs,
        success_checkpoint=artifact_template.success_checkpoint,
        known_business_outcomes=artifact_template.known_business_outcomes,
        safety_profile=artifact_template.safety_profile,
    )
    request = DiscoveryRequest(
        goal=arguments.goal,
        artifact_definition=definition,
        runtime_parameters=[RuntimeParameter(name="member_id", value=arguments.member_id)],
    )
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    api_key = os.environ["OPENAI_API_KEY"]
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    provider = OpenAICompatibleDecisionProvider(base_url, api_key, model_name)
    policy = SafetyPolicy(
        allowed_targets=[
            {
                "origin": _origin(arguments.target),
                "route_prefixes": ["/members", "/accounts"],
            }
        ],
        permitted_action_types=artifact_template.safety_profile.permitted_action_types,
    )
    redactor = SensitiveDataRedactor(
        RedactionPolicy(
            sensitive_field_names=["member_id", "authorization", "cookie", "token", "balance"],
            sensitive_value_patterns=[r"Bearer\s+\S+", r"token=[^\s&]+"],
        )
    )

    with sync_playwright() as browser_runtime:
        browser = browser_runtime.chromium.launch(channel="chrome")
        page = browser.new_page()
        surface = PlaywrightBrowserSurfaceAdapter(page)
        guarded_surface = PolicyEnforcedSurfaceAdapter(surface, SafetyPolicyEvaluator(policy))
        result = DiscoveryRunner(
            surface,
            provider,
            guarded_surface,
            JsonlEvidenceWriter(Path(arguments.evidence), redactor),
        ).run(request)
        if result.artifact is not None:
            Path(arguments.output).parent.mkdir(parents=True, exist_ok=True)
            Path(arguments.output).write_text(result.artifact.model_dump_json(indent=2), encoding="utf-8")
        print(json.dumps({"stop_state": result.stop_state.value, "steps_executed": result.steps_executed, "reason": result.reason}))
        browser.close()


def _origin(target: str) -> str:
    from urllib.parse import urlsplit

    parsed_target = urlsplit(target)
    return f"{parsed_target.scheme}://{parsed_target.netloc}"


if __name__ == "__main__":
    main()