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
import re
from collections import Counter
from dataclasses import dataclass, field

from checkwash import __version__
from checkwash.allowlist import load_allowlist
from checkwash.config import load_config, read_base_config_file
from checkwash.contract import Contract
from checkwash.deps import MANIFESTS, SKIPPABLE_OVERSIZED, parse_manifest, project_names
from checkwash.policy_shadow import PolicyBase
from checkwash.engine import analyze
from checkwash.gitio import GitSourceOverLimit, grep_head_paths, list_range_changes, read_base_file
from checkwash.gitio.pytest_configs import PairedPytestConfigs
from checkwash.gitio.snapshot import GitSnapshot
from checkwash.ir.model import judged_as_test
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
    # Optional, per-commit observations; neither findings nor successful runs.
    commit_diagnostics: list[dict] = field(default_factory=list)

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
        if self.commit_diagnostics:
            payload["commit_diagnostics"] = self.commit_diagnostics
        return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def _diagnostic(result, sha, parent, phase, kind, message, **details):
    event = {"commit": sha, "phase": phase, "kind": kind, "message": message, **details}
    if parent is not None:
        event["parent"] = parent
    result.commit_diagnostics.append(event)


def _parse_position(error: str) -> dict:
    # Only the parser's numeric suffix is retained. Never copy a TOML key,
    # supplied value or arbitrary exception text into a new output surface.
    match = re.search(
        r"\(at line ([0-9]{1,9}), column ([0-9]{1,9})\)\); "
        r"(?:defaults are in effect|no exemptions are active)$", error[-160:],
    )
    return {"line": int(match[1]), "column": int(match[2])} if match else {}


def _config_warning(warning: str) -> tuple[str, str]:
    # load_config's value diagnostics may contain credentials in a supplied
    # string or role name. Report the fixed setting and fallback, not that value.
    if warning.startswith("config.toml: gate.fail_on "):
        return "gate.fail_on", "invalid gate.fail_on; default 'high' is in effect"
    if warning.startswith("config.toml: gate.on_engine_error "):
        return "gate.on_engine_error", "invalid gate.on_engine_error; default 'pass_with_warning' is in effect"
    if warning.startswith("config.toml: unknown role "):
        return "roles", "unknown role ignored"
    if warning.startswith("config.toml: roles."):
        return "roles", "roles entry must be a list of glob strings; ignored"
    if warning.startswith("config.toml: detectors.disable "):
        return "detectors.disable", "detectors.disable must be a list of rule IDs; ignored"
    return "config", "configuration value warning; supplied value omitted"


def _exception_details(exc: Exception, phase: str) -> dict:
    # Do not call str(exc): Git stderr and repository-controlled paths/values
    # can contain credentials or terminal controls. Even formatting an unknown
    # exception can fail. The type and phase still locate the failed operation.
    name = type(exc).__name__
    name = name if len(name) <= 80 and name.isidentifier() else "Exception"
    reason = "source byte limit exceeded" if isinstance(exc, GitSourceOverLimit) else "operation could not be completed"
    return {"exception_type": name, "message": f"{phase}: {reason}; exception text omitted"}


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
        parent = None
        phase = "read_commit"
        try:
            from checkwash.gitio.git import read_commit_parents

            parents = read_commit_parents(repo, sha)
            if not parents:
                result.skipped += 1  # Proven root, never inferred from a read failure.
                continue
            parent = parents[0]
            phase = "read_changes"
            changes = list_range_changes(repo, parent, sha)
            phase = "load_config"
            config_path, config_data = read_base_config_file(repo, parent, "config.toml")
            config, config_error, config_warnings = load_config(config_data, path=config_path)
            if config_error:
                _diagnostic(result, sha, parent, phase, "config_parse_error",
                            f"{config_path}: could not be parsed; defaults are in effect",
                            path=config_path, **_parse_position(config_error))
            for warning in config_warnings:
                setting, message = _config_warning(warning)
                _diagnostic(result, sha, parent, phase, "config_warning",
                            f"{config_path}: {message}", path=config_path, field=setting)
            if fail_on:
                config.fail_on = fail_on
            phase = "load_allowlist"
            allow_path, allow_data = read_base_config_file(repo, parent, "allow.toml")
            allow, allow_error = load_allowlist(allow_data, path=allow_path)
            if allow_error:
                _diagnostic(result, sha, parent, phase, "allow_parse_error",
                            f"{allow_path}: could not be parsed; no exemptions are active",
                            path=allow_path, **_parse_position(allow_error))

            phase = "read_manifests"
            declared: set[str] = set()
            self_modules: set[str] = set()
            found = False
            for manifest in MANIFESTS:
                try:
                    data = read_base_file(repo, parent, manifest)
                except GitSourceOverLimit:
                    # As `check` does, without its stderr note (#415).
                    if manifest not in SKIPPABLE_OVERSIZED:
                        raise
                    continue
                if data is not None:
                    found = True
                    declared |= parse_manifest(manifest, data)
                    self_modules |= project_names(manifest, data)
            known = (known_baseline() | declared) if found else None

            phase = "analyze"
            root_snapshot = GitSnapshot(repo, sha, side="head")
            pytest_configs = PairedPytestConfigs(
                GitSnapshot(repo, parent, side="base"), root_snapshot,
            )
            ir, findings, verdict = analyze(
                changes, config, Contract(), allow, today, base_label=parent,
                head_label=sha, known_modules=known, self_modules=self_modules,
                head_reader=root_snapshot.read,
                head_searcher=lambda needles, _sha=sha: grep_head_paths(repo, _sha, needles),
                root_reader=root_snapshot.read,
                root_searcher=root_snapshot.search,
                root_path_lister=root_snapshot.list_paths,
                root_batch_reader=root_snapshot.read_many,
                pytest_configs=pytest_configs,
                policy_base=PolicyBase(config_path, config_data, allow_path, allow_data),
            )
        except Exception as exc:  # noqa: BLE001 - a sweep must survive one bad commit
            result.errors += 1
            _diagnostic(result, sha, parent, phase, "analysis_exception", **_exception_details(exc, phase))
            continue

        result.commits += 1
        if ir.globals.prod_opaque_change:
            result.opaque_prod_change += 1
        if any(judged_as_test(f) for f in ir.files) or any(
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
