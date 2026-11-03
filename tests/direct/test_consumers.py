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
    heads = {}
    opened = {}
    emitted = []
    delivery = {}
    def hook(vm, data):
        if 'CallContract' in data:
            call = data['CallContract']['calldata']
            method = call['method']
            value = heads.get(call['args'][1], '') if method == 'get_subject_head' else {'exists': call['args'][0] in opened} if method == 'get_request_state' else delivery
            return b'\0' + gl.calldata.encode(value)
        if 'PostMessage' in data:
            emitted.append(data['PostMessage'])
            return b''
        return None
    direct_vm._gl_call_hook = hook
    e = {'request_id': 'r1', 'owner': Address(direct_alice).as_hex.lower(), 'parties': [], 'policy_id': 'policy', 'policy_revision': 1, 'subject_id': 'subject', 'subject_digest': digest('claim'), 'source_manifest_digest': digest('manifest'), 'consumer': gl.message.contract_address.as_hex.lower(), 'consequence_digest': cfg['consequence_digest'], 'generation': 1, 'deadline': '2031-01-01T00:00:00Z', 'target_time': '2030-01-01T00:00:00Z', 'supersedes': ''}
    c.approve_request(canon(e))
    heads['subject'] = 'r1'
    opened['r1'] = e
    cert = {**e, 'request_binding_digest': digest(e), 'lifecycle_status': 'CERTIFIED', 'unresolved_flags': [], 'coverage': {'complete_packet': True}, 'intervals': {'EFFECTIVE': {'lower': 100, 'upper': None}}, 'first_publication_upper': 70, 'applies_at_target': {'EFFECTIVE': True, 'OCCURRENCE': True}}
    payload = {'resolver': resolver.as_hex.lower(), 'consumer': e['consumer'], 'operation_id': 'op1', 'certificate': cert}
    delivery.update(consumer=e['consumer'], request_id='r1', payload_digest=digest(payload), valid=True)
    return {'c': c, 'e': e, 'payload': payload, 'delivery': delivery, 'emitted': emitted, 'resolver': direct_bob, 'owner': direct_alice, 'notice': notice, 'heads': heads, 'opened': opened}


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


def test_new_delivery_id_preserves_executed_consequence(adapter, direct_vm):
    receive(adapter, direct_vm)
    direct_vm.sender = adapter['owner']
    adapter['c'].execute('subject', 'first-action')
    before = adapter['c'].get_state('subject')
    assert before['active'] is True and before['executed'] is True
    adapter['payload']['operation_id'] = 'second-delivery'
    receive(adapter, direct_vm)
    state = adapter['c'].get_state('subject')
    assert state['active'] is True and state['executed'] is True
    assert adapter['c'].get_receipt('op1')['executed'] is True
    assert adapter['c'].get_receipt('second-delivery')['executed'] is True
    direct_vm.sender = adapter['owner']
    with direct_vm.expect_revert('CONSEQUENCE_ALREADY_EXECUTED'):
        adapter['c'].execute('subject', 'second-action')


def test_unopened_successor_can_be_cancelled_and_replaced_without_reviving_old_permission(adapter, direct_vm):
    receive(adapter, direct_vm)
    direct_vm.sender = adapter['owner']
    adapter['c'].execute('subject', 'first-action')
    bad = {**adapter['e'], 'request_id': 'bad', 'generation': 2, 'supersedes': 'r1', 'source_manifest_digest': '1'*64}
    adapter['c'].approve_request(canon(bad))
    assert adapter['c'].get_state('subject')['permitted'] is False
    corrected = {**bad, 'source_manifest_digest': adapter['e']['source_manifest_digest']}
    with direct_vm.expect_revert('APPROVAL_REUSE'):
        adapter['c'].approve_request(canon(corrected))
    too_far = {**bad, 'request_id': 'g3', 'generation': 3, 'supersedes': 'bad'}
    with direct_vm.expect_revert('PREDECESSOR_NOT_OPEN'):
        adapter['c'].approve_request(canon(too_far))
    adapter['c'].cancel_request('bad')
    adapter['c'].cancel_request('bad')
    assert adapter['c'].get_request_approval('bad') == ''
    assert adapter['c'].get_state('subject')['permitted'] is False
    with direct_vm.expect_revert('APPROVAL_CANCELLED'):
        adapter['c'].approve_request(canon(bad))
    # Delayed old or cancelled callbacks must not clear the recovery restriction.
    adapter['payload']['operation_id'] = 'delayed-old'
    receive(adapter, direct_vm)
    assert adapter['c'].get_state('subject')['permitted'] is False
    adapter['payload']['certificate'] = {**adapter['payload']['certificate'], **bad, 'request_binding_digest': digest(bad)}
    adapter['payload']['operation_id'] = 'delayed-cancelled'
    adapter['delivery']['request_id'] = 'bad'
    receive(adapter, direct_vm)
    assert adapter['c'].get_receipt('delayed-cancelled')['acknowledgement'] == 'STALE'
    assert adapter['c'].get_state('subject')['permitted'] is False
    direct_vm.sender = adapter['owner']
    replacement = {**corrected, 'request_id': 'replacement'}
    adapter['c'].approve_request(canon(replacement))
    adapter['heads']['subject'] = 'replacement'
    adapter['opened']['replacement'] = replacement
    adapter['payload']['certificate'] = {**adapter['payload']['certificate'], **replacement, 'request_binding_digest': digest(replacement)}
    adapter['payload']['operation_id'] = 'recovered'
    adapter['delivery']['request_id'] = 'replacement'
    receive(adapter, direct_vm)
    assert adapter['c'].get_state('subject')['permitted'] is True
    assert adapter['c'].get_state('subject')['executed'] is False
    direct_vm.sender = adapter['owner']
    adapter['c'].execute('subject', 'generation-two-action')
    with direct_vm.expect_revert('REQUEST_ALREADY_OPEN'):
        adapter['c'].cancel_request('replacement')


def test_first_unopened_approval_cancellation_keeps_namespace_reusable(adapter, direct_vm):
    c = adapter['c']
    pending = {**adapter['e'], 'request_id': 'first-pending', 'subject_id': 'new-subject'}
    c.approve_request(canon(pending))
    assert c.get_request_approval(pending['request_id']) == canon(pending)
    with direct_vm.prank(adapter['resolver']):
        with direct_vm.expect_revert('OWNER_ONLY'):
            c.cancel_request(pending['request_id'])
    c.cancel_request(pending['request_id'])
    replacement = {**pending, 'request_id': 'first-replacement'}
    c.approve_request(canon(replacement))
    assert c.get_request_approval(replacement['request_id']) == canon(replacement)


def test_cancellation_reconciles_against_actual_resolver_head(adapter, direct_vm):
    pending = {**adapter['e'], 'request_id': 'pending', 'generation': 2, 'supersedes': 'r1'}
    adapter['c'].approve_request(canon(pending))
    adapter['heads']['subject'] = 'unexpected'
    with direct_vm.expect_revert('RESOLVER_GENERATION_CONFLICT'):
        adapter['c'].cancel_request('pending')
    assert adapter['c'].get_request_approval('pending') == canon(pending)
