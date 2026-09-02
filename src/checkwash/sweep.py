"""Batch analysis over a repository's history — the measurement harness.

`checkwash sweep` runs the analyzer over N consecutive commits of any local
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

from checkwash import __version__
from checkwash.allowlist import load_allowlist
from checkwash.config import load_config, read_base_config_file
from checkwash.contract import Contract
from checkwash.deps import MANIFESTS, parse_manifest, project_names
from checkwash.engine import analyze
from checkwash.gitio import GitError, grep_head_paths, list_range_changes, read_base_file
from checkwash.pyenv import known_baseline


@dataclass
class SweepResult:
    commits: int = 0
    errors: int = 0
    skipped: int = 0  # no parent to diff against (root commit)
    touching_tests: int = 0
    blocked: int = 0
    by_rule_severity: Counter = field(default_factory=Counter)
    blocked_commits: list[dict] = field(default_factory=list)
    # What was measured, so the numbers can be reproduced from a clone: the
    # newest and oldest commit in the swept range, and the tool version. A
    # sweep JSON that does not say which commits it covered is not a
    # measurement anyone else can check (reader audit 2026-08-02).
    corpus_newest: str = ""
    corpus_oldest: str = ""
    # How many analysed commits carried a prod change checkwash cannot read
    # (non-Python, deleted, or unparseable). Each of those gets the blanket
    # conservative exemption of THREATMODEL #4, so this is the share of the
    # pass rate that rests on a documented blind spot rather than on analysis.
    opaque_prod_change: int = 0

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
            # Said out loud, because it was not. `rev-list --no-merges` means
            # this rate is the rate a *commit* gate sees, not the rate a merge
            # gate sees: on pallets/jinja the merge of a blocked PR blocks
            # with the same findings and never appeared in the sweep, so one
            # defect was counted once where a PR gate hits it twice (field
            # integration 2026-08-07).
            "merge_commits": "excluded (rev-list --no-merges); a merge gate sees them too",
            "commits_with_opaque_prod_change": self.opaque_prod_change,
            "findings_by_rule": counts,
            "blocked_commits": self.blocked_commits,
            "corpus": {
                "newest_commit": self.corpus_newest,
                "oldest_commit": self.corpus_oldest,
                "checkwash_version": __version__,
            },
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def _commit_list(repo: str, revs: str, limit: int) -> list[str]:
    from checkwash.gitio.git import _run

    out = _run(repo, ["rev-list", "--no-merges", f"--max-count={limit}", revs])
    return [line for line in out.decode("ascii", "replace").split("\n") if line.strip()]


def sweep(repo: str, revs: str, limit: int, today: datetime.date, fail_on: str | None = None) -> SweepResult:
    result = SweepResult()
    commits = _commit_list(repo, revs, limit)
    if commits:
        result.corpus_newest = commits[0]
        result.corpus_oldest = commits[-1]
    for sha in commits:
        parent = f"{sha}^"
        try:
            changes = list_range_changes(repo, parent, sha)
        except GitError:
            # A root commit has no parent: nothing to diff, not an error.
            result.skipped += 1
            continue
        config_path, config_data = read_base_config_file(repo, parent, "config.toml")
        config, _err, _warn = load_config(config_data, path=config_path)
        if fail_on:
            config.fail_on = fail_on
        allow_path, allow_data = read_base_config_file(repo, parent, "allow.toml")
        allow, _aerr = load_allowlist(allow_data, path=allow_path)

        declared: set[str] = set()
        self_modules: set[str] = set()
        found = False
        for manifest in MANIFESTS:
            data = read_base_file(repo, parent, manifest)
            if data is not None:
                found = True
                declared |= parse_manifest(manifest, data)
                self_modules |= project_names(manifest, data)
        known = (known_baseline() | declared) if found else None

        try:
            ir, findings, verdict = analyze(
                changes, config, Contract(), allow, today, base_label=parent,
                head_label=sha, known_modules=known, self_modules=self_modules,
                head_reader=lambda p, _sha=sha: read_base_file(repo, _sha, p),
                head_searcher=lambda needles, _sha=sha: grep_head_paths(repo, _sha, needles),
            )
        except Exception:  # noqa: BLE001 - a sweep must survive one bad commit
            result.errors += 1
            continue

        result.commits += 1
        if ir.globals.prod_opaque_change:
            result.opaque_prod_change += 1
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
