# Security policy

## What checkwash is trusted with

checkwash reads your git diff and, in worktree/hook mode, your working tree.
It runs entirely locally: **no network, no telemetry, no LLM, no code
execution.** "No network" is enforced by a test (`tests/conftest.py` blocks
sockets during the suite), not just promised. It never runs the code under
review — it parses it. Evidence quoted in findings stays on your machine.

## Threat model

The design assumes the head side of the diff is **attacker-controlled** (it
is written by the agent under review). Configuration, the allowlist, and the
task contract are therefore read from the base side. What checkwash can and
cannot catch, and the full list of known and closed bypasses, is documented
in the open at [THREATMODEL.md](THREATMODEL.md) — including the ones that are
out of scope on purpose.

checkwash is a **tripwire that raises the cost of tampering**, not a
guarantee. It is worth running as one required check among others, not as the
only thing standing between an agent and your main branch.

## Known issue: Action trust boundary

**Affected:** every published release of the GitHub Action
`taipei49314/checkwash/action` up to and including v0.7.0
(`d647a65e9734f2b6e57b528ea595b1507dc31094`), and v0.6.0, whose Action is
identical. Fixed in v0.8.0 (`f02b5d8a07fa39ee1898881f66c571eb164cb11c`), the
currently recommended pin.

**What happens:** the composite Action runs `python -m pip` to install
checkwash, then runs whichever `checkwash` is first on `PATH`, with the pull
request's checkout as the working directory. Because `python -m` puts that
directory first on the import path, a module in the checkout (for example a
top-level `pip` package) can replace the installer and, through it, the checker.
A pull request can therefore tamper with the result it is judged by.
[#372](https://github.com/taipei49314/checkwash/pull/372) describes the full set
of exposures. The engine still parses rather than executes the code under
review; the exposure is in how the Action installs and starts it. With
`comment-pr: true`, the step that runs `checkwash` for the comments also holds
the job token.

**Who is affected:** any workflow that runs this Action on a pull request whose
head the author, or the agent under review, controls. Under the threat model
above, that is every pull request checkwash judges, so on v0.7.0 or earlier a
pass is not a trustworthy verdict on its own.

**Fix:** [#372](https://github.com/taipei49314/checkwash/pull/372) (merge
`0b42e2343d5c6983d22011dbd846f0da74ac623a`) installs into a private environment
with the setup-python interpreter, verifies the installed package and invokes it
explicitly; [#375](https://github.com/taipei49314/checkwash/pull/375) applies the
same isolation to the separate quality preview Action. Both shipped in v0.8.0
(2026-10-15), and the README recommends the v0.8.0 Action (maintainer decision,
2026-10-14: no one-release lag). Pin it by its peeled commit
([action/README.md](action/README.md#public-pin-and-upgrade)). The v0.8.0
Action needs setup-python in the same job, a checkout with both refs, and a
dedicated job that runs no pull-request code before the check.

**If you stay on v0.7.0 or earlier:**

- Treat a pass as advisory and review the pull request before merging it. Look
  in particular for new top-level Python modules or packages (such as `pip/` or
  names that shadow standard-library modules) and other new files at the
  repository root.
- Leave `comment-pr` at its default `false`.
- When the branch rule requires code-owner review, a code owner for
  `.github/workflows/` ([docs/enterprise.md](docs/enterprise.md#4-codeowners))
  must approve edits to the check itself, but that does not address this issue:
  the files involved need not be under `.github/`.

## Reporting a vulnerability

A bypass that lets real tampering through is a `false-negative` issue, not a
private disclosure — open it in public via the "Send us a cheat" template.
The bypass table in THREATMODEL.md is meant to grow in the open; a documented,
reproduced bypass is more useful to everyone than a quiet one.

The exception is a vulnerability in checkwash's own execution — e.g. a crafted
input that runs code, exfiltrates data, or escapes the read-only contract.
That would contradict the guarantees above; report it privately to the
maintainer before disclosure.

## Supply chain

checkwash has **zero runtime dependencies** — pure standard-library Python.
That is a deliberate security property for a tool that inspects other code: a
monitor with a large dependency tree is itself an attack surface. Releases are
built from the tagged commit; the CI matrix and the cross-OS byte-compare job
run on every push.
