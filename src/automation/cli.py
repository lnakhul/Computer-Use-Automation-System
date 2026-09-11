"""Evaluator-facing commands for the local computer-use vertical slice."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urljoin

from automation.capabilities.models import CapabilityArtifact, ElementTarget, NavigateAction
from automation.evidence import JsonlEvidenceWriter, RedactionPolicy, SensitiveDataRedactor
from automation.intervention import HumanInterventionCoordinator
from automation.policy import AllowedTarget, PolicyEnforcedSurfaceAdapter, SafetyPolicy, SafetyPolicyEvaluator
from automation.replay import CapabilityReplayRunner
from automation.surface.contracts import HumanSurfaceAction, HumanSurfaceActionType
from automation.surface.playwright_adapter import PlaywrightBrowserSurfaceAdapter


def main() -> None:
    parser = argparse.ArgumentParser(prog="automation", description="Computer-use automation demonstration commands")
    subparsers = parser.add_subparsers(dest="command", required=True)

    demo_parser = subparsers.add_parser("demo", help="start the local legacy member-servicing app")
    demo_parser.add_argument("--host", default="127.0.0.1")
    demo_parser.add_argument("--port", type=int, default=5001)

    discover_parser = subparsers.add_parser("discover", help="run LLM-driven discovery")
    discover_parser.add_argument("--goal", required=True)
    discover_parser.add_argument("--timeout", type=float, default=120)
    discover_parser.add_argument("--interactive", action="store_true")
    discover_parser.add_argument("--target", default="http://127.0.0.1:5001/members/search")
    discover_parser.add_argument("--member-id", required=True)
    discover_parser.add_argument("--artifact", default="examples/member_savings_balance.json")
    discover_parser.add_argument("--output", default="evidence/discovery-artifact.json")
    discover_parser.add_argument("--evidence", default="evidence/discovery-run.jsonl")

    replay_parser = subparsers.add_parser("replay", help="replay a named artifact without an LLM")
    replay_parser.add_argument("artifact", help="path to the capability artifact JSON")
    replay_parser.add_argument("--member-id", required=True)
    replay_parser.add_argument("--interactive", action="store_true")
    replay_parser.add_argument("--target", default="http://127.0.0.1:5001/members/search")
    replay_parser.add_argument("--evidence", default="evidence/replay-run.jsonl")
    replay_parser.add_argument("--evidence-directory", default="evidence/replay-failures")

    exceptional_parser = subparsers.add_parser("replay-not-found", help="replay the artifact with a missing member")
    exceptional_parser.add_argument("artifact", nargs="?", default="examples/member_savings_balance.json")
    exceptional_parser.add_argument("--evidence-directory", default="evidence/replay-failures")
    exceptional_parser.add_argument("--interactive", action="store_true")
    exceptional_parser.add_argument("--target", default="http://127.0.0.1:5001/members/search")
    exceptional_parser.add_argument("--evidence", default="evidence/replay-not-found.jsonl")

    human_parser = subparsers.add_parser("human-demo", help="exercise same-session human handoff and resume")
    human_parser.add_argument("--target", default="http://127.0.0.1:5001/members/12345")
    human_parser.add_argument("--evidence", default="evidence/human-intervention.jsonl")
    human_parser.add_argument("--evidence-directory", default="evidence/human-intervention")

    arguments = parser.parse_args()
    if arguments.command == "demo":
        _run_demo(arguments.host, arguments.port)
    elif arguments.command == "discover":
        _run_discovery(arguments)
    elif arguments.command == "replay":
        _run_replay(arguments, "success")
    elif arguments.command == "replay-not-found":
        _run_replay(arguments, "not_found")
    elif arguments.command == "human-demo":
        _run_human_demo(arguments)


def _run_demo(host: str, port: int) -> None:
    from automation.demo_app import create_demo_application

    print(f"Starting local demo at http://{host}:{port}")
    create_demo_application().run(host=host, port=port, debug=False)


def _run_discovery(arguments: argparse.Namespace) -> None:
    import httpx  # noqa: F401  # Ensures the configured-provider dependency is explicit.
    from playwright.sync_api import sync_playwright

    from automation.discovery.models import DiscoveryArtifactDefinition, DiscoveryRequest, RuntimeParameter
    from automation.discovery.openai_provider import OpenAICompatibleDecisionProvider
    from automation.discovery.runner import DiscoveryRunner

    run_id = str(uuid.uuid4())
    template = _load_artifact(arguments.artifact)
    definition = DiscoveryArtifactDefinition(
        capability_id=template.capability_id,
        revision=template.revision,
        name=template.name,
        description=template.description,
        compatibility=template.compatibility,
        entry_point=arguments.target,
        inputs=template.inputs,
        outputs=template.outputs,
        success_checkpoint=template.success_checkpoint,
        known_business_outcomes=template.known_business_outcomes,
        safety_profile=template.safety_profile,
    )
    request = DiscoveryRequest(
        goal=arguments.goal,
        total_timeout_seconds=arguments.timeout,
        artifact_definition=definition,
        runtime_parameters=[RuntimeParameter(name="member_id", value=arguments.member_id)],
    )
    provider = OpenAICompatibleDecisionProvider(
        os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        os.environ["OPENAI_API_KEY"],
        os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
    )
    writer = _writer(arguments.evidence, run_id, template)
    policy_surface_factory = _policy_for_target(arguments.target, template)
    with sync_playwright() as browser_runtime:
        browser = browser_runtime.chromium.launch(channel="chrome", headless=not getattr(arguments, "interactive", False))
        page = browser.new_page(service_workers="block", accept_downloads=False)
        surface = PlaywrightBrowserSurfaceAdapter(page)
        operator = _operator_handler(surface, writer, Path("evidence/discovery-failures")) if arguments.interactive else None
        result = DiscoveryRunner(surface, provider, policy_surface_factory(surface), writer,
                                 Path("evidence/discovery-failures"), operator).run(request)
        if operator and result.artifact is None:
            operator(template.capability_id, "Discovery stopped", "discovery", result.steps_executed, result.stop_state.value)
        if result.artifact is not None:
            Path(arguments.output).parent.mkdir(parents=True, exist_ok=True)
            Path(arguments.output).write_text(result.artifact.model_dump_json(indent=2), encoding="utf-8")
        writer.write_event({"event_type": "discovery_result", "stop_state": result.stop_state.value, "steps_executed": result.steps_executed, "reason": result.reason})
        print(json.dumps(result.model_dump(mode="json")))
        browser.close()


def _run_replay(arguments: argparse.Namespace, mode: str) -> None:
    from playwright.sync_api import sync_playwright

    run_id = str(uuid.uuid4())
    template = _load_artifact(arguments.artifact)
    target = arguments.target
    if mode == "not_found":
        member_id = "99999"
    else:
        member_id = arguments.member_id
    artifact = _artifact_for_target(template, target)
    writer = _writer(arguments.evidence, run_id, artifact)
    writer.write_event({"event_type": "replay_started", "invocation": {"member_id": "[REDACTED]"}})
    with sync_playwright() as browser_runtime:
        browser = browser_runtime.chromium.launch(channel="chrome", headless=not getattr(arguments, "interactive", False))
        page = browser.new_page(service_workers="block", accept_downloads=False)
        surface = PlaywrightBrowserSurfaceAdapter(page)
        runner = CapabilityReplayRunner(
            surface,
            _policy_for_target(target, artifact)(surface),
            writer,
            Path(arguments.evidence_directory),
            intervention_handler=_operator_handler(surface, writer, Path(arguments.evidence_directory)) if arguments.interactive else None,
        )
        result = runner.replay(artifact, {"member_id": member_id})
        writer.write_event({"event_type": "replay_result", "result": result.model_dump(mode="json"), "checkpoint_verification": result.result_type == "succeeded"})
        print(json.dumps(result.model_dump(mode="json")))
        browser.close()


def _run_human_demo(arguments: argparse.Namespace) -> None:
    from playwright.sync_api import sync_playwright

    run_id = str(uuid.uuid4())
    writer = _writer(arguments.evidence, run_id)
    target = f"{arguments.target}?simulate=dialog"
    with sync_playwright() as browser_runtime:
        browser = browser_runtime.chromium.launch(channel="chrome", headless=not getattr(arguments, "interactive", False))
        page = browser.new_page(service_workers="block", accept_downloads=False)
        surface = PlaywrightBrowserSurfaceAdapter(page)
        surface.navigate(target)
        coordinator = HumanInterventionCoordinator(surface, writer, Path(arguments.evidence_directory))
        request = coordinator.request_intervention(
            "member.session.notice.dismiss",
            "Open member details and dismiss the session notice",
            "dismiss-session-notice",
            0,
            "A session notice requires operator acknowledgement",
        )
        writer.write_event({"event_type": "intervention_request", "request": request.model_dump(mode="json")})
        action = HumanSurfaceAction(
            HumanSurfaceActionType.CLICK,
            target=ElementTarget(
                description="Dismiss notice",
                candidates=[{"priority": 1, "strategy": {"kind": "text", "text": "Dismiss notice"}}],
            ),
            description="Dismiss the session notice",
        )
        record = coordinator.perform_human_action(action)
        resume_event = coordinator.resume_automation()
        writer.write_event({"event_type": "human_demo_result", "action": record.model_dump(mode="json"), "control_transfer": resume_event.model_dump(mode="json")})
        print(json.dumps({"request_id": request.request_id, "session_id": request.session_id, "resumed": True}))
        browser.close()


def _operator_handler(surface, writer, evidence_directory):
    """A minimal explicit-action operator UI on the exact paused browser session."""
    coordinator = HumanInterventionCoordinator(surface, writer, evidence_directory)
    def handle(capability_id, goal, step_id, step_index, reason):
        request = coordinator.request_intervention(capability_id, goal, step_id, step_index, reason)
        print(json.dumps({"intervention_request": request.model_dump(mode="json")}))
        print('Enter a human action JSON: {"action_type":"click","target":{...}}; or resume / stop. Use this console so actions are recorded.')
        while True:
            try:
                command = input("operator> ").strip()
            except (EOFError, KeyboardInterrupt):
                command = "stop"
            if command in {"resume", "stop"}:
                coordinator.resume_automation()
                return command == "resume"
            try:
                payload = json.loads(command)
                action = HumanSurfaceAction(
                    action_type=HumanSurfaceActionType(payload["action_type"]),
                    target=ElementTarget.model_validate(payload["target"]) if "target" in payload else None,
                    destination=payload.get("destination"), value=payload.get("value"),
                    description="Explicit operator action")
                coordinator.perform_human_action(action)
            except Exception:
                print("Operator action failed; session remains paused.")
    return handle


def _load_artifact(path: str) -> CapabilityArtifact:
    return CapabilityArtifact.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _artifact_for_target(artifact: CapabilityArtifact, target: str) -> CapabilityArtifact:
    absolute_entry_point = target
    absolute_actions = []
    for action in artifact.actions:
        if isinstance(action, NavigateAction) and action.route.startswith("/"):
            action = action.model_copy(update={"route": urljoin(target, action.route)})
        absolute_actions.append(action)
    return CapabilityArtifact.model_validate(artifact.model_copy(update={"entry_point": absolute_entry_point, "actions": absolute_actions}).model_dump())


def _policy_for_target(target: str, artifact: CapabilityArtifact):
    origin = _origin(target)
    # Trusted demo deployment configuration is independent of generated artifacts.
    from automation.capabilities.models import ActionRisk
    from automation.policy.demo import approved_interactions
    interactions = approved_interactions()
    policy = SafetyPolicy(
        approved_interactions=interactions,
        allowed_post_routes=["/members/search"],
        denied_risks=[ActionRisk.IRREVERSIBLE] if artifact.safety_profile.risky_action_policy == "block" else [],
        allowed_targets=[AllowedTarget(origin=origin, route_prefixes=["/members", "/accounts"])],
        permitted_action_types=artifact.safety_profile.permitted_action_types,
    )
    return lambda surface: PolicyEnforcedSurfaceAdapter(surface, SafetyPolicyEvaluator(policy))


def _writer(path: str, run_id: str, artifact: CapabilityArtifact | None = None) -> JsonlEvidenceWriter:
    return JsonlEvidenceWriter(
        Path(path),
        SensitiveDataRedactor(RedactionPolicy(
            sensitive_field_names=["member_id", "authorization", "cookie", "token", "balance", "savings_balance", "outputs", "visible_text", "dialog_text", "value", "observed_state", "sanitized_current_state", "current_location", "location", "title", "reasoning_summary", "goal", "description", "debugging_summary"],
            sensitive_value_patterns=[r"Bearer\s+\S+", r"token=[^\s&]+"],
        )),
        run_id=run_id,
        capability_id=artifact.capability_id if artifact else None,
        artifact_schema_version=artifact.artifact_schema_version if artifact else None,
    )


def _origin(target: str) -> str:
    parsed_target = urlsplit(target)
    return f"{parsed_target.scheme}://{parsed_target.netloc}"


if __name__ == "__main__":
    main()