"""Configuration (.greenwash/config.toml, read from the BASE side — SPEC §1).

Detector logic is not configurable; detectors can only be disabled whole.
"""

from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass, field

DEFAULT_ROLES: dict[str, list[str]] = {
    "conftest": ["**/conftest.py"],
    "test": ["tests/**", "**/test_*.py", "**/*_test.py"],
    # guardrail = agent-instruction files + greenwash's own config. NOT
    # pre-commit: hook-version bumps are weekly routine in human repos and
    # critical-on-touch made it 62% of all blocked commits in the 1800-commit
    # FP sweep. It lives under ci (warn; weakened commands still escalate).
    "guardrail": [
        "CLAUDE.md",
        "AGENTS.md",
        ".cursorrules",
        ".claude/**",
        ".greenwash/**",
    ],
    # CI and test-runner configuration. pytest's own config decides which
    # files and functions are collected and what `addopts` filters them, so
    # editing it can silence the entire suite — and none of these files had a
    # role at all, which meant no detector ever looked at them (reader audit
    # 2026-08-02).
    "ci": [
        ".github/workflows/**",
        ".gitlab-ci.yml",
        ".pre-commit-config.yaml",
        "pytest.ini",
        "tox.ini",
        "setup.cfg",
        # Any pyproject, not just the root one: an example app's pyproject is
        # still packaging/test-runner config, and as prod it fed the opaque
        # exemption (13 flask commits in the FP corpus).
        "**/pyproject.toml",
        # Other pipelines run tests too. Knowing only GitHub Actions and
        # GitLab meant the identical weakening blocked or passed depending on
        # which CI the project happened to use (probe 2026-08-07).
        ".circleci/**",
        ".buildkite/**",
        "**/Jenkinsfile",
        ".travis.yml",
        ".drone.yml",
        "appveyor.yml",
        "azure-pipelines.yml",
        "bitbucket-pipelines.yml",
        # Task runners whose entire purpose is running sessions/recipes.
        # Multi-purpose runners (Makefile, shell scripts) are NOT here: they
        # are classified by content in the engine, because a Makefile that
        # builds a C extension is production and its edit is real repair
        # evidence. See engine._is_runner_script.
        "noxfile.py",
        # Every spelling explicitly, because `_match` uses fnmatchcase on
        # purpose (fnmatch folds case on Windows and broke the byte-identical
        # guarantee), and because a plain "justfile" pattern matched neither
        # `Justfile` nor `ci/justfile` — both measured as complete bypasses on
        # 2026-08-11 (THREATMODEL 87).
        "**/justfile",
        "**/Justfile",
        "**/.justfile",
        "**/JUSTFILE",
    ],
    "snapshot": ["**/__snapshots__/**", "**/golden/**", "**/*.golden", "**/*.snap"],
    "lockfile": [
        "poetry.lock",
        "uv.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
        "requirements*.txt",
        # pip-compile sources; fnmatch's * crosses "/", so this also catches
        # flask's requirements/*.in layout. A pin source changes nothing at
        # runtime until compiled, and the compiled .txt co-changes.
        "requirements*.in",
    ],
    "docs": ["**/*.md", "**/*.rst", "**/README"],
}

_ROLE_ORDER = ["guardrail", "ci", "snapshot", "lockfile", "conftest", "test", "docs"]

SEVERITY_ORDER = {"info": 0, "warn": 1, "high": 2, "critical": 3}


@dataclass
class Config:
    roles: dict[str, list[str]] = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_ROLES.items()})
    fail_on: str = "high"
    on_engine_error: str = "pass_with_warning"  # or "block"
    disabled_detectors: list[str] = field(default_factory=list)

    def role_of(self, path: str) -> str:
        p = path.replace("\\", "/")
        for role in _ROLE_ORDER:
            for pattern in self.roles.get(role, []):
                if _match(p, pattern):
                    return role
        return "prod"


def _match(path: str, pattern: str) -> bool:
    # fnmatchcase, never fnmatch: fnmatch folds case on Windows, so the same
    # commit pair classified files differently per OS and broke the
    # byte-identical guarantee (SPEC §8).
    if fnmatch.fnmatchcase(path, pattern):
        return True
    # fnmatch's "*" already crosses "/" (it is not pathlib-style), but a
    # leading "**/" should also match paths with no directory component.
    if pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]):
        return True
    return False


def load_config(data: bytes | None) -> tuple[Config, str | None, list[str]]:
    """-> (config, error, warnings). A malformed config is never silently
    ignored: a hardened `fail_on` reverting to defaults must be visible
    (SPEC §6).

    The error slot is for parse failures (defaults in effect, exit-2-able
    under `on_engine_error = "block"`). Value-level problems — a `fail_on`
    that is not a severity, an `on_engine_error` spelling the enum does not
    contain, roles that are not globs — collect in `warnings`: visible in
    stderr and `config_errors`, never fatal, because the one value such a
    warning can concern (`on_engine_error` itself) must not become the
    engine error it describes (audit 2026-08-19: `on_engine_error = "Block"`
    silently reverted to `pass_with_warning`, the loosening direction, with
    `config_errors: []`)."""
    cfg = Config()
    if not data:
        return cfg, None, []
    try:
        raw = tomllib.loads(data.decode("utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return cfg, f".greenwash/config.toml could not be parsed ({exc}); defaults are in effect", []
    warnings: list[str] = []
    roles = raw.get("roles")
    if isinstance(roles, dict):
        for role, globs in roles.items():
            if isinstance(globs, list) and all(isinstance(g, str) for g in globs):
                if role not in cfg.roles:
                    warnings.append(f"config.toml: unknown role '{role}' (known: {', '.join(_ROLE_ORDER)})")
                    continue
                cfg.roles[role] = globs
            else:
                warnings.append(f"config.toml: roles.{role} must be a list of glob strings; ignored")
    gate = raw.get("gate", {})
    if isinstance(gate, dict):
        fail_on = gate.get("fail_on")
        if fail_on in SEVERITY_ORDER:
            cfg.fail_on = fail_on
        elif fail_on is not None:
            warnings.append(
                f"config.toml: gate.fail_on must be one of {', '.join(SEVERITY_ORDER)}; "
                f"got {fail_on!r}, default 'high' is in effect"
            )
        oee = gate.get("on_engine_error")
        if oee in ("pass_with_warning", "block"):
            cfg.on_engine_error = oee
        elif oee is not None:
            warnings.append(
                "config.toml: gate.on_engine_error must be 'pass_with_warning' or 'block'; "
                f"got {oee!r}, default 'pass_with_warning' is in effect"
            )
    detectors = raw.get("detectors", {})
    if isinstance(detectors, dict):
        disable = detectors.get("disable")
        if isinstance(disable, list) and all(isinstance(d, str) for d in disable):
            cfg.disabled_detectors = disable
        elif disable is not None:
            warnings.append("config.toml: detectors.disable must be a list of rule IDs; ignored")
    return cfg, None, warnings
