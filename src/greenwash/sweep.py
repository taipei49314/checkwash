"""Batch analysis over a repository's history — the measurement harness.

`greenwash sweep` runs the analyzer over N consecutive commits of any local
repo and reports how often each rule fires at each severity. On human-authored
history the high-severity rate IS the false-positive rate, which is the number
the "blockable by default" claim lives or dies on (SPEC §5, gates README).

No network, no cloning: point it at a repo you already have.
"""

from __future__ import annotations

import datetime
import json
from collections import Counter
from dataclasses import dataclass, field

from greenwash.allowlist import load_allowlist
from greenwash.config import load_config
from greenwash.contract import Contract
from greenwash.deps import MANIFESTS, parse_manifest
from greenwash.engine import analyze
from greenwash.gitio import GitError, list_range_changes, read_base_file
from greenwash.pyenv import known_baseline


@dataclass
class SweepResult:
    commits: int = 0
    errors: int = 0
    skipped: int = 0  # no parent to diff against (root commit)
    touching_tests: int = 0
    blocked: int = 0
    by_rule_severity: Counter = field(default_factory=Counter)
    blocked_commits: list[dict] = field(default_factory=list)

    def to_json(self) -> str:
        counts: dict[str, dict[str, int]] = {}
        for (rule, severity), n in sorted(self.by_rule_severity.items()):
            counts.setdefault(rule, {})[severity] = n
        payload = {
            "commits_analysed": self.commits,
            "commits_touching_tests": self.touching_tests,
            "commits_blocked": self.blocked,
            "block_rate": (
                round(self.blocked / self.commits, 4) if self.commits else 0.0
            ),
            "engine_errors": self.errors,
            "commits_skipped_no_parent": self.skipped,
            "findings_by_rule": counts,
            "blocked_commits": self.blocked_commits,
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def _commit_list(repo: str, revs: str, limit: int) -> list[str]:
    from greenwash.gitio.git import _run

    out = _run(repo, ["rev-list", "--no-merges", f"--max-count={limit}", revs])
    return [line for line in out.decode("ascii", "replace").split("\n") if line.strip()]


def sweep(repo: str, revs: str, limit: int, today: datetime.date, fail_on: str | None = None) -> SweepResult:
    result = SweepResult()
    commits = _commit_list(repo, revs, limit)
    for sha in commits:
        parent = f"{sha}^"
        try:
            changes = list_range_changes(repo, parent, sha)
        except GitError:
            # A root commit has no parent: nothing to diff, not an error.
            result.skipped += 1
            continue
        config, _err = load_config(read_base_file(repo, parent, ".greenwash/config.toml"))
        if fail_on:
            config.fail_on = fail_on
        allow, _aerr = load_allowlist(read_base_file(repo, parent, ".greenwash/allow.toml"))

        declared: set[str] = set()
        found = False
        for manifest in MANIFESTS:
            data = read_base_file(repo, parent, manifest)
            if data is not None:
                found = True
                declared |= parse_manifest(manifest, data)
        known = (known_baseline() | declared) if found else None

        try:
            ir, findings, verdict = analyze(
                changes, config, Contract(), allow, today, base_label=parent,
                head_label=sha, known_modules=known,
            )
        except Exception:  # noqa: BLE001 - a sweep must survive one bad commit
            result.errors += 1
            continue

        result.commits += 1
        if any(f.role == "test" for f in ir.files) or any(
            f.role == "conftest" for f in ir.files
        ):
            result.touching_tests += 1
        visible = [f for f in findings if not f.allowlisted]
        for f in visible:
            result.by_rule_severity[(f.rule, f.severity)] += 1
        if verdict == "block":
            result.blocked += 1
            result.blocked_commits.append(
                {
                    "commit": sha,
                    "findings": [
                        {
                            "rule": f.rule,
                            "severity": f.severity,
                            "path": f.path,
                            "unit": f.unit,
                            "message": f.message,
                        }
                        for f in visible
                        if f.severity in ("high", "critical")
                    ],
                }
            )
    return result
