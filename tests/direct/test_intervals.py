import sys
import pytest
from conftest import assess_packet, canon


@pytest.fixture
def temporal(packet):
    return sys.modules[packet["c"].__class__.__module__]


@pytest.mark.parametrize("timestamp,expected", [
    ("1970-01-01T00:00:00Z", 0),
    ("2025-01-01T01:00:00+01:00", 1735689600),
    ("2024-12-31T19:00:00-05:00", 1735689600),
    ("9999-12-31T23:59:59Z", 253402300799),
])
def test_utc_offset_and_integer_extremes(temporal, timestamp, expected):
    assert temporal.utc(timestamp) == expected


@pytest.mark.parametrize("timestamp", ["2025-01-01", "2025-01-01T00:00:00", "2025-01-01T00:00:60Z", "2025-02-29T00:00:00Z", "1969-12-31T23:59:59Z", "1447 Ramadan 1", "2025-01-01T00:00:00+14:01", "2025-01-01T00:00:00+00:60"])
def test_unsupported_times(temporal, direct_vm, timestamp):
    with direct_vm.expect_revert("UNSUPPORTED_TIME" if not timestamp.startswith("1969") else "INTEGER_BOUNDS"):
        temporal.utc(timestamp)


def test_date_only_explicit_policy(temporal, direct_vm):
    assert temporal.utc("2024-02-29", True) == temporal.utc("2024-02-29T00:00:00Z")
    with direct_vm.expect_revert("UNSUPPORTED_TIME"):
        temporal.utc("2024-02-29", False)


def test_intersection_and_endpoint_boundaries(temporal, direct_vm):
    a = temporal.interval(10, 20)
    b = temporal.interval(20, 30)
    assert temporal.intersect(a, b) is None
    assert temporal.intersect(a, temporal.interval(19, None)) == temporal.interval(19, 20)
    assert temporal.intersect(temporal.interval(None, 20), temporal.interval(10, None)) == a
    assert temporal.intersect(temporal.interval(None, None), a) == a
    with direct_vm.expect_revert("EMPTY_INTERVAL"):
        temporal.interval(10, 10)


def test_backdated_heading_does_not_backdate_publication(packet, direct_vm):
    packet["output"]["assertions"][1]["role"] = "PUBLICATION"
    direct_vm._llm_mocks.clear()
    direct_vm.mock_llm(r".*", canon(packet["output"]))
    assess_packet(packet)
    cert = packet["c"].get_interval_certificate("request1")["certificate"]
    assert cert["first_publication_upper"] == 1793448000
    assert cert["first_publication_upper"] > 1735689600
    assert cert["intervals"]["PUBLICATION"]["lower"] is None


def test_vmerror_and_expected_failure_agreement(packet, direct_vm):
    from genlayer import gl
    c = packet["c"]
    assert c._agree(gl.vm.VMError("OOM"), lambda: {}) is False
    def same_failure():
        raise gl.vm.UserError("[EXPECTED] matching")
    assert c._agree(gl.vm.UserError("[EXPECTED] matching"), same_failure) is True
    assert c._agree(gl.vm.UserError("[EXPECTED] different"), same_failure) is False
    assert c._agree(gl.vm.UserError("[LLM_ERROR] matching"), same_failure) is False


def test_nondet_closures_pickle(packet, direct_vm):
    direct_vm._check_pickling = True
    assess_packet(packet)
    assert direct_vm.run_validator() is True
