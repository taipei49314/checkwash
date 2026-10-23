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

Run tests on PJU. If PJU or a required environment is unavailable, record
`NOT_RUN` with the reason. Do not fall back to pool or GitHub-hosted tests.
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
**LOCAL_RECEIPT_BRIDGE_NOT_READY:** no workflow currently verifies PJU
receipts and satisfies those contexts. New PRs cannot merge while the
required contexts are missing. There is no skip-success or administrator
bypass. Release source, inventory and publication gates also remain blocked
until a reviewed handoff can consume the PJU evidence without remote tests.

A future bridge must verify actual PJU execution and bind every receipt to
the exact source/checkout and artifact bytes before reporting a result.
This document does not claim that bridge exists or that any test has run.

## Unchanged boundaries

Other projects and LAPTOP-16NUA5I8 retain their own current policies. No
host-wide runtime, security, service, runner or label change is authorized
here. Historical results are not retroactively accepted. Protected product
rulings, fixture expectations, issue acceptance and release/PyPI approvals
retain their existing gates. The separately selected #212 pool independent
reviewers and arbitration channel, API key setup and paid calls retain their
own admission and approval boundaries.
