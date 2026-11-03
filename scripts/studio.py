"""Resumable Studio client. Journals submission before receipt polling."""
import hashlib
import base64
import json
import os
from pathlib import Path
import re
import time
from eth_account import Account
from genlayer_py import create_client
from genlayer_py.chains import studionet
from genlayer_py.types import TransactionStatus
from genlayer_py.types.calldata import CalldataAddress
from genlayer_py.abi import calldata
from gltest.assertions import tx_execution_succeeded

ROOT = Path(__file__).resolve().parents[1]


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=lambda v: {"$address": v.as_hex} if isinstance(v, CalldataAddress) else str(v))


def digest(value):
    return hashlib.sha256(canon(value).encode()).hexdigest()


def atomic(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, default=str) + '\n')
    temporary.replace(path)


def receipt_calldata(receipt):
    encoded = receipt['data']['calldata']
    return base64.b64decode(encoded['base64'] if isinstance(encoded, dict) else encoded, validate=True)


def verify_identity(receipt, tx, signer, specification):
    assert receipt['hash'].lower() == tx.lower(), 'Receipt transaction hash mismatch'
    assert receipt['from_address'].lower() == signer.lower(), 'Receipt signer mismatch'
    assert receipt.get('triggered_by') is None, 'Parent receipt is a child transaction'
    expected = {'args': specification['args']} if specification['args'] else {}
    if 'method' in specification:
        expected['method'] = specification['method']
        assert receipt['type'] == 2, 'Receipt transaction type mismatch'
        assert receipt['to_address'].lower() == specification['address'].lower(), 'Receipt destination mismatch'
    else:
        assert receipt['type'] == 1, 'Receipt deployment type mismatch'
        code = base64.b64decode(receipt['data']['contract_code'], validate=True)
        assert hashlib.sha256(code).hexdigest() == specification['code_sha256'], 'Receipt deployment source mismatch'
        assert receipt['to_address'].lower() == receipt['data']['contract_address'].lower(), 'Receipt deployment address mismatch'
    assert receipt_calldata(receipt) == bytes(calldata.encode(expected)), 'Receipt operation calldata mismatch'


class Studio:
    def __init__(self, key_name="deployer", journal="studio"):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', journal):
            raise ValueError('Journal must be a directory name using letters, numbers, _ or -')
        supplied = os.environ.get("JANUS_" + key_name.upper() + "_KEY")
        if supplied is None:
            supplied = (ROOT / '.secrets' / key_name).read_text().strip()
        self.account = Account.from_key(supplied)
        self.client = create_client(chain=studionet, account=self.account)
        self.folder = ROOT / 'evidence' / journal
        self.folder.mkdir(parents=True, exist_ok=True)
        self.journal_path = self.folder / 'journal.json'
        self.journal = json.loads(self.journal_path.read_text()) if self.journal_path.exists() else {}
        context_path = self.folder / 'context.json'
        context = {'chain_id': studionet.id, 'account': self.account.address.lower()}
        if context_path.exists():
            assert json.loads(context_path.read_text()) == context, 'Journal belongs to another account or chain'
        else:
            for operation in self.journal:
                receipt_path = self.folder / (operation + '.json')
                if receipt_path.exists():
                    previous = json.loads(receipt_path.read_text())
                    assert previous['from_address'].lower() == context['account'], 'Journal belongs to another account'
            atomic(context_path, context)

    def transaction(self, operation, specification, submit, expect_success=True):
        binding = digest(specification)
        if operation in self.journal:
            item = self.journal[operation]
            assert item['binding'] == binding, "Journal operation conflicts: " + operation
            tx = item['tx']
        else:
            tx = str(submit())
            item = {'binding': binding, 'specification': specification, 'tx': tx}
            self.journal[operation] = item
            atomic(self.journal_path, self.journal)
            print(operation, 'submitted', tx, flush=True)
        receipt_path = self.folder / (operation + '.json')
        if receipt_path.exists():
            receipt = json.loads(receipt_path.read_text())
        else:
            receipt = self.client.wait_for_transaction_receipt(tx, status=TransactionStatus.FINALIZED, interval=15000, retries=100, full_transaction=True)
            verify_identity(receipt, tx, self.account.address, specification)
            atomic(receipt_path, receipt)
        verify_identity(receipt, tx, self.account.address, specification)
        assert receipt.get('status_name') == 'FINALIZED', 'Receipt is not finalized: ' + tx
        succeeded = tx_execution_succeeded(receipt)
        print(operation, 'FINALIZED', 'SUCCESS' if succeeded else 'FAILED', flush=True)
        if succeeded != expect_success:
            leaders = receipt.get('consensus_data', {}).get('leader_receipt', [])
            print(json.dumps(leaders, default=str)[-8000:], flush=True)
            raise AssertionError(operation + ': unexpected execution result')
        return receipt

    def deploy(self, operation, path, args):
        code = (ROOT / path).read_bytes()
        receipt = self.transaction(operation, {'file': path, 'code_sha256': hashlib.sha256(code).hexdigest(), 'args': args}, lambda: self.client.deploy_contract(code=code, args=args))
        return receipt['data']['contract_address']

    def write(self, operation, address, method, args, expect_success=True):
        return self.transaction(operation, {'address': address, 'method': method, 'args': args}, lambda: self.client.write_contract(address=address, function_name=method, args=args), expect_success)

    def call(self, address, method, args=None):
        return self.client.read_contract(address=address, function_name=method, args=args or [])

    def verify_source(self, address, path):
        result = self.client.provider.make_request(method='gen_getContractCode', params=[address])['result']
        source = base64.b64decode(result, validate=True)
        assert source == (ROOT / path).read_bytes(), 'Deployed source differs: ' + path
        return {'address': address, 'file': path, 'sha256': hashlib.sha256(source).hexdigest(), 'byte_length': len(source)}

    def await_children(self, receipt):
        children = receipt.get('triggered_transactions', [])
        pending = receipt.get('consensus_data', {}).get('leader_receipt', [{}])[0].get('pending_transactions', [])
        emitted = [message for message in pending if message['on'] == 'finalized']
        assert len(children) == len(emitted), 'Finalized child evidence incomplete'
        matched = set()
        for child in children:
            tx = child if isinstance(child, str) else child.get('hash', child.get('transaction_hash'))
            if not tx:
                raise AssertionError('Unrecognized child transaction')
            child_path = self.folder / ('child-' + tx + '.json')
            if child_path.exists():
                r = json.loads(child_path.read_text())
            else:
                r = self.client.wait_for_transaction_receipt(tx, status=TransactionStatus.FINALIZED, interval=15000, retries=100, full_transaction=True)
            assert r['hash'].lower() == tx.lower(), 'Child receipt transaction hash mismatch'
            assert r['triggered_by'].lower() == receipt['hash'].lower(), 'Child receipt parent mismatch'
            assert r['from_address'].lower() == receipt['to_address'].lower(), 'Child receipt sender mismatch'
            assert r['type'] == 2 and r['triggered_on'] == 'finalized', 'Child receipt operation type mismatch'
            binding = next((index for index, message in enumerate(emitted)
                            if index not in matched and message['address'].lower() == r['to_address'].lower()
                            and message['value'] == r['value']
                            and base64.b64decode(message['calldata'], validate=True) == receipt_calldata(r)), None)
            assert binding is not None, 'Child receipt emitted operation mismatch'
            matched.add(binding)
            assert r.get('status_name') == 'FINALIZED', 'Child receipt is not finalized: ' + tx
            assert tx_execution_succeeded(r), 'Finalized child execution failed: ' + tx
            atomic(child_path, r)
            self.await_children(r)

    def wait_for(self, address, method, args, predicate, seconds=600):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            result = self.call(address, method, args)
            if predicate(result):
                return result
            time.sleep(10)
        raise AssertionError('Timed out waiting for ' + method)
