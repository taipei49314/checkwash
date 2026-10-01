"""JavaScript stand-ins that an existing test's own oracle reads (issue #177).

`vi.mock("./src/billing.js", () => ({ invoiceTotal: () => 78.75 }))` added
above an untouched `expect(invoiceTotal(items)).toBe(78.75)` is the JS
spelling of THREATMODEL rows 60/90: production and every assertion stay
byte-identical while the assertion now checks the stand-in. No path in the
engine read a mock call, so the reported diff passed with zero findings.

Every spelling feeds one definition. An installation replaces either a whole
first-party module or one member path of it. A test unit *consumes* it when
one of its own assertions reads a binding of that module - directly or
through one hop of a local binding - after the installation took effect.
The TEST_PATCHES_SUBJECT conditions then carry over unchanged: the unit
existed and was live on both sides, the stand-in is new (the base side of
the file replaced that target nowhere, so moving, reformatting or respelling
an installation is not one), and the unit's own oracle reads it. Mocking a
collaborator the oracle never reads is how unit tests are written, and stays
silent.

When an installation takes effect is part of the evidence:

- hoisted module mocks - `vi.mock` and `jest.mock` at module level - precede
  every import of the file (Vitest hoists them, as does babel-jest);
- ordered module mocks reach only `require()` / `await import()` bindings
  evaluated after them, never a static import: `vi.doMock`, `jest.doMock`,
  `jest.unstable_mockModule`, `jest.setMock`, node:test `mock.module` and
  `t.mock.module`. `vi.mock` / `jest.mock` written inside a test body get the
  same ordered treatment - a conservative choice of this scan, not a claim
  about how a runner hoists them;
- member replacements: `vi.spyOn` / `jest.spyOn` / `vi.mocked(x)` /
  `jest.mocked(x)` chained to a replacing `mock*` call, `x.mock*(...)` on an
  imported binding (also through a TypeScript cast or non-null assertion),
  `jest.replaceProperty`, and node:test `mock.method` with an
  implementation. Inside a test body they reach only later reads.

A factory that reaches for the original module (`importOriginal`,
`importActual`, `requireActual`, or its own parameter) replaces every name it
spells - an identifier, a member name, or an identifier-shaped string such as
a quoted or computed key - and nothing else. No factory is an automock and
replaces every export. Vitest's `{ spy: true }` and a spy with no replacement
keep the real code. An object-literal key in an assertion names a property;
it does not read the binding of the same name.

First-party means a `./` or `../` specifier that stays inside the repository
and outside dependency/build output. Bare specifiers are packages and
builtins - faking network, time and the filesystem is hygiene - and aliases
(`@/`, tsconfig paths, `#imports`, root-relative `/src`) resolve through
runner configuration this scan does not execute.

Silent rather than guessed: setup files, `__mocks__` directories and
`automock` configuration (the conftest analogue, which needs that same
configuration); installations in hooks, helpers and `describe` bodies;
two-statement spies, on either side; plain assignment to a module object's
member; template-literal keys and partial-factory names spelled outside the
factory; cast types that contain parentheses; non-literal specifiers;
re-exports and two hops; and oracles the frontend does not represent
(interaction matchers, `.resolves`, snapshots).
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from checkwash.frontends.javascript.bindings import CALL, NAME, Bindings
from checkwash.frontends.javascript.frontend import (
    _call_argument_spans,
    _code_positions,
    is_js_test_path,
)
from checkwash.roles import is_artifact

# A file that spells none of these installs nothing, so most JS test files
# never reach the binding scan below. `doMock` and `setMock` spell a capital M.
_TRIGGER = re.compile(rb"[mM]ock|spyOn|replaceProperty")
_IDENT = re.compile(NAME + r"\Z")
_REFERENCE = re.compile(r"(?<![\w$])" + NAME)
_MEMBER = re.compile(r"\s*\??\.\s*(" + NAME + r")")
_DOTTED = re.compile(r"(" + NAME + r")(?:\s*\.\s*(" + NAME + r"))?")
_STRING = re.compile(r"""(['"])((?:\\.|(?!\1).)*)\1""", re.DOTALL)
_IMPORT_CALL = re.compile(r"""import\s*\(\s*(['"])((?:\\.|(?!\1).)*)\1\s*\)""", re.DOTALL)
_REPLACER = re.compile(r"mock(?:ReturnValue|Implementation|ResolvedValue|RejectedValue)(?:Once)?")
_REPLACING = re.compile(r"\s*\??\.\s*" + _REPLACER.pattern + r"\s*\(")
# TypeScript spells `x.mockReturnValue(...)` through a cast or a non-null
# assertion: `(x as Mock)`, `(x as unknown as jest.Mock)`, `(<Mock>x)`, `x!`.
_CAST = re.compile(
    r"(?<![\w$.#])(?:\(\s*(?:<[^<>()]*>\s*)?(" + NAME + r")(?:\s*\.\s*(" + NAME + r"))?"
    + r"(?:\s+as\s[^()]*)?\s*\)|(" + NAME + r")(?:\s*\.\s*(" + NAME + r"))?\s*!)"
    + _REPLACING.pattern
)
_ORIGINAL = re.compile(r"(?<![\w$])(?:importOriginal|importActual|requireActual)(?![\w$])")
_PARAMETER = re.compile(
    r"\s*(?:async\s*)?(?:function\b[^(]*)?\(\s*(" + NAME + r")"
    + r"|\s*(?:async\s+)?(" + NAME + r")\s*=>"
)
_SPY_OPTION = re.compile(r"(?<![\w$])spy\s*:\s*true(?![\w$])")
_EXTENSIONS = (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx")
# (module, export) -> the runner object it is. `vi` and `jest` are also
# injected as globals; node:test's `mock` has to be imported.
_RUNNERS = {("vitest", "vi"): "vi", ("@jest/globals", "jest"): "jest", ("node:test", "mock"): "mock"}
_MODULE_MOCKS = {
    "vi": frozenset({"mock", "doMock"}),
    "jest": frozenset({"mock", "doMock", "unstable_mockModule", "setMock"}),
    "mock": frozenset({"module"}),
}
_MEMBER_REPLACEMENTS = {
    "vi": frozenset({"spyOn", "mocked"}),
    "jest": frozenset({"spyOn", "mocked", "replaceProperty"}),
    "mock": frozenset({"method"}),
}


def module_key(test_path: str, specifier: str) -> str | None:
    """The repository module a relative specifier names, extension-insensitive.

    Only `./` and `../` specifiers are first-party by construction. A bare
    name is a package or a builtin, and an alias resolves through runner
    configuration this scan does not execute. A specifier that leaves the
    repository root, or lands in dependency or build output, names nothing
    the project owns. `./billing`, `./billing.js` and `./billing.ts` are one
    module, as are `./src` and `./src/index.js`.
    """
    if not specifier.startswith(("./", "../")) or any(char in specifier for char in "?#\\"):
        return None
    directory = test_path.replace("\\", "/").rpartition("/")[0]
    path = posixpath.normpath(posixpath.join(directory, specifier))
    if path in {".", ".."} or path.startswith(("../", "/")) or is_artifact(path):
        return None
    for extension in _EXTENSIONS:
        if path.endswith(extension) and len(path) > len(extension):
            path = path[:-len(extension)]
            break
    return path[:-len("/index")] if path.endswith("/index") else path


@dataclass(frozen=True)
class _Binding:
    module: str
    export: str  # "*" for a namespace or module object, else the export name
    ready: int  # -1: a static import, bound before any test code runs
    scope: int  # declaring scope


@dataclass(frozen=True)
class _Install:
    module: str
    member: tuple[str, ...] | None  # replaced member path; None for a module mock
    names: frozenset[str] | None  # module mock: the exports it replaces, None = all
    hoisted: bool
    owner: int  # the function scope that executes it; 0 = module level
    position: int
    text: str
    span: tuple[int, int]


def _path(binding: _Binding, member: str | None) -> tuple[str, ...]:
    """The export path a read takes. A namespace member is the named export
    itself; a member of a default or named export object stays below it."""
    head = () if binding.export == "*" else (binding.export,)
    return head + ((member,) if member else ())


def _references(text: str, start: int = 0, end: int | None = None):
    """(name, member, position) for identifiers that are not property names."""
    end = len(text) if end is None else end
    for match in _REFERENCE.finditer(text, start, end):
        previous = match.start() - 1
        while previous >= start and text[previous].isspace():
            previous -= 1
        if previous >= start and text[previous] in ".#":
            continue
        tail = _MEMBER.match(text, match.end(), end)
        yield match.group(), tail.group(1) if tail else None, match.start()


def _module_expression(value) -> tuple[str, str, str] | None:
    """(specifier, export, loader) of `[await] require|import("x")[.name]`."""
    if not isinstance(value, tuple):
        return None
    tokens = value[1:] if value[:1] == ("await",) else value
    if (len(tokens) < 4 or tokens[0] not in {"require", "import"} or tokens[1] != "("
            or tokens[2][:1] not in {"'", '"'} or tokens[3] != ")"):
        return None
    if len(tokens) == 4:
        return tokens[2][1:-1], "*", tokens[0]
    if len(tokens) == 6 and tokens[4] == "." and _IDENT.fullmatch(tokens[5]):
        return tokens[2][1:-1], tokens[5], tokens[0]
    return None


def _uses_original(factory: str) -> bool:
    """Does a mock factory build on the real module - a partial mock?"""
    if _ORIGINAL.search(factory):
        return True
    match = _PARAMETER.match(factory)
    parameter = (match.group(1) or match.group(2)) if match else None
    return parameter is not None and sum(
        1 for name, _member, _position in _references(factory) if name == parameter
    ) > 1


class _Side:
    """One side of a JS test file: its static imports and its installations."""

    def __init__(self, path: str, data: bytes):
        self.path = path
        # The frontend's normalization, so assertion spans index this text.
        self.text = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
        self.code = _code_positions(self.text)
        self.bindings = Bindings(self.text, self.code, _code_positions(self.text, keep_strings=True))
        self.imports: dict[str, tuple[str, str]] = {}
        self._static_imports()
        self.installs = sorted(self._installations(), key=lambda item: item.position)

    def _static_imports(self) -> None:
        """Module-level `import ... from "x"`: local -> (specifier, export).

        The binding model records these imports as unknown values, which is
        right for assertion authority; which module a local came from is the
        fact this pass needs, so it reads the same tokens once more.
        """
        bindings = self.bindings
        for index, (token, start, _end) in enumerate(bindings.tokens):
            if (token != "import" or not self.code[start] or bindings.scope_at[index] != 0
                    or bindings.token(index + 1) in {"(", ".", "type"}):
                continue
            end = index + 1
            while end < len(bindings.tokens) and bindings.token(end) not in {"from", ";"}:
                if bindings.tokens[end][1] - start > 1000:
                    break
                end += 1
            specifier = bindings.token(end + 1)
            if bindings.token(end) != "from" or specifier[:1] not in {"'", '"'}:
                continue
            names = []
            if _IDENT.fullmatch(bindings.token(index + 1)):
                names.append(("default", bindings.token(index + 1)))
            for cursor in range(index + 1, end):
                if bindings.token(cursor) == "*" and bindings.token(cursor + 1) == "as":
                    names.append(("*", bindings.token(cursor + 2)))
                elif bindings.token(cursor) == "{" and cursor in bindings.pairs:
                    names.extend(bindings._pattern(cursor + 1, bindings.pairs[cursor]))
            for export, local in names:
                if _IDENT.fullmatch(local):
                    self.imports[local] = (specifier[1:-1], export)

    def _declaration(self, name: str, position: int):
        """(scope, value) of the declaration visible at `position`; the value
        is None while that binding is not yet initialized."""
        bindings = self.bindings
        scope = bindings.scope(position)
        while True:
            found = bindings.scopes[scope].declarations.get(name)
            if found is not None:
                ready, value = found
                return scope, (value if ready <= position else None)
            parent = bindings.scopes[scope].parent
            if parent is None:
                return None
            scope = parent

    def _binding(self, name: str, position: int) -> _Binding | None:
        """The first-party module binding `name` denotes at `position`."""
        bindings = self.bindings
        found = self._declaration(name, position)
        if found is None or bindings._written((name,), position):
            return None
        scope, value = found
        if scope == 0 and name in self.imports:
            specifier, export = self.imports[name]
            module = module_key(self.path, specifier)
            return _Binding(module, export, -1, 0) if module else None
        parsed = _module_expression(value)
        if parsed is None:
            return None
        specifier, export, loader = parsed
        if loader == "require" and bindings.resolve("require", position).kind != "require":
            return None
        module = module_key(self.path, specifier)
        if module is None:
            return None
        return _Binding(module, export, bindings.scopes[scope].declarations[name][0], scope)

    def _runner(self, name: str, position: int) -> str | None:
        """'vi', 'jest' or 'mock' when `name` denotes that runner object."""
        found = self._declaration(name, position)
        if self.bindings._written((name,), position):
            return None
        if found is None:
            return name if name in {"vi", "jest"} else None
        scope, value = found
        if scope == 0 and name in self.imports:
            return _RUNNERS.get(self.imports[name])
        parsed = _module_expression(value)
        return _RUNNERS.get(parsed[:2]) if parsed is not None else None

    def _api(self, parts: list[str], position: int) -> tuple[str, str] | None:
        """(runner, method) of a recognised installation call."""
        if len(parts) == 3 and parts[1] == "mock":
            # node:test's test context: `t.mock.module(...)`, `t.mock.method(...)`.
            if self.bindings.resolve(parts[0], position).kind != "context":
                return None
            runner, method = "mock", parts[2]
        elif len(parts) == 2:
            runner, method = self._runner(parts[0], position), parts[1]
        else:
            return None
        if runner is None or method not in _MODULE_MOCKS[runner] | _MEMBER_REPLACEMENTS[runner]:
            return None
        return runner, method

    def _installations(self) -> list[_Install]:
        bindings, text, masked = self.bindings, self.text, self.bindings.masked
        found = []
        for call in CALL.finditer(masked):
            start = call.start()
            previous = start - 1
            while previous >= 0 and masked[previous].isspace():
                previous -= 1
            if previous >= 0 and masked[previous] in ".#":
                continue  # a member of something else, e.g. `obj. vi.mock(`
            parts = re.sub(r"\s+", "", call.group("callee")).split(".")
            direct = len(parts) in (2, 3) and _REPLACER.fullmatch(parts[-1]) is not None
            api = None if direct else self._api(parts, start)
            if not direct and api is None:
                continue
            arguments = _call_argument_spans(text, self.code, call.end() - 1, len(text))
            if arguments is None:
                continue
            spans, end = arguments
            owner = bindings._function_scope(bindings.scope(start))
            if direct:
                # `invoiceTotal.mockReturnValue(...)` on an automocked import.
                install = self._member_install(parts[0], parts[1] if len(parts) == 3 else None,
                                               owner, start, end)
            else:
                install = self._install(api[0], api[1], spans, owner, start, end)
            if install is not None:
                found.append(install)
        for cast in _CAST.finditer(masked):
            # `(invoiceTotal as Mock).mockReturnValue(...)`: the direct form above.
            arguments = _call_argument_spans(text, self.code, cast.end() - 1, len(text))
            if arguments is None:
                continue
            name, member = (cast.group(1), cast.group(2)) if cast.group(1) else (cast.group(3), cast.group(4))
            owner = bindings._function_scope(bindings.scope(cast.start()))
            install = self._member_install(name, member, owner, cast.start(), arguments[1])
            if install is not None:
                found.append(install)
        return found

    def _member_install(self, name, member, owner, start, end) -> _Install | None:
        binding = self._binding(name, start) if name else None
        path = _path(binding, member) if binding is not None else ()
        if not path:
            return None  # replacing a whole namespace object is not a member
        return _Install(binding.module, path, None, False, owner, start,
                        self.text[start:end], (start, end))

    def _spelled(self, first: int, last: int) -> frozenset[str]:
        """Every name a partial factory spells, so every export it may replace:
        identifiers and member names (`actual.invoiceTotal = ...`) and
        identifier-shaped string literals (`"invoiceTotal": ...`,
        `["invoiceTotal"]: ...`). Comments and template literals stay opaque."""
        bindings = self.bindings
        names = {match.group() for match in _REFERENCE.finditer(bindings.masked, first, last)}
        names.update(token[1:-1] for token, start, _end in bindings.tokens
                     if first <= start < last and token[:1] in {"'", '"'} and _IDENT.fullmatch(token[1:-1]))
        return frozenset(names)

    def _install(self, runner, method, spans, owner, start, end) -> _Install | None:
        args = [self.text[first:last].strip() for first, last in spans]
        if method in _MEMBER_REPLACEMENTS[runner]:
            if method == "mocked":
                reference = _DOTTED.fullmatch(args[0]) if args else None
                name, member = (reference.group(1), reference.group(2)) if reference else (None, None)
            else:
                literal = _STRING.fullmatch(args[1]) if len(args) > 1 else None
                if literal is None or not _IDENT.fullmatch(args[0]) or not _IDENT.fullmatch(literal.group(2)):
                    return None
                name, member = args[0], literal.group(2)
            if method in {"spyOn", "mocked"} and not _REPLACING.match(self.bindings.masked, end):
                return None  # a bare spy, or a type cast, still runs the real code
            if method == "replaceProperty" and len(args) < 3:
                return None
            if method == "method" and (len(args) < 3 or args[2].startswith("{")):
                return None  # without an implementation node:test spies on the original
            return self._member_install(name, member, owner, start, end)
        literal = _STRING.fullmatch(args[0]) if args else None
        if literal is None and runner == "vi" and args:
            literal = _IMPORT_CALL.fullmatch(args[0])
        module = module_key(self.path, literal.group(2)) if literal is not None else None
        if module is None:
            return None
        names = None
        if len(args) > 1 and method not in {"setMock", "module"}:
            factory = self.bindings.masked[spans[1][0]:spans[1][1]]
            if factory.strip().startswith("{"):
                if _SPY_OPTION.search(factory):
                    return None  # Vitest `{ spy: true }` keeps every real implementation
            elif _uses_original(factory):
                names = self._spelled(*spans[1])
        hoisted = method == "mock" and owner == 0
        return _Install(module, None, names, hoisted, owner, start, self.text[start:end], (start, end))

    def _callback(self, span: tuple[int, int]) -> int | None:
        """The test callback's own function scope: the one function scope
        inside the unit whose enclosing function lies outside it."""
        bindings = self.bindings
        start, end = span
        found = [
            index for index, scope in enumerate(bindings.scopes)
            if index and scope.function and start < scope.start < end
            and not start < bindings.scopes[bindings._function_scope(scope.parent)].start < end
        ]
        return found[0] if len(found) == 1 else None

    def _reach(self, start: int, end: int):
        """(binding, export path, position) for each first-party read of an assertion."""
        bindings = self.bindings
        found = []
        for name, member, position in _references(bindings.masked, start, end):
            if (bindings.masked[position + len(name):end].lstrip()[:1] == ":"
                    and bindings.masked[start:position].rstrip()[-1:] in {"{", ","}):
                continue  # `{ invoiceTotal: 78.75 }` names a property; it reads no binding
            binding = self._binding(name, position)
            if binding is not None:
                found.append((binding, _path(binding, member), position))
                continue
            # One hop, the bound TEST_PATCHES_SUBJECT draws: `const total =
            # invoiceTotal(items)` then `expect(total)` is the more natural way
            # to write the attack. A rebound name is refused, not guessed at.
            alias = self._declaration(name, position)
            if alias is None or not isinstance(alias[1], tuple) or bindings._written((name,), position):
                continue
            expression = alias[1]
            ready = bindings.scopes[alias[0]].declarations[name][0]
            for index, token in enumerate(expression):
                if not _IDENT.fullmatch(token) or (index and expression[index - 1] in {".", "?."}):
                    continue
                if (index and expression[index - 1] in {"{", ","}
                        and index + 1 < len(expression) and expression[index + 1] == ":"):
                    continue  # a property key, not a read of the binding
                hop = self._binding(token, max(ready - 1, 0))
                if hop is None:
                    continue
                hop_member = None
                if (index + 2 < len(expression) and expression[index + 1] in {".", "?."}
                        and _IDENT.fullmatch(expression[index + 2])):
                    hop_member = expression[index + 2]
                found.append((hop, _path(hop, hop_member), ready))
        return found

    def _covers(self, install: _Install, binding: _Binding, path: tuple[str, ...],
                position: int, callback: int | None) -> bool:
        if install.module != binding.module or install.owner not in (0, callback):
            return False
        bindings = self.bindings
        if install.member is not None:
            if path[:len(install.member)] != install.member:
                return False
            if install.owner == 0:
                # Module-level code runs before any test body; a module-level
                # read written before the replacement used the real code.
                return position > install.position or bindings._function_scope(bindings.scope(position)) != 0
            body = bindings.scopes[callback]
            return install.position < position and body.start <= position <= body.end
        if install.names is not None and not (path and path[0] in install.names):
            return False
        if install.hoisted:
            return True
        if binding.ready < 0:
            return False  # a static import is bound before an ordered mock runs
        declared_in = bindings._function_scope(binding.scope)
        if install.owner == 0:
            return binding.ready > install.position or declared_in != 0
        return declared_in == callback and binding.ready > install.position

    def consumed(self, side) -> dict[str, tuple[_Install, str, tuple[str, ...]]]:
        """Stand-in targets this unit side's own assertions read: target ->
        (earliest covering installation, module, export path)."""
        callback = self._callback(side.span)
        found: dict[str, tuple[_Install, str, tuple[str, ...]]] = {}
        for assertion in side.assertions:
            for binding, path, position in self._reach(*assertion.span):
                for install in self.installs:
                    if self._covers(install, binding, path, position, callback):
                        target = f"{binding.module}:{'.'.join(path) or '*'}"
                        found.setdefault(target, (install, binding.module, path))
                        break
        return found

    def replaces(self, module: str, path: tuple[str, ...]) -> bool:
        """Does any installation in this file, wherever it runs, replace it?"""
        for install in self.installs:
            if install.module != module:
                continue
            if install.member is not None:
                if path[:len(install.member)] == install.member:
                    return True
            elif install.names is None or (path and path[0] in install.names):
                return True
        return False


def module_mock_events(ir, changes) -> list[tuple[str, str, str, str, tuple[int, int]]]:
    """(path, unit, target, text, span) for each new stand-in an existing JS oracle reads."""
    files = {file.path: file for file in ir.files if file.role == "test"}
    events: set[tuple[str, str, str, str, tuple[int, int]]] = set()
    for change in changes:
        path = change.path.replace("\\", "/")
        file = files.get(path)
        if (file is None or not is_js_test_path(path) or change.before is None
                or change.after is None or not _TRIGGER.search(change.after)):
            continue
        # Condition 1: a test written with its mock was written against the
        # stand-in from the start; only an existing live oracle can have one
        # slipped under it.
        units = [unit for unit in file.units
                 if unit.before is not None and unit.after is not None and unit.after.assertions
                 and not unit.before.markers and not unit.after.markers]
        if not units:
            continue
        head = _Side(path, change.after)
        if not head.installs:
            continue
        base = (_Side((change.old_path or change.path).replace("\\", "/"), change.before)
                if _TRIGGER.search(change.before) else None)
        for unit in units:
            for target, (install, module, target_path) in head.consumed(unit.after).items():
                # Condition 2: a target the base side already replaced - in a
                # hook, a describe body or another test - moved; it was not
                # installed by this diff.
                if base is not None and base.replaces(module, target_path):
                    continue
                events.add((path, unit.qualname, target, install.text, install.span))
    return sorted(events)
