"""Offline journal fault probes; these fixtures make no network transactions."""
import json
import base64
from genlayer_py.abi import calldata
from types import SimpleNamespace

import pytest

from scripts import studio


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setattr(studio, 'ROOT', tmp_path)
    monkeypatch.setenv('JANUS_DEPLOYER_KEY', 'offline-fixture')
    monkeypatch.setattr(studio.Account, 'from_key', lambda _: SimpleNamespace(address='0x1111'))
    monkeypatch.setattr(studio, 'create_client', lambda **_: SimpleNamespace())
    monkeypatch.setattr(studio, 'tx_execution_succeeded', lambda receipt: receipt['execution_success'])
    return studio.Studio(journal='offline')


def test_submission_is_journaled_before_polling_and_resumed(journal):
    def interrupted(tx, **kwargs):
        assert json.loads(journal.journal_path.read_text())['operation']['tx'] == tx
        raise TimeoutError('synthetic interrupted poll')

    journal.client.wait_for_transaction_receipt = interrupted
    with pytest.raises(TimeoutError):
        journal.transaction('operation', {'address': '0x3333', 'method': 'work', 'args': [1]}, lambda: 'tx-offline')

    journal.client.wait_for_transaction_receipt = lambda *a, **k: parent_receipt()

    def resubmit():
        pytest.fail('A journaled transaction must not be resubmitted')

    journal.transaction('operation', {'address': '0x3333', 'method': 'work', 'args': [1]}, resubmit)
    with pytest.raises(AssertionError, match='conflicts'):
        journal.transaction('operation', {'address': '0x3333', 'method': 'work', 'args': [2]}, resubmit)


@pytest.mark.parametrize('status,success', [('ACCEPTED', True), ('FINALIZED', False)])
def test_cached_receipt_requires_finality_and_execution_success(journal, status, success):
    spec = {'address': '0x3333', 'method': 'work', 'args': [1]}
    journal.journal['operation'] = {'binding': studio.digest(spec), 'tx': 'tx-offline'}
    studio.atomic(journal.folder / 'operation.json', {**parent_receipt(), 'status_name': status, 'execution_success': success})
    with pytest.raises(AssertionError):
        journal.transaction('operation', spec, lambda: pytest.fail('cached transaction resubmitted'))


def test_journal_rejects_another_signer(journal, monkeypatch):
    monkeypatch.setattr(studio.Account, 'from_key', lambda _: SimpleNamespace(address='0x2222'))
    with pytest.raises(AssertionError, match='another account'):
        studio.Studio(journal='offline')


def test_journal_directory_cannot_escape_evidence(journal):
    with pytest.raises(ValueError, match='directory name'):
        studio.Studio(journal='../outside')


def parent_receipt():
    return {'hash': 'tx-offline', 'from_address': '0x1111', 'to_address': '0x3333',
            'type': 2, 'triggered_by': None, 'status_name': 'FINALIZED', 'execution_success': True,
            'data': {'calldata': {'base64': base64.b64encode(bytes(calldata.encode({'method': 'work', 'args': [1]}))).decode()}}}


def child_evidence():
    encoded = base64.b64encode(bytes(calldata.encode({'method': 'receive', 'args': ['packet']}))).decode()
    parent = {**parent_receipt(), 'triggered_transactions': ['tx-child'],
              'consensus_data': {'leader_receipt': [{'pending_transactions': [
                  {'on': 'finalized', 'address': '0x4444', 'value': 0, 'calldata': encoded}]}]}}
    child = {'hash': 'tx-child', 'triggered_by': 'tx-offline', 'from_address': '0x3333',
             'to_address': '0x4444', 'value': 0, 'type': 2, 'triggered_on': 'finalized',
             'status_name': 'FINALIZED', 'execution_success': True, 'triggered_transactions': [],
             'data': {'calldata': {'base64': encoded}}}
    return parent, child


def test_finalized_child_receipts_are_reused_and_checked(journal):
    parent, child = child_evidence()
    studio.atomic(journal.folder / 'child-tx-child.json', child)
    journal.client.wait_for_transaction_receipt = lambda *a, **k: pytest.fail('Cached child polled again')
    journal.await_children(parent)
    child['execution_success'] = False
    studio.atomic(journal.folder / 'child-tx-child.json', child)
    with pytest.raises(AssertionError, match='child execution failed'):
        journal.await_children(parent)


@pytest.mark.parametrize('field,value,reason', [
    ('hash', 'another-tx', 'hash mismatch'),
    ('from_address', '0x2222', 'signer mismatch'),
    ('to_address', '0x9999', 'destination mismatch'),
    ('type', 1, 'type mismatch'),
    ('data', {'calldata': {'base64': base64.b64encode(bytes(calldata.encode({'method': 'different', 'args': [1]}))).decode()}}, 'calldata mismatch'),
])
def test_successful_cached_parent_substitution_rejected(journal, field, value, reason):
    spec = {'address': '0x3333', 'method': 'work', 'args': [1]}
    journal.journal['operation'] = {'binding': studio.digest(spec), 'tx': 'tx-offline'}
    receipt = parent_receipt()
    receipt[field] = value
    studio.atomic(journal.folder / 'operation.json', receipt)
    with pytest.raises(AssertionError, match=reason):
        journal.transaction('operation', spec, lambda: pytest.fail('resubmission'))


@pytest.mark.parametrize('field,value,reason', [
    ('hash', 'another-tx', 'hash mismatch'),
    ('triggered_by', 'another-parent', 'parent mismatch'),
    ('from_address', '0x9999', 'sender mismatch'),
    ('to_address', '0x9999', 'emitted operation mismatch'),
    ('triggered_on', 'accepted', 'type mismatch'),
    ('data', {'calldata': {'base64': 'AAAA'}}, 'emitted operation mismatch'),
])
def test_successful_cached_child_substitution_rejected(journal, field, value, reason):
    parent, child = child_evidence()
    child[field] = value
    studio.atomic(journal.folder / 'child-tx-child.json', child)
    with pytest.raises(AssertionError, match=reason):
        journal.await_children(parent)


def test_missing_finalized_children_do_not_count_as_verification(journal):
    parent, _ = child_evidence()
    parent['triggered_transactions'] = []
    with pytest.raises(AssertionError, match='incomplete'):
        journal.await_children(parent)


def test_raw_sdk_receipt_calldata_is_verified(journal):
    receipt = parent_receipt()
    receipt['data']['calldata'] = receipt['data']['calldata']['base64']
    studio.verify_identity(receipt, 'tx-offline', '0x1111', {'address': '0x3333', 'method': 'work', 'args': [1]})


def test_deployment_receipt_binds_source_and_constructor():
    import hashlib
    source = b'contract source'
    receipt = {**parent_receipt(), 'type': 1, 'data': {'contract_code': base64.b64encode(source).decode(),
               'contract_address': '0x3333', 'calldata': base64.b64encode(bytes(calldata.encode({'args': [1]}))).decode()}}
    spec = {'file': 'contract.py', 'code_sha256': hashlib.sha256(source).hexdigest(), 'args': [1]}
    studio.verify_identity(receipt, 'tx-offline', '0x1111', spec)
    with pytest.raises(AssertionError, match='source mismatch'):
        studio.verify_identity(receipt, 'tx-offline', '0x1111', {**spec, 'code_sha256': '1'*64})
