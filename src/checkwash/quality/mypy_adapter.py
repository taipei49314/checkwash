"""Mypy configuration adapter."""
from __future__ import annotations
import posixpath
import re
from .model import QualityError, inside
from .resolver import attach, boolean, check_dynamic, declarations, integer, resolved_sources, strings
from .snapshot import source
from .scope import scope

MYPY_FLAGS = {"disallow_untyped_defs": False, "check_untyped_defs": False,
              "disallow_incomplete_defs": False, "warn_return_any": False,
              "strict_optional": True, "ignore_errors": False, "ignore_missing_imports": False}
MYPY_CODES = {"assignment", "arg-type", "call-arg", "attr-defined", "return-value", "return", "operator", "index", "union-attr"}


def mypy(snapshot, target, side, profile):
    result, raw, path, text = resolved_sources(snapshot, target, side)
    result.declarations = declarations(raw)
    check_dynamic(raw)
    defaults = {**profile.get("mypy_defaults", {}), **MYPY_FLAGS}
    dimensions = ["mypy." + k for k in defaults] + ["mypy.error_codes"]
    harmless = {"show_error_codes", "show_column_numbers", "pretty", "color_output", "cache_dir"}
    allowed = set(defaults) | harmless | {"strict", "enable_error_code", "disable_error_code"}
    unknown = set(raw) - allowed
    # Inline options override global options. Inventory only the declared
    # source universe; every relevant source becomes fingerprint context.
    for candidate in snapshot.paths:
        if candidate.endswith((".py", ".pyi")) and any(inside(candidate, p.rstrip("/")) for p in target.paths):
            record, data = source(snapshot, side, candidate, "context")
            result.sources.append(record)
            if data and re.search(rb"(?m)^\s*#\s*mypy\s*:", data):
                unknown.add("inline-options")
    if unknown:
        result.problem("UNSUPPORTED_KEY", "Unqualified mypy context: " + ", ".join(sorted(unknown)), dimensions)
        return result
    if boolean(raw.get("strict", False)):
        expansion = profile.get("strict_expansion")
        if not expansion or set(expansion) - set(defaults):
            result.problem("CONTEXT_UNRESOLVED", "Full mypy strict expansion is not qualified", dimensions)
            return result
        defaults.update(expansion)
    for key, default in defaults.items():
        attach(result, "mypy." + key, boolean(raw.get(key, default)), path, side, text, key)
    if result.values["mypy.ignore_errors"]:
        for key in defaults:
            if key not in {"ignore_errors", "ignore_missing_imports", "implicit_reexport"}:
                result.values["mypy." + key] = False
        result.values["mypy.ignore_missing_imports"] = True
        if "implicit_reexport" in defaults:
            result.values["mypy.implicit_reexport"] = True
    disabled = set(strings(raw.get("disable_error_code", [])))
    enabled = set(strings(raw.get("enable_error_code", [])))
    if (disabled | enabled) - MYPY_CODES:
        result.problem("UNSUPPORTED_KEY", "Only qualified default mypy error codes can be compared", ["mypy.error_codes"])
    else:
        codes = [] if result.values["mypy.ignore_errors"] else sorted((MYPY_CODES - disabled) | enabled)
        attach(result, "mypy.error_codes", codes, path, side, text, "disable_error_code")
    return result


