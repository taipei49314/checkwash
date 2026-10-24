# CheckWash test execution on PJU

On 2026-10-23, after the host and conflict with the general work-machine rule
were identified, Nelson explicitly instructed: all CheckWash tests run on
this PJU, make it a standing rule, and keep other projects' rules unchanged.
The host is **LAPTOP-01AGNPJU**. This covers CheckWash's tests and validation
harnesses, including those housed in checkwash-lab and checkwash-corpus.

The source-linked standing rule is EC POLICY
[`checkwash-pju-tests`, T-606](https://github.com/taipei49314/estate-consolidation/blob/e9ce2342fc4834f5b5d580461b26f8784b64481a/POLICY.md),
with the [explicit human instruction](https://github.com/taipei49314/estate-consolidation/blob/e9ce2342fc4834f5b5d580461b26f8784b64481a/evidence/requests/2dd0ee8d-8df9-4f36-8a80-ff94953a09c2/checkwash-local-tests-authority.md).
It includes CheckWash lint/type checks and builds needed for testing, with
test dependencies and artifacts confined to the task directory. A change of
host does not establish an isolation capability; unmet isolation requirements
remain `NOT_RUN`.

On 2026-10-24 the maintainer made PJU the default execution host across
authorized projects, superseding conflicting venue restrictions above:
[PJU primary policy, T-610](https://github.com/taipei49314/estate-consolidation/blob/103c52abd38eb87c13980aa7cf6f0db4412e53ac/POLICY.md).
This has no automatic Tuesday expiry. Capable pool hosts may supply validation
after connectivity is restored. Nelson confirmed the outage and stopped
connection investigation; do not poll hosts or set up monitoring.

Run tests on PJU. If a required capability is unavailable, record
`NOT_RUN` with the specific reason. The newer rule does not authorize changing
host security, services, permissions, runner labels or profiles.
Keep fixed-source approvals and run budgets for already-declared sweeps;
the venue decision does not renew an attempt or extend a timeout.

Record the actual host, source commit, checkout commit/tree, runtime,
commands, exit codes, raw logs and relevant JUnit/qualification receipts.
Label these `HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL`. A Windows result
does not prove an unexecuted Linux/macOS matrix leg. Source, wheel and pyz
qualification must still identify the exact tested bytes. CLI dogfood does
not establish the composite Action's wiring.

## Transition state

Remote workflows containing tests are disabled through GitHub workflow
state. Their definitions are retained, including the mixed release workflow;
no release is requested by this venue change. Pure metadata collection can
remain active. Existing results and failures retain their original provenance.

The required-check ruleset stays in force. Its required GitHub Actions
contexts are `checkwash` and `candidate assertion contract (source)`,
`candidate assertion contract (wheel)`, `candidate assertion contract (pyz)`.
The [PJU receipt bridge](pju-receipt-bridge.md) collects full local test,
pinned/candidate composite Action and source/wheel/pyz qualification evidence.
The existing manual quality-intake workflow has a receipt mode that verifies
an immutable, maintainer-admitted evidence commit and manifest digest against
the current PR head/base before publishing those contexts. It performs data
verification only; product execution stays on PJU. This is maintainer-backed
evidence, not hardware attestation or an unexecuted platform's result.

Missing, failed or stale evidence produces no successful required check.
The ruleset is unchanged and there is no skip-success or administrator bypass.
Native Linux/macOS and other absent runtimes remain `NOT_RUN`; a green local
receipt does not waive any separately required platform or release validation.
The mixed release workflow remains disabled, and a release still needs its
own reviewed publication handoff and one-time authorization.

The initial AGENTS.md amendment and the proposed allowlist exemption both
produced retained critical dogfood receipts. The final route is recorded here,
in STATE.md (already required reading by AGENTS.md), and in EC POLICY. No
AGENTS.md or allowlist change is needed; the final complete diff must pass.

## Unchanged boundaries

The newer PJU primary policy also covers other projects; LAPTOP-16NUA5I8
retains its independently applicable authorizations and owner assignments. No
host-wide runtime, security, service, runner or label change is authorized
here. Historical results are not retroactively accepted. Protected product
rulings, fixture expectations, issue acceptance and release/PyPI approvals
retain their existing gates. The separately selected #212 pool independent
reviewers and arbitration channel, API key setup and paid calls retain their
own admission and approval boundaries. Conflicting venue-only restrictions
yield to T-610; independence, source, budget and attempt conditions remain.
