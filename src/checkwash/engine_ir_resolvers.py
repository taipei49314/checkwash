"""IR pipeline stage 2: bounded conftest-chain, cross-file oracle, and head-collection resolvers."""

from __future__ import annotations

import re
import sys
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.frontends.python.frontend import ParsedFile, parse_conftest_level
from checkwash.frontends.python.root_oracles import (
    project_root_oracles,
    root_caller_unchanged,
    root_imports,
)
from checkwash.frontends.python.setup_skip_controls import ConftestLevel, unreadable_level
from checkwash.ir.astutil import same_expr
from checkwash.opaque import split_inventory
from checkwash.report.context import ReportContext

if TYPE_CHECKING:
    import types

_UNKNOWN = object()

_CHAIN_ERRORS = (
    "conftest chain exceeds the source read limit",
    "conftest chain strict snapshot returned invalid source bytes",
    "conftest chain exceeds the source byte limit",
)
_HELPER_ERRORS = (
    "imported helper modules exceed the source read limit",
    "imported helper strict snapshot returned invalid source bytes",
    "imported helper modules exceed the source byte limit",
)
_MARK_CONFIG_NAMES = (
    "pytest.ini",
    ".pytest.ini",
    "pytest.toml",
    ".pytest.toml",
    "pyproject.toml",
    "tox.ini",
    "setup.cfg",
)


def _eng() -> types.ModuleType:
    mod = sys.modules.get("checkwash.engine")
    if mod is None:
        import checkwash.engine as mod
    return mod


class ConftestChainResolver:
    """Resolves per-side ancestor conftest chains, mark plugin configs, and imported helpers."""

    def __init__(
        self,
        changes: list[FileChange],
        config: Config,
        root_reader: Any,
        report_context: ReportContext | None,
    ) -> None:
        self.config = config
        self.root_reader = root_reader
        self.report_context = report_context
        self.chain_sides: dict[str, tuple[bytes | None, bytes | None]] = {}
        for c in changes:
            cpath = c.path.replace("\\", "/")
            old = (c.old_path or cpath).replace("\\", "/")
            if old != cpath:
                self.chain_sides[old] = (c.before, None)
                self.chain_sides[cpath] = (None, c.after)
            else:
                self.chain_sides[cpath] = (c.before, c.after)
        self.chain_levels: dict[tuple[str, int], object] = {}
        self.chain_sources: dict[tuple[str, int], bytes | None] = {}
        self.chain_reads = [0, 0]
        self.mark_config_cache: dict[tuple[str, int], bool] = {}
        self.helper_modules: dict[tuple[str, int], Any] = {}

    def _read_bounded_snapshot(
        self,
        path: str,
        errors: tuple[str, str, str],
    ) -> bytes | None:
        eng = _eng()
        read_err, invalid_err, byte_err = errors
        if self.chain_reads[0] >= eng._MAX_CHAIN_READS:
            raise EngineError(read_err)
        self.chain_reads[0] += 1
        data = self.root_reader(path)
        if data is not None and not isinstance(data, bytes):
            raise EngineError(invalid_err)
        if data is not None:
            self.chain_reads[1] += len(data)
            if self.chain_reads[1] > eng._MAX_CHAIN_BYTES:
                raise EngineError(byte_err)
            if self.report_context is not None:
                self.report_context.snapshot(path, 0, data)
                self.report_context.snapshot(path, 1, data)
        return data

    def config_may_load_marks(self, directory: str, side: int) -> bool:
        """Explicit plugin configuration defeats a known static mark set."""
        key = (directory, side)
        if key in self.mark_config_cache:
            return self.mark_config_cache[key]
        found = False
        for name in _MARK_CONFIG_NAMES:
            cpath = f"{directory}/{name}" if directory else name
            if cpath in self.chain_sides:
                data = self.chain_sides[cpath][side]
            elif self.root_reader is None:
                found = True
                break
            else:
                data = self._read_bounded_snapshot(cpath, _CHAIN_ERRORS)
            if data and (
                re.search(rb"(?<![\w-])-p(?:\s|[A-Za-z_])", data)
                or b"PYTEST_PLUGINS" in data
                or b"pytest11" in data
            ):
                found = True
        self.mark_config_cache[key] = found
        return found

    def chain_level(self, cpath: str, side: int) -> object:
        """`cpath`'s level on `side`: a ConftestLevel, None when absent, `_UNKNOWN` when unknowable."""
        key = (cpath, side if cpath in self.chain_sides else -1)
        if key in self.chain_levels:
            return self.chain_levels[key]
        if cpath in self.chain_sides:
            data = self.chain_sides[cpath][side]
        elif self.root_reader is None:
            self.chain_levels[key] = _UNKNOWN
            return _UNKNOWN
        else:
            data = self._read_bounded_snapshot(cpath, _CHAIN_ERRORS)
        self.chain_sources[key] = data
        level = None if data is None else parse_conftest_level(data, cpath)
        self.chain_levels[key] = _UNKNOWN if data is not None and level is None else level
        return self.chain_levels[key]

    def conftest_chain(self, tpath: str, side: int, test_source: bytes) -> tuple:
        """Every `conftest.py` from `tpath`'s directory up to the repository root, nearest first."""
        levels = []
        directories = []
        directory = tpath.rpartition("/")[0]
        while True:
            directories.append(directory)
            cpath = f"{directory}/conftest.py" if directory else "conftest.py"
            level = self.chain_level(cpath, side)
            if level is _UNKNOWN:
                # What it defines is unknown, and so are the marks it may add to a test (#358).
                levels.append(unreadable_level(cpath))
                break
            if level is not None:
                levels.append(level)
            if not directory:
                break
            directory = directory.rpartition("/")[0]
        reads_own_marks = b"request" in test_source and any(
            word in test_source for word in (b"marker", b"keywords")
        )
        reads_own_marks |= any(
            outcome
            and outcome[2]
            and "request" in outcome[2]
            and ("marker" in outcome[2] or "keywords" in outcome[2])
            for level in levels
            for _requested, _autouse, outcome in level.fixtures.values()
        )
        if reads_own_marks and any(self.config_may_load_marks(d, side) for d in directories):
            levels.append(
                ConftestLevel("<plugin-configuration>", {}, frozenset(), False, adds_marks=True)
            )
        return tuple(levels)

    def helper_module(self, mpath: str, side: int):
        """Read and wrap a test/conftest helper module under the shared chain read/byte budget."""
        eng = _eng()
        key = (mpath, side if mpath in self.chain_sides else -1)
        if key in self.helper_modules:
            return self.helper_modules[key]
        data = None
        if self.config.role_of(mpath) in ("test", "conftest"):
            if mpath in self.chain_sides:
                data = self.chain_sides[mpath][side]
            elif self.root_reader is not None:
                data = self._read_bounded_snapshot(mpath, _HELPER_ERRORS)
        self.helper_modules[key] = eng.HelperModule(data, mpath) if data is not None else None
        return self.helper_modules[key]

    def imported_helpers(self, tpath: str, side: int):
        """`(module, original) -> outcomes` for the test module at `tpath` on `side`."""
        tdir = tpath.rpartition("/")[0]

        def resolve(module: str, original: str) -> tuple:
            if "." in module:
                mpath = module.replace(".", "/") + ".py"
            else:
                mpath = f"{tdir}/{module}.py" if tdir else f"{module}.py"
            helper = self.helper_module(mpath, side)
            return helper.outcomes(original) if helper is not None else ()

        return resolve

    def level_source(self, path: str, side: int) -> bytes | None:
        """Cached source bytes for `path` on `side` (or `-1` when unchanged)."""
        return self.chain_sources.get((path, side if path in self.chain_sides else -1))


class CrossfileOracleResolver:
    """Folds imported-helper, root-helper, and requested-fixture assertions into units (A5-x)."""

    def __init__(
        self,
        raw_by_path: dict[str, tuple[bytes | None, bytes | None]],
        config: Config,
        root_reader: Any,
        head_reader: Any,
        report_context: ReportContext | None,
        importer_reads: int,
        reviewed_root_modules: set[str],
    ) -> None:
        self.raw_by_path = raw_by_path
        self.config = config
        self.root_reader = root_reader
        self.head_reader = head_reader
        self.report_context = report_context
        self.reviewed_root_modules = reviewed_root_modules
        self.oracle_memo: dict[tuple[str, int], ParsedFile | None] = {}
        self.oracle_sources: dict[tuple[str, int], bytes | None] = {}
        self.strict_oracle_sources: set[tuple[str, int]] = set()
        self.root_import_memo: dict[tuple[str, int], dict] = {}
        self.root_projection_memo: dict[tuple[str, int, str], dict] = {}
        self.oracle_head_reads = [importer_reads]

    def oracle_file(
        self,
        opath: str,
        side: int,
        *,
        strict: bool = False,
        absence_only: bool = False,
    ) -> ParsedFile | None:
        """A test/conftest module parsed for its oracle carriers, or None."""
        eng = _eng()
        in_diff = opath in self.raw_by_path
        key = (opath, side if in_diff else -1)
        if key in self.oracle_memo and (not strict or key in self.strict_oracle_sources):
            return self.oracle_memo[key]
        parsed: ParsedFile | None = None
        oracle_role = self.config.role_of(opath) in ("test", "conftest")
        if not oracle_role and not (strict and absence_only):
            self.oracle_memo[key] = None
            return None
        reader = self.root_reader if strict else self.head_reader
        if in_diff:
            data = self.raw_by_path[opath][side]
        elif reader is not None and self.oracle_head_reads[0] < eng._MAX_ORACLE_READS:
            self.oracle_head_reads[0] += 1
            data = reader(opath)
        else:
            data = None
            # Exhausting the read budget is unknown, not an absent sibling.
            self.oracle_memo[key] = None
            return None
        self.oracle_sources[key] = data
        if strict or in_diff:
            self.strict_oracle_sources.add(key)
        if data is not None and oracle_role:
            if self.report_context is not None:
                self.report_context.snapshot(opath, side, data)
                if not in_diff:
                    self.report_context.snapshot(opath, 1 - side, data)
            parsed = eng.parse_python(
                data, collect_tests=True, conftest=opath.endswith("conftest.py"),
            )
            if not parsed.parse_ok:
                parsed = None
        self.oracle_memo[key] = parsed
        return parsed

    def _try_root_helper_channel(
        self,
        tpath: str,
        unit,
        side: int,
        n: str,
        module: str,
        orig: str,
        tdir: str,
        candidate: str,
        before_by_path: dict[str, ParsedFile],
    ) -> tuple[bool, tuple | list]:
        """Resolve an unqualified root-helper import; `(handled, projected_assertions)`."""
        root = f"{module}.py"
        if not (
            self.root_reader is not None
            and "." not in module
            and tdir
            and self.config.role_of(root) in ("test", "conftest")
        ):
            return False, ()
        import_key = (tpath, side)
        source = self.raw_by_path[tpath][side]
        if import_key not in self.root_import_memo:
            self.root_import_memo[import_key] = root_imports(source)
        if self.root_import_memo[import_key].get(n) != (module, orig):
            return False, ()
        self.oracle_file(root, side, strict=True)
        root_key = (root, side if root in self.raw_by_path else -1)
        if root_key not in self.strict_oracle_sources:
            return True, ()
        root_source = self.oracle_sources[root_key]
        if root_source is None:
            return False, ()
        # A present (even unparseable) sibling makes the runtime import target ambiguous.
        alternatives = (candidate, f"{module}/__init__.py", f"{tdir}/{module}/__init__.py")
        alternative_keys = []
        for alternative in alternatives:
            self.oracle_file(alternative, side, strict=True, absence_only=True)
            alternative_keys.append((alternative, side if alternative in self.raw_by_path else -1))
        unknown = any(key not in self.strict_oracle_sources for key in alternative_keys)
        present = any(self.oracle_sources.get(key) is not None for key in alternative_keys)
        if unknown and module in self.reviewed_root_modules:
            raise EngineError("root assertion helper resolution exceeds the snapshot read budget")
        if present and module in self.reviewed_root_modules:
            raise EngineError("changed root assertion helper has an ambiguous sibling import")
        if unknown or present:
            return True, ()
        projection_key = (tpath, side, n)
        if projection_key not in self.root_projection_memo:
            self.root_projection_memo[projection_key] = (
                project_root_oracles(source, root_source, n, orig)
                if self.oracle_memo[root_key] is not None
                else {}
            )
        projected = self.root_projection_memo[projection_key].get(unit.qualname, ())
        if side == 1 and self.raw_by_path[tpath][0] is not None:
            if not root_caller_unchanged(
                self.raw_by_path[tpath][0], source, module, n, orig, unit.qualname,
            ):
                projected = []
        if side == 1 and tpath in before_by_path:
            prior = next(
                (u for u in before_by_path[tpath].units if u.qualname == unit.qualname), None,
            )
            if prior is not None:
                projected = [
                    a for a in projected
                    if any(same_expr(a.left, b.left) for b in prior.side.assertions)
                ]
        return True, projected

    def merge_crossfile_oracles(
        self,
        tpath: str,
        parsed: ParsedFile | None,
        side: int,
        before_by_path: dict[str, ParsedFile],
    ) -> None:
        """Fold imported-helper and requested-fixture asserts into each unit of `parsed`."""
        if parsed is None or not parsed.parse_ok or not parsed.units:
            return
        tdir = tpath.rsplit("/", 1)[0] if "/" in tpath else ""
        conftest_path = f"{tdir}/conftest.py" if tdir else "conftest.py"

        for unit in parsed.units:
            uside = unit.side
            extra: list = []

            def inherit(assertions, source_path: str) -> None:
                extra.extend(assertions)
                if self.report_context is not None:
                    for assertion in assertions:
                        self.report_context.bind(tpath, side, assertion, source_path)

            requested = list(uside.params)
            conftest = None
            if requested and any(p not in parsed.fixture_asserts for p in requested):
                conftest = self.oracle_file(conftest_path, side)
            for p in requested:
                found = parsed.fixture_asserts.get(p)
                source_path = tpath
                if found is None and conftest is not None:
                    found = conftest.fixture_asserts.get(p)
                    source_path = conftest_path
                if found:
                    inherit(found, source_path)
            for name in parsed.autouse_fixtures:
                if name not in requested:
                    inherit(parsed.fixture_asserts.get(name, ()), tpath)
            if conftest_path in self.raw_by_path and conftest_path != tpath:
                c = self.oracle_file(conftest_path, side)
                if c is not None:
                    for name in c.autouse_fixtures:
                        if name not in requested:
                            inherit(c.fixture_asserts.get(name, ()), conftest_path)
            for n in sorted(set(uside.invoked) & set(parsed.from_imports)):
                module, orig = parsed.from_imports[n]
                if "." in module:
                    candidate = module.replace(".", "/") + ".py"
                else:
                    candidate = f"{tdir}/{module}.py" if tdir else f"{module}.py"
                handled, projected = self._try_root_helper_channel(
                    tpath, unit, side, n, module, orig, tdir, candidate, before_by_path,
                )
                if handled:
                    if projected:
                        inherit(projected, tpath)
                    continue
                helper = self.oracle_file(candidate, side)
                if helper is not None:
                    inherit(helper.helper_asserts.get(orig, ()), candidate)
            if extra:
                uside.assertions.extend(replace(a) for a in extra)
                for i, a in enumerate(uside.assertions):
                    a.id = f"a{i}"

    def strict_head_sources(self) -> dict[str, bytes | None]:
        """Unchanged strict head snapshot sources read during oracle resolution."""
        return {
            path: data
            for (path, side), data in self.oracle_sources.items()
            if side == -1 and (path, side) in self.strict_oracle_sources
        }


class HeadCollectionResolver:
    """Lazy head-side pytest collection predicate for rename continuity and arrival credits (D-193)."""

    def __init__(
        self,
        changes: list[FileChange],
        chain_sources: dict[tuple[str, int], bytes | None],
        root_reader: Any,
        root_batch_reader: Any,
        root_path_lister: Any,
        config_evidence: Any,
    ) -> None:
        self.chain_sources = chain_sources
        self.root_reader = root_reader
        self.root_batch_reader = root_batch_reader
        self.root_path_lister = root_path_lister
        self.config_evidence = config_evidence
        self.head_sides: dict[str, set] = {}
        for change in changes:
            path = change.path.replace("\\", "/")
            self.head_sides.setdefault(path, set()).add(change.after)
            old = (change.old_path or path).replace("\\", "/")
            if old != path:
                self.head_sides.setdefault(old, set())
        self._collector_cache: list[Any] = []

    def head_source(self, candidate: str) -> bytes | None:
        eng = _eng()
        if candidate in self.head_sides:
            if len(self.head_sides[candidate]) > 1:
                raise ValueError("conflicting head sides of a changed path")
            return next(iter(self.head_sides[candidate]), None)
        if (candidate, -1) in self.chain_sources:
            return self.chain_sources[(candidate, -1)]
        try:
            return self.root_reader(candidate)
        except EngineError:
            # pytest follows a root config that is a link; the config
            # evidence reads it the same way, where the snapshot refuses it.
            if self.config_evidence is None or "/" in candidate or candidate not in eng._PYTEST_CONFIGS:
                raise
            return self.config_evidence.sources("after", [candidate])[candidate]

    def head_many(self, candidates) -> dict[str, bytes | None]:
        candidates = list(dict.fromkeys(candidates))
        rest = [
            candidate
            for candidate in candidates
            if candidate not in self.head_sides and (candidate, -1) not in self.chain_sources
        ]
        found = {}
        if rest and self.root_batch_reader is not None:
            try:
                found = dict(self.root_batch_reader(rest))
            except EngineError:
                found = {}  # one refused path refuses a batch: each is read alone
        return {
            candidate: found[candidate] if candidate in found else self.head_source(candidate)
            for candidate in candidates
        }

    def head_paths(self) -> list[str]:
        listed = self.root_path_lister()
        selected = {path for path in split_inventory(listed)[0] if isinstance(path, str)}
        for candidate in self.head_sides:
            selected.discard(candidate)
            if self.head_source(candidate) is not None:
                selected.add(candidate)
        return [
            *sorted(selected),
            *(path for path in listed if isinstance(path, str) and path.endswith("/")),
        ]

    def collector(self):
        if not self._collector_cache:
            eng = _eng()
            self._collector_cache.append(
                eng.arrival_collector(
                    self.head_source,
                    self.head_paths if self.root_path_lister is not None else None,
                    self.head_many,
                )
                if self.root_reader is not None
                else None
            )
        return self._collector_cache[0]

    def excludes(self, path: str) -> bool:
        collection_ = self.collector()
        return collection_ is not None and collection_.excludes(path)

    def collected(self, path: str, qualname: str, source: bytes | None) -> bool:
        collection_ = self.collector()
        return collection_ is not None and collection_(path, qualname, source)
