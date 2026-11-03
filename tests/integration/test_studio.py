"""Run genuine flows and independently bind their receipts, deployed bytes and chain state."""
import json
import sys
from pathlib import Path
import pytest
from genlayer_py.types.calldata import CalldataAddress

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))


def run_main(module):
    original = sys.argv
    try:
        sys.argv = [module.__name__+'.py']
        module.main()
    finally:
        sys.argv = original


@pytest.mark.integration
def test_real_studio_flow():
    import live_flow
    from studio import Studio, verify_identity
    run_main(live_flow)
    deployment = json.loads((ROOT/'evidence/deployment.json').read_text())
    s = Studio(journal=deployment['journal'])
    consumers = {'notice': deployment['notice_consumer'], 'event': deployment['event_consumer']}
    for address, path in ((deployment['resolver'], 'contracts/janus.py'), (consumers['notice'], 'contracts/notice_gate.py'), (consumers['event'], 'contracts/event_registry.py')):
        assert s.verify_source(address, path)['sha256'] == deployment['code_sha256'][path]
    results = json.loads((ROOT/'evidence/live-results.json').read_text())
    assert {row['request_id'] for row in results} == {'notice-permitted', 'notice-refused', 'event-permitted', 'event-refused'}
    for row in results:
        rid, op = row['request_id'], row['operation_id']
        current = s.call(deployment['resolver'], 'get_interval_certificate', [rid])
        assert current == row['certificate'] and current['valid'] is True
        delivery = s.call(deployment['resolver'], 'get_delivery', [op])
        assert delivery == row['delivery'] and delivery['acknowledged'] is True
        assessment = json.loads((s.folder/('assess-'+rid+'.json')).read_text())
        live_flow.assert_consensus(assessment)
        request = json.loads((ROOT/'evidence'/('request-'+rid+'.json')).read_text())
        cli = Studio(rid.split('-')[0], deployment['journal']+'-'+rid.split('-')[0])
        consumer = consumers[rid.split('-')[0]]
        execution = json.loads((cli.folder/('execute-'+rid+'.json')).read_text())
        verify_identity(execution, cli.journal['execute-'+rid]['tx'], cli.account.address, {'address': consumer, 'method': 'execute', 'args': [rid, 'action-'+rid]})
        state = cli.call(consumer, 'get_state', [rid])
        assert state == row['consumer_state'] and state['permitted'] is row['expected_permitted']
        assert cli.call(consumer, 'get_receipt', [op])['executed'] is row['expected_permitted']
        assert s.call(deployment['resolver'], 'get_subject_head', [CalldataAddress(consumer), request['envelope']['subject_id']]) == rid


@pytest.mark.integration
def test_both_live_consumer_lifecycles():
    import live_lifecycle
    from studio import Studio
    run_main(live_lifecycle)
    deployment = json.loads((ROOT/'evidence/deployment.json').read_text())
    s = Studio(journal=deployment['journal'])
    results = json.loads((ROOT/'evidence/live-lifecycle-results.json').read_text())
    assert {row['mode'] for row in results} == {'notice', 'event'}
    for row in results:
        cli = Studio(row['mode'], deployment['journal']+'-'+row['mode'])
        assert row['executed_after_redelivery']['executed'] is True
        assert row['executed_after_redelivery']['active'] == row['executed_before_redelivery']['active']
        state = cli.call(row['consumer'], 'get_state', [row['subject_id']])
        assert state == row['final_state'] and state['executed'] is True and state['generation'] == 2
        assert s.call(deployment['resolver'], 'get_interval_certificate', [row['recovered_request']]) == row['certificate']
        for rid in row['cancelled_requests']:
            assert cli.call(row['consumer'], 'get_request_approval', [rid]) == ''
            assert s.call(deployment['resolver'], 'get_request_state', [rid])['exists'] is False
        assert s.call(deployment['resolver'], 'get_interval_certificate', [row['original_request']])['valid'] is False
