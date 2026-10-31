import json
from pathlib import Path
from eth_account import Account
from genlayer_py import create_client
from genlayer_py.chains import studionet
from genlayer_py.types import TransactionStatus
from gltest.assertions import tx_execution_succeeded

root = Path(__file__).resolve().parents[1]
client = create_client(chain=studionet, account=Account.from_key((root/'.secrets/deployer').read_text().strip()))
tx = client.deploy_contract(code=(root/'tests/runtime/compatibility.py').read_bytes(), args=[])
(root/'evidence/runtime-pending.json').write_text(json.dumps({'tx':str(tx)}))
print('Runtime probe submitted', tx, flush=True)
r = client.wait_for_transaction_receipt(tx, status=TransactionStatus.FINALIZED, interval=5000, retries=120, full_transaction=True)
(root/'evidence/runtime-receipt.json').write_text(json.dumps(r, default=str, indent=2))
print('Status',r.get('status'),'execution',tx_execution_succeeded(r),flush=True)
if tx_execution_succeeded(r):
    a = r['data']['contract_address'] if isinstance(r.get('data'),dict) else r.get('to_address')
    print('Receipt fields',list(r.keys()), 'address',a,flush=True)
