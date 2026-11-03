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

The isolated lock-file installation and dependency check succeeded. All three current contracts pass AST and SDK validation. The current Python 3.14 suite passes **149 direct tests** in 4.48 seconds; the redirect-rejecting source transport passes **17 Node tests**, and the optional authenticated RPC relay passes **8 Node tests**. Logs: [current direct tests](../evidence/remediation-direct-tests.log), [source transport tests](../evidence/source-transport-tests.log), [RPC relay tests](../evidence/rpc-transport-tests.log), [isolated installation](../evidence/clean-replay.log), and [current lint with source hashes](../evidence/remediation-lint.log). Earlier clean-environment results are retained as historical evidence. The lock file includes transitive dependencies; the short requirements file pins the five direct dependencies.

Direct verification covers:

| Area | Executed checks |
| --- | --- |
| Temporal normalization | UTC offsets, date-only policy, invalid calendars/timezones, second/day endpoints, interval intersections and integer bounds |
| Independent validation | Explicit `run_validator()` accepts a matching independent derivation and rejects changed roles, intervals, witnesses, omitted assertions/exceptions, changed source bytes and fabricated result kinds |
| Model and source faults | Hallucinated dates, malformed output, web outages, VM/UserError handling, omitted full-packet documents, UTF-8 and span integrity |
| Completeness and bounds | Four sources with six assertions, oversized joint packets, per-source limits, no truncation |
| Availability | Backdated headings cannot establish old availability; publication claims cannot supply observation coverage; pending confirmation cannot support assessment; later exceptions, corrections and unselected records control the conservative bound |
| Confirmation | Self-sender authentication, post-observation callback timestamp, immutable repeated confirmation, principal-only retries with three finalized broadcasts |
| Authority and state | Immutable policy revisions, exact consumer-approved envelopes before subject acquisition, authorized owner rotation after quarantine, separate roles, URL escape and terminal dot-segment rejection, permanent quarantine and supersession |
| Recovery | Separate attempt reservations, three-attempt recovery, actual network-time field, deadline expiry, bounded histories |
| Consumer and delivery | Sender/binding checks, finalized emit selection, duplicate/reordered callbacks, execution persists across delivery IDs, second distinct action rejected, cancellation reconciles unopened approvals, cancelled callbacks remain stale, delayed old deliveries retain recovery restrictions, acknowledgements and action-time validity |
| Transaction tooling | Persist submission before polling, resume interrupted polls, bind cached hash/signer/destination/raw calldata/deployment bytes and emitted parent-child relationships, require finality and execution success, preserve exact RPC parameters through quota recovery, retain completed summaries and isolate deployments |

The direct runtime executes leader code by default. The independent validator checks listed above explicitly invoke captured validators with separate or adversarial outcomes. Tests use synthetic web/model outputs and callback/source views; they do not prove network consensus, finality, or network callback authentication. The installed test runtime's `warp` helper does not refresh `gl.message_raw["datetime"]`; time-bound tests explicitly update that field. Production contracts read only the real network field.

## Studio deployment and live verification

Current deployment: [metadata](../evidence/deployment.json), resolver [journal](../evidence/studio-v4/journal.json), [notice journal](../evidence/studio-v4-notice/journal.json), and [event journal](../evidence/studio-v4-event/journal.json).

| Contract | Address | Finalized deployment transaction |
| --- | --- | --- |
| Janus | `0x053f2c4bD3Db613AE3A566B8EFc543c44D212e9E` | `0x17a27ecff9fd762c476680dca0e6a83b409a5b1d46b58c7b567c504e04f70fa6` |
| Notice | `0xf5d64152E73Bb2B74034CA9B80dfBd7b04945384` | `0x1954ab5b84907b214d62027c35cd2b866b1bb8b4b76d0fe29a9189bc3d829204` |
| Event | `0x751d7Bc9bA337AAcbf6928e79BA45c7C1097cA9B` | `0xeb98946673048d6db478da8c188278ad9f5734e266687854a669c17522551593` |

All three deployment receipts assert FINALIZED and execution success. [On-chain source verification](../evidence/deployed-source-verification.json) records byte-for-byte matches to the committed contract sources. [Source transport evidence](../evidence/source-transport.json) records the deployed gateway source identities, exact publisher bytes, a real rejected redirect and rejected path escapes. Transport correctness and availability are explicit deployment-owner trust dependencies. Deployment metadata commits the SHA-256 of each local source and records separate consumer owners. The initial runtime compatibility probe is preserved in [its receipt](../evidence/runtime-receipt.json).

An older resolver at `0xaD877A491C467E0bbb0a619675cC6aaA643BD0BA` predates finalized source confirmation. Its receipts are retained under `evidence/studio*`; its [archived deployment metadata](../evidence/deployment-0xaD877A491C467E0bbb0a619675cC6aaA643BD0BA.json) is historical evidence, not the current implementation. Resuming its flow exposed the mismatch; the current flow rejects deployment metadata without source commitments. An initial new-deployment attempt hit Studio's reported 500 requests/hour cap before returning a transaction hash; a later attempt succeeded.

Both real public source observations and their authenticated finalized self-confirmations completed successfully on this deployment. Their confirmed views are preserved for the [schedule](../evidence/source-confirmed-node-schedule-1.json) and [release](../evidence/source-confirmed-node-release-1.json). Each observation has four validators and three agreeing votes with `leader_only: false`. Both consumer registrations and policies finalized. All four current baseline cases completed request opening, multi-validator assessment, finalized delivery and acknowledgement, and successful or intentionally blocked execution. Their resulting chain state is preserved in [live results](../evidence/live-results.json). Earlier notice outcomes remain separately labelled historical evidence.

The flow uses two complete immutable public records:

| Source | Bytes | SHA-256 |
| --- | --- | --- |
| Node.js release schedule | 3,254 | `50fe35a4df02398f741fdffbc666aceca323fcdb7f46d05af93145bf610d0049` |
| Node.js v24.1.0 release announcement | 21,059 | `fe45d6ed72cd08143dc86976e07186c25aca559f25ede9585ec3ab38d4cf46d7` |

Their committed URLs and byte spans are in [source manifests](../evidence/live-source-manifests.json). The schedule tests an adequate notice period for v26 maintenance and late availability for v24 maintenance. The release announcement tests an occurrence target inside its release day and another at the exclusive next-day boundary. Each source observation and assessment must have at least two agreeing validator votes with `leader_only: false`. Parent and triggered child transactions must finalize successfully; intentionally blocked execute transactions must finalize with execution failure.

Current consumer results are retained in [live results](../evidence/live-results.json) after matching-deployment receipt and state checks. The completed integration runs isolated authorization, repeated-delivery, cancellation, delayed-callback, quarantine and owner-rotation transitions for both consumers; both isolated lifecycles passed on the matching deployment. Its independent assertions compare deployed bytes, genuine finalized receipt identities, certificates, acknowledgements and chain state.

The final live integration completed with **2 passed and 0 skipped**. Its [full log](../evidence/remediation-integration-tests.log), [machine-readable summary](../evidence/verification-summary.json) and [receipt identity report](../evidence/receipt-verification.json) retain the measured checks. Both [notice lifecycle](../evidence/lifecycle-notice.json) and [event lifecycle](../evidence/lifecycle-event.json) verify unapproved opening rejection, preserved execution across a second delivery, rejection of a second distinct action, cancellation of unopenable and unopened successors, stale delayed delivery, and consumer-approved generation-2 recovery with a changed request owner after quarantine. Cancellation of an already opened generation is rejected. All emitted delivery and acknowledgement children finalized successfully.

| Current case | Assessment | Delivery and execution |
| --- | --- | --- |
| notice-permitted | CERTIFIED, finalized successful assessment | APPLIED acknowledgement; finalized successful execution, scheduled activation |
| notice-refused | CERTIFIED, finalized successful assessment | BLOCKED acknowledgement; finalized failed execution with ACTION_BLOCKED |
| event-permitted | CERTIFIED, finalized successful assessment | APPLIED acknowledgement; finalized successful execution, active registry consequence |
| event-refused | CERTIFIED, finalized successful assessment | BLOCKED acknowledgement; finalized failed execution with ACTION_BLOCKED |

The current schedule availability upper bound is 2026-11-03T11:00:20Z; the release upper bound is 2026-11-03T11:13:06Z. These are finalized observation bounds for the complete committed revisions. Historical [two-notice results](../evidence/studio-v2-results/live-results.json) and [resumption logs](../evidence/live-flow-v3-resume.log) remain separate evidence for the earlier deployment.

To resume the same deployment:

```bash
.venv/bin/python scripts/deploy.py --journal studio-v4
.venv/bin/python scripts/live_flow.py
.venv/bin/gltest tests/integration/test_studio.py -v -s --network studionet
```

[RPC transport evidence](../evidence/rpc-transport.json) records the optional authenticated relay used during final verification. It forwards requests unchanged to the same Studio API and returns the original response bytes with lossless compression. Six uploaded source identities, the actual Studio chain ID, all three on-chain contract sources and rejection of unauthenticated access were checked. Client pacing remains eight seconds. An optional mode-0600 `.secrets/studio-rpc.json` contains only `url` and `token`; the private token is excluded from evidence. This transport is tooling controlled by the deployment owner and makes no consensus or semantic decisions.

Use the original signers from their ignored local secret files or environment variables. A different signer needs its own new deployment and journal. Scripts assert code commitments and bind journals to the account and chain before reuse. Receipt polling can be interrupted and resumed without resubmitting an already journaled operation. There remains an unavoidable client-side gap between the RPC accepting a submission and its returned hash being persisted; an interrupted submission without a saved hash requires reconciliation before retrying. Do not interpret missing local evidence as proof that the network never received a transaction.

## Limits of this verification

These checks cover the included policies and consumers; they are not an independent security audit. Network model choice, latency, provider failures and validator membership are managed by Studio. Enforced byte/model-call ceilings are checked in code and direct tests; they are not a throughput benchmark at every maximum. Historical availability is limited to this deployment's finalized signed observations. The Node.js observers are application observer keys, not claims of Node.js publisher identity. There is no archive, publisher-signature or pre-observation availability verification in this version.
