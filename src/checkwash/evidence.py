"""IR evidence helpers: modules, callers, D6 constants. Extracted from engine (E5)."""
from __future__ import annotations

from collections import Counter

from checkwash.frontends.python.frontend import ParsedFile, module_constants
from checkwash.ir.markers import bare_names, marker_call, parse_expr
from checkwash.ir.model import DiffGlobals

# Bounds for skip-condition constant resolution. Small on purpose: a real
# compatibility gate references one or two constants; anything needing more
# reads than this stays unevaluable, which fails toward flagging.
_MAX_CONST_ENTRIES = 24
_MAX_HEAD_READS = 8
_MAX_DUP_READS = 8


def _mark_weakened_guards(file) -> None:
    """Flag skips whose text is unchanged but whose meaning became "always skip".

    `STRICT = True` -> `STRICT = False` under `if not STRICT: pytest.skip(...)`
    silences a test with no marker event of any kind: the guard text is
    identical on both sides, so nothing is "added". A real agent found this
    in one line on the first try (decoy probe arm 2026-08-04). The condition
    is evaluated in both environments; only "used to run somewhere, now
    skips everywhere" counts, so honest version-gate bumps stay silent.
    """
    from checkwash.gating import guard_always_skips

    for unit in file.units:
        if unit.before is None or unit.after is None or unit.delta is None:
            continue
        before_by_name = {m.name: m for m in unit.before.markers}
        for m in unit.after.markers:
            if not m.guard or m.name in unit.delta.markers_added:
                continue
            old = before_by_name.get(m.name)
            if old is None or not old.guard:
                continue
            # Same-text path is THREATMODEL 59 (constant behind the guard).
            # Different-text path is THREATMODEL 54 (if X: skip → if True: skip).
            # Guard text is not in the fingerprint; only the meaning change
            # is an event, so recorded allowlists survive a rewrite of a
            # still-discriminating condition.
            if guard_always_skips(m.guard, file.constants) and not guard_always_skips(
                old.guard, file.constants_before
            ):
                unit.delta.guards_weakened.append(m.name)
        # A conftest that already had a collection control produced no event at
        # all when a second one was appended: markers deduplicate by name, so
        # `collect_ignore.append(...)` beside an existing `collect_ignore = [...]`
        # removed a whole test file in silence (THREATMODEL 81). The resolved
        # path set is what makes it an event — the marker's name never moves.
        # Two conditions, both learned by breaking existing fixtures with the
        # first version: the marker must not be newly added (that event is
        # already reported, and reporting it twice is noise), and the control
        # must be unguarded — a growing optional-dependency gate is still a
        # gate, which is the whole reason `except ImportError` is recorded as
        # a condition rather than dropped.
        control = next(
            (m for m in unit.after.markers if m.name == "conftest.collect_ignore"), None
        )
        gained = set(unit.after.collect_ignored) - set(unit.before.collect_ignored)
        if (
            gained
            and control is not None
            and control.guard is None
            and control.name not in unit.delta.markers_added
        ):
            unit.delta.guards_weakened.append("conftest.collect_ignore")
        unit.delta.guards_weakened.sort()


def _gate_condition_names(parsed: ParsedFile) -> set[str]:
    """Bare names referenced by this file's skipif/xfail conditions and guards."""
    names: set[str] = set()
    for unit in parsed.units:
        for m in unit.side.markers:
            canonical = m.name.split("(", 1)[0]
            if canonical.rsplit(".", 1)[-1] in ("skipif", "xfail"):
                call = marker_call(m.text)
                if call is not None and call.args:
                    names |= bare_names(call.args[0])
            if m.guard:
                guard = parse_expr(m.guard)
                if guard is not None:
                    names |= bare_names(guard)
    return names


def _pull_closure(out: dict[str, str], seeds: set[str], source: dict[str, str]) -> None:
    """Copy seeds and the same-module names their expressions reference."""
    queue = sorted(n for n in seeds if n in source and n not in out)
    seen = set(queue)
    while queue and len(out) < _MAX_CONST_ENTRIES:
        name = queue.pop(0)
        out[name] = source[name]
        expr = parse_expr(source[name])
        if expr is None:
            continue
        for ref in sorted(bare_names(expr)):
            if ref not in seen and ref in source:
                seen.add(ref)
                queue.append(ref)


def _module_candidates(module: str) -> list[str]:
    # `module` comes from an `ast.ImportFrom` with level 0: a chain of
    # identifiers, so joining on "/" cannot traverse outside the repo.
    rel = module.replace(".", "/")
    return [f"{rel}.py", f"src/{rel}.py", f"{rel}/__init__.py", f"src/{rel}/__init__.py"]


def _gate_constants(
    parsed: ParsedFile,
    after_by_path: dict[str, ParsedFile],
    head_reader,
) -> dict[str, str]:
    """The constant environment D6 evaluates this file's skip conditions in."""
    needed = _gate_condition_names(parsed)
    if not needed:
        return {}
    consts: dict[str, str] = {}
    # A name bound both by a top-level assignment and a from-import is
    # order-dependent at runtime; picking either binding could hand the
    # credit to the wrong expression. Ambiguity resolves to "unevaluable".
    unambiguous = {
        n: e for n, e in parsed.constants.items() if n not in parsed.from_imports
    }
    _pull_closure(consts, needed, unambiguous)

    module_cache: dict[str, dict[str, str] | None] = {}
    reads = 0
    for name in sorted(needed):
        if len(consts) >= _MAX_CONST_ENTRIES:
            break
        if name in consts or name not in parsed.from_imports:
            continue
        if name in parsed.constants:
            continue  # ambiguous: also assigned at top level in this file
        module, orig = parsed.from_imports[name]
        if module not in module_cache:
            found: dict[str, str] | None = None
            for candidate in _module_candidates(module):
                in_diff = after_by_path.get(candidate)
                if in_diff is not None:
                    found = in_diff.constants
                    break
                if head_reader is not None and reads < _MAX_HEAD_READS:
                    reads += 1
                    data = head_reader(candidate)
                    if data is not None:
                        found = module_constants(data)
                        break
            module_cache[module] = found
        source = module_cache[module]
        if not source or orig not in source:
            continue
        sub: dict[str, str] = {}
        _pull_closure(sub, {orig}, source)
        expr = sub.pop(orig, None)
        if expr is None:
            continue
        # A sibling constant colliding with a name already bound here would
        # make the evaluation ambiguous; ambiguity resolves to "unevaluable".
        if any(k in consts or k in parsed.constants or k in parsed.from_imports for k in sub):
            continue
        consts[name] = expr
        consts.update(sub)
    return {k: consts[k] for k in sorted(consts)}


def _scope_match(path: str, pattern: str) -> bool:
    import fnmatch

    if fnmatch.fnmatchcase(path, pattern):  # case-folding fnmatch breaks §8
        return True
    if pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]):
        return True
    return False


def _module_of(path: str) -> str:
    """`pkg/mod.py` -> `pkg.mod`. Symbols are qualified by module so a
    same-named function in an unrelated module cannot supply evidence.

    A leading `src/` is dropped. Under the src-layout that attrs, click and
    flask all use, `src/attr/_make.py` is imported as `attr._make`; keeping
    the source root in the name made the changed module unreachable from
    every test's imports, which silently denied repair evidence to every
    src-layout project in the corpus (reader audit 2026-08-02). Other source
    roots are handled by suffix alignment in gating._module_reachable.
    """
    p = path.replace("\\", "/")
    if p.endswith(".py"):
        p = p[:-3]
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    if p.startswith("src/"):
        p = p[len("src/") :]
    return p.replace("/", ".")


def _record_callers(g: DiffGlobals, parsed: ParsedFile, changed: list[str]) -> None:
    """Index which prod symbols call a changed symbol (one-hop repair evidence).

    A test that calls `format_invoice` is legitimately updated when
    `compute_total` â€” which format_invoice calls â€” changes; without this the
    symbol-level E1 would fire on that honest work.
    """
    changed_leaves = {q.rsplit(".", 1)[-1] for q in changed}
    for qual, callees in parsed.symbol_calls.items():
        hits = sorted(set(callees) & changed_leaves)
        if hits:
            g.prod_symbol_callers[qual.rsplit(".", 1)[-1]] = hits


def _suppression_texts(parsed: ParsedFile | None) -> Counter[str]:
    counter: Counter[str] = Counter()
    if parsed is None:
        return counter
    for entry in parsed.suppressions:
        counter[entry.split(":", 1)[1] if ":" in entry else entry] += 1
    return counter


