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
published stable release. A tag pin is mutable; pin a verified commit instead.
A release cannot embed its own commit SHA. Up to v0.10.0 a release commit
carried the prior release's pin, and once the new release's publication was
verified a follow-up on main recommended its peeled commit (since 2026-10-14;
before that the recommendation trailed by one release). From v0.11.0 (D-194) a
release has two commits: its Action commit, and the release merge, which the
distributions are built from. The release pull request's last commit changes
one line, doctor's own Action pin, to the Action commit, so the merge differs
from the Action commit only in that line. The Action commit is the recommended
Action pin once the release's publication is verified. The Action runs only
`checkwash check`, which does not import doctor, so it runs the same check at
either commit. A release's doctor accepts that release's Action commit and the
pin recommended before it. The v0.11.0 tag points at the merge, so v0.11.0's
Action commit is the tag's second parent's parent. From v0.12.0 (D-200)
the tag points at the Action commit, so the recommended pin is the tag's
peeled commit again. Source changes here do not update that public
pin.
The recommended v0.12.0 Action contains this installation repair; v0.7.0 and
earlier do not. Promoting a security release/pin requires a separate recorded
publication decision; do not silently re-pin consumers to unreleased source.

Verify the current pins. The checkout and setup-python pins and the
recommended checkwash pin, v0.12.0's Action commit, are their tags' peeled
commits:

```bash
git ls-remote https://github.com/actions/checkout.git refs/tags/v7.0.1
git ls-remote https://github.com/actions/setup-python.git refs/tags/v7.0.0
git ls-remote https://github.com/taipei49314/checkwash.git 'refs/tags/v0.12.0^{}'
```

A checkwash pin up to v0.10.0 is its tag's peeled commit too: use that tag in
the last line. The v0.11.0 pin, v0.11.0's Action commit, is not the commit
its tag points to, so `git ls-remote` cannot show it. Verify it in a clone;
the diff shows one changed line, in `src/checkwash/doctor.py`:

```bash
git clone --filter=blob:none https://github.com/taipei49314/checkwash.git
git -C checkwash rev-parse 'v0.11.0^2^1'
git -C checkwash diff 'v0.11.0^2^1' v0.11.0
```

Pin updaters such as Dependabot and Renovate follow the `# vX.Y.Z` comment and
propose the commit the tag points to; what this paragraph says about them
and about zizmor is inferred from those tools' documentation, not run. From
v0.12.0 that commit is the release's Action commit, which that release's
doctor accepts, and zizmor's `ref-version-mismatch` audit (1.14.0 and later)
and its pedantic `stale-action-refs` should not report the pin. For a
v0.11.0 pin they can propose the v0.11.0 merge, which doctor rejects, and
zizmor can report the comment and the untagged commit; an update to v0.12.0
proposes v0.12.0's Action commit, which doctor 0.12.0 accepts and doctor
0.11.0 rejects. The Action itself is unaffected: it runs the same check at
either commit. Upgrade the CLI and its local hooks first, then the Action
pin. From v0.12.0 a CLI installed through Git from the release tag is the
Action commit's, and its doctor rejects that release's own pin: install the
CLI from PyPI or the pyz.

The hosted `action-security` qualification invoked the actual candidate composite
on all three operating systems. Expected BLOCK/ERROR jobs stayed failed; a separate
qualification job checked every original outcome and receipt. It last ran on
2026-10-22 (UTC), and the workflow has been disabled since 2026-10-23 with
the other hosted workflows that run tests
([testing on PJU](../docs/testing-on-pju.md)).
`action.yml` has not changed since 2026-10-12, so those runs exercised this
wrapper, but not with the engines released after them. Since then each pull
request's [PJU receipt](../docs/pju-receipt-bridge.md) replays the composite
on Windows only, on the maintainer's receipt host (PJU), and labels the
result a local composite replay, not a GitHub runner execution. Each
release's [hosted verification](../docs/RELEASING.md#hosted-release-verification)
also runs the composite at the release's Action commit once on a
GitHub-hosted `ubuntu-latest` runner with Python 3.12, on the release's own
range with the default inputs except `base`, which a dispatched run gives,
and with `CHECKWASH_TODAY` set to the release merge's commit date, from a
checkout of that commit used by a local path. Its first run, for v0.12.0 after publication on 2026-11-11,
exited 0 ([record](../docs/releases/v0.12.0-publication-verification.md#hosted-verification-after-publication-2026-11-11)).
That range passes, so the run does not show the Action blocking a change.
macOS, Windows, other Python versions and inputs, GitHub's resolution of
`taipei49314/checkwash/action@<sha>` and a `pull_request` trigger remain
`NOT_RUN`. A successful source review or a local wrapper test does not
substitute for a hosted result.
