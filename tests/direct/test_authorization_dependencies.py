"""Controlled source/model and consumer views; genuine live flows are separate."""
import copy
import hashlib
import pytest
from conftest import canon, digest, open_packet, assess_packet


def raw_open(p, envelope):
    p['c'].open_record(envelope['request_id'], p['proposition'], envelope['target_time'], canon(p['manifest']), canon(envelope))


def test_unapproved_subject_capture_does_not_mutate_namespace(packet, direct_vm, direct_charlie):
    from genlayer import Address
    attacker = {**packet['envelope'], 'owner': direct_charlie.as_hex.lower(), 'request_id': 'attacker'}
    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert('CONSUMER_APPROVAL_REQUIRED'):
        raw_open(packet, attacker)
    assert packet['c'].get_subject_head(packet['consumer'], 'service') == ''
    assert packet['c'].get_request_state('attacker')['exists'] is False
    direct_vm.sender = packet['owner']
    open_packet(packet)
    assert packet['c'].get_subject_head(packet['consumer'], 'service') == 'request1'


@pytest.mark.parametrize('field,value', [('request_id', 'other'), ('owner', '0x'+'12'*20), ('parties', ['0x'+'12'*20]), ('generation', 2), ('deadline', '2030-12-31T00:00:00Z'), ('source_manifest_digest', '1'*64)])
def test_approval_must_match_entire_envelope(packet, direct_vm, field, value):
    packet['approval'] = canon({**packet['envelope'], field: value})
    with direct_vm.expect_revert('CONSUMER_APPROVAL_REQUIRED'):
        raw_open(packet, packet['envelope'])
    assert packet['c'].list_history('REQUEST', 0, 50) == []


def test_consumer_authorized_successor_recovers_quarantine_and_rotates_owner(packet, direct_vm, direct_charlie):
    from genlayer import Address
    open_packet(packet)
    packet['c'].quarantine('REQUEST', 'request1', digest('revoked'))
    successor = {**packet['envelope'], 'request_id': 'recovery', 'generation': 2, 'supersedes': 'request1', 'owner': direct_charlie.as_hex.lower()}
    direct_vm.sender = direct_charlie
    with direct_vm.expect_revert('CONSUMER_APPROVAL_REQUIRED'):
        raw_open(packet, successor)
    packet['approval'] = canon(successor)
    raw_open(packet, successor)
    assert packet['c'].get_subject_head(packet['consumer'], 'service') == 'recovery'
    assert packet['c'].get_interval_certificate('request1')['superseded_by'] == 'recovery'
    assert packet['c'].get_request_state('recovery')['envelope']['owner'] == successor['owner']


@pytest.mark.parametrize('controlling', ['exception', 'correction', 'unselected'])
def test_later_packet_dependency_controls_publication_bound(packet, direct_vm, controlling):
    from genlayer import gl
    later = copy.deepcopy(packet['record'])
    later.update(source_id='source2', subject_id='customer-exemption', url='https://evidence.example/later')
    raw = b'The named customer is exempt from the exclusion. Correction: the proposition applies.'
    later.update(raw_sha256=hashlib.sha256(raw).hexdigest(), byte_length=len(raw), spans=[{'span_id': 'exception', 'start': 0, 'end': len(raw), 'text': raw.decode()}])
    direct_vm._web_mocks.clear()
    direct_vm.mock_web(r'https://evidence.example/record', {'status': 200, 'body': packet['raw']})
    direct_vm.mock_web(r'https://evidence.example/later', {'status': 200, 'body': raw})
    packet['c'].observe_source(canon(later))
    direct_vm.warp('2029-12-20T00:00:00Z')
    gl.message_raw['datetime'] = direct_vm._datetime
    with direct_vm.prank(gl.message.contract_address):
        packet['c'].confirm_source('source2')
    packet['manifest']['records'].append('source2')
    packet['envelope']['source_manifest_digest'] = digest(packet['manifest'])
    if controlling != 'unselected':
        packet['output']['exceptions'] = [{'source_id': 'source2', 'span_id': 'exception', 'rule_id': 'meaning'}]
        packet['output']['flags'] = ['CORRECTION'] if controlling == 'correction' else []
    direct_vm._llm_mocks.clear()
    direct_vm.mock_llm(r'.*', canon(packet['output']))
    assess_packet(packet)
    assert direct_vm.run_validator() is True
    cert = packet['c'].get_interval_certificate('request1')['certificate']
    assert cert['lifecycle_status'] == 'CERTIFIED'
    later_upper = packet['c'].get_source('source2')['observed_upper']
    assert cert['first_publication_upper'] == later_upper
    assert [s['source_id'] for s in cert['publication_support']] == ['source1', 'source2']
    # Execute the unchanged production eligibility predicate with the result.
    import ast
    from pathlib import Path
    tree = ast.parse(Path('contracts/notice_gate.py').read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'DeprecationGate')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_eligible')
    namespace = {'MODE': 'NOTICE'}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), '<production eligibility>', 'exec'), namespace)
    from types import SimpleNamespace
    eligible = namespace['_eligible']
    assert eligible(SimpleNamespace(notice_seconds=30*86400), cert) is False
    earlier = {**cert, 'first_publication_upper': packet['c'].get_source('source1')['observed_upper']}
    assert eligible(SimpleNamespace(notice_seconds=30*86400), earlier) is (controlling != 'correction')
