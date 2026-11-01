"""Synthetic adversarial fixtures. Production and Studio use real web/model I/O."""
import hashlib
import json
import pytest


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canon(value).encode()).hexdigest()


@pytest.fixture
def packet(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.sender = direct_alice
    direct_vm.warp("2026-10-31T12:00:00Z")
    c = direct_deploy("contracts/janus.py", 100)
    from genlayer import Address
    owner = Address(direct_alice).as_hex.lower()
    consumer = Address(direct_bob)
    config = {"channel": "PUBLIC_SIGNED_OBSERVATION", "url_prefix": "https://evidence.example/", "scope": "service", "public_evidence_url": "https://evidence.example/principal"}
    c.register_authority("issuer", Address(direct_alice), canon(config))
    c.accept_authority("issuer")
    text = "The service becomes effective from 2030-01-01T00:00:00Z. The launch occurred on 2025-01-01T00:00:00Z."
    raw = text.encode()
    record = {"source_id": "source1", "authority_id": "issuer", "channel": config["channel"], "url": "https://evidence.example/record", "raw_sha256": hashlib.sha256(raw).hexdigest(), "byte_length": len(raw), "revision": 1, "subject_id": "document", "scope": "service", "spans": [{"span_id": "temporal", "start": 0, "end": len(raw), "text": text}], "supersedes": ""}
    direct_vm.mock_web(r"https://evidence.example/.*", {"status": 200, "body": raw})
    c.observe_source(canon(record))
    rules = {"revision": 1, "date_only_utc": True, "rules": [{"rule_id": "meaning", "instruction": "Resolve the stated effective and occurrence dates. Apply all controlling exceptions and corrections."}], "required_roles": ["EFFECTIVE", "PUBLICATION"]}
    c.register_temporal_policy("temporal", canon(rules), canon({"authorities": ["issuer"], "publication_support": "SIGNED_PUBLIC_OBSERVATION"}))
    consequence = digest({"action": "test_only"})
    direct_vm.sender = direct_bob
    c.register_consumer(consumer, canon({"policy_id": "temporal", "policy_revision": 1, "consequence_digest": consequence, "unresolved_consequence": "BLOCK"}))
    direct_vm.sender = direct_alice
    proposition = "The service applies from its effective date."
    manifest = {"records": ["source1"], "assertions": [{"assertion_id": "effect", "question": "When does the service become effective?", "rule_id": "meaning"}, {"assertion_id": "event", "question": "When did the launch occur?", "rule_id": "meaning"}]}
    envelope = {"request_id": "request1", "owner": owner, "parties": [], "policy_id": "temporal", "policy_revision": 1, "subject_id": "service", "subject_digest": digest(proposition), "source_manifest_digest": digest(manifest), "consumer": consumer.as_hex.lower(), "consequence_digest": consequence, "generation": 1, "deadline": "2031-01-01T00:00:00Z", "target_time": "2030-01-01T00:00:00Z", "supersedes": ""}
    output = {"assertions": [{"assertion_id": "effect", "role": "EFFECTIVE", "qualifier": "FROM", "source_id": "source1", "span_id": "temporal", "start": "2030-01-01T00:00:00Z", "end": ""}, {"assertion_id": "event", "role": "OCCURRENCE", "qualifier": "EXACT", "source_id": "source1", "span_id": "temporal", "start": "2025-01-01T00:00:00Z", "end": ""}], "flags": [], "exceptions": []}
    direct_vm.mock_llm(r".*", canon(output))
    return {"c": c, "record": record, "rules": rules, "manifest": manifest, "envelope": envelope, "output": output, "proposition": proposition, "owner": direct_alice, "consumer": consumer, "raw": raw}


def open_packet(p):
    e = p["envelope"]
    p["c"].open_record(e["request_id"], p["proposition"], e["target_time"], canon(p["manifest"]), canon(e))


def assess_packet(p):
    open_packet(p)
    p["c"].reserve_assessment(p["envelope"]["request_id"], 1)
    p["c"].assess_intervals(p["envelope"]["request_id"], 1)
