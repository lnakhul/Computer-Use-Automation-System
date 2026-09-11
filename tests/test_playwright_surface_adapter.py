from threading import Thread
from pathlib import Path

import pytest
from werkzeug.serving import make_server

from automation.capabilities.models import ElementTarget
from automation.demo_app import create_demo_application
from automation.surface.errors import SessionControlError, TargetResolutionError, AmbiguousTargetError
from automation.surface.playwright_adapter import PlaywrightBrowserSurfaceAdapter

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def demo_server():
    server = make_server("127.0.0.1", 0, create_demo_application())
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server_thread.join(timeout=2)


def member_id_target() -> ElementTarget:
    return ElementTarget(
        description="Member ID field",
        candidates=[
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
    )


def test_adapter_operates_on_demo_app_and_records_fallback_metadata(demo_server: str, tmp_path: Path) -> None:
    with playwright.sync_playwright() as browser_runtime:
        browser = browser_runtime.chromium.launch(channel="chrome")
        page = browser.new_page()
        adapter = PlaywrightBrowserSurfaceAdapter(page)

        adapter.navigate(f"{demo_server}/members/search")
        adapter.enter_text(member_id_target(), "12345")
        search_button = ElementTarget(
            description="Search button",
            candidates=[
                {
                    "priority": 1,
                    "strategy": {"kind": "role", "role": "button", "accessible_name": "Search"},
                }
            ],
        )
        adapter.click(search_button)
        page.wait_for_url("**/members/12345")

        balance_target = ElementTarget(
            description="Savings balance value",
            candidates=[
                {
                    "priority": 1,
                    "strategy": {"kind": "label", "label": "Savings balance"},
                }
            ],
        )
        assert adapter.read_text_or_value(balance_target) == "$1,240.50"
        assert adapter.last_resolution.selected_priority == 1
        assert adapter.last_resolution.strategy_kind == "label"
        observation = adapter.observe()
        assert observation.current_location.endswith("/members/12345")
        assert "Member Details" in observation.visible_text

        evidence_path = adapter.capture_evidence(tmp_path / "member-detail.png")
        assert evidence_path.exists()
        browser.close()


def test_adapter_requires_unique_target_resolution(demo_server: str) -> None:
    with playwright.sync_playwright() as browser_runtime:
        browser = browser_runtime.chromium.launch(channel="chrome")
        page = browser.new_page()
        adapter = PlaywrightBrowserSurfaceAdapter(page)
        adapter.navigate(f"{demo_server}/members/search")

        ambiguous_target = ElementTarget(
            description="Ambiguous text",
            candidates=[
                {
                    "priority": 1,
                    "strategy": {"kind": "text", "text": "Member", "exact": False},
                }
            ],
        )
        with pytest.raises(AmbiguousTargetError):
            adapter.resolve_recorded_target(ambiguous_target)
        browser.close()


def test_adapter_transfers_and_restores_same_live_session(demo_server: str) -> None:
    with playwright.sync_playwright() as browser_runtime:
        browser = browser_runtime.chromium.launch(channel="chrome")
        page = browser.new_page()
        adapter = PlaywrightBrowserSurfaceAdapter(page)
        adapter.navigate(f"{demo_server}/members/search")

        human_session = adapter.expose_live_session()
        assert human_session.control_owner == "human"
        with pytest.raises(SessionControlError):
            adapter.observe()

        resumed_session = adapter.resume_live_session(human_session.session_id)
        assert resumed_session.session_id == human_session.session_id
        assert resumed_session.control_owner == "automation"
        assert adapter.observe().current_location.endswith("/members/search")
        browser.close()

def test_delayed_target_text_hidden_and_ambiguous_fallback():
    from automation.capabilities.models import ElementVisibleCondition, TextContainsCondition
    from automation.surface.errors import SurfaceTimeoutError, AmbiguousTargetError
    from automation.capabilities.runtime import condition_matches
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel='chrome')
        page = browser.new_page()
        adapter = PlaywrightBrowserSurfaceAdapter(page)
        page.set_content('<body><button>A</button><button>A</button><button>B</button><div hidden id="hidden">Ready</div><script>setTimeout(()=>{let e=document.createElement("p");e.id="later";e.textContent="Loading";document.body.append(e);setTimeout(()=>e.textContent="Ready",100)},100)</script></body>')
        delayed = ElementTarget(description='Delayed status',candidates=[{'priority':1,'strategy':{'kind':'css','selector':'#later'}}])
        adapter.wait_for_state(TextContainsCondition(target=delayed,expected_text='Ready'), 2)
        hidden = ElementTarget(description='Hidden status',candidates=[{'priority':1,'strategy':{'kind':'css','selector':'#hidden'}}])
        assert not condition_matches(adapter,ElementVisibleCondition(target=hidden),{}, {})
        ambiguous = ElementTarget(description='Ambiguous',candidates=[{'priority':1,'strategy':{'kind':'text','text':'A'}},{'priority':2,'strategy':{'kind':'text','text':'B'}}])
        with pytest.raises(AmbiguousTargetError): adapter.click(ambiguous)
        adapter.expose_live_session()
        with pytest.raises(SessionControlError): adapter.wait_for_state(ElementVisibleCondition(target=delayed),1)
        browser.close()


def test_real_replay_and_not_found(demo_server, tmp_path):
    from decimal import Decimal
    from automation.cli import _load_artifact, _artifact_for_target, _policy_for_target
    from automation.replay import CapabilityReplayRunner
    artifact = _artifact_for_target(_load_artifact('examples/member_savings_balance.json'),demo_server+'/members/search')
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel='chrome')
        page = browser.new_page(service_workers='block')
        adapter = PlaywrightBrowserSurfaceAdapter(page)
        runner = CapabilityReplayRunner(adapter,_policy_for_target(demo_server+'/members/search',artifact)(adapter),evidence_directory=tmp_path)
        assert runner.replay(artifact,{'member_id':'12345'}).outputs == {'savings_balance':Decimal('1240.50')}
        assert runner.replay(artifact,{'member_id':'67890'}).outputs == {'savings_balance':Decimal('85.00')}
        assert runner.replay(artifact,{'member_id':'99999'}).outcome_code == 'MEMBER_NOT_FOUND'
        browser.close()


def test_redirect_and_post_are_blocked_before_destination_receives_request(demo_server):
    from automation.policy import SafetyPolicy, AllowedTarget, SafetyPolicyEvaluator, PolicyEnforcedSurfaceAdapter
    from automation.capabilities.models import NavigateAction
    from automation.surface.errors import SurfaceAdapterError
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel='chrome')
        page = browser.new_page(service_workers='block')
        adapter = PlaywrightBrowserSurfaceAdapter(page)
        policy = SafetyPolicy(allowed_targets=[AllowedTarget(origin=demo_server,route_prefixes=['/members/search'])],permitted_action_types=['navigate'])
        facade = PolicyEnforcedSurfaceAdapter(adapter,SafetyPolicyEvaluator(policy))
        facade.execute_action(NavigateAction(action_id='open',description='open',route=demo_server+'/members/search'))
        # Browser-initiated requests are guarded even outside execute_action.
        received = []
        page.on('response',lambda response: received.append(response.url))
        with pytest.raises(playwright.Error): page.goto(demo_server+'/members/12345')
        assert not any('/members/12345' in url for url in received)
        browser.close()


def test_cli_discovery_with_stub_provider_then_replay_and_not_found(demo_server, tmp_path, monkeypatch, capsys):
    # Explicitly a stub-provider regression, NOT genuine LLM discovery evidence.
    import sys
    from automation.cli import main, _load_artifact
    from automation.discovery.models import FillDecision, ClickDecision, ExtractTextDecision, GoalAchievedDecision
    import automation.discovery.openai_provider as provider_module
    example = _load_artifact('examples/member_savings_balance.json')
    class StubProvider:
        def __init__(self, *args):
            self.decisions = iter([
                FillDecision(reasoning_summary='fill',target=example.actions[1].target,text='12345',parameter_name='member_id'),
                ClickDecision(reasoning_summary='search',target=example.actions[2].target),
                ExtractTextDecision(reasoning_summary='read',target=example.actions[4].target,output_name='savings_balance'),
                GoalAchievedDecision(reasoning_summary='done')])
        def decide(self, goal, observation): return next(self.decisions)
    monkeypatch.setattr(provider_module,'OpenAICompatibleDecisionProvider',StubProvider)
    monkeypatch.setenv('OPENAI_API_KEY','test-only-stub')
    output = tmp_path/'discovered.json'
    monkeypatch.setattr(sys,'argv',['automation','discover','--goal','read member 12345 balance','--member-id','12345','--target',demo_server+'/members/search','--output',str(output),'--evidence',str(tmp_path/'discovery.jsonl')])
    main()
    assert output.exists()
    assert '12345' not in output.read_text()
    capsys.readouterr()
    monkeypatch.setattr(sys,'argv',['automation','replay',str(output),'--member-id','67890','--target',demo_server+'/members/search','--evidence',str(tmp_path/'replay.jsonl'),'--evidence-directory',str(tmp_path/'failures')])
    main()
    import json
    assert json.loads(capsys.readouterr().out)['outputs']['savings_balance'] == '85.00'
    monkeypatch.setattr(sys,'argv',['automation','replay-not-found',str(output),'--target',demo_server+'/members/search','--evidence',str(tmp_path/'missing.jsonl'),'--evidence-directory',str(tmp_path/'failures')])
    main()
    assert json.loads(capsys.readouterr().out)['outcome_code'] == 'MEMBER_NOT_FOUND'


def test_replay_routes_dialog_to_same_session_and_resumes(demo_server, tmp_path):
    from automation.cli import _load_artifact, _artifact_for_target, _policy_for_target
    from automation.replay import CapabilityReplayRunner
    from automation.intervention import HumanInterventionCoordinator
    from automation.surface.contracts import HumanSurfaceAction, HumanSurfaceActionType
    artifact = _artifact_for_target(_load_artifact('examples/member_savings_balance.json'),demo_server+'/members/search')
    with playwright.sync_playwright() as runtime:
        browser = runtime.chromium.launch(channel='chrome')
        page = browser.new_page(service_workers='block')
        class DialogSurface(PlaywrightBrowserSurfaceAdapter):
            def navigate(self,destination):
                super().navigate(destination)
                page.evaluate("()=>{let d=document.createElement('div');d.setAttribute('role','dialog');d.innerHTML='<button onclick=\"this.parentElement.remove()\">Dismiss</button>';document.body.append(d)}")
        adapter = DialogSurface(page)
        coordinator = HumanInterventionCoordinator(adapter,evidence_directory=tmp_path)
        sessions=[]
        def operator(*context):
            request = coordinator.request_intervention(*context)
            sessions.append(request.session_id)
            with pytest.raises(SessionControlError): adapter.observe()
            coordinator.perform_human_action(HumanSurfaceAction(HumanSurfaceActionType.CLICK,target=ElementTarget(description='Dismiss',candidates=[{'priority':1,'strategy':{'kind':'role','role':'button','accessible_name':'Dismiss'}}])))
            event = coordinator.resume_automation()
            assert event.session_id == request.session_id
            return True
        replay = CapabilityReplayRunner(adapter,_policy_for_target(demo_server+'/members/search',artifact)(adapter),intervention_handler=operator)
        assert replay.replay(artifact,{'member_id':'12345'}).result_type == 'succeeded'
        assert len(sessions) == 1
        assert adapter.observe().current_location.endswith('/members/12345')
        browser.close()
