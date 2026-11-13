# CheckWash test execution on PJU

The current 2026-10-27 repair task also has a
[task-specific 16NU receipt route](local-receipt-route-20261027.md), under the
latest continuation instruction and the recorded agent interpretation. It
records the actual local host; the PJU default and historical provenance below
are retained. The route extension itself is not a passing receipt.

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

Run tests on PJU. The one exception is the release-time
[hosted release verification](RELEASING.md#hosted-release-verification),
under EC POLICY `checkwash-release-hosted-verification-20261111`
(2026-11-11). If a required capability is unavailable, record
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
state. Their definitions are retained. The release workflow was among them
until it was rewritten and re-enabled on 2026-10-24 (below);
no release is requested by this venue change. Pure metadata collection can
remain active. Existing results and failures retain their original provenance.
One test workflow is an exception, under EC POLICY
`checkwash-release-hosted-verification-20261111`: the
[hosted release verification](RELEASING.md#hosted-release-verification),
which each release runs once, as two dispatched checkpoints, on
GitHub-hosted macOS and Linux. It records `HUMAN_AUTHORIZED_GITHUB_HOSTED_NOT_PJU_RECEIPT`;
it is not a PJU receipt, each pull request's tests still run on PJU, and a
failure in it still stops the release.

The required-check ruleset (`22032046`) stays in force. From D-209
(2026-11-13), its required context is `checkwash` bound to GitHub Actions
(`integration_id: 15368`, matching `action/required-ruleset.json`), replacing
the earlier four-context ordinary-PR ruleset that also required three separate
`candidate assertion contract (...)` contexts on every PR. For ordinary PRs,
the [PJU receipt bridge](pju-receipt-bridge.md) compact-receipt path
(`mode=receipt` with `compact_receipt`) runs the full local test suite
(`pytest -n 16`, including the in-process assertion contracts),
pinned/candidate composite Action replay, and wheel/sdist/pyz byte-identity
plus isolated wheel/pyz CLI checks on PJU, then verifies a maintainer-admitted
compact JSON digest via `workflow_dispatch` without creating `evidence/*`
branches in the product repository (historical `evidence/*` branches are
retained untouched). Release pull requests and
release stages continue to use the full [release handoff](pju-release-handoff.md)
(`tools/collect_pju_release.py` and `tools/pju_release_bridge.py`), including
full `3x283` source/wheel/pyz CLI qualification and artifact inventories. Both
modes perform hosted data verification only; product execution stays on PJU.
This is maintainer-backed evidence, not hardware attestation or an unexecuted
platform's result.

Missing, failed or stale evidence produces no successful required check.
The bridge publishes no success for a skipped job, and the ruleset has no
standing bypass actor (read back 2026-11-10 UTC: `bypass_actors` is empty).
One temporary bypass has been used: on 2026-10-24, under Nelson's approval
(EC T-619), a bypass actor was added through the browser to merge #563,
whose required `checkwash` check had no successful result because
checkwash's own verdict on it was block, on 24 high findings that Nelson
accepted; the actor was removed after the merge
([RELEASING](RELEASING.md)).
In a pull request's evidence, native Linux and macOS and other absent
runtimes remain `NOT_RUN`; at a release, the hosted release verification
adds GitHub-hosted Linux and macOS runs, and everything outside it and the
supplementary six-leg batch stays `NOT_RUN`. A green local receipt does not waive any separately required
platform or release validation.
The release workflow was rewritten and re-enabled on 2026-10-24: it captures
native metadata, verifies published receipts and publishes, and product
execution stays on PJU ([release handoff](pju-release-handoff.md)). The
hosted workflows that run tests stay disabled, apart from the release-time
hosted verification above, and a release still needs its own reviewed
publication handoff and one-time authorization.

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
retain their existing gates. Since EC POLICY
`checkwash-212-blind-raters-20261108`, an after-the-fact record of the
rating already run ([D-203](../DECISIONS.md)), #212's rating
uses the two raters named for it, a Claude Code sub-agent and Gemini 4
Argon, with Nelson settling disagreements, in place of the separately
selected pool reviewers and arbitration channel
([EC POLICY `checkwash-212-blind-raters-20261108`](https://github.com/taipei49314/estate-consolidation/blob/227236bcd705ea229f49022788bc57d41ed714e2/POLICY.md)).
API key setup and paid calls retain their own admission and approval
boundaries. Conflicting venue-only restrictions yield to T-610;
independence, source, budget and attempt conditions remain.
