"""Offline recovery checks for persisted real-flow summaries; no network calls."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def save_result(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'scripts'))
    from live_flow import save_live_result
    return save_live_result


def test_interrupted_replay_preserves_later_verified_cases(tmp_path, save_result):
    path = tmp_path / 'results.json'
    permitted = {'request_id': 'notice-permitted', 'delivery': {'consumer': '0xnotice'}, 'verified': 1}
    refused = {'request_id': 'notice-refused', 'delivery': {'consumer': '0xnotice'}, 'verified': 1}
    path.write_text(json.dumps([permitted, refused]))

    refreshed = {**permitted, 'verified': 2}
    save_result(path, refreshed, ['0xNOTICE', '0xevent'])
    # A quota failure before the next case must leave its prior measured result intact.
    assert json.loads(path.read_text()) == [refreshed, refused]


def test_new_deployment_does_not_inherit_old_consumer_results(tmp_path, save_result):
    path = tmp_path / 'results.json'
    path.write_text(json.dumps([{'request_id': 'notice-permitted', 'delivery': {'consumer': '0xold'}}]))
    current = {'request_id': 'event-permitted', 'delivery': {'consumer': '0xevent'}}
    save_result(path, current, ['0xnotice', '0xevent'])
    assert json.loads(path.read_text()) == [current]
