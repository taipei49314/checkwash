"""CI weakening scan. Extracted from engine (E5)."""
from __future__ import annotations

import re

from greenwash.change import FileChange
from greenwash.deps import parse_manifest_pins
from greenwash.config import Config
from greenwash.ir.model import DiffGlobals
from greenwash.roles import (
    _CI_NARROWING_TOKENS,
    _CI_SWALLOW_TOKENS,
    _TEST_RUNNER_TOKENS,
    _added_lines,
    _is_runner_script,
    _runner_shape,
    _runs_tests,
    is_artifact,
)

def _is_ci_workflow(path: str) -> bool:
    """A CI pipeline definition, as opposed to test-runner configuration.

    Deleting a workflow removes a gate. Deleting `tox.ini` or `setup.cfg`
    almost always means the settings moved into `pyproject.toml`, which is
    housekeeping — treating that as "the test command was weakened" blocked
    two such consolidations in the corpus. The edit is still reported at warn.
    """
    p = path.replace("\\", "/")
    return p.startswith(".github/workflows/") or p in (".gitlab-ci.yml", ".pre-commit-config.yaml")

def _errexit_on(data: bytes | None) -> bool:
    """Would a failing command abort this script?

    Tracks `set -e` / `set +e` and the flags on the shebang itself
    (`#!/bin/sh -e`, which is how httpx and starlette arm theirs). Last
    setting wins, exactly as the shell reads it.
    """
    if not data or len(data) > 1_000_000:
        return False
    state = False
    for line in data.decode("utf-8", errors="replace").splitlines():
        stripped = line.strip()
        words = stripped.split()
        if stripped.startswith("#!"):
            flags = words[1:]
        elif words[:1] == ["set"]:
            flags = words[1:]
        else:
            continue
        i = 0
        while i < len(flags):
            word = flags[i]
            # `set -o errexit` / `set +o errexit`: the option name is a
            # separate word, so the single-letter scan below saw neither an
            # `e` in `-o` nor a flag in `errexit` and concluded errexit was
            # never on. That is the spelling the Google shell style guide
            # recommends, which made the most careful projects the least
            # readable — and it printed "a failing command no longer fails
            # the script" over a script that still exits 1 (audit 2026-08-07).
            if word in ("-o", "+o") and i + 1 < len(flags):
                if flags[i + 1] == "errexit":
                    state = word == "-o"
                i += 2
                continue
            if word.startswith("-") and "e" in word.lstrip("-"):
                state = True
            elif word.startswith("+") and "e" in word.lstrip("+"):
                state = False
            i += 1
    return state


def _make_ignores_error(line: str) -> bool:
    """A make recipe prefixed with `-` reports success whatever it does.

    Recipes are tab-indented — YAML forbids tabs for indentation — so the tab
    is what keeps this from firing on every `- run: pytest` step in a
    workflow. `@-` and `-@` are both valid orderings.
    """
    if not line.startswith("\t"):
        return False
    body = line[1:].lstrip("@")
    return body.startswith("-") and not body[1:2].isspace() and body[1:2] != ""


def _ci_base_surface(changes: list[FileChange], config: Config, one_hop: set[str] | None = None) -> str:
    """Every ci-role file's *base* side, lowercased and concatenated.

    A narrowing that already existed somewhere on this surface is not being
    introduced by the diff, wherever in the diff it now appears. That is what
    lets a configuration move between files — `setup.cfg` to `pyproject.toml`
    is the migration most of the ecosystem has made — without reading as a
    weakened test command.
    """
    parts: list[str] = []
    for change in changes:
        path = change.path.replace("\\", "/")
        if is_artifact(path) or not change.before:
            continue
        role = config.role_of(path)
        if role == "prod" and (
            _is_runner_script(path, change.before, change.after) or path in (one_hop or ())
        ):
            role = "ci"
        if role == "ci":
            parts.append(change.before.decode("utf-8", errors="replace").lower())
    return "\n".join(parts)


_OWN_VERSION_LINE = re.compile(rb"^\s*(?:__)?version(?:__)?\s*=.*$", re.MULTILINE)


def _deps_differ(before: bytes | None, after: bytes | None, path: str) -> bool:
    """Did a manifest's *dependencies* change — not its bytes, its pins?

    D9 `DEPENDENCY_DRIFT` credits an expectation that moved because a pinned
    dependency's behaviour moved. Any edit to a manifest used to satisfy it,
    which meant **a project bumping its own version bought the credit** — and
    almost every release commit does exactly that.

    The comparison was still bytes after the own-version strip, so a comment
    appended to requirements.txt or a swap of the `name`/`version` lines in
    pyproject.toml — no dependency touched — granted the credit to an
    expectation rewrite riding along in the same diff (audit 2026-08-19,
    both shapes reproduced as verdict pass). The semantic content is the set
    of `(distribution, pin)` pairs (`parse_manifest_pins`): reorder-invisible
    and comment-blind, while a real specifier change still differs. When
    neither side parses to a single pin, fall back to the byte comparison
    rather than declaring an exotic manifest inert.
    """
    b_pins = parse_manifest_pins(path, before or b"")
    a_pins = parse_manifest_pins(path, after or b"")
    if b_pins or a_pins:
        return b_pins != a_pins
    b = _OWN_VERSION_LINE.sub(b"", before or b"")
    a = _OWN_VERSION_LINE.sub(b"", after or b"")
    return b != a


# Swallow spellings that only mean something in one dialect, keyed on suffix so
# PowerShell idioms are not hunted in sh and vice versa. `.ps1`/`.bat`/`.cmd`
# were already reclassified to `ci` — so they never bought the opaque exemption
# — but the token table was shell/YAML-shaped, so their weakening was simply
# invisible (THREATMODEL 87a, measured 2026-08-11).
_DIALECT_SWALLOW_TOKENS: dict[tuple[str, ...], tuple[str, ...]] = {
    (".ps1",): (
        "$erroractionpreference = 'continue'",
        '$erroractionpreference = "continue"',
        "$erroractionpreference = 'silentlycontinue'",
        '$erroractionpreference = "silentlycontinue"',
        "$erroractionpreference = 'ignore'",
        '$erroractionpreference = "ignore"',
        "-erroraction silentlycontinue",
        "-erroraction ignore",
    ),
    (".bat", ".cmd"): ("exit /b 0",),
    (".sh", ".bash", ".zsh"): ("|| echo", "|| printf", "; true"),
}

# `if ! pytest; then :; fi` — the runner's failure is caught by a no-op branch.
# Requires a runner token on the same line, so a bare `then :` elsewhere in a
# script is not matched.
_NOOP_BRANCH = re.compile(r"then\s*:\s*(;|$)")


def _dialect_swallow_tokens(path: str) -> tuple[str, ...]:
    for suffixes, tokens in _DIALECT_SWALLOW_TOKENS.items():
        if path.endswith(suffixes):
            return tokens
    # A shell shebang with no extension (httpx and starlette both ship
    # `scripts/test`) still gets the sh spellings.
    return _DIALECT_SWALLOW_TOKENS[(".sh", ".bash", ".zsh")]


def _exit_code_checked(data: bytes | None, needle: str) -> bool:
    """Does this script inspect the runner's exit status at all?

    The two-sided counterpart of `_errexit_on`, for dialects that have no
    `set -e`: PowerShell scripts gate on `$LASTEXITCODE`, cmd scripts on
    `if errorlevel`. Losing the check is exactly as permissive as losing
    errexit, and produces no added line for the scan above to see.
    """
    if not data or len(data) > 1_000_000:
        return False
    return needle in data.decode("utf-8", errors="replace").lower()


def _scan_ci_weakening(
    g: DiffGlobals,
    path: str,
    before: bytes | None,
    after: bytes | None,
    ci_base: str = "",
) -> None:
    # A file that did not exist at base cannot have *narrowed* anything —
    # there was no test command there to narrow. It can still swallow an exit
    # code, which is why the two families are separated.
    existed = bool(before)
    dialect = _dialect_swallow_tokens(path) if _runner_shape(path, before, after) else ()
    for line in _added_lines(before, after):
        lowered = line.lower()
        swallowed = any(token in lowered for token in _CI_SWALLOW_TOKENS) or (
            any(token in lowered for token in dialect)
        ) or (
            bool(_NOOP_BRANCH.search(lowered))
            and any(tok in lowered for tok in _TEST_RUNNER_TOKENS)
        )
        narrowed = existed and any(
            token in lowered and token not in ci_base for token in _CI_NARROWING_TOKENS
        )
        if swallowed or narrowed or (
            _make_ignores_error(line) and any(t in lowered for t in _TEST_RUNNER_TOKENS)
        ):
            g.ci_weakening_lines.append((path, line.strip()[:200]))
    # The two weakenings that a scan of *added* lines can never see, both
    # meaningful only in a shell script — so a yaml or ini file, where
    # neither idea applies, is not judged on them. `after` truthy, not just
    # non-None: a deleted or emptied script has no commands left to be
    # lenient about, and removal is the consolidation case this project
    # deliberately does not escalate.
    if not (after and _runner_shape(path, before, after)):
        return
    if _errexit_on(before) and not _errexit_on(after):
        # `#!/bin/sh -e` -> `#!/bin/sh` removes the only reason a failing
        # pytest fails the script, and adds no line worth scanning.
        g.ci_weakening_lines.append((path, "errexit removed: a failing command no longer fails the script"))
    if path.endswith(".ps1") and _exit_code_checked(before, "$lastexitcode") and not _exit_code_checked(
        after, "$lastexitcode"
    ):
        g.ci_weakening_lines.append(
            (path, "$LASTEXITCODE is no longer checked: a failing command no longer fails the script")
        )
    if path.endswith((".bat", ".cmd")) and _exit_code_checked(
        before, "errorlevel"
    ) and not _exit_code_checked(after, "errorlevel"):
        g.ci_weakening_lines.append(
            (path, "errorlevel is no longer checked: a failing command no longer fails the script")
        )
    if _runs_tests(before) and not _runs_tests(after):
        # Deleting the invocation is the same gate removal as weakening it,
        # and quieter: the pipeline still calls a script that still exits 0.
        # Swapping one runner for another (pytest -> nox) keeps the token and
        # earns nothing, which is the consolidation this must not punish.
        g.ci_weakening_lines.append((path, "the test suite is no longer invoked by this script"))

