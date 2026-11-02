"""Offline journal fault probes; these fixtures make no network transactions."""
import json
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
        journal.transaction('operation', {'args': [1]}, lambda: 'tx-offline')

    journal.client.wait_for_transaction_receipt = lambda *a, **k: {'status_name': 'FINALIZED', 'execution_success': True}

    def resubmit():
        pytest.fail('A journaled transaction must not be resubmitted')

    journal.transaction('operation', {'args': [1]}, resubmit)
    with pytest.raises(AssertionError, match='conflicts'):
        journal.transaction('operation', {'args': [2]}, resubmit)


@pytest.mark.parametrize('status,success', [('ACCEPTED', True), ('FINALIZED', False)])
def test_cached_receipt_requires_finality_and_execution_success(journal, status, success):
    spec = {'args': [1]}
    journal.journal['operation'] = {'binding': studio.digest(spec), 'tx': 'tx-offline'}
    studio.atomic(journal.folder / 'operation.json', {'status_name': status, 'execution_success': success})
    with pytest.raises(AssertionError):
        journal.transaction('operation', spec, lambda: pytest.fail('cached transaction resubmitted'))


def test_journal_rejects_another_signer(journal, monkeypatch):
    monkeypatch.setattr(studio.Account, 'from_key', lambda _: SimpleNamespace(address='0x2222'))
    with pytest.raises(AssertionError, match='another account'):
        studio.Studio(journal='offline')


def test_journal_directory_cannot_escape_evidence(journal):
    with pytest.raises(ValueError, match='directory name'):
        studio.Studio(journal='../outside')


def test_finalized_child_receipts_are_reused_and_checked(journal):
    studio.atomic(journal.folder / 'child-tx-child.json', {
        'status_name': 'FINALIZED', 'execution_success': True, 'triggered_transactions': []})
    journal.client.wait_for_transaction_receipt = lambda *a, **k: pytest.fail('Cached child polled again')
    journal.await_children({'triggered_transactions': ['tx-child']})
    studio.atomic(journal.folder / 'child-tx-child.json', {
        'status_name': 'FINALIZED', 'execution_success': False, 'triggered_transactions': []})
    with pytest.raises(AssertionError, match='child execution failed'):
        journal.await_children({'triggered_transactions': ['tx-child']})
