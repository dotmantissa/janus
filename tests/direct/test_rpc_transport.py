"""Offline client transport checks; no chain or production credentials."""
from types import SimpleNamespace
import pytest
import requests
from scripts import studio

TOKEN = 'a' * 64


def test_authenticated_transport_preserves_signed_parameters_and_reply(monkeypatch):
    seen = []
    reply = {'jsonrpc': '2.0', 'id': 1, 'result': 'signed-transaction-hash'}
    def post(url, **kwargs):
        seen.append((url, kwargs))
        return SimpleNamespace(json=lambda: reply)
    monkeypatch.setattr(studio.requests, 'post', post)
    params = ['unchanged-signed-raw-transaction']
    rpc = studio.authenticated_rpc('https://relay.example/api/rpc', TOKEN)
    assert rpc('eth_sendRawTransaction', params) is reply
    assert seen[0][1]['json']['params'] is params
    assert seen[0][1]['headers']['Authorization'] == 'Bearer ' + TOKEN
    assert seen[0][1]['allow_redirects'] is False


def test_authenticated_transport_propagates_quota_and_ambiguous_network_errors(monkeypatch):
    rpc = studio.authenticated_rpc('https://relay.example/api/rpc', TOKEN)
    reply = {'jsonrpc': '2.0', 'error': {'code': -32029, 'message': 'quota'}}
    monkeypatch.setattr(studio.requests, 'post', lambda *a, **k: SimpleNamespace(json=lambda: reply))
    with pytest.raises(studio.GenLayerError, match='code=-32029'):
        rpc('eth_sendRawTransaction', ['signed'])
    calls = []
    def unavailable(*args, **kwargs):
        calls.append(1)
        raise requests.exceptions.Timeout('offline timeout')
    monkeypatch.setattr(studio.requests, 'post', unavailable)
    with pytest.raises(studio.GenLayerError, match='transport failed'):
        rpc('eth_sendRawTransaction', ['signed'])
    assert calls == [1]


@pytest.mark.parametrize('url,token', [('http://relay.example/rpc', TOKEN), ('https://user@relay.example/rpc', TOKEN), ('https://relay.example/rpc?token=x', TOKEN), ('https://relay.example/rpc', 'invalid')])
def test_authenticated_transport_rejects_invalid_private_configuration(url, token):
    with pytest.raises(ValueError):
        studio.authenticated_rpc(url, token)


def test_authenticated_transport_rejects_non_rpc_reply(monkeypatch):
    monkeypatch.setattr(studio.requests, 'post', lambda *a, **k: SimpleNamespace(json=lambda: {}))
    with pytest.raises(studio.GenLayerError, match='invalid reply'):
        studio.authenticated_rpc('https://relay.example/rpc', TOKEN)('gen_call', [])
