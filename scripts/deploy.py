"""Deploy Janus and separately owned executable consumer integrations to Studio."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from eth_account import Account
from genlayer_py.types.calldata import CalldataAddress
from studio import Studio, ROOT, atomic


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--journal', default='studio')
    args = parser.parse_args()
    transport = json.loads((ROOT / 'evidence/source-transport.json').read_text())
    assert transport['redirect_policy'] == 'REJECT' and transport['live_verification'], 'Source transport is not verified'
    for path, expected in transport['source_sha256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == expected, 'Transport source differs: '+path
    for name in ('notice', 'event'):
        path = ROOT / '.secrets' / name
        if not path.exists() and not os.environ.get('JANUS_' + name.upper() + '_KEY'):
            path.parent.mkdir(mode=0o700, exist_ok=True)
            with path.open('x', opener=lambda name, flags: os.open(name, flags, 0o600)) as output:
                output.write(Account.create().key.hex())
    s = Studio(journal=args.journal)
    resolver = s.deploy('deploy-janus', 'contracts/janus.py', [10000, transport['url']])
    notice = Studio('notice', args.journal + '-notice')
    gate = notice.deploy('deploy-notice', 'contracts/notice_gate.py', [CalldataAddress(resolver), 'notice-v1', 1, 2592000])
    event = Studio('event', args.journal + '-event')
    registry = event.deploy('deploy-event', 'contracts/event_registry.py', [CalldataAddress(resolver), 'event-v1', 1, 0])
    for address, path in ((resolver, 'contracts/janus.py'), (gate, 'contracts/notice_gate.py'), (registry, 'contracts/event_registry.py')):
        s.verify_source(address, path)
    result = {'network': 'studionet', 'chain_id': 61999, 'rpc': 'https://studio.genlayer.com/api', 'runtime': 'py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6', 'resolver': resolver, 'notice_consumer': gate, 'event_consumer': registry, 'owners': {'resolver': s.account.address, 'notice': notice.account.address, 'event': event.account.address}}
    result['journal'] = args.journal
    result['source_transport'] = transport
    result['code_sha256'] = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in ('contracts/janus.py', 'contracts/notice_gate.py', 'contracts/event_registry.py')}
    metadata = ROOT / 'evidence' / 'deployment.json'
    if metadata.exists():
        previous = json.loads(metadata.read_text())
        if previous['resolver'] != resolver:
            atomic(ROOT / 'evidence' / ('deployment-' + previous['resolver'] + '.json'), previous)
    atomic(metadata, result)
    print(result, flush=True)


if __name__ == '__main__':
    main()
