# Janus

Janus is a bitemporal evidence interval resolver for GenLayer. It answers when a proposition applied, when a described event occurred, and what public availability can actually be supported. A page fetched today with an old heading cannot establish that its statements were publicly available on the heading date.

The package contains three independently deployable Intelligent Contracts:

| Contract | Responsibility |
| --- | --- |
| `contracts/janus.py` | Authority and policy registry, immutable public source observations, independent temporal assessment, certificates, quarantine and finalized delivery |
| `contracts/notice_gate.py` | Approves and schedules changes only when supported public availability precedes the effective interval by the configured notice period |
| `contracts/event_registry.py` | Registers a release occurrence at its certified target instant without requiring historical publication availability |

All contracts pin `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`. The runner was deployed and checked on Studio before implementation. [Deployment metadata](evidence/deployment.json) records the network, contract addresses, code commitments, journal and separate owners. [Verification](docs/verification.md) distinguishes direct fault probes from real Studio validator consensus.

## Consensus boundary

Each assessment participant independently fetches every committed HTTPS revision through the pinned source transport, checks its SHA-256 commitment and byte spans, reads the entire packet, and makes one substantive model evaluation. The deployment-owned transport rejects every redirect and enforces the configured source origin and directory prefix. Its code commitments and public HTTP verification are recorded in [transport evidence](evidence/source-transport.json); transport correctness and availability remain explicit trust dependencies. The model assigns dates to occurrence, effect or disclosure roles, identifies qualifiers and controlling exceptions, and selects source-grounded witnesses. Python then parses the selected date strings and builds UTC intervals deterministically.

The custom validator repeats that work independently. It compares normalized roles, qualifiers, intervals, coverage, exception rule IDs and canonical witnesses. It never compares free-form prose or accepts an answer merely because its JSON is valid. A malformed or hallucinated model response fails validation. An unavailable source yields no affirmative interval conclusion. State transitions consume only the agreed canonical result.

Janus owns that evidence-to-certificate transition. Integrators own subject selection, consequence configuration, request approval and application UI. Public source publishers own their assertions. Governance explicitly selects which principals and channels may provide evidence; a hash or URL establishes neither authority nor truth.

## Public availability support

An authorized observation principal submits a source manifest in a signed `observe_source` transaction. Consensus verifies the complete public bytes against the locked commitment. Janus stores the exact UTF-8 text and manifest, then emits an authenticated self-callback on finalization. The callback records its own network transaction time as a conservative public-availability upper bound after the observation became final. A pending confirmation cannot support an assessment. The public historical record is signed by the principal and verified by validators.

That observation establishes only an inclusive upper bound on first public availability. The lower bound remains unknown. It does not establish the source's original publication date, its truth, or availability before the observation. Assessment fetch time never becomes publication time. When temporal evidence is supported, the certificate conservatively takes the latest observation upper bound across every committed record, including controlling exceptions, corrections and records without selected temporal witnesses.

This deployment supports `SIGNED_PUBLIC_OBSERVATION`. It deliberately does not accept archive timestamps, release metadata or backdated headings as historical availability evidence. Adding another provenance mechanism requires a separately audited implementation and new policy binding.

## Run locally

Python 3.12 or later is required by the GenLayer SDK. The verified setup uses Python 3.14.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/genvm-lint check contracts/janus.py
.venv/bin/genvm-lint check contracts/notice_gate.py
.venv/bin/genvm-lint check contracts/event_registry.py
.venv/bin/python -m pytest tests/direct -v
```

If the system Python lacks `ensurepip`, create the isolated environment without it and manage that environment with an existing pip:

```bash
python3 -m venv --without-pip .venv
python3 -m pip --python .venv/bin/python install -r requirements.lock
```

The direct tests contain explicitly synthetic fault fixtures for web responses, model output and callback source views. They exercise the actual contract methods and explicit `direct_vm.run_validator()` calls. They are not network consensus or finality proof. Neither the production contracts nor the Studio flow substitutes synthetic evidence or model responses.

## Deploy and integrate

Set `JANUS_DEPLOYER_KEY`, `JANUS_NOTICE_KEY` and `JANUS_EVENT_KEY` in the process environment. Use separate keys for the two consumers. If a variable is absent, the scripts use the corresponding ignored `.secrets/deployer`, `.secrets/notice` or `.secrets/event` file. The deploy script creates missing consumer keys locally with restrictive file permissions. Never send private keys or private originals to a contract.

```bash
.venv/bin/python scripts/deploy.py --journal my-deployment
.venv/bin/python scripts/live_flow.py
```

The scripts target `studionet`, chain ID `61999`, through the configured GenLayer Python SDK. Studio is gasless. Choose a new journal name for each new deployment and retain it when resuming. Transactions are journaled by operation before polling; rerunning an unchanged command resumes the same transaction instead of rebroadcasting. Journals bind the signer and chain. All successful operations assert execution success as well as `FINALIZED` status. The live flow reads its journal and code commitments from deployment metadata, uses immutable public Node.js records and requires multiple agreeing validators. `requirements.lock` records the verified Python 3.14 dependency environment; `requirements.txt` pins direct dependencies for other supported Python versions.

The optional `rpc_transport` service forwards authenticated verification requests to the same Studio API without changing their signed parameters or receipt bytes. Private endpoint configuration uses the ignored `.secrets/studio-rpc.json` with `url` and `token`. [Verification](docs/verification.md) records deployed transport provenance and real chain checks.

For a different application, follow these steps:

1. Deploy `Janus(capacity, transport_url)` with your registry owner and a verified transport that rejects redirects. The published transport supports `raw.githubusercontent.com` and `github.com`; another publisher requires an explicitly configured transport.
2. Have the owner call `register_authority`, disclosing channel, exact HTTPS prefix, scope and public authority evidence. Have the designated principal sign `accept_authority`.
3. Have that principal sign `observe_source` for each complete committed revision. Wait for its successful finalized receipt and self-confirmation. Check `get_source(...).confirmed` and `valid` before opening a request.
4. Register an immutable temporal policy and its accepted authority IDs.
5. Deploy a consumer with its own owner and selected policy revision. Its owner calls `register`, which sends the resolver a finalized authenticated registration message.
6. Commit the proposition, manifest, consumer, consequence, generation, target instant and deadline in a canonical envelope. The consumer owner approves that exact envelope. The request owner calls `open_record`, which checks consumer approval before assigning ownership or the subject head.
7. Reserve an assessment attempt, wait for that transaction, then call `assess_intervals`. Inspect its successful receipt and certificate. Reserve no more than three application attempts per revision.
8. Call `publish_to` with a unique operation ID. Janus emits `receive_certificate` only on finalization. The consumer authenticates Janus, verifies every binding and checks current revocation state. Its finalized acknowledgement is persisted on Janus.
9. Execute the application action through the consumer. It checks the current generation and source validity again. UNKNOWN, pending, stale and quarantined evidence remains visibly blocked.

See [schemas and method examples](docs/api.md), [authority and lifecycle](docs/architecture.md), and [execution limits](docs/limits.md). Replayable request envelopes, manifests, certificates and transaction receipts are in `evidence/`.

## Consumer behavior

The notice gate checks `first_publication_upper + notice_seconds <= effective.lower`. The public observation upper is inclusive. The effective interval lower is inclusive. An equality at exactly the agreed notice period is sufficient. `execute` schedules a permitted change; `get_state.active` becomes true at or after the effective lower boundary and before its exclusive upper boundary. A notice whose supported availability was too late remains blocked even if the temporal statement itself is certified.

The event registry checks the occurrence interval at the locked target instant. Its `execute` records that certified event consequence. A release date can be accepted as an occurrence statement under the explicit source policy even though the public observation supporting that exact revision is much later. The certificate continues to disclose that availability limitation.

Both consumers require owner-approved envelopes and finalized authenticated source messages, retain their last applied generation and acknowledgements, block pending successors, and reject stale or quarantined evidence at action time. Execution persists per request generation across delivery IDs. The consumer owner may cancel an approval that never opened after reconciling the resolver head, then approve a replacement at the same generation. Cancellation permanently revokes the old approval and keeps restrictions until a replacement certificate arrives. Opened generations recover through consumer-approved successors, which may explicitly change the request owner. Their consequence is restricted to their own on-chain registry or scheduled activation state. They do not grant arbitrary external account permissions.
