"""`greenwash doctor` — is this installation actually load-bearing?

The failure this exists for is not a crash. It is a repository that has
greenwash installed, green, and unable to block anything: a stop-hook with no
CI check behind it, or a CI job gated by an `if:` that is never true. This
project shipped that exact defect itself — the dogfood job was
`if: github.event_name == 'pull_request'` in a repository that has never had a
pull request, so it never executed once while the README told people to use it.

Everything here is best-effort and local. Branch protection lives in GitHub's
API behind token scopes greenwash does not ask for, so this command cannot
prove a check is *required*; it says so rather than implying otherwise, which
is the whole point of the command.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# "This job runs greenwash as a check" — not merely "mentions greenwash".
#
# The distinction is the whole value of the command, and the first version got
# it wrong in both directions on this very repository: it missed the `dogfood`
# job, which uses a *local* `uses: ./action`, and it warned about the release
# pipeline's `build` and `pypi` jobs, which only `pip install greenwash` to
# package it. A doctor that reports the wrong jobs is worse than none.
_INVOKES = re.compile(
    r"""
      greenwash/action                 # uses: owner/greenwash/action@vX
    | greenwash(\.pyz)?\s+check        # greenwash check / greenwash.pyz check
    | -m\s+greenwash\s+check           # python -m greenwash check
    """,
    re.VERBOSE,
)
# A repository-local composite action: only counts if that action is greenwash.
_LOCAL_ACTION = re.compile(r"uses:\s*\./([A-Za-z0-9._/-]+)")
# A job key at two-space indent inside `jobs:`.
_JOB_KEY = re.compile(r"^  ([A-Za-z0-9_-]+):", re.MULTILINE)


@dataclass
class Note:
    level: str  # "ok" | "warn" | "problem" | "info"
    title: str
    detail: str


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


_GATING_EVENTS = ("push", "pull_request", "pull_request_target", "merge_group")


def _gates_merges(text: str) -> bool:
    """Is this workflow triggered by something that can gate a merge?

    A workflow that runs only on `release` or `workflow_dispatch` cannot block
    anyone's pull request, so its jobs must not be judged as if they could.
    Checking every greenwash-invoking job regardless produced three confident
    warnings about this project's own release pipeline on the first run.
    """
    head = text.split("\njobs:", 1)[0]
    return any(re.search(rf"^\s+{event}:", head, re.MULTILINE) for event in _GATING_EVENTS)


def _workflow_jobs_invoking_greenwash(root: Path) -> list[tuple[str, str, str]]:
    """(workflow path, job name, job body, gates_merges) per greenwash job."""
    out = []
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return out
    local_actions = _greenwash_local_actions(root)

    def invokes(blob: str) -> bool:
        if _INVOKES.search(blob):
            return True
        return any(m.group(1).rstrip("/") in local_actions for m in _LOCAL_ACTION.finditer(blob))

    for path in sorted(wf_dir.glob("*.y*ml")):
        text = _read(path)
        if not invokes(text):
            continue
        starts = [(m.group(1), m.start()) for m in _JOB_KEY.finditer(text)]
        for i, (name, start) in enumerate(starts):
            end = starts[i + 1][1] if i + 1 < len(starts) else len(text)
            body = text[start:end]
            if invokes(body):
                rel = path.relative_to(root).as_posix()
                out.append((rel, name, body, _gates_merges(text)))
    return out


def _greenwash_local_actions(root: Path) -> set[str]:
    """Directories holding a repo-local composite action that runs greenwash.

    `uses: ./action` says nothing on its own — it is greenwash only if that
    action.yml is greenwash's. This repository dogfoods exactly that way.
    """
    found = set()
    for candidate in sorted(root.glob("**/action.yml")) + sorted(root.glob("**/action.yaml")):
        if ".git" in candidate.parts:
            continue
        if "greenwash" in _read(candidate):
            found.add(candidate.parent.relative_to(root).as_posix())
    return found


def _conditions(job_body: str) -> list[str]:
    return [
        line.strip()[3:].strip()
        for line in job_body.split("\n")
        if line.strip().startswith("if:")
    ]


def collect(root: Path) -> list[Note]:
    notes: list[Note] = []

    jobs = _workflow_jobs_invoking_greenwash(root)
    hook_installed = "greenwash" in _read(root / ".claude" / "settings.json")
    precommit = _read(root / ".pre-commit-config.yaml")
    precommit_installed = "greenwash" in precommit

    if not jobs:
        where = [
            name
            for name, present in (
                ("a Claude Code stop-hook", hook_installed),
                ("pre-commit", precommit_installed),
            )
            if present
        ]
        if where:
            notes.append(Note(
                "problem",
                "greenwash runs locally but not in CI",
                "Found " + " and ".join(where) + ", and no workflow under "
                ".github/workflows that invokes greenwash. A local hook is an "
                "author-side convenience: it is skipped with --no-verify, and it "
                "is not present at all when someone else pushes. Nothing here can "
                "stop a merge.",
            ))
        else:
            notes.append(Note(
                "problem",
                "no greenwash installation found",
                "No workflow invokes greenwash and no local hook was found. See "
                "the Required check section of the README.",
            ))
    else:
        notes.append(Note(
            "ok",
            f"{len(jobs)} CI job(s) invoke greenwash",
            ", ".join(f"{path} :: {job}" for path, job, _, _ in jobs),
        ))
        # Only jobs in a workflow that a pull request or push can trigger are
        # capable of gating a merge at all. A release-only job being
        # conditional says nothing.
        gating = [(path, job, body) for path, job, body, gates in jobs if gates]
        unconditional = [(p, j) for p, j, body in gating if not _conditions(body)]
        if not gating:
            notes.append(Note(
                "problem",
                "greenwash never runs on a pull request or a push",
                "Every workflow that invokes greenwash is triggered only by "
                "events that cannot gate a merge (release, workflow_dispatch, "
                "schedule). Nothing here can stop a change from landing.",
            ))
        elif not unconditional:
            notes.append(Note(
                "warn",
                "every greenwash gate is conditional",
                "; ".join(f"{p} :: {j} gated on {_conditions(b)}" for p, j, b in gating)
                + ". A job that does not run cannot block. This project shipped "
                "exactly that: a dogfood job gated to pull_request in a repository "
                "that had never had one, so it never executed while the docs said "
                "it did. At least one gate should be unconditional.",
            ))
        else:
            notes.append(Note(
                "ok",
                "at least one greenwash gate runs unconditionally",
                ", ".join(f"{p} :: {j}" for p, j in unconditional),
            ))

    notes.append(Note(
        "info",
        "greenwash cannot tell whether the check is *required*",
        "Branch protection lives behind GitHub API token scopes this tool does "
        "not ask for. A green job that is not a required status check does not "
        "prevent a merge. Make the job's status check required, and match the "
        "status-check name to the job name exactly. The README step 2 command "
        "is: gh api repos/OWNER/REPO/rulesets --method POST "
        "--input action/required-ruleset.json",
    ))

    notes.append(Note(
        "info",
        "greenwash cannot block when it does not run",
        "A change that deletes or disables the greenwash job disarms it in the "
        "same diff that would have been judged. Protect the workflow file (code "
        "owners, or a required review on .github/**) — the tool can report that "
        "the invocation disappeared, but it cannot enforce its own presence.",
    ))

    cfg = root / ".greenwash" / "config.toml"
    allow = root / ".greenwash" / "allow.toml"
    notes.append(Note(
        "info" if cfg.exists() or allow.exists() else "info",
        "configuration is read from the BASE side of the diff",
        f"config: {'present' if cfg.exists() else 'absent (defaults)'}; "
        f"allowlist: {'present' if allow.exists() else 'absent'}. "
        "Both are read from the base commit on purpose, so a diff cannot exempt "
        "itself. A new allowlist entry therefore takes effect on the *next* diff, "
        "and must be committed.",
    ))

    notes.append(Note(
        "info",
        "use a three-dot range for pull requests",
        "`greenwash check BASE...HEAD` resolves through the merge base, so the "
        "diff holds only the PR's own commits. A two-dot range drags in "
        "base-branch commits and reports findings the PR did not introduce.",
    ))

    return notes


_SYMBOL = {"ok": "OK  ", "warn": "WARN", "problem": "FAIL", "info": "note"}


def run(root: str = ".", stream=None) -> int:
    """Print the report. 0 when nothing is wrong, 1 when something is."""
    import sys

    stream = stream or sys.stdout
    notes = collect(Path(root))
    for note in notes:
        stream.write(f"{_SYMBOL[note.level]}  {note.title}\n")
        for line in _wrap(note.detail):
            stream.write(f"      {line}\n")
        stream.write("\n")

    problems = [n for n in notes if n.level == "problem"]
    warns = [n for n in notes if n.level == "warn"]
    stream.write(
        f"summary: {len(problems)} problem(s), {len(warns)} warning(s). "
        "greenwash cannot verify branch protection; see the note above.\n"
    )
    return 1 if problems or warns else 0


def _wrap(text: str, width: int = 76) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines
