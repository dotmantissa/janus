"""Synthetic finalized-message probes; network finality is verified separately."""
import copy

import pytest

from conftest import canon, digest, open_packet


def pending_source(packet):
    record = copy.deepcopy(packet['record'])
    record.update(source_id='pending', subject_id='pending')
    packet['c'].observe_source(canon(record))
    return record


def test_only_finalized_self_callback_establishes_availability(packet, direct_vm):
    from genlayer import gl

    pending_source(packet)
    c = packet['c']
    source = c.get_source('pending')
    assert source['observed_upper'] is None
    assert source['confirmed'] is False
    assert source['valid'] is False
    with direct_vm.expect_revert('FINALIZED_SELF_MESSAGE_ONLY'):
        c.confirm_source('pending')

    packet['manifest']['records'] = ['pending']
    packet['envelope']['source_manifest_digest'] = digest(packet['manifest'])
    with direct_vm.expect_revert('SOURCE_INACTIVE'):
        open_packet(packet)

    # The callback is created after parent finality, later than submission time.
    direct_vm.warp('2026-11-02T12:00:00Z')
    gl.message_raw['datetime'] = direct_vm._datetime
    with direct_vm.prank(gl.message.contract_address):
        c.confirm_source('pending')
    upper = c.get_source('pending')['observed_upper']
    assert upper == 1793620800
    assert c.get_source('pending')['valid'] is True
    open_packet(packet)

    direct_vm.warp('2026-11-03T12:00:00Z')
    gl.message_raw['datetime'] = direct_vm._datetime
    with direct_vm.prank(gl.message.contract_address):
        c.confirm_source('pending')
    assert c.get_source('pending')['observed_upper'] == upper


def test_confirmation_retries_are_principal_only_bounded_and_finalized(packet, direct_vm, direct_bob):
    emitted = []

    def hook(vm, data):
        if 'PostMessage' in data:
            emitted.append(data['PostMessage'])
            return b''
        return None

    direct_vm._gl_call_hook = hook
    pending_source(packet)
    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert('PRINCIPAL_ONLY'):
            packet['c'].retry_source_confirmation('pending')
    packet['c'].retry_source_confirmation('pending')
    packet['c'].retry_source_confirmation('pending')
    with direct_vm.expect_revert('CONFIRMATION_RETRY_EXHAUSTED'):
        packet['c'].retry_source_confirmation('pending')
    assert len(emitted) == 3
    assert all(message['on'] == 'finalized' for message in emitted)
    assert packet['c'].get_source('pending')['confirmed'] is False


@pytest.mark.parametrize('url', [
    'https://evidence.example/../outside',
    'https://evidence.example/./record',
    'https://evidence.example/%2e%2e/outside',
    'https://evidence.example/record?redirect=outside',
    'https://evidence.example/record#fragment',
    'https://evidence.example/record\\outside',
])
def test_source_url_cannot_escape_registered_channel(packet, direct_vm, url):
    record = copy.deepcopy(packet['record'])
    record.update(source_id='invalid', subject_id='invalid', url=url)
    with direct_vm.expect_revert('SOURCE_CHANNEL'):
        packet['c'].observe_source(canon(record))


def test_authority_subject_pairs_cannot_collide(packet, direct_vm):
    from genlayer import Address

    c = packet['c']
    first = copy.deepcopy(packet['record'])
    first.update(source_id='first', subject_id='branch:document')
    c.observe_source(canon(first))
    config = {'channel': 'PUBLIC_SIGNED_OBSERVATION', 'url_prefix': 'https://evidence.example/',
              'scope': 'service', 'public_evidence_url': 'https://evidence.example/principal'}
    c.register_authority('issuer:branch', Address(packet['owner']), canon(config))
    c.accept_authority('issuer:branch')
    second = copy.deepcopy(packet['record'])
    second.update(source_id='second', authority_id='issuer:branch')
    c.observe_source(canon(second))
    assert c.get_source('first')['superseded_by'] == ''
    assert c.get_source('second')['manifest']['revision'] == 1
