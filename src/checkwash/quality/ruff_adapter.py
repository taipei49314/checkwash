"""Ruff configuration adapter."""
from __future__ import annotations
import posixpath
import re
from .model import QualityError, inside
from .resolver import attach, boolean, check_dynamic, declarations, integer, resolved_sources, strings
from .snapshot import source
from .scope import scope

def selected_rules(select, ignore, profile):
    catalog = set(profile["rule_catalog"])
    preview = set(profile.get("preview_rules", []))
    def matches(selector):
        if selector == "ALL":
            return catalog - preview
        found = {r for r in catalog if r.startswith(selector)}
        if not found:
            raise QualityError("UNSUPPORTED_KEY", "Unknown or unsupported Ruff rule selector: " + selector)
        if found & preview:
            raise QualityError("CONTEXT_UNRESOLVED", "Preview rule selection is not qualified")
        return found
    choices = {}
    for enabled, selectors in ((True, select), (False, ignore)):
        for selector in selectors:
            for code in matches(selector):
                priority = 0 if selector == "ALL" else len(selector)
                if code not in choices or priority >= choices[code][0]:
                    choices[code] = (priority, enabled)
    return sorted(code for code, (_, enabled) in choices.items() if enabled)


def ruff(snapshot, target, side, profile):
    result, raw, path, text = resolved_sources(snapshot, target, side)
    result.declarations = declarations(raw)
    check_dynamic(raw)
    lint = raw.get("lint", {})
    if not isinstance(lint, dict):
        raise QualityError("SOURCE_INVALID", "Ruff lint settings must be a table", kind="error")
    dimension = "ruff.lint.rules"
    allowed = {"select", "extend-select", "ignore"}
    top_allowed = {"lint", "exclude", "extend-exclude", "format", "line-length", "indent-width", "cache-dir"}
    unknown = (set(lint) - allowed) | (set(raw) - top_allowed)
    if unknown:
        result.problem("UNSUPPORTED_KEY", "Unqualified Ruff context: " + ", ".join(sorted(unknown)), [dimension, "ruff.scope"])
    else:
        select = strings(lint["select"]) if "select" in lint else list(profile["default_rules"])
        select += strings(lint.get("extend-select", []))
        value = selected_rules(select, strings(lint.get("ignore", [])), profile)
        attach(result, dimension, value, path, side, text, "ignore")
    try:
        if unknown:
            raise QualityError("CONTEXT_UNRESOLVED", "Ruff scope context is not qualified")
        # Respect gitignore only after a separate qualification. Existing
        # ignore files must not be mistaken for absent configuration.
        for candidate in snapshot.paths:
            if posixpath.basename(candidate) in {".gitignore", ".ignore"}:
                record, data = source(snapshot, side, candidate, "context")
                result.sources.append(record)
                if data and data.strip():
                    raise QualityError("CONTEXT_UNRESOLVED", "Ruff gitignore discovery is not qualified")
        # Native defaults do not match the accepted user-pattern grammar;
        # qualification supplies their known path-segment exclusions.
        value = scope(snapshot, target, strings(raw.get("exclude", [])) + strings(raw.get("extend-exclude", [])), profile, result, side, "lint")
        if "exclude" not in raw:
            value = [p for p in value if not (set(p.split("/")) & set(profile["default_excludes"]))]
        attach(result, "ruff.scope", value, path, side, text, "exclude")
    except QualityError as exc:
        if exc.kind == "error":
            raise
        result.problem(exc.code, str(exc), ["ruff.scope"])
    return result


