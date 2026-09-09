"""Resolve configuration sources without importing or executing the subject."""
from __future__ import annotations

import configparser
import posixpath
from decimal import Decimal, InvalidOperation

from .model import MAX_SOURCES, QualityError, Resolved, inside, joined, location
from .policy import toml
from .snapshot import source

NAMES = {
    "coverage": [".coveragerc", ".coveragerc.toml", "setup.cfg", "tox.ini", "pyproject.toml"],
    "ruff": [".ruff.toml", "ruff.toml", "pyproject.toml"],
    "mypy": ["mypy.ini", ".mypy.ini", "pyproject.toml", "setup.cfg"],
}


def decode(data):
    try:
        return data.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeError as exc:
        raise QualityError("SOURCE_INVALID", "Configuration is not UTF-8", kind="error") from exc


def read_config(data, path, tool):
    text = decode(data)
    if path.endswith(".toml"):
        raw = toml(data)
        if posixpath.basename(path) == "pyproject.toml":
            tools = raw.get("tool", {})
            if not isinstance(tools, dict):
                raise QualityError("SOURCE_INVALID", "Invalid tool section", kind="error")
            raw = tools.get(tool)
        if raw is not None and not isinstance(raw, dict):
            raise QualityError("SOURCE_INVALID", "Expected a tool table", kind="error")
        return raw, text
    ini = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        ini.read_string(text)
    except configparser.Error as exc:
        raise QualityError("SOURCE_INVALID", "Invalid INI source", kind="error") from exc
    if ini.defaults():
        raise QualityError("CONTEXT_UNRESOLVED", "INI DEFAULT inheritance is not modeled")
    if tool == "coverage":
        prefix = "coverage:" if posixpath.basename(path) in {"setup.cfg", "tox.ini"} else ""
        raw = {s[len(prefix):]: dict(ini[s]) for s in ini.sections() if s.startswith(prefix)}
        if prefix:
            raw = {s: value for s, value in raw.items() if s in {"run", "report", "html", "xml", "json", "lcov", "paths"}}
        return raw or None, text
    if tool == "mypy":
        if not ini.has_section("mypy"):
            return None, text
        raw = dict(ini["mypy"])
        if any(s.startswith("mypy-") for s in ini.sections()):
            raw["overrides"] = True
        return raw, text
    raise QualityError("SOURCE_INVALID", "Ruff requires TOML configuration", kind="error")


def choose(snapshot, target, side, result, root=None):
    root = target.root if root is None else root
    paths = ([target.config] if target.config != "auto" and root == target.root
             else [joined(root, n) for n in NAMES[target.tool]])
    chosen = None
    for path in paths:
        record, data = source(snapshot, side, path, "candidate")
        result.sources.append(record)
        if data is None:
            continue
        if chosen is not None:
            # A lower-precedence file is shadowed, not a second effective policy.
            record["role"] = "shadowed"
            continue
        raw, text = read_config(data, path, target.tool)
        if raw is None:
            continue
        chosen = (path, raw, text)
        record["role"] = "selected"
    if len(result.sources) > MAX_SOURCES:
        raise QualityError("RESOURCE_LIMIT", "Configuration source closure exceeds limit")
    return chosen


def resolved_sources(snapshot, target, side):
    result = Resolved()
    chosen = choose(snapshot, target, side, result)
    if chosen is None:
        return result, {}, target.config if target.config != "auto" else joined(target.root, NAMES[target.tool][0]), ""
    path, raw, text = chosen
    result.layers = [(path, raw, text)]
    # Nested configurations can override a root target. v0.4 does not silently
    # apply the root settings to a nested Ruff domain it has not resolved.
    if target.tool == "ruff" and target.config == "auto":
        nested = [p for p in snapshot.paths if inside(p, target.root)
                  and posixpath.basename(p) in NAMES["ruff"]
                  and posixpath.dirname(p) != ("" if target.root == "." else target.root)]
        for nested_path in nested:
            record, data = source(snapshot, side, nested_path, "context")
            result.sources.append(record)
            if data is not None and read_config(data, nested_path, "ruff")[0] is not None:
                raise QualityError("CONTEXT_UNRESOLVED", "Nested Ruff configuration requires a separate explicit target")
    if target.tool == "ruff":
        seen = {path}
        current_path, current_raw = path, raw
        while "extend" in current_raw:
            parent = current_raw["extend"]
            if not isinstance(parent, str) or any(c in parent for c in "\\\0\r\n:$") or parent.startswith("/"):
                raise QualityError("EXTERNAL_SOURCE", "Ruff extend must be a literal repository path")
            parent = posixpath.normpath(posixpath.join(posixpath.dirname(current_path), parent))
            if parent == ".." or parent.startswith("../"):
                raise QualityError("EXTERNAL_SOURCE", "Ruff extend leaves the repository")
            if parent in seen:
                raise QualityError("INHERITANCE_CYCLE", "Ruff extend cycle")
            if len(seen) >= 8:
                raise QualityError("RESOURCE_LIMIT", "Ruff extend depth limit")
            seen.add(parent)
            record, data = source(snapshot, side, parent, "inherited")
            result.sources.append(record)
            if data is None:
                raise QualityError("CONTEXT_UNRESOLVED", "Ruff extend source is absent")
            parent_raw, parent_text = read_config(data, parent, "ruff")
            if parent_raw is None:
                raise QualityError("SOURCE_INVALID", "Extended file has no Ruff configuration", kind="error")
            result.layers.insert(0, (parent, parent_raw, parent_text))
            current_path, current_raw = parent, parent_raw
    return result, raw, path, text


def boolean(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false", "on", "off", "1", "0", "yes", "no"}:
        return value.lower() in {"true", "on", "1", "yes"}
    raise QualityError("SOURCE_INVALID", "Invalid boolean setting", kind="error")


def integer(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise QualityError("SOURCE_INVALID", "Invalid numeric setting", kind="error")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise QualityError("SOURCE_INVALID", "Invalid numeric setting", kind="error") from exc
    if not number.is_finite():
        raise QualityError("SOURCE_INVALID", "Non-finite numeric setting", kind="error")
    if number != number.to_integral_value():
        raise QualityError("CONTEXT_UNRESOLVED", "Fractional thresholds are not qualified")
    return int(number)


def strings(value):
    if isinstance(value, str):
        value = [p.strip() for p in value.replace("\n", ",").split(",") if p.strip()]
    if not isinstance(value, list) or not all(isinstance(p, str) for p in value):
        raise QualityError("SOURCE_INVALID", "Expected string list", kind="error")
    if len(value) > 256 or any(len(p) > 1024 for p in value):
        raise QualityError("RESOURCE_LIMIT", "Setting list limit exceeded")
    return value


def attach(result, dimension, value, path, side, text, key):
    result.values[dimension] = value
    result.locations[dimension] = location(path, side, text, key)


def declarations(raw):
    def convert(value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [convert(v) for v in value]
        if isinstance(value, (str, bool, int)) or value is None:
            return value
        return str(value)
    return convert(raw)


def check_dynamic(raw):
    if isinstance(raw, str) and "$" in raw:
        raise QualityError("DYNAMIC_VALUE", "Environment expansion is not evaluated")
    if isinstance(raw, dict):
        for value in raw.values():
            check_dynamic(value)
    if isinstance(raw, list):
        for value in raw:
            check_dynamic(value)
