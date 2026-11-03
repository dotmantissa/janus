# Contract interfaces

Contracts are standalone Python sources. `Address` parameters must be encoded as typed calldata addresses (`genlayer_py.types.calldata.CalldataAddress` in the Python client). JSON parameters are UTF-8 strings. IDs use `[A-Za-z0-9_.:-]{1,96}`; digests are lowercase, 64-character SHA-256 hex strings.

## Canonical commitments

All commitments use this encoding, without a trailing newline:

```python
import hashlib
import json

def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

def digest(value):
    return hashlib.sha256(canon(value).encode("utf-8")).hexdigest()
```

`raw_sha256` hashes the original response bytes directly. `subject_digest` hashes the canonical JSON **string** containing the proposition. `source_manifest_digest` hashes the normalized manifest object. Sort manifest `records` by source ID and `assertions` by assertion ID before hashing. Sort and deduplicate envelope `parties`; normalize owner and consumer addresses to lowercase before approval. Unknown or additional JSON keys are rejected.

## Authority and source registration

Deploy `Janus(capacity: int)` with capacity from 1 through 10,000. The sender becomes registry owner.

| Write method | Arguments and behavior |
| --- | --- |
| `register_authority` | `authority_id: str, principal: Address, configuration: str`; owner registers an immutable principal and channel |
| `accept_authority` | `authority_id: str`; principal accepts that configuration |
| `observe_source` | `record: str`; principal commits a complete source revision, independently fetched in consensus |
| `confirm_source` | `source_id: str`; authenticated self-message emitted on observation finalization; callers cannot establish availability themselves |
| `retry_source_confirmation` | `source_id: str`; principal retries the finalized callback, at most three broadcasts total |
| `register_temporal_policy` | `policy_id: str, interpretation_rules: str, accepted_time_sources: str`; owner appends a consecutive policy revision |
| `register_consumer` | `consumer: Address, configuration: str`; consumer contract registers itself through its `register` method |

Authority configuration has exactly `channel`, `url_prefix`, `scope`, and `public_evidence_url`, all nonempty strings at most 512 characters. The HTTPS prefix limits accepted source URLs; it does not establish the organization's ownership of the principal. The deployment owner audits that relationship. Current URLs support ordinary HTTPS host/path characters and reject credentials, queries, fragments, percent encoding and dot-path traversal.

A source record has this shape; offsets count UTF-8 **bytes**, with an exclusive end:

```json
{
  "source_id": "schedule-1",
  "authority_id": "schedule-observer",
  "channel": "PUBLIC_RECORD",
  "url": "https://publisher.example/immutable/schedule.json",
  "raw_sha256": "<sha256 of complete response bytes>",
  "byte_length": 1234,
  "revision": 1,
  "subject_id": "schedule",
  "scope": "release-schedule",
  "spans": [{"span_id": "maintenance", "start": 100, "end": 140, "text": "<exact decoded bytes at these offsets>"}],
  "supersedes": ""
}
```

The placeholders above must be replaced with measured values. Each revision needs a new source ID, the same authority/subject, consecutive revision number, and the prior source ID in `supersedes`. An observation invalidates its predecessor immediately, while the new source stays unusable until its finalized confirmation. `get_source` returns `observed_upper: null`, `confirmed: false`, and `valid: false` while confirmation is pending. A successful self-callback fixes an immutable inclusive upper bound using its network transaction time, after public observation finalization.

Interpretation rules have exactly these keys:

```json
{
  "revision": 1,
  "date_only_utc": true,
  "rules": [{"rule_id": "maintenance", "instruction": "Use maintenance as the inclusive effective start and end as the exclusive end."}],
  "required_roles": ["EFFECTIVE", "PUBLICATION"]
}
```

Accepted time sources have exactly `authorities: ["schedule-observer"]` and `publication_support: "SIGNED_PUBLIC_OBSERVATION"`. Roles are `OCCURRENCE`, `EFFECTIVE`, and `PUBLICATION`. Historical publication headings never satisfy availability support on their own.

Consumer registration configuration has exactly `policy_id`, `policy_revision`, `consequence_digest`, and `unresolved_consequence: "BLOCK"`. Get it from the consumer's `get_configuration`; do not compute a different consequence configuration off chain.

## Requests and assessment

A request manifest contains exactly `records` and `assertions`:

```json
{
  "records": ["schedule-1"],
  "assertions": [{"assertion_id": "effect", "question": "When is maintenance effective?", "rule_id": "maintenance"}]
}
```

The owner-approved request envelope contains exactly:

| Field | Binding |
| --- | --- |
| `request_id` | New request ID |
| `owner`, `parties` | Owner address and up to four additional assessment/delivery addresses |
| `policy_id`, `policy_revision` | Immutable interpretation and trust policy |
| `subject_id`, `subject_digest` | Application subject ID and canonical proposition commitment |
| `source_manifest_digest` | Normalized manifest commitment |
| `consumer`, `consequence_digest` | Consumer contract and its configured action commitment |
| `generation` | 1 initially, then consecutive per consumer and application subject |
| `deadline` | Explicit-offset UTC-compatible timestamp after creation time |
| `target_time` | Locked instant against which intervals are evaluated |
| `supersedes` | Empty initially; prior request ID on a successor |

An executable construction example is in [the live flow](../scripts/live_flow.py). The consumer owner first calls `approve_request(canon(envelope))`. The request owner then calls `open_record(request_id, proposition, target_time, canon(manifest), canon(envelope))` on Janus. Approving a successor blocks the previous consumer state immediately.

| Write method | Arguments and behavior |
| --- | --- |
| `open_record` | `request_id: str, proposition: str, target_time: str, source_manifest: str, envelope: str`; locks the request |
| `reserve_assessment` | `request_id: str, attempt: int`; reserves consecutive attempt 1, 2 or 3 in a separate transaction |
| `assess_intervals` | `request_id: str, attempt: int`; independently evaluates every committed source and requested assertion |
| `expire_record` | `request_id: str`; exposes UNKNOWN after deadline or three reserved attempts |
| `quarantine` | `kind: str, record_id: str, reason_digest: str`; owner permanently invalidates authority, source, policy or request |

Wait for each reservation's successful finalized receipt before assessment. Failed execution does not consume a new application reservation automatically. After an unavailable outcome on attempts 1 or 2, the request remains OPEN; reserve the next attempt explicitly. After a malformed assessment fails, the separately recorded reservation remains consumed. Network validator rotations are managed by GenLayer independently of these application attempts.

Quarantine kinds are `AUTHORITY`, `SOURCE`, `POLICY`, and `REQUEST`. A policy record ID is `policy_id:revision`, for example `notice-v1:1`. No quarantine operation erases historical certificates or restores validity.

## Certificate and finalized delivery

`get_interval_certificate(request_id)` returns `status`, current `valid`, `superseded_by`, `attempts`, `assessed_attempt`, the locked `envelope`, and `certificate` (empty before an assessment). The certificate repeats every envelope field and adds:

| Field | Meaning |
| --- | --- |
| `proposition`, `request_binding_digest` | Exact text and canonical approved-envelope commitment |
| `lifecycle_status` | CERTIFIED or UNKNOWN; inspect wrapper status for an OPEN transient assessment |
| `decision_vector` | Assertion IDs, roles, qualifiers, normalized intervals, and source/hash/byte witnesses |
| `intervals` | OCCURRENCE, EFFECTIVE and PUBLICATION intervals or null |
| `applies_at_target` | OCCURRENCE and EFFECTIVE booleans, or null when unsupported |
| `first_publication_upper`, `publication_support` | Inclusive public-availability bound and controlling observation/hash provenance |
| `controlling_rule_ids`, `exceptions` | Policy rule IDs and source/span/rule exception witnesses |
| `coverage`, `unresolved_flags` | Complete-packet status, missing roles and unresolved reasons |
| `superseded_by` | Successor present when the certificate was formed; wrapper validity supplies current state |

Intervals contain `lower`, `upper`, `lower_inclusive: true`, `upper_inclusive: false`. Null bounds mean unbounded or unknown, never independently verified timeless truth. See [precise interval semantics and ceilings](limits.md).

| Write method | Arguments and behavior |
| --- | --- |
| `publish_to` | `request_id: str, consumer: Address, operation_id: str`; journals payload and emits finalized `receive_certificate` |
| `retry_delivery` | `operation_id: str`; retries an unacknowledged, current operation, at most three broadcasts total |
| `acknowledge` | `operation_id: str, payload_digest: str, acknowledgement: str`; bound consumer only; immutable APPLIED/BLOCKED/STALE |

Read `get_delivery(operation_id)` until `acknowledged` is true. Its fields are `request_id`, `consumer`, `payload_digest`, current `valid`, `acknowledged`, `acknowledgement`, and `broadcasts`. A synchronous certificate view alone is not finality evidence. Duplicate identical operations are idempotent; conflicting reuse is rejected.

Other Janus views are `get_source(source_id)`, `get_policy(policy_id, revision)`, `get_consumer(consumer: Address)`, `get_quarantine_reason(kind, record_id)`, and `list_history(kind, offset, limit)`. History kinds are `REQUEST`, `SOURCE`, `DELIVERY`; limits are 1–50.

## Consumer interfaces

Deploy `DeprecationGate` or `EventRegistry` with `(resolver: Address, policy_id: str, policy_revision: int, notice_seconds: int)`. EventRegistry requires zero notice seconds. The sender becomes that consumer's owner.

| Method | Behavior |
| --- | --- |
| `register()` | Owner emits finalized resolver registration |
| `approve_request(envelope: str)` | Owner approves the exact request and next subject generation |
| `receive_certificate(payload: str)` | Resolver-only finalized delivery; verifies all bindings, journal and current validity; emits acknowledgement |
| `execute(subject_id: str, action_id: str)` | Owner executes the permitted consequence with a unique action ID; rechecks current validity |
| `get_configuration()` | Resolver, owner, mode, policy, notice period and consequence commitment |
| `get_receipt(operation_id: str)` | Applied generation, acknowledgement, execution flag and payload digest |
| `get_state(subject_id: str)` | Current permitted/active/unresolved flags, operation, generation, acknowledgement and execution flag |
| `list_receipts(offset: int, limit: int)` | Paginated operation IDs, at most 50 |

The notice consumer schedules activation inside the effective interval after execution. The event consumer records the certified occurrence consequence immediately. Repeating an existing action ID for the same subject is an idempotent acknowledgement of that prior execution; it does not execute a new consequence. Choose a new action ID for a new generation.
