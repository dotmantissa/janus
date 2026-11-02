"""Resumable Studio client. Journals submission before receipt polling."""
import hashlib
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
            receipt = self.client.wait_for_transaction_receipt(tx, status=TransactionStatus.FINALIZED, interval=7000, retries=200, full_transaction=True)
            atomic(receipt_path, receipt)
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

    def await_children(self, receipt):
        children = receipt.get('triggered_transactions', [])
        for child in children:
            tx = child if isinstance(child, str) else child.get('hash', child.get('transaction_hash'))
            if not tx:
                raise AssertionError('Unrecognized child transaction')
            r = self.client.wait_for_transaction_receipt(tx, status=TransactionStatus.FINALIZED, interval=7000, retries=200, full_transaction=True)
            atomic(self.folder / ('child-' + tx + '.json'), r)
            assert r.get('status_name') == 'FINALIZED', 'Child receipt is not finalized: ' + tx
            assert tx_execution_succeeded(r), 'Finalized child execution failed: ' + tx
            self.await_children(r)

    def wait_for(self, address, method, args, predicate, seconds=600):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            result = self.call(address, method, args)
            if predicate(result):
                return result
            time.sleep(10)
        raise AssertionError('Timed out waiting for ' + method)
