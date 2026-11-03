"""Genuine Studio authorization, execution and recovery transitions for both consumers."""
import argparse
import json
from genlayer_py.types.calldata import CalldataAddress
from studio import Studio, ROOT, canon, digest, atomic
from live_flow import assert_consensus


def failure(cli, operation, address, method, args, code):
    receipt = cli.write(operation, address, method, args, expect_success=False)
    assert code in canon(receipt['consensus_data']['leader_receipt'][0]['result'])
    return receipt


def deliver(s, cli, resolver, consumer, rid, operation, expected):
    receipt = s.write('publish-'+operation, resolver, 'publish_to', [rid, CalldataAddress(consumer), operation])
    s.await_children(receipt)
    delivery = s.wait_for(resolver, 'get_delivery', [operation], lambda v: v['acknowledged'])
    assert delivery['acknowledgement'] == expected
    return delivery


def main():
    parser = argparse.ArgumentParser()
    parser.parse_args()
    deployment = json.loads((ROOT/'evidence/deployment.json').read_text())
    journal = deployment['journal']
    s = Studio(journal=journal)
    records = []
    for label, key, consumer in [('notice', 'notice', deployment['notice_consumer']), ('event', 'event', deployment['event_consumer'])]:
        cli = Studio(key, journal+'-'+key)
        resolver = deployment['resolver']
        template = json.loads((ROOT/'evidence'/('request-'+label+'-permitted.json')).read_text())
        proposition, manifest = template['proposition'], template['manifest']
        subject = 'lifecycle-'+label
        original = {**template['envelope'], 'request_id': subject+'-1', 'subject_id': subject}
        opening = lambda envelope: [envelope['request_id'], proposition, envelope['target_time'], canon(manifest), canon(envelope)]
        progress_path = ROOT/'evidence'/(subject+'-progress.json')
        progress = json.loads(progress_path.read_text()) if progress_path.exists() else {'stage': 0, 'consumer': consumer}
        assert progress['consumer'] == consumer, 'Lifecycle progress belongs to another deployment'
        if progress['stage'] < 1:
            # The consumer's owner is an unrelated account at the resolver.
            unauthorized = {**original, 'request_id': subject+'-unauthorized', 'owner': cli.account.address.lower()}
            failure(cli, subject+'-unapproved-open', resolver, 'open_record', opening(unauthorized), 'CONSUMER_APPROVAL_REQUIRED')
            assert s.call(resolver, 'get_request_state', [unauthorized['request_id']])['exists'] is False
            cli.write(subject+'-approve-original', consumer, 'approve_request', [canon(original)])
            s.write(subject+'-open-original', resolver, 'open_record', opening(original))
            s.write(subject+'-reserve-original', resolver, 'reserve_assessment', [original['request_id'], 1])
            assessment = s.write(subject+'-assess-original', resolver, 'assess_intervals', [original['request_id'], 1])
            assert_consensus(assessment)
            assert s.call(resolver, 'get_interval_certificate', [original['request_id']])['status'] == 'CERTIFIED'
            deliver(s, cli, resolver, consumer, original['request_id'], subject+'-delivery-1', 'APPLIED')
            cli.write(subject+'-execute-1', consumer, 'execute', [subject, subject+'-action-1'])
            executed = cli.call(consumer, 'get_state', [subject])
            assert executed['executed'] is True
            deliver(s, cli, resolver, consumer, original['request_id'], subject+'-delivery-2', 'APPLIED')
            redelivered = cli.call(consumer, 'get_state', [subject])
            assert redelivered['executed'] is True and redelivered['active'] == executed['active']
            failure(cli, subject+'-second-action-blocked', consumer, 'execute', [subject, subject+'-action-2'], 'CONSEQUENCE_ALREADY_EXECUTED')
            progress.update(stage=1, executed=executed, redelivered=redelivered)
            atomic(progress_path, progress)
        executed, redelivered = progress['executed'], progress['redelivered']
        bad = {**original, 'request_id': subject+'-bad-2', 'generation': 2, 'supersedes': original['request_id'], 'source_manifest_digest': '1'*64}
        cancelled = {**bad, 'request_id': subject+'-cancelled-2', 'source_manifest_digest': original['source_manifest_digest']}
        if progress['stage'] < 2:
            cli.write(subject+'-approve-bad', consumer, 'approve_request', [canon(bad)])
            assert cli.call(consumer, 'get_state', [subject])['permitted'] is False
            failure(s, subject+'-bad-open-blocked', resolver, 'open_record', opening(bad), 'MANIFEST_DIGEST')
            cli.write(subject+'-cancel-bad', consumer, 'cancel_request', [bad['request_id']])
            assert cli.call(consumer, 'get_request_approval', [bad['request_id']]) == ''
            # A previously valid delivery cannot lift the cancellation restriction.
            deliver(s, cli, resolver, consumer, original['request_id'], subject+'-delayed-old', 'STALE')
            assert cli.call(consumer, 'get_state', [subject])['permitted'] is False
            cli.write(subject+'-approve-cancellable', consumer, 'approve_request', [canon(cancelled)])
            cli.write(subject+'-cancel-cancellable', consumer, 'cancel_request', [cancelled['request_id']])
            failure(s, subject+'-cancelled-open-blocked', resolver, 'open_record', opening(cancelled), 'CONSUMER_APPROVAL_REQUIRED')
            assert s.call(resolver, 'get_request_state', [cancelled['request_id']])['exists'] is False
            progress['stage'] = 2
            atomic(progress_path, progress)
        # Quarantine and an owner change cannot strand the consumer-authorized successor.
        s.write(subject+'-quarantine-original', resolver, 'quarantine', ['REQUEST', original['request_id'], digest('consumer-authorized recovery verification')])
        recovered = {**cancelled, 'request_id': subject+'-recovered-2', 'owner': cli.account.address.lower()}
        cli.write(subject+'-approve-recovery', consumer, 'approve_request', [canon(recovered)])
        cli.write(subject+'-open-recovery', resolver, 'open_record', opening(recovered))
        cli.write(subject+'-reserve-recovery', resolver, 'reserve_assessment', [recovered['request_id'], 1])
        assessment = cli.write(subject+'-assess-recovery', resolver, 'assess_intervals', [recovered['request_id'], 1])
        assert_consensus(assessment)
        certificate = s.call(resolver, 'get_interval_certificate', [recovered['request_id']])
        assert certificate['status'] == 'CERTIFIED' and certificate['valid'] is True
        deliver(cli, cli, resolver, consumer, recovered['request_id'], subject+'-recovered-delivery', 'APPLIED')
        cli.write(subject+'-execute-recovery', consumer, 'execute', [subject, subject+'-recovered-action'])
        failure(cli, subject+'-opened-cancellation-blocked', consumer, 'cancel_request', [recovered['request_id']], 'REQUEST_ALREADY_OPEN')
        state = cli.call(consumer, 'get_state', [subject])
        assert state['generation'] == 2 and state['permitted'] is True and state['executed'] is True
        assert s.call(resolver, 'get_subject_head', [CalldataAddress(consumer), subject]) == recovered['request_id']
        records.append({'consumer': consumer, 'mode': label, 'subject_id': subject, 'original_request': original['request_id'], 'recovered_request': recovered['request_id'], 'cancelled_requests': [bad['request_id'], cancelled['request_id']], 'executed_before_redelivery': executed, 'executed_after_redelivery': redelivered, 'certificate': certificate, 'final_state': state})
        atomic(ROOT/'evidence'/('lifecycle-'+label+'.json'), records[-1])
        print('VERIFIED', label, 'authorization, repeated delivery, cancellation, delayed delivery, quarantine and owner recovery', flush=True)
    atomic(ROOT/'evidence/live-lifecycle-results.json', records)


if __name__ == '__main__':
    main()
