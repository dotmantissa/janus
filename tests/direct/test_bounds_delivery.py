import copy
import hashlib
import pytest
from conftest import canon, digest, open_packet, assess_packet


def test_four_complete_sources_six_assertions(packet, direct_vm):
    c = packet['c']
    for number in range(2,5):
        record = copy.deepcopy(packet['record'])
        record.update(source_id='source'+str(number), subject_id='doc'+str(number))
        c.observe_source(canon(record))
        from genlayer import gl
        with direct_vm.prank(gl.message.contract_address):
            c.confirm_source(record['source_id'])
        packet['manifest']['records'].append(record['source_id'])
    for number in range(2,6):
        a = copy.deepcopy(packet['manifest']['assertions'][0])
        a['assertion_id'] = 'effect'+str(number)
        packet['manifest']['assertions'].append(a)
        out = copy.deepcopy(packet['output']['assertions'][0])
        out['assertion_id'] = a['assertion_id']
        packet['output']['assertions'].append(out)
    packet['manifest']['assertions'].sort(key=lambda a: a['assertion_id'])
    packet['envelope']['source_manifest_digest'] = digest(packet['manifest'])
    direct_vm._llm_mocks.clear()
    direct_vm.mock_llm(r'.*',canon(packet['output']))
    assess_packet(packet)
    assert c.get_interval_certificate('request1')['status'] == 'CERTIFIED'
    assert len(c.get_interval_certificate('request1')['certificate']['decision_vector']) == 6
    assert direct_vm.run_validator() is True


def test_complete_packet_cannot_truncate_a_missing_document(packet,direct_vm):
    c = packet['c']
    record = copy.deepcopy(packet['record'])
    record.update(source_id='source2',subject_id='second',url='https://evidence.example/second')
    c.observe_source(canon(record))
    from genlayer import gl
    with direct_vm.prank(gl.message.contract_address):
        c.confirm_source(record['source_id'])
    packet['manifest']['records'].append('source2')
    packet['envelope']['source_manifest_digest'] = digest(packet['manifest'])
    open_packet(packet)
    direct_vm._web_mocks.clear()
    direct_vm.mock_web(r'https://evidence.example/record', {'status':200,'body':packet['raw']})
    direct_vm.mock_web(r'https://evidence.example/second', {'status':404,'body':b'gone'})
    c.reserve_assessment('request1',1)
    c.assess_intervals('request1',1)
    result = c.get_interval_certificate('request1')
    assert result['status'] == 'OPEN'
    assert result['certificate']['coverage']['complete_packet'] is False
    assert result['certificate']['decision_vector'] == []
    assert direct_vm.run_validator() is True


def test_byte_limits_before_model_execution(packet,direct_vm):
    record=copy.deepcopy(packet['record'])
    record['byte_length']=49153
    with direct_vm.expect_revert('INTEGER_BOUNDS'):
        packet['c'].observe_source(canon(record))
    record=copy.deepcopy(packet['record'])
    record['spans'][0]['text']='x'*2049
    with direct_vm.expect_revert('SPAN_BOUNDS'):
        packet['c'].observe_source(canon(record))


def test_oversized_joint_packet_rejected(packet,direct_vm):
    for number in range(2,5):
        raw = ('x'*22000).encode()
        record=copy.deepcopy(packet['record'])
        record.update(source_id='large'+str(number),subject_id='large'+str(number),url='https://evidence.example/large'+str(number),raw_sha256=hashlib.sha256(raw).hexdigest(),byte_length=len(raw),spans=[{'span_id':'one','start':0,'end':1,'text':'x'}])
        direct_vm._web_mocks.clear()
        direct_vm.mock_web(r'.*',{'status':200,'body':raw})
        packet['c'].observe_source(canon(record))
        from genlayer import gl
        with direct_vm.prank(gl.message.contract_address):
            packet['c'].confirm_source(record['source_id'])
        packet['manifest']['records'].append(record['source_id'])
    packet['manifest']['records'].sort()
    packet['envelope']['source_manifest_digest']=digest(packet['manifest'])
    with direct_vm.expect_revert('COMPLETE_PACKET_BOUNDS'):
        open_packet(packet)


def test_invalid_utf8_and_forged_byte_mapping(packet,direct_vm):
    for raw, span, expected in ((b'\xff',[{'span_id':'one','start':0,'end':1,'text':'x'}],'UNSUPPORTED_ENCODING'),(b'hello',[{'span_id':'one','start':0,'end':1,'text':'hacked'}],'INVALID_SPAN')):
        record=copy.deepcopy(packet['record'])
        record.update(source_id='bad',subject_id='bad',raw_sha256=hashlib.sha256(raw).hexdigest(),byte_length=len(raw),spans=span)
        direct_vm._web_mocks.clear()
        direct_vm.mock_web(r'.*',{'status':200,'body':raw})
        with direct_vm.expect_revert(expected):
            packet['c'].observe_source(canon(record))


def test_delivery_journal_finalized_retries_ack_and_conflicts(packet,direct_vm,direct_bob):
    assess_packet(packet)
    emitted=[]
    def hook(vm,data):
        if 'PostMessage' in data:
            emitted.append(data['PostMessage'])
            return b''
        return None
    direct_vm._gl_call_hook=hook
    c=packet['c']
    c.publish_to('request1',packet['consumer'],'operation')
    c.publish_to('request1',packet['consumer'],'operation')
    assert len(emitted)==1
    assert emitted[0]['on']=='finalized'
    assert c.get_delivery('operation')['acknowledged'] is False
    c.retry_delivery('operation')
    c.retry_delivery('operation')
    assert len(emitted)==3
    with direct_vm.expect_revert('DELIVERY_RETRY_OR_STALE'):
        c.retry_delivery('operation')
    delivery=c.get_delivery('operation')
    with direct_vm.expect_revert('CONSUMER_ONLY'):
        c.acknowledge('operation',delivery['payload_digest'],'APPLIED')
    direct_vm.sender=direct_bob
    c.acknowledge('operation',delivery['payload_digest'],'APPLIED')
    c.acknowledge('operation',delivery['payload_digest'],'APPLIED')
    assert c.get_delivery('operation')['acknowledgement']=='APPLIED'
    with direct_vm.expect_revert('ACK_REUSE'):
        c.acknowledge('operation',delivery['payload_digest'],'BLOCKED')


def test_controlling_intersection_conflict_unknown(packet,direct_vm):
    packet['output']['assertions'][1]['role']='EFFECTIVE'
    direct_vm._llm_mocks.clear()
    direct_vm.mock_llm(r'.*',canon(packet['output']))
    assess_packet(packet)
    cert=packet['c'].get_interval_certificate('request1')['certificate']
    assert cert['lifecycle_status']=='UNKNOWN'
    assert 'CONTRADICTION' in cert['unresolved_flags']
