"""Produce two standalone contracts from one reviewed adapter implementation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = '''# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""MODE consumer. Only authenticated finalized Janus messages establish eligibility.

The owner approves request bindings before delivery. Action-time checks retain
unresolved restrictions and reject superseded or quarantined sources.
"""
from genlayer import *
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re

MODE = "MODE_VALUE"
MAX_TIME = 253402300799


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canon(value).encode("utf-8")).hexdigest()


def fail(code):
    raise gl.vm.UserError("[EXPECTED] " + code)


def utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}(?:Z|[+-]\\d{2}:\\d{2})", value):
        fail("UNSUPPORTED_TIME")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        delta = dt - datetime(1970, 1, 1, tzinfo=timezone.utc)
        result = delta.days * 86400 + delta.seconds
        if not 0 <= result <= MAX_TIME:
            fail("TIME_BOUNDS")
        return result
    except Exception:
        fail("UNSUPPORTED_TIME")


@allow_storage
@dataclass
class Receipt:
    request_id: str
    subject_id: str
    generation: u64
    payload: str
    acknowledgement: str
    executed: bool


class CLASS_NAME(gl.Contract):
    owner: Address
    resolver: Address
    policy_id: str
    policy_revision: u32
    notice_seconds: u64
    consequence_digest: str
    approved: TreeMap[str, str]
    expected_subject: TreeMap[str, str]
    receipts: TreeMap[str, Receipt]
    last_applied_generation: TreeMap[str, u64]
    last_operation: TreeMap[str, str]
    executed_operations: TreeMap[str, str]
    history: DynArray[str]
    approvals: DynArray[str]

    def __init__(self, resolver: Address, policy_id: str, policy_revision: int, notice_seconds: int):
        if not isinstance(policy_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", policy_id):
            fail("POLICY_ID")
        if type(policy_revision) is not int or not 1 <= policy_revision <= 2**32 - 1:
            fail("REVISION_BOUNDS")
        if type(notice_seconds) is not int or not 0 <= notice_seconds <= 315360000 or (MODE == "EVENT" and notice_seconds != 0):
            fail("NOTICE_BOUNDS")
        self.owner = gl.message.sender_address
        self.resolver = resolver
        self.policy_id = policy_id
        self.policy_revision = u32(policy_revision)
        self.notice_seconds = u64(notice_seconds)
        self.consequence_digest = digest({"mode": MODE, "notice_seconds": notice_seconds, "unresolved": "BLOCK", "version": 1})

    def _owner(self):
        if gl.message.sender_address != self.owner:
            fail("OWNER_ONLY")

    def _config(self):
        return {"policy_id": self.policy_id, "policy_revision": int(self.policy_revision), "consequence_digest": self.consequence_digest, "unresolved_consequence": "BLOCK"}

    @gl.public.write
    def register(self) -> None:
        self._owner()
        gl.get_contract_at(self.resolver).emit(on="finalized").register_consumer(gl.message.contract_address, canon(self._config()))

    @gl.public.write
    def approve_request(self, envelope: str) -> None:
        self._owner()
        if not isinstance(envelope, str) or len(envelope.encode("utf-8")) > 20000:
            fail("ENVELOPE_BOUNDS")
        try:
            e = json.loads(envelope)
        except Exception:
            fail("ENVELOPE_JSON")
        fields = {"request_id", "owner", "parties", "policy_id", "policy_revision", "subject_id", "subject_digest", "source_manifest_digest", "consumer", "consequence_digest", "generation", "deadline", "target_time", "supersedes"}
        if not isinstance(e, dict) or set(e) != fields:
            fail("ENVELOPE_SCHEMA")
        if Address(e["consumer"]) != gl.message.contract_address or e["policy_id"] != self.policy_id or e["policy_revision"] != self.policy_revision or e["consequence_digest"] != self.consequence_digest:
            fail("CONSUMER_BINDING")
        if type(e["generation"]) is not int or not 1 <= e["generation"] <= 2**64 - 1:
            fail("GENERATION_BOUNDS")
        for k in ("request_id", "subject_id"):
            if not isinstance(e[k], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", e[k]):
                fail("INVALID_ID")
        for k in ("subject_digest", "source_manifest_digest", "consequence_digest"):
            if not isinstance(e[k], str) or not re.fullmatch(r"[0-9a-f]{64}", e[k]):
                fail("INVALID_DIGEST")
        utc(e["target_time"])
        utc(e["deadline"])
        e["owner"] = Address(e["owner"]).as_hex.lower()
        e["consumer"] = Address(e["consumer"]).as_hex.lower()
        if not isinstance(e["parties"], list) or len(e["parties"]) > 4:
            fail("PARTIES_BOUNDS")
        e["parties"] = sorted(set(Address(x).as_hex.lower() for x in e["parties"]))
        rid = e["request_id"]
        if rid in self.approved:
            if self.approved[rid] == canon(e):
                return
            fail("APPROVAL_REUSE")
        if len(self.approvals) >= 10000:
            fail("CAPACITY")
        subject = e["subject_id"]
        old_id = self.expected_subject.get(subject, "")
        if old_id:
            old = json.loads(self.approved[old_id])
            if e["generation"] != old["generation"] + 1 or e["supersedes"] != old_id:
                fail("APPROVAL_REVISION")
        elif e["generation"] != 1 or e["supersedes"]:
            fail("APPROVAL_REVISION")
        self.approved[rid] = canon(e)
        self.expected_subject[subject] = rid
        self.approvals.append(rid)

    def _eligible(self, cert):
        if cert["lifecycle_status"] != "CERTIFIED" or cert["unresolved_flags"] or not cert["coverage"]["complete_packet"]:
            return False
        if MODE == "EVENT":
            return cert["applies_at_target"]["OCCURRENCE"] is True
        effective = cert["intervals"]["EFFECTIVE"]
        upper = cert["first_publication_upper"]
        if effective is None or effective["lower"] is None or upper is None or cert["applies_at_target"]["EFFECTIVE"] is not True:
            return False
        # The signed observation upper bound is inclusive, unlike interval upper endpoints.
        return upper + int(self.notice_seconds) <= effective["lower"]

    @gl.public.write
    def receive_certificate(self, payload: str) -> None:
        if gl.message.sender_address != self.resolver:
            fail("RESOLVER_ONLY")
        if not isinstance(payload, str) or len(payload.encode("utf-8")) > 40000:
            fail("PAYLOAD_BOUNDS")
        try:
            p = json.loads(payload)
            cert = p["certificate"]
            operation = p["operation_id"]
            rid = cert["request_id"]
        except Exception:
            fail("PAYLOAD_JSON")
        if p["resolver"] != self.resolver.as_hex.lower() or p["consumer"] != gl.message.contract_address.as_hex.lower():
            fail("SENDER_BINDING")
        if rid not in self.approved:
            fail("REQUEST_NOT_APPROVED")
        expected = json.loads(self.approved[rid])
        if any(cert.get(k) != v for k, v in expected.items()) or cert["request_binding_digest"] != digest(expected):
            fail("CERTIFICATE_BINDING")
        if operation in self.receipts:
            r = self.receipts[operation]
            if r.payload != canon(p):
                fail("OPERATION_REUSE")
            gl.get_contract_at(self.resolver).emit(on="finalized").acknowledge(operation, digest(p), r.acknowledgement)
            return
        if len(self.history) >= 10000:
            fail("CAPACITY")
        delivery = gl.get_contract_at(self.resolver).view().get_delivery(operation)
        if delivery["consumer"] != gl.message.contract_address.as_hex.lower() or delivery["request_id"] != rid or delivery["payload_digest"] != digest(p):
            fail("DELIVERY_BINDING")
        subject = cert["subject_id"]
        last = self.last_applied_generation.get(subject, u64(0))
        stale = not delivery["valid"] or self.expected_subject[subject] != rid or cert["generation"] < last
        ack = "STALE" if stale else "APPLIED" if self._eligible(cert) else "BLOCKED"
        self.receipts[operation] = Receipt(rid, subject, u64(cert["generation"]), canon(p), ack, False)
        self.history.append(operation)
        if not stale:
            self.last_applied_generation[subject] = u64(cert["generation"])
            self.last_operation[subject] = operation
        gl.get_contract_at(self.resolver).emit(on="finalized").acknowledge(operation, digest(p), ack)

    @gl.public.write
    def execute(self, subject_id: str, action_id: str) -> None:
        self._owner()
        if not isinstance(action_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,96}", action_id):
            fail("ACTION_ID")
        if action_id in self.executed_operations:
            if self.executed_operations[action_id] == subject_id:
                return
            fail("ACTION_REUSE")
        state = self.get_state(subject_id)
        if not state["permitted"]:
            fail("ACTION_BLOCKED")
        operation = state["operation_id"]
        if self.receipts[operation].executed:
            fail("CONSEQUENCE_ALREADY_EXECUTED")
        if len(self.executed_operations) >= 10000:
            fail("CAPACITY")
        self.executed_operations[action_id] = subject_id
        self.receipts[operation].executed = True

    @gl.public.view
    def get_configuration(self) -> dict:
        return {**self._config(), "owner": self.owner.as_hex.lower(), "resolver": self.resolver.as_hex.lower(), "mode": MODE, "notice_seconds": int(self.notice_seconds)}

    @gl.public.view
    def get_receipt(self, operation_id: str) -> dict:
        if operation_id not in self.receipts:
            return {}
        r = self.receipts[operation_id]
        return {"request_id": r.request_id, "subject_id": r.subject_id, "generation": int(r.generation), "acknowledgement": r.acknowledgement, "executed": r.executed, "payload_digest": digest(json.loads(r.payload))}

    @gl.public.view
    def get_state(self, subject_id: str) -> dict:
        operation = self.last_operation.get(subject_id, "")
        if not operation:
            return {"permitted": False, "active": False, "unresolved": True, "operation_id": "", "generation": 0}
        r = self.receipts[operation]
        cert = json.loads(r.payload)["certificate"]
        delivery = gl.get_contract_at(self.resolver).view().get_delivery(operation)
        current = self.expected_subject.get(subject_id, "") == r.request_id and delivery["valid"]
        permitted = current and r.acknowledgement == "APPLIED"
        active = permitted and r.executed
        if active and MODE == "NOTICE":
            raw = re.sub(r"\\.\\d+(?=Z|[+-]\\d{2}:\\d{2}$)", "", gl.message_raw["datetime"])
            now = utc(raw)
            effective = cert["intervals"]["EFFECTIVE"]
            active = now >= effective["lower"] and (effective["upper"] is None or now < effective["upper"])
        return {"permitted": permitted, "active": active, "unresolved": cert["lifecycle_status"] == "UNKNOWN" or not current, "operation_id": operation, "generation": int(r.generation), "acknowledgement": r.acknowledgement, "executed": r.executed}

    @gl.public.view
    def list_receipts(self, offset: int, limit: int) -> list[str]:
        if type(offset) is not int or type(limit) is not int or not 0 <= offset <= 10000 or not 1 <= limit <= 50:
            fail("PAGE_BOUNDS")
        return [self.history[i] for i in range(offset, min(offset + limit, len(self.history)))]
'''


def build():
    for filename, name, mode in (
        ("notice_gate.py", "DeprecationGate", "NOTICE"),
        ("event_registry.py", "EventRegistry", "EVENT"),
    ):
        text = TEMPLATE.replace('MODE consumer', mode + ' consumer').replace('MODE_VALUE', mode).replace('CLASS_NAME', name)
        (ROOT / 'contracts' / filename).write_text(text)


if __name__ == '__main__':
    build()
