"""Ruff configuration adapter."""
from __future__ import annotations
import posixpath
import re
from .model import QualityError, inside
from .resolver import attach, boolean, check_dynamic, declarations, integer, resolved_sources, strings
from .snapshot import source
from .scope import scope

def selection_updates(select, ignore, profile):
    catalog = set(profile["rule_catalog"])
    preview = set(profile.get("preview_rules", []))
    def matches(selector):
        if selector == "ALL":
            if profile.get("uncoded_rules"):
                raise QualityError("CONTEXT_UNRESOLVED", "ALL includes rules without qualified legacy codes")
            return catalog - preview
        found = {r for r in catalog if r.startswith(selector)}
        if not found:
            raise QualityError("UNSUPPORTED_KEY", "Unknown or unsupported Ruff rule selector: " + selector)
        if selector in preview:
            raise QualityError("CONTEXT_UNRESOLVED", "Preview rule selection is not qualified")
        return found - preview
    choices = {}
    for enabled, selectors in ((True, select), (False, ignore)):
        for selector in selectors:
            for code in matches(selector):
                priority = 0 if selector == "ALL" else len(selector)
                if code not in choices or priority >= choices[code][0]:
                    choices[code] = (priority, enabled)
    return {code: enabled for code, (_, enabled) in choices.items()}


def selected_rules(select, ignore, profile):
    return sorted(code for code, enabled in selection_updates(select, ignore, profile).items() if enabled)


def ruff(snapshot, target, side, profile):
    result, raw, path, text = resolved_sources(snapshot, target, side)
    layers = result.layers or [(path, raw, text)]
    result.declarations = declarations({p: r for p, r, _ in layers})
    dimension = "ruff.lint.rules"
    allowed = {"select", "extend-select", "ignore"}
    top_allowed = {"extend", "lint", "exclude", "extend-exclude", "format", "line-length", "indent-width", "cache-dir"}
    unknown = set()
    selections, scope_raw = [], {}
    for layer_path, layer, layer_text in layers:
        check_dynamic(layer)
        lint = layer.get("lint", {})
        if not isinstance(lint, dict):
            raise QualityError("SOURCE_INVALID", "Ruff lint settings must be a table", kind="error")
        unknown.update((set(lint) - allowed) | (set(layer) - top_allowed))
        selections.append(lint)
        if "exclude" in layer:
            scope_raw["exclude"] = layer["exclude"]
        scope_raw["extend-exclude"] = strings(scope_raw.get("extend-exclude", [])) + strings(layer.get("extend-exclude", []))
    if unknown:
        result.problem("UNSUPPORTED_KEY", "Unqualified Ruff context: " + ", ".join(sorted(unknown)), [dimension, "ruff.scope"])
    else:
        if not any("select" in lint for lint in selections) and profile.get("uncoded_rules"):
            raise QualityError("CONTEXT_UNRESOLVED", "Default selection includes unqualified uncoded rules; declare explicit supported selectors")
        value = set(profile["default_rules"])
        carry = []
        for lint in selections:
            select = strings(lint.get("select", []))
            extend = strings(lint.get("extend-select", []))
            ignore = strings(lint.get("ignore", []))
            updates = selection_updates(select + extend, ignore + carry, profile)
            carry = ignore if "select" in lint and not select and not extend else []
            if "select" in lint:
                value = set()
            for code, enabled in updates.items():
                if enabled:
                    value.add(code)
                else:
                    value.discard(code)
        attach(result, dimension, sorted(value), path, side, text, "ignore")
    try:
        if unknown:
            raise QualityError("CONTEXT_UNRESOLVED", "Ruff scope context is not qualified")
        if any(posixpath.dirname(p) != posixpath.dirname(path) and ("exclude" in r or r.get("extend-exclude")) for p, r, _ in layers):
            raise QualityError("CONTEXT_UNRESOLVED", "Inherited exclude path anchoring is not qualified")
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
        value = scope(snapshot, target, strings(scope_raw.get("exclude", [])) + strings(scope_raw.get("extend-exclude", [])), profile, result, side, "lint")
        if "exclude" not in scope_raw:
            value = [p for p in value if not (set(p.split("/")) & set(profile["default_excludes"]))]
        attach(result, "ruff.scope", value, path, side, text, "exclude")
    except QualityError as exc:
        if exc.kind == "error":
            raise
        result.problem(exc.code, str(exc), ["ruff.scope"])
    return result


