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
    "ci": [".github/workflows/**", ".gitlab-ci.yml", ".pre-commit-config.yaml"],
    "snapshot": ["**/__snapshots__/**", "**/golden/**", "**/*.golden", "**/*.snap"],
    "lockfile": [
        "poetry.lock",
        "uv.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
        "requirements*.txt",
    ],
    "docs": ["**/*.md", "**/*.rst"],
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


def load_config(data: bytes | None) -> tuple[Config, str | None]:
    """-> (config, error). A malformed config is never silently ignored: a
    hardened `fail_on` reverting to defaults must be visible (SPEC §6)."""
    cfg = Config()
    if not data:
        return cfg, None
    try:
        raw = tomllib.loads(data.decode("utf-8", errors="replace"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        return cfg, f".greenwash/config.toml could not be parsed ({exc}); defaults are in effect"
    roles = raw.get("roles")
    if isinstance(roles, dict):
        for role, globs in roles.items():
            if isinstance(globs, list) and all(isinstance(g, str) for g in globs):
                cfg.roles[role] = globs
    gate = raw.get("gate", {})
    if isinstance(gate, dict):
        fail_on = gate.get("fail_on")
        if fail_on in SEVERITY_ORDER:
            cfg.fail_on = fail_on
        oee = gate.get("on_engine_error")
        if oee in ("pass_with_warning", "block"):
            cfg.on_engine_error = oee
    detectors = raw.get("detectors", {})
    if isinstance(detectors, dict):
        disable = detectors.get("disable")
        if isinstance(disable, list) and all(isinstance(d, str) for d in disable):
            cfg.disabled_detectors = disable
    return cfg, None
