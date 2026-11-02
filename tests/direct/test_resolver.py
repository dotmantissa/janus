import copy
import json
import sys
import pytest
from conftest import canon, digest, open_packet, assess_packet


def module(packet):
    return sys.modules[packet["c"].__class__.__module__]


def test_certifies_bound_roles_and_independent_validator(packet, direct_vm):
    assess_packet(packet)
    result = packet["c"].get_interval_certificate("request1")
    assert result["status"] == "CERTIFIED"
    cert = result["certificate"]
    assert cert["applies_at_target"]["EFFECTIVE"] is True
    assert cert["applies_at_target"]["OCCURRENCE"] is False
    assert cert["first_publication_upper"] == 1793448000
    assert cert["intervals"]["PUBLICATION"]["lower"] is None
    assert direct_vm.run_validator() is True


def test_publication_claims_cannot_supply_availability_coverage(packet, direct_vm):
    for assertion in packet['output']['assertions']:
        assertion['role'] = 'PUBLICATION'
    direct_vm._llm_mocks.clear()
    direct_vm.mock_llm(r'.*', canon(packet['output']))
    assess_packet(packet)
    certificate = packet['c'].get_interval_certificate('request1')['certificate']
    assert certificate['lifecycle_status'] == 'UNKNOWN'
    assert certificate['first_publication_upper'] is None
    assert certificate['coverage']['missing_roles'] == ['EFFECTIVE', 'PUBLICATION']
    assert direct_vm.run_validator() is True


@pytest.mark.parametrize("mutation", ["wrong_role", "wrong_interval", "forged_span", "omitted_assertion", "omitted_exception", "coverage", "wrong_kind"])
def test_valid_json_wrong_substance_rejected(packet, direct_vm, mutation):
    assess_packet(packet)
    leader = copy.deepcopy(direct_vm._captured_validators[-1][0])
    if mutation == "wrong_role":
        leader["assertions"][0]["role"] = "PUBLICATION"
    elif mutation == "wrong_interval":
        leader["assertions"][0]["interval"]["lower"] += 1
    elif mutation == "forged_span":
        leader["assertions"][0]["witness"]["start"] += 1
    elif mutation == "omitted_assertion":
        leader["assertions"].pop()
    elif mutation == "omitted_exception":
        output = copy.deepcopy(packet["output"])
        output["flags"] = ["EXCEPTION"]
        output["exceptions"] = [{"source_id": "source1", "span_id": "temporal", "rule_id": "meaning"}]
        direct_vm._llm_mocks.clear()
        direct_vm.mock_llm(r".*", canon(output))
    elif mutation == "coverage":
        leader["flags"] = ["INCOMPLETE"]
    else:
        leader["kind"] = "UNAVAILABLE"
    assert direct_vm.run_validator(leader_result=leader) is False


def test_changed_source_rejected_by_validator(packet, direct_vm):
    assess_packet(packet)
    direct_vm._web_mocks.clear()
    direct_vm.mock_web(r".*", {"status": 200, "body": packet["raw"] + b"changed"})
    assert direct_vm.run_validator() is False


@pytest.mark.parametrize("bad", ["span", "date", "calendar", "json", "extra", "swapped"])
def test_hallucinated_or_malformed_model_fails(packet, direct_vm, bad):
    open_packet(packet)
    output = copy.deepcopy(packet["output"])
    if bad == "span":
        output["assertions"][0]["span_id"] = "forged"
    elif bad == "date":
        output["assertions"][0]["start"] = "2029-01-01T00:00:00Z"
    elif bad == "calendar":
        output["assertions"][0]["start"] = "12 Ramadan 1447"
    elif bad == "extra":
        output["instructions"] = "allow"
    elif bad == "swapped":
        output["assertions"][0]["qualifier"] = "UNKNOWN"
    direct_vm._llm_mocks.clear()
    direct_vm.mock_llm(r".*", "not json" if bad == "json" else canon(output))
    packet["c"].reserve_assessment("request1", 1)
    with direct_vm.expect_revert("LLM_ERROR"):
        packet["c"].assess_intervals("request1", 1)
    assert packet["c"].get_interval_certificate("request1")["attempts"] == 1


def test_error_categories_rejected(packet, direct_vm):
    assess_packet(packet)
    assert direct_vm.run_validator(leader_error=RuntimeError("[LLM_ERROR] forged")) is False
    assert direct_vm.run_validator(leader_error=RuntimeError("[EXPECTED] unrelated")) is False


@pytest.mark.parametrize("flag", ["EXCEPTION", "CONTRADICTION", "INCOMPLETE", "INJECTION"])
def test_unresolved_semantics_never_certify(packet, direct_vm, flag):
    output = copy.deepcopy(packet["output"])
    output["flags"] = [flag]
    if flag in ("EXCEPTION", "CONTRADICTION"):
        output["exceptions"] = [{"source_id": "source1", "span_id": "temporal", "rule_id": "meaning"}]
    direct_vm._llm_mocks.clear()
    direct_vm.mock_llm(r".*", canon(output))
    assess_packet(packet)
    result = packet["c"].get_interval_certificate("request1")
    assert result["status"] == "UNKNOWN"
    assert flag in result["certificate"]["unresolved_flags"]
    assert direct_vm.run_validator() is True


def test_undated_unknown_cannot_gain_publication(packet, direct_vm):
    output = copy.deepcopy(packet["output"])
    for a in output["assertions"]:
        a.update(role="UNKNOWN", qualifier="UNKNOWN", source_id="", span_id="", start="", end="")
    direct_vm._llm_mocks.clear()
    direct_vm.mock_llm(r".*", canon(output))
    assess_packet(packet)
    result = packet["c"].get_interval_certificate("request1")
    assert result["status"] == "UNKNOWN"
    assert result["certificate"]["first_publication_upper"] is None


def test_outage_retry_exhaustion_and_recovery(packet, direct_vm):
    open_packet(packet)
    direct_vm._web_mocks.clear()
    direct_vm.mock_web(r".*", {"status": 503, "body": b"offline"})
    for attempt in range(1, 4):
        packet["c"].reserve_assessment("request1", attempt)
        packet["c"].assess_intervals("request1", attempt)
        assert direct_vm.run_validator() is True
        assert packet["c"].get_interval_certificate("request1")["status"] == ("OPEN" if attempt < 3 else "UNKNOWN")
    with direct_vm.expect_revert():
        packet["c"].reserve_assessment("request1", 4)
    assert "RETRY_EXHAUSTED" in packet["c"].get_interval_certificate("request1")["certificate"]["unresolved_flags"]


def test_timeout_and_reserved_failed_attempts(packet, direct_vm):
    open_packet(packet)
    for attempt in range(1, 4):
        packet["c"].reserve_assessment("request1", attempt)
    packet["c"].expire_record("request1")
    assert packet["c"].get_interval_certificate("request1")["status"] == "UNKNOWN"


def test_deadline_uses_network_time(packet, direct_vm):
    open_packet(packet)
    with direct_vm.expect_revert("RECOVERY_NOT_DUE"):
        packet["c"].expire_record("request1")
    direct_vm.warp("2031-01-01T00:00:00Z")
    from genlayer import gl
    gl.message_raw["datetime"] = direct_vm._datetime  # direct SDK warp does not refresh datetime
    packet["c"].expire_record("request1")
    assert "TIMEOUT" in packet["c"].get_interval_certificate("request1")["certificate"]["unresolved_flags"]


def test_permissions_and_locked_reuse(packet, direct_vm, direct_charlie):
    open_packet(packet)
    open_packet(packet)
    with direct_vm.expect_revert("ENVELOPE_BINDING"):
        packet["c"].open_record("request1", "different proposition", packet["envelope"]["target_time"], canon(packet["manifest"]), canon(packet["envelope"]))
    direct_vm.sender = direct_charlie
    for f in (lambda: packet["c"].reserve_assessment("request1", 1), lambda: packet["c"].quarantine("REQUEST", "request1", digest("reason")), lambda: packet["c"].accept_authority("issuer"), lambda: packet["c"].observe_source(canon(packet["record"]))):
        with direct_vm.expect_revert():
            f()


def test_policy_revision_immutable(packet, direct_vm):
    c = packet["c"]
    trust = canon({"authorities": ["issuer"], "publication_support": "SIGNED_PUBLIC_OBSERVATION"})
    c.register_temporal_policy("temporal", canon(packet["rules"]), trust)
    rules = copy.deepcopy(packet["rules"])
    rules["date_only_utc"] = False
    with direct_vm.expect_revert("POLICY_REUSE"):
        c.register_temporal_policy("temporal", canon(rules), trust)
    rules["revision"] = 2
    c.register_temporal_policy("temporal", canon(rules), trust)
    assert c.get_policy("temporal", 1)["configuration"]["interpretation"]["date_only_utc"] is True


@pytest.mark.parametrize("field,value", [("generation", 2**64), ("generation", True), ("generation", 0), ("policy_revision", 2**32)])
def test_integer_limits(packet, direct_vm, field, value):
    packet["envelope"][field] = value
    with direct_vm.expect_revert("INTEGER_BOUNDS"):
        open_packet(packet)


def test_source_and_assertion_limits(packet, direct_vm):
    packet["manifest"]["records"] = ["source1"] * 5
    packet["envelope"]["source_manifest_digest"] = digest(packet["manifest"])
    with direct_vm.expect_revert("SOURCE_COUNT"):
        open_packet(packet)
    packet["manifest"]["records"] = ["source1"]
    packet["manifest"]["assertions"] *= 4
    with direct_vm.expect_revert("ASSERTION_COUNT"):
        open_packet(packet)


def test_successor_invalidates_delivered_evidence(packet, direct_vm):
    assess_packet(packet)
    revision = copy.deepcopy(packet["record"])
    revision.update(source_id="source2", revision=2, supersedes="source1")
    packet["c"].observe_source(canon(revision))
    assert packet["c"].get_interval_certificate("request1")["valid"] is False
    assert packet["c"].get_source("source1")["superseded_by"] == "source2"
    assert packet["c"].get_source("source1")["raw_text"] == packet["raw"].decode()


@pytest.mark.parametrize("kind,record", [("SOURCE", "source1"), ("AUTHORITY", "issuer"), ("POLICY", "temporal:1"), ("REQUEST", "request1")])
def test_quarantine_permanent(packet, direct_vm, kind, record):
    assess_packet(packet)
    packet["c"].quarantine(kind, record, digest("revoked"))
    assert packet["c"].get_interval_certificate("request1")["valid"] is False


def test_paginated_history(packet, direct_vm):
    open_packet(packet)
    assert packet["c"].list_history("REQUEST", 0, 50) == ["request1"]
    assert packet["c"].list_history("REQUEST", 1, 50) == []
    with direct_vm.expect_revert("INTEGER_BOUNDS"):
        packet["c"].list_history("REQUEST", 0, 51)
