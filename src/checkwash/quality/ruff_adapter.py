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
    namespaces = profile.get("selector_namespaces", sorted({re.match(r"[A-Z]+", r).group() for r in catalog}))
    def namespace(value):
        return next((p for p in sorted(namespaces, key=lambda p: (-len(p), p)) if value.startswith(p)), None)
    def matches(selector):
        if selector == "ALL":
            if profile.get("uncoded_rules"):
                raise QualityError("CONTEXT_UNRESOLVED", "ALL includes rules without qualified legacy codes")
            return catalog - preview
        family = namespace(selector)
        found = {r for r in catalog if family is not None and namespace(r) == family and r.startswith(selector)}
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
    return final_rules({code for code, enabled in selection_updates(select, ignore, profile).items() if enabled}, profile)


def final_rules(value, profile):
    value = set(value)
    for preferred, expendable in profile.get("incompatible_rules", []):
        if preferred in value:
            value.discard(expendable)
    return sorted(value)


def _ruff_flat(snapshot, target, side, profile):
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
        attach(result, dimension, final_rules(value, profile), path, side, text, "ignore")
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


def ruff(snapshot, target, side, profile, common_paths=None):
    """Resolve auto configuration per surviving source, on both snapshots.

    Comparing by stable source path detects a new nested config even when the
    old snapshot had no corresponding configuration domain.
    """
    if target.config != "auto":
        return _ruff_flat(snapshot, target, side, profile)
    from dataclasses import replace
    from .model import Resolved, canonical
    from .resolver import choose

    paths = sorted(p for p in (snapshot.paths if common_paths is None else common_paths)
                   if p.endswith((".py", ".pyi")) and any(p == s or (s.endswith("/") and p.startswith(s)) for s in target.paths))
    if len(paths) * max(1, len(profile["rule_catalog"])) > 1_000_000:
        raise QualityError("RESOURCE_LIMIT", "Ruff configuration-domain comparison budget exceeded")
    result = Resolved()
    domains = {}
    selection_cache = {}
    for subject in paths or [None]:
        directory = posixpath.dirname(subject) if subject else ("" if target.root == "." else target.root)
        initial_directory = directory
        if directory in selection_cache:
            domains.setdefault(selection_cache[directory], []).append(subject)
            continue
        selected = None
        while True:
            selected = choose(snapshot, target, side, result, root=directory or ".")
            if selected is not None or not directory:
                break
            directory = posixpath.dirname(directory)
        config_path = selected[0] if selected else ""
        selection_cache[initial_directory] = config_path
        domains.setdefault(config_path, []).append(subject)
    scopes = set()
    all_scope_known = True
    for config_path, subjects in sorted(domains.items()):
        domain = replace(target, config=config_path or "auto", root=posixpath.dirname(config_path) or ".",
                         paths=[p for p in subjects if p] or target.paths)
        resolved = _ruff_flat(snapshot, domain, side, profile)
        result.sources.extend(resolved.sources)
        result.declarations[config_path] = resolved.declarations
        for subject in subjects:
            dim = "ruff.lint.rules@" + (subject or "root")
            if "ruff.lint.rules" in resolved.values:
                result.values[dim] = resolved.values["ruff.lint.rules"]
                if "ruff.lint.rules" in resolved.locations:
                    result.locations[dim] = resolved.locations["ruff.lint.rules"]
            for code, message, dimensions in resolved.problems:
                if "ruff.lint.rules" in dimensions:
                    result.problem(code, message, [dim])
        if "ruff.scope" in resolved.values:
            scopes.update(resolved.values["ruff.scope"])
            if "ruff.scope" in resolved.locations:
                result.locations["ruff.scope"] = resolved.locations["ruff.scope"]
        else:
            all_scope_known = False
            for code, message, dimensions in resolved.problems:
                if "ruff.scope" in dimensions:
                    result.problem(code, message, ["ruff.scope"])
    if all_scope_known:
        result.values["ruff.scope"] = sorted(scopes)
    # Candidate absence is meaningful, but repeated discovery of the same
    # source through two files is not two independent sources.
    result.sources = [record for _, record in sorted({canonical(r): r for r in result.sources}.items())]
    return result


