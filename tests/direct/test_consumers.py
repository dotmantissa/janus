"""Adapter fault probes use a synthetic source view, never claim network finality."""
import copy
import json
import pytest
from conftest import canon, digest


@pytest.fixture(params=['notice_gate.py', 'event_registry.py'])
def adapter(request, direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    from gltest.direct.sdk_loader import setup_sdk_paths
    from pathlib import Path
    setup_sdk_paths(Path('contracts/' + request.param))
    # The deploy fixture installs the SDK/message context before addresses are imported.
    from genlayer import Address
    resolver = Address(direct_bob)
    notice = request.param == 'notice_gate.py'
    c = direct_deploy('contracts/' + request.param, resolver, 'policy', 1, 30 if notice else 0)
    from genlayer import gl, Address
    cfg = c.get_configuration()
    e = {'request_id': 'r1', 'owner': Address(direct_alice).as_hex.lower(), 'parties': [], 'policy_id': 'policy', 'policy_revision': 1, 'subject_id': 'subject', 'subject_digest': digest('claim'), 'source_manifest_digest': digest('manifest'), 'consumer': gl.message.contract_address.as_hex.lower(), 'consequence_digest': cfg['consequence_digest'], 'generation': 1, 'deadline': '2031-01-01T00:00:00Z', 'target_time': '2030-01-01T00:00:00Z', 'supersedes': ''}
    c.approve_request(canon(e))
    cert = {**e, 'request_binding_digest': digest(e), 'lifecycle_status': 'CERTIFIED', 'unresolved_flags': [], 'coverage': {'complete_packet': True}, 'intervals': {'EFFECTIVE': {'lower': 100, 'upper': None}}, 'first_publication_upper': 70, 'applies_at_target': {'EFFECTIVE': True, 'OCCURRENCE': True}}
    payload = {'resolver': resolver.as_hex.lower(), 'consumer': e['consumer'], 'operation_id': 'op1', 'certificate': cert}
    delivery = {'consumer': e['consumer'], 'request_id': 'r1', 'payload_digest': digest(payload), 'valid': True}
    emitted = []
    def hook(vm, data):
        from genlayer import gl
        if 'CallContract' in data:
            return b'\0' + gl.calldata.encode(delivery)
        if 'PostMessage' in data:
            emitted.append(data['PostMessage'])
            return b''
        return None
    direct_vm._gl_call_hook = hook
    return {'c': c, 'e': e, 'payload': payload, 'delivery': delivery, 'emitted': emitted, 'resolver': direct_bob, 'owner': direct_alice, 'notice': notice}


def receive(p, vm):
    vm.sender = p['resolver']
    p['delivery']['payload_digest'] = digest(p['payload'])
    p['c'].receive_certificate(canon(p['payload']))


def test_authenticated_delivery_and_action(adapter, direct_vm):
    receive(adapter, direct_vm)
    assert adapter['c'].get_receipt('op1')['acknowledgement'] == 'APPLIED'
    assert adapter['emitted'][-1]['on'] == 'finalized'
    direct_vm.sender = adapter['owner']
    adapter['c'].execute('subject', 'action')
    adapter['c'].execute('subject', 'action')
    assert adapter['c'].get_receipt('op1')['executed'] is True
    receive(adapter, direct_vm)
    assert adapter['c'].list_receipts(0, 50) == ['op1']


def test_unresolved_blocks_even_previous_permission(adapter, direct_vm):
    adapter['payload']['certificate']['lifecycle_status'] = 'UNKNOWN'
    adapter['payload']['certificate']['unresolved_flags'] = ['INCOMPLETE']
    receive(adapter, direct_vm)
    assert adapter['c'].get_receipt('op1')['acknowledgement'] == 'BLOCKED'
    direct_vm.sender = adapter['owner']
    with direct_vm.expect_revert('ACTION_BLOCKED'):
        adapter['c'].execute('subject', 'action')


def test_sender_binding_and_conflicting_operation(adapter, direct_vm):
    with direct_vm.expect_revert('RESOLVER_ONLY'):
        adapter['c'].receive_certificate(canon(adapter['payload']))
    receive(adapter, direct_vm)
    adapter['payload']['certificate']['first_publication_upper'] = 69
    with direct_vm.expect_revert('OPERATION_REUSE'):
        receive(adapter, direct_vm)


def test_stale_and_reordered_callback_cannot_clear_new_restriction(adapter, direct_vm):
    receive(adapter, direct_vm)
    direct_vm.sender = adapter['owner']
    e2 = copy.deepcopy(adapter['e'])
    e2.update(request_id='r2', generation=2, supersedes='r1')
    adapter['c'].approve_request(canon(e2))
    assert adapter['c'].get_state('subject')['permitted'] is False
    receive(adapter, direct_vm)
    assert adapter['c'].get_state('subject')['permitted'] is False
    adapter['payload']['operation_id'] = 'old-reordered'
    receive(adapter, direct_vm)
    assert adapter['c'].get_receipt('old-reordered')['acknowledgement'] == 'STALE'
    assert adapter['c'].get_state('subject')['permitted'] is False


def test_action_time_quarantine_check(adapter, direct_vm):
    receive(adapter, direct_vm)
    adapter['delivery']['valid'] = False
    direct_vm.sender = adapter['owner']
    assert adapter['c'].get_state('subject')['unresolved'] is True
    with direct_vm.expect_revert('ACTION_BLOCKED'):
        adapter['c'].execute('subject', 'action')


def test_notice_inclusive_upper_boundary_and_event_target(adapter, direct_vm):
    cert = adapter['payload']['certificate']
    if adapter['notice']:
        cert['first_publication_upper'] = 71
    else:
        cert['applies_at_target']['OCCURRENCE'] = False
    receive(adapter, direct_vm)
    assert adapter['c'].get_receipt('op1')['acknowledgement'] == 'BLOCKED'


def test_no_positive_action_without_finalized_callback(adapter, direct_vm):
    assert adapter['c'].get_state('subject')['permitted'] is False
    with direct_vm.expect_revert('ACTION_BLOCKED'):
        adapter['c'].execute('subject', 'action')
