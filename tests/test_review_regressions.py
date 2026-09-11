"""Regressions for the assessment review; no live model evidence is implied."""
from decimal import Decimal
from pathlib import Path
import json
import pytest
from automation.capabilities.models import CapabilityArtifact, ElementTarget
from automation.capabilities.runtime import validate_inputs, parse_outputs, condition_matches
from automation.cli import _artifact_for_target, _policy_for_target, _load_artifact
from automation.policy import SafetyPolicy, SafetyPolicyEvaluator, AllowedTarget
from automation.policy.models import PolicyActionRequest
from automation.surface.errors import SurfaceAdapterError, SurfaceTimeoutError, AmbiguousTargetError
from test_replay_runner import artifact, runner, ReplaySurface
from test_discovery_runner import request, FakeDiscoverySurface, FakeDecisionProvider, runner as discovery_runner, target
from automation.discovery.models import GoalAchievedDecision, ExtractTextDecision
from automation.intervention import HumanInterventionCoordinator
from test_intervention import HandoffSurface


@pytest.mark.parametrize('value', [12345, True, '12', 'abcde', None])
def test_invalid_invocation_does_not_touch_ui(value):
    surface = ReplaySurface()
    result = runner(surface).replay(artifact(), {'member_id': value})
    assert result.result_type == 'failed'
    assert result.failure_category == 'invalid_invocation'
    assert not surface.action_order


def test_default_is_validated_and_applied():
    p = artifact().inputs[0].model_copy(update={'default':'12345'})
    assert validate_inputs([p], {}) == {'member_id':'12345'}
    with pytest.raises(ValueError):
        validate_inputs([p.model_copy(update={'default':'bad'})], {})


@pytest.mark.parametrize('mutation', ['duplicate_input','wrong_source','wrong_parser','unknown_reference','literal_fill'])
def test_invalid_artifact_contract_rejected(mutation):
    payload = artifact().model_dump(mode='json')
    if mutation == 'duplicate_input': payload['inputs'] *= 2
    if mutation == 'wrong_source': payload['outputs'][0]['source_action_id'] = 'submit-search'
    if mutation == 'wrong_parser': payload['outputs'][0]['parser'] = 'raw_text'
    if mutation == 'unknown_reference': payload['actions'][1]['value_template'] = '${unknown}'
    if mutation == 'literal_fill': payload['actions'][1]['value_template'] = 'secret ${member_id}'
    with pytest.raises(ValueError): CapabilityArtifact.model_validate(payload)


@pytest.mark.parametrize('text', ['NaN', '$1,24.50', '$oops', 'Infinity'])
def test_invalid_currency_rejected(text):
    with pytest.raises(ValueError): parse_outputs(artifact().outputs, {'savings_balance':text})


def test_relative_routes_are_preserved():
    flow = artifact()
    flow.actions[0].route = '/members/other'
    resolved = _artifact_for_target(flow, 'https://bank.example.test/members/search')
    assert resolved.actions[0].route == 'https://bank.example.test/members/other'


def test_current_origin_unknown_control_and_path_prefix_are_denied():
    evaluator = SafetyPolicyEvaluator(SafetyPolicy(allowed_targets=[AllowedTarget(origin='https://safe.test', route_prefixes=['/members'])], permitted_action_types=['click','navigate']))
    assert evaluator.evaluate(PolicyActionRequest(action_type='click',risk='read_only'), 'https://evil.test/members').decision == 'denied'
    assert evaluator.evaluate(PolicyActionRequest(action_type='click',risk='read_only',target=target('Confirm')), 'https://safe.test/members').decision == 'denied'
    assert not evaluator.allows_request('https://safe.test/members-evil')
    assert not evaluator.allows_request('https://safe.test/members/%2e%2e/accounts')
    assert not evaluator.allows_request('https://safe.test/members', 'POST')


def test_failure_capture_cannot_mask_original_error():
    class Broken(ReplaySurface):
        def observe(self): raise SurfaceAdapterError('secret')
        def capture_evidence(self, destination): raise SurfaceAdapterError('secret')
    result = runner(Broken(), evidence_directory=Path('/tmp')).replay(artifact(), {'member_id':'12345'})
    assert result.result_type == 'failed'
    assert result.observed_state == 'surface unavailable'
    assert 'secret' not in result.model_dump_json()


def test_evidence_failure_does_not_break_handoff_ownership():
    class BrokenEvidence(HandoffSurface):
        def capture_evidence(self, destination): raise SurfaceAdapterError('secret')
    surface = BrokenEvidence()
    coordinator = HumanInterventionCoordinator(surface, evidence_directory=Path('/tmp'))
    request = coordinator.request_intervention('member.lookup','goal','step',0,'stuck')
    assert coordinator.control_owner.value == 'human'
    assert request.screenshot_evidence_reference is None
    coordinator.resume_automation()
    assert coordinator.control_owner.value == 'automation'


def test_discovery_cannot_publish_without_required_output():
    result = discovery_runner(FakeDecisionProvider([GoalAchievedDecision(reasoning_summary='done')]), FakeDiscoverySurface()).run(request())
    assert result.artifact is None


def test_discovery_verifies_checkpoint_instead_of_model_assertion():
    req = request()
    req.artifact_definition.success_checkpoint.conditions = [
        {'condition_type':'url_matches','pattern':'/never-reached$'}]
    from automation.capabilities.models import SuccessCheckpoint
    req.artifact_definition.success_checkpoint = SuccessCheckpoint(description='wrong page',conditions=req.artifact_definition.success_checkpoint.conditions)
    provider = FakeDecisionProvider([ExtractTextDecision(reasoning_summary='read', target=target('Savings balance'), output_name='savings_balance'),GoalAchievedDecision(reasoning_summary='done')])
    result = discovery_runner(provider, FakeDiscoverySurface()).run(req)
    assert result.artifact is None


def test_ambiguous_checkpoint_is_hard_failure_not_missing():
    class Ambiguous(ReplaySurface):
        def wait_for_state(self, condition, timeout_seconds): raise AmbiguousTargetError('ambiguous')
    result = runner(Ambiguous()).replay(artifact(), {'member_id':'12345'})
    assert result.result_type == 'failed'


def test_typed_read_timeout_is_retried_and_recorded(tmp_path):
    from automation.evidence import JsonlEvidenceWriter, SensitiveDataRedactor, RedactionPolicy
    class SlowRead(ReplaySurface):
        attempts = 0
        def read_text_or_value(self, target):
            if target.description == 'Savings balance':
                self.attempts += 1
                if self.attempts == 1: raise SurfaceTimeoutError('timeout')
            return super().read_text_or_value(target)
    surface = SlowRead()
    replay = runner(surface)
    evidence = tmp_path/'run.jsonl'
    replay._evidence_writer = JsonlEvidenceWriter(evidence,SensitiveDataRedactor(RedactionPolicy()))
    result = replay.replay(artifact(),{'member_id':'12345'})
    assert result.result_type == 'succeeded'
    assert surface.attempts == 2
    events = [json.loads(line) for line in evidence.read_text().splitlines()]
    assert len([event for event in events if event['event_type']=='recovery_attempt']) == 1
    assert len({event['run_id'] for event in events}) == 1
    assert '12345' not in evidence.read_text()
    assert '1,240.50' not in evidence.read_text()


def test_output_extraction_parse_failure_is_not_success():
    class InvalidBalance(ReplaySurface):
        def read_text_or_value(self, target):
            if target.description == 'Savings balance': return '$1,24.50'
            return super().read_text_or_value(target)
    assert runner(InvalidBalance()).replay(artifact(),{'member_id':'12345'}).result_type == 'failed'
