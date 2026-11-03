# Verification record

Verification is recorded for the pinned source and Python 3.14 environment. Saved receipt files are raw network responses; synthetic fault fixtures exist only in the direct tests.

## Local verification

The fresh environment at `.venv/replay` was created without system `ensurepip`, then populated using an existing pip targeting that environment:

```bash
python3 -m venv --without-pip .venv/replay
python3 -m pip --python .venv/replay/bin/python install -r requirements.lock
python3 -m pip --python .venv/replay/bin/python check
.venv/replay/bin/genvm-lint check contracts/janus.py
.venv/replay/bin/genvm-lint check contracts/notice_gate.py
.venv/replay/bin/genvm-lint check contracts/event_registry.py
.venv/replay/bin/python -m pytest tests/direct -v
```

Results: no broken dependencies, all three contracts pass AST and SDK validation, and **91 direct tests pass** in 9.56 seconds in the final clean-environment replay on 2026-11-03. The earlier replay passed 90 tests in 4.02 seconds; the added case verifies that cached child receipts are reused and still checked for finalized execution success. All six transaction-journal regression cases pass. Logs: [installation](../evidence/clean-replay.log), [lint](../evidence/lint.log), [final tests](../evidence/direct-tests-final.log), [earlier tests](../evidence/clean-replay-tests.log), [journal regression checks](../evidence/journal-tests.log). The lock file includes transitive dependencies; the short requirements file pins the five direct dependencies.

Direct verification covers:

| Area | Executed checks |
| --- | --- |
| Temporal normalization | UTC offsets, date-only policy, invalid calendars/timezones, second/day endpoints, interval intersections and integer bounds |
| Independent validation | Explicit `run_validator()` accepts a matching independent derivation and rejects changed roles, intervals, witnesses, omitted assertions/exceptions, changed source bytes and fabricated result kinds |
| Model and source faults | Hallucinated dates, malformed output, web outages, VM/UserError handling, omitted full-packet documents, UTF-8 and span integrity |
| Completeness and bounds | Four sources with six assertions, oversized joint packets, per-source limits, no truncation |
| Availability | Backdated headings cannot establish old availability; publication claims cannot supply observation coverage; pending confirmation cannot support assessment |
| Confirmation | Self-sender authentication, post-observation callback timestamp, immutable repeated confirmation, principal-only retries with three finalized broadcasts |
| Authority and state | Immutable policy revisions, locked envelope reuse, separate roles, colon-containing authority/subject IDs, URL escape rejection, permanent quarantine and supersession |
| Recovery | Separate attempt reservations, three-attempt recovery, actual network-time field, deadline expiry, bounded histories |
| Consumer and delivery | Sender/binding checks, finalized emit selection, duplicate/reordered callbacks, stale generations, blocked successors, unresolved outcomes, acknowledgements, delivery retry limits and action-time validity |
| Transaction tooling | Persist submission before polling, resume interrupted polls, reject conflicting operation reuse, require cached finality and execution success, reject another signer or path traversal |

The direct runtime executes leader code by default. The independent validator checks listed above explicitly invoke captured validators with separate or adversarial outcomes. Tests use synthetic web/model outputs and callback/source views; they do not prove network consensus, finality, or network callback authentication. The installed test runtime's `warp` helper does not refresh `gl.message_raw["datetime"]`; time-bound tests explicitly update that field. Production contracts read only the real network field.

## Studio deployment and live verification

Current deployment: [metadata](../evidence/deployment.json), resolver [journal](../evidence/studio-v2/journal.json), [notice journal](../evidence/studio-v2-notice/journal.json), and [event journal](../evidence/studio-v2-event/journal.json).

| Contract | Address | Finalized deployment transaction |
| --- | --- | --- |
| Janus | `0x18c6F68B614a3aBca5e4967b13290CCfE782E922` | `0xeeda2567a18f12b1d30d1f7fdf1de99b1034e4486a6806e5cdcecb5988e3af4d` |
| Notice | `0xBfEBCa71DA46ccaa81F019EF371e49F70daF5857` | `0xc36e768f893c50c95004f8c7449b3229a4399aba9d69e1011995b94d3f3d7fac` |
| Event | `0xC55C927D5A5f1401aC0017a8A9C8EdC6Da0BB59B` | `0x612a901ded6c838b36b00a910bb818902e999a99ca50d0fe144027756aff2ffc` |

All three deployment receipts assert FINALIZED and execution success. Deployment metadata commits the SHA-256 of each local source and records separate consumer owners. The initial runtime compatibility probe is preserved in [its receipt](../evidence/runtime-receipt.json).

An older resolver at `0xaD877A491C467E0bbb0a619675cC6aaA643BD0BA` predates finalized source confirmation. Its receipts are retained under `evidence/studio*`; its [archived deployment metadata](../evidence/deployment-0xaD877A491C467E0bbb0a619675cC6aaA643BD0BA.json) is historical evidence, not the current implementation. Resuming its flow exposed the mismatch; the current flow rejects deployment metadata without source commitments. An initial new-deployment attempt hit Studio's reported 500 requests/hour cap before returning a transaction hash; a later attempt succeeded.

Both real public source observations and their authenticated finalized self-confirmations completed successfully. Their confirmed views are preserved for the [schedule](../evidence/source-confirmed-node-schedule-1.json) and [release](../evidence/source-confirmed-node-release-1.json). Each observation has four validators and three agreeing votes with `leader_only: false`. The two notice consumer cases have completed assessment, finalized delivery, acknowledgement and action checks. Both event cases remain pending after Studio rejected the first event request submission with its reported 500-requests/hour rate limit. Two recovery retries at five-minute intervals also failed on read-only RPC calls. The retry process has stopped; resuming the command below uses the original journals after the external quota resets.

The flow uses two complete immutable public records:

| Source | Bytes | SHA-256 |
| --- | --- | --- |
| Node.js release schedule | 3,254 | `50fe35a4df02398f741fdffbc666aceca323fcdb7f46d05af93145bf610d0049` |
| Node.js v24.1.0 release announcement | 21,059 | `fe45d6ed72cd08143dc86976e07186c25aca559f25ede9585ec3ab38d4cf46d7` |

Their committed URLs and byte spans are in [source manifests](../evidence/live-source-manifests.json). The schedule tests an adequate notice period for v26 maintenance and late availability for v24 maintenance. The release announcement tests an occurrence target inside its release day and another at the exclusive next-day boundary. Each source observation and assessment must have at least two agreeing validator votes with `leader_only: false`. Parent and triggered child transactions must finalize successfully; intentionally blocked execute transactions must finalize with execution failure.

Executed consumer results are saved in [live results](../evidence/live-results.json). The [resumption log](../evidence/live-flow-v3-resume.log) preserves the transient network failure, safe recovery and rate-limit rejection.

| Case | Certified interval (UTC, upper exclusive) | Acknowledgement | Execution |
| --- | --- | --- | --- |
| notice-permitted | v26 maintenance: 2027-10-20 to 2029-04-30 | APPLIED, finalized acknowledgement | SUCCESS; scheduled, currently inactive |
| notice-refused | v24 maintenance: 2026-10-20 to 2028-04-30 | BLOCKED, finalized acknowledgement | Expected ACTION_BLOCKED failure |
| event-permitted | Pending assessment | Pending | Pending |
| event-refused | Pending assessment | Pending | Pending |

Both notice assessment receipts have four validators and three agreeing votes with `leader_only: false`. Their final-round monitoring records 15.924 and 15.682 seconds from PENDING to ACCEPTED, respectively; these measurements exclude the later finalization wait and are not latency guarantees. The schedule availability upper bound is 2026-11-02T10:36:02Z. It supports the required 30 days before v26 maintenance and arrives after v24 maintenance has already begun.

To resume the same deployment:

```bash
.venv/bin/python scripts/deploy.py --journal studio-v2
.venv/bin/python scripts/live_flow.py
.venv/bin/python -m pytest tests/integration -v -s --network studionet
```

Use the original signers from their ignored local secret files or environment variables. A different signer needs its own new deployment and journal. Scripts assert code commitments and bind journals to the account and chain before reuse. Receipt polling can be interrupted and resumed without resubmitting an already journaled operation. There remains an unavoidable client-side gap between the RPC accepting a submission and its returned hash being persisted; an interrupted submission without a saved hash requires reconciliation before retrying. Do not interpret missing local evidence as proof that the network never received a transaction.

## Limits of this verification

These checks cover the included policies and consumers; they are not an independent security audit. Network model choice, latency, provider failures and validator membership are managed by Studio. Enforced byte/model-call ceilings are checked in code and direct tests; they are not a throughput benchmark at every maximum. Historical availability is limited to this deployment's finalized signed observations. The Node.js observers are application observer keys, not claims of Node.js publisher identity. There is no archive, publisher-signature or pre-observation availability verification in this version.
