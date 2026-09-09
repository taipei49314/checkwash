"""Shared values. Unknown is distinct from absence and never a default."""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass, field

POLICY_PATH = ".checkwash/quality.toml"
ALLOW_PATH = ".checkwash/quality-allow.toml"
MAX_BYTES = 1_000_000  # Existing strict snapshot reader's limit, intentionally retained.
MAX_TOTAL = 16 * 1024 * 1024
MAX_PATHS = 100_000
MAX_SOURCES = 128
RULES = ("QW_THRESHOLD_LOWERED", "QW_RULE_DISABLED", "QW_SCOPE_NARROWED",
         "QW_POLICY_CHANGED", "QW_ANALYSIS_INCOMPLETE")
STRONG_RULES = frozenset(RULES[:3])
TARGET_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")


class QualityError(Exception):
    def __init__(self, code, message, *, kind="incomplete"):
        super().__init__(message)
        self.code, self.kind = code, kind


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def content_digest(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def safe_path(value, *, root=False):
    if not isinstance(value, str) or not value or any(c in value for c in "\\\0\r\n:"):
        raise QualityError("POLICY_INVALID", "Expected a repository-relative slash path", kind="error")
    if root and value == ".":
        return value
    if value.startswith("/") or any(p in {"", ".", ".."} for p in value.rstrip("/").split("/")):
        raise QualityError("POLICY_INVALID", "Path must remain inside the repository", kind="error")
    return value


def inside(path, scope):
    return scope == "." or path == scope.rstrip("/") or path.startswith(scope.rstrip("/") + "/")


def joined(root, path):
    return path if root == "." else posixpath.join(root, path)


def known(value):
    return {"state": "known", "data": value}


@dataclass
class Target:
    id: str
    tool: str
    root: str
    config: str
    profile: str
    paths: list[str]
    version_files: list[str] = field(default_factory=list)


@dataclass
class Resolved:
    values: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    locations: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    declarations: dict = field(default_factory=dict)

    def problem(self, code, message, dimensions):
        self.problems.append((code, message, list(dimensions)))
        for dimension in dimensions:
            self.values.pop(dimension, None)


def location(path, side, text, key):
    """Only claim a key span when its assignment location is unambiguous."""
    matches = list(re.finditer(r"(?m)^\s*" + re.escape(key) + r"\s*=.*$", text))
    if len(matches) != 1:
        return {"side": side, "path": path, "start_line": 1, "start_column": 1,
                "end_line": 1, "end_column": 1}
    match = matches[0]
    start = match.start()
    while start < match.end() and text[start] in " \t\n":
        start += 1
    line = text.count("\n", 0, start) + 1
    column = start - text.rfind("\n", 0, start)
    return {"side": side, "path": path, "start_line": line, "start_column": column,
            "end_line": text.count("\n", 0, match.end()) + 1,
            "end_column": match.end() - text.rfind("\n", 0, match.end())}
