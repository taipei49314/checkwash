# checkwash GitHub Action

Composite action that installs the source belonging to its pinned Action commit
and runs `checkwash check` against the PR (or `HEAD~1` on a push).

## Caller workflow

Copy the hash-pinned snippet in the root [README](../README.md). Use a dedicated
fresh GitHub-hosted job containing trusted checkout, setup-python and this Action.
Do not install dependencies, run tests, run local actions from the subject PR or
restore subject-provided executable environments before the check. Isolation of
Python imports cannot recover a runner already compromised by a previous step.

Required in the caller workflow:

- `permissions: contents: read` and no secrets for the check;
- `fetch-depth: 0` and `persist-credentials: false` on checkout;
- full 40-character commit SHAs on every `uses:`;
- setup-python with Python 3.11, 3.12 or 3.13;
- an unconditional job named `checkwash`, required by the repository ruleset.

The Action takes the absolute interpreter from setup-python's `pythonLocation`.
It does not fall back to a `python` executable found through PATH. Callers may
instead pass setup-python's `python-path` output to the optional input. Run the
Action before executing any code from the subject checkout.

The interpreter input, setup-python environment, shell startup environment and
runner OS directories are trusted caller configuration. Checks performed inside
Python occur after that interpreter has started; they are not protection against
a malicious interpreter, `BASH_ENV`, or operating-system loader configuration.

Installation creates a fresh environment under `RUNNER_TEMP`. Python runs with
isolated mode and explicit UTF-8 mode. The installer disables pip configuration,
subject search paths, caches and inherited install/build overrides. It installs
only the pinned Action source with its declared build backend from PyPI. PyPI,
the pinned setup-python Action and the runner image remain trusted dependencies;
this is not an offline or hash-locked build toolchain.

Before running the engine, the Action compares the installed package's files and
version against its pinned source. It rejects extra/missing/changed files,
symlinks and installed bytecode caches. The engine uses that private interpreter
with bytecode writes disabled. Subject `pip`, `checkwash` or `sitecustomize`
modules and fake console scripts cannot become the installer or runtime.

The Action requires the requested base and HEAD commits to be present; it does
not turn a fetch/ref failure into a successful empty comparison. Full-history
checkout is the supported setup. Both refs are fixed before analysis; the engine
retains three-dot merge-base semantics and base-side configuration/allowlist.

## Inputs

| Input | Default | Meaning |
|---|---|---|
| `fail-on` | `high` | Caller-owned severity threshold; retains CLI precedence over base configuration |
| `base` | PR base SHA, else `HEAD~1` | Left side of the comparison; must already be fetched |
| `comment-pr` | `false` | Optional advisory review comments, retaining the existing success-step condition |
| `python-path` | setup-python `pythonLocation` | Optional absolute trusted interpreter from setup-python's `python-path` output |

Inputs reach scripts through environment variables and validated arguments, not
shell source interpolation. Do not set the interpreter input to a PR checkout or
an environment prepared by PR code. Protect edits to the caller workflow through
repository review policy: a composite Action cannot require its own invocation
or prevent a caller from choosing weaker inputs.

## Results and diagnostics

| Output | Meaning |
|---|---|
| `exit-code` | `0` pass, `1` block, or `2` engine/integration error |
| `receipt-path` | Runner-temporary receipt with fixed refs, runtime identity, analysis exit and Action exit |
| `identity-path` | Installed file digest, package path/version and interpreter identity |

BLOCK and ERROR remain actual failed Action steps. If reporting the result fails,
the receipt retains the original analysis exit where available and the Action
fails with an integration error. Raw stdout/stderr are stored next to the receipt.
Subject evidence is displayed with workflow-command processing suspended. Paths
are temporary to that job; explicitly upload the receipts if you need to retain
them. Initial installation failure may occur before an identity/receipt exists.
Successful installation also keeps pip's installation report and verbose build
logs next to the receipt, so installer and resolved build-tool evidence can be
retained with the candidate's hosted run.

`comment-pr: true` needs `pull-requests: write`. The token is passed only to the
trusted comment helper after analysis and is absent from install/engine child
environments. Comment/network failure remains advisory. The default recommended
configuration sends no comments. Commenting does not verify branch protection.

## Require the check

The job name in the README snippet is `checkwash`, which is the required status
context. After the workflow runs once, require it in Settings → Rules → Rulesets.
Administrators may also use the existing ruleset payload:

```bash
gh api repos/OWNER/REPO/rulesets --method POST --input action/required-ruleset.json
```

This adds a ruleset; it does not replace existing ones. `doctor` can inspect the
local workflow but cannot verify live branch protection.

## Public pin and upgrade

The root README, self-audit workflow and doctor's trusted pin remain tied to a
published stable release. A tag pin is mutable; use its verified peeled commit.
A release cannot embed its own commit SHA, so a release commit carries the prior
release's pin, and once the new release's publication is verified a follow-up on
main recommends it (since 2026-10-14; before that the recommendation trailed by
one release). Source changes here do not update that public pin.
The recommended v0.8.0 Action contains this installation repair; v0.7.0 and
earlier do not. Promoting a security release/pin requires a separate recorded
publication decision; do not silently re-pin consumers to unreleased source.

```bash
git ls-remote https://github.com/actions/checkout.git refs/tags/v7.0.1
git ls-remote https://github.com/actions/setup-python.git refs/tags/v7.0.0
git ls-remote https://github.com/taipei49314/checkwash.git 'refs/tags/v0.8.0^{}'
```

The hosted `action-security` qualification invokes the actual candidate composite
on all three operating systems. Expected BLOCK/ERROR jobs stay failed; a separate
qualification job checks every original outcome and receipt. A successful source
review or a local wrapper test does not substitute for those hosted results.
