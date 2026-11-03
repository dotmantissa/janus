"""Real Studio consensus and finalized consumer actions using public Node.js records."""
import argparse
import hashlib
import json
from genlayer_py.types.calldata import CalldataAddress
from studio import Studio, ROOT, canon, digest, atomic


def source_record(filename, metadata, source_id, authority_id, subject, snippets):
    raw = (ROOT / 'evidence' / filename).read_bytes()
    spans = []
    for span_id, snippet in snippets:
        encoded = snippet.encode()
        start = raw.index(encoded)
        spans.append({'span_id': span_id, 'start': start, 'end': start + len(encoded), 'text': snippet})
    assert 0 < len(raw) <= 49152
    return {'source_id': source_id, 'authority_id': authority_id, 'channel': 'PUBLIC_NODEJS_RECORD', 'url': json.loads((ROOT/'evidence'/metadata).read_text())['url'], 'raw_sha256': hashlib.sha256(raw).hexdigest(), 'byte_length': len(raw), 'revision': 1, 'subject_id': subject, 'scope': 'nodejs-release', 'spans': sorted(spans, key=lambda s: s['span_id']), 'supersedes': ''}


def assert_consensus(receipt):
    assert receipt.get('leader_only') is False
    data = receipt['consensus_data']
    assert len(data['validators']) >= 2
    agreeing = [vote for vote in data['votes'].values() if vote == 'agree']
    assert len(agreeing) >= 2
    assert receipt['status_name'] == 'FINALIZED'


def save_live_result(path, result, consumers):
    """Keep completed cases when a resumed flow stops before revisiting them."""
    previous = json.loads(path.read_text()) if path.exists() else []
    current = {address.lower() for address in consumers}
    records = [row for row in previous if row['delivery']['consumer'].lower() in current]
    for index, row in enumerate(records):
        if row['request_id'] == result['request_id']:
            records[index] = result
            break
    else:
        records.append(result)
    atomic(path, records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--journal')
    args = parser.parse_args()
    deployment = json.loads((ROOT/'evidence/deployment.json').read_text())
    assert deployment.get('code_sha256'), 'Deployment predates current source; run deploy.py with a new --journal'
    args.journal = args.journal or deployment.get('journal', 'studio')
    for path, expected in deployment.get('code_sha256', {}).items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, 'Deployment source differs: ' + path
    resolver, gate, registry = deployment['resolver'], deployment['notice_consumer'], deployment['event_consumer']
    s, n, ev = Studio(journal=args.journal), Studio('notice', args.journal+'-notice'), Studio('event', args.journal+'-event')
    configs = [
        ('node-schedule-observer', 'https://raw.githubusercontent.com/nodejs/Release/', 'https://github.com/nodejs/Release'),
        ('node-release-observer', 'https://raw.githubusercontent.com/nodejs/nodejs.org/', 'https://github.com/nodejs/nodejs.org'),
    ]
    for aid, prefix, public in configs:
        config = {'channel': 'PUBLIC_NODEJS_RECORD', 'url_prefix': prefix, 'scope': 'nodejs-release', 'public_evidence_url': public}
        s.write('authority-'+aid, resolver, 'register_authority', [aid, CalldataAddress(s.account.address), canon(config)])
        s.write('accept-'+aid, resolver, 'accept_authority', [aid])
    schedule_text = (ROOT/'evidence/node-schedule.json').read_text()
    snippets = []
    for major in ('v24','v26'):
        start = schedule_text.index('"'+major+'": {')
        end = schedule_text.index('\n  }', start)+4
        snippets.append((major, schedule_text[start:end]))
    release_text = (ROOT/'evidence/node-release.md').read_text()
    head = release_text[:release_text.index('### Notable Changes')]
    sources = [source_record('node-schedule.json','node-source.json','node-schedule-1','node-schedule-observer','schedule',snippets), source_record('node-release.md','node-release-source.json','node-release-1','node-release-observer','v24.1.0', [('release-header',head)])]
    atomic(ROOT/'evidence/live-source-manifests.json', sources)
    for source in sources:
        r = s.write('observe-'+source['source_id'], resolver, 'observe_source', [canon(source)])
        assert_consensus(r)
        s.await_children(r)
        confirmed = s.wait_for(resolver, 'get_source', [source['source_id']], lambda v: v['confirmed'])
        assert confirmed['valid'] is True
        assert hashlib.sha256(confirmed['raw_text'].encode()).hexdigest() == source['raw_sha256']
        atomic(ROOT/'evidence'/('source-confirmed-'+source['source_id']+'.json'), confirmed)
    policies = [
        ('notice-v1', ['EFFECTIVE','PUBLICATION'], 'The Node.js schedule maintenance field is an effective start inclusive at UTC midnight. The end field ends maintenance exclusively at UTC midnight. Use EFFECTIVE and RANGE, with start=maintenance and end=end, for the specified major version. Never substitute alpha, start or lts fields. Dates in unrelated major versions are not controlling exceptions. Publication availability comes only from the signed public observation.'),
        ('event-v1', ['OCCURRENCE'], 'The release announcement heading date is the Gregorian UTC date of the announced release occurrence. Use OCCURRENCE and EXACT, with the whole date day from the heading. Frontmatter publication metadata cannot prove historical availability. Evaluate the occurrence independently of when the committed revision was observed. Check notable changes and corrections for any withdrawal or cancellation of this release.'),
    ]
    for pid, roles, instruction in policies:
        rules = {'revision': 1, 'date_only_utc': True, 'rules': [{'rule_id': 'temporal-role', 'instruction': instruction}], 'required_roles': roles}
        trust = {'authorities': [x[0] for x in configs], 'publication_support': 'SIGNED_PUBLIC_OBSERVATION'}
        s.write('policy-'+pid, resolver, 'register_temporal_policy', [pid,canon(rules),canon(trust)])
    for cli, consumer, label in ((n,gate,'notice'), (ev,registry,'event')):
        r = cli.write('register-'+label, consumer, 'register', [])
        cli.await_children(r)
        s.wait_for(resolver, 'get_consumer', [CalldataAddress(consumer)], lambda v: bool(v))
    cases = [
        ('notice-permitted', n, gate, 'notice-v1', 'Node.js v26 is in its maintenance support phase during the maintenance interval specified in the committed Node.js schedule.', '2027-10-20T00:00:00Z', 'node-schedule-1', 'When is the effective maintenance interval for v26?', True),
        ('notice-refused', n, gate, 'notice-v1', 'Node.js v24 is in its maintenance support phase during the maintenance interval specified in the committed Node.js schedule.', '2026-10-20T00:00:00Z', 'node-schedule-1', 'When is the effective maintenance interval for v24?', False),
        ('event-permitted', ev, registry, 'event-v1', 'The Node.js v24.1.0 release occurred on the date of its committed release announcement.', '2025-05-21T12:00:00Z', 'node-release-1', 'On what UTC date did the v24.1.0 release occurrence take place?', True),
        ('event-refused', ev, registry, 'event-v1', 'The Node.js v24.1.0 release occurred on the date of its committed release announcement.', '2025-05-22T00:00:00Z', 'node-release-1', 'On what UTC date did the v24.1.0 release occurrence take place?', False),
    ]
    for rid, cli, consumer, pid, proposition, target, sid, question, allowed in cases:
        config = cli.call(consumer, 'get_configuration')
        manifest = {'records': [sid], 'assertions': [{'assertion_id': 'temporal', 'question': question, 'rule_id': 'temporal-role'}]}
        envelope = {'request_id': rid, 'owner': s.account.address.lower(), 'parties': [], 'policy_id': pid, 'policy_revision': 1, 'subject_id': rid, 'subject_digest': digest(proposition), 'source_manifest_digest': digest(manifest), 'consumer': consumer.lower(), 'consequence_digest': config['consequence_digest'], 'generation': 1, 'deadline': '2032-01-01T00:00:00Z', 'target_time': target, 'supersedes': ''}
        atomic(ROOT/'evidence'/('request-'+rid+'.json'), {'proposition': proposition, 'manifest': manifest, 'envelope': envelope})
        cli.write('approve-'+rid, consumer, 'approve_request', [canon(envelope)])
        s.write('open-'+rid, resolver, 'open_record', [rid,proposition,target,canon(manifest),canon(envelope)])
        s.write('reserve-'+rid, resolver, 'reserve_assessment', [rid,1])
        r = s.write('assess-'+rid, resolver, 'assess_intervals', [rid,1])
        assert_consensus(r)
        result = s.call(resolver,'get_interval_certificate',[rid])
        atomic(ROOT/'evidence'/('certificate-'+rid+'.json'), result)
        assert result['status'] == 'CERTIFIED', result
        publication = result['certificate']['first_publication_upper']
        assert publication is not None and publication > 1760000000
        operation = 'deliver-'+rid
        r = s.write('publish-'+rid, resolver, 'publish_to', [rid,CalldataAddress(consumer),operation])
        s.await_children(r)
        ack = s.wait_for(resolver,'get_delivery',[operation],lambda v:v['acknowledged'])
        assert ack['acknowledgement'] == ('APPLIED' if allowed else 'BLOCKED'), ack
        execution = cli.write('execute-'+rid, consumer, 'execute', [rid,'action-'+rid], expect_success=allowed)
        if not allowed:
            assert 'ACTION_BLOCKED' in canon(execution['consensus_data']['leader_receipt'][0]['result'])
        state = cli.call(consumer,'get_state',[rid])
        assert state['permitted'] is allowed
        if allowed:
            assert state['executed'] is True
            assert state['active'] is (pid=='event-v1')
        save_live_result(ROOT/'evidence/live-results.json', {'request_id':rid,'operation_id':operation,'certificate':result,'delivery':ack,'consumer_state':state,'expected_permitted':allowed}, [gate, registry])
        print('VERIFIED',rid,ack['acknowledgement'],flush=True)
    print('All four real-source finalized consumer flows verified.',flush=True)


if __name__ == '__main__':
    main()
