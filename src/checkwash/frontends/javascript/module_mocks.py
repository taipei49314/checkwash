"""JavaScript stand-ins that an existing test's own oracle reads (issue #177).

`vi.mock("./src/billing.js", () => ({ invoiceTotal: () => 78.75 }))` added
above an untouched `expect(invoiceTotal(items)).toBe(78.75)` is the JS
spelling of THREATMODEL rows 60/90: production and every assertion stay
byte-identical while the assertion now checks the stand-in. No path in the
engine read a mock call, so the reported diff passed with zero findings.

Every spelling feeds one definition. An installation replaces either a whole
first-party module or one member path of it. A test unit *consumes* it when
one of its own assertions reads an export of that module - directly or
through one hop of a local binding - after the installation took effect. A
named or default import names its export in any use; a namespace or
`require()` object only through a member, so `compute(billing)` reads none
(#196 188.3). The TEST_PATCHES_SUBJECT conditions then carry over unchanged:
the unit existed and was live on both sides, the stand-in is new for that
unit (the base side installed the target neither at module level, in a hook,
a describe body or a helper, nor in the unit itself - one inside another
test never ran for it, #196 188.2 - so moving, reformatting or respelling an
installation is not one), and the unit's own oracle reads it. Mocking a
collaborator the oracle never reads is how unit tests are written, and stays
silent.

When an installation takes effect is part of the evidence:

- hoisted module mocks precede every import of the file: `vi.mock` wherever
  it is written, and `jest.mock` at module level. Vitest 3.2 and 4.1 hoist a
  `vi.mock` written in a test, a describe body, a hook or a helper to the
  top of the file (4.1 warns) and 5.0 refuses the file; babel-jest hoists
  `jest.mock` only within its own block (#196 188.1);
- ordered module mocks reach only `require()` / `await import()` bindings
  evaluated after them, never a static import: `vi.doMock`, `jest.doMock`,
  `jest.unstable_mockModule`, `jest.setMock`, node:test `mock.module` and
  `t.mock.module`, and `jest.mock` written inside a test body;
- member replacements: `vi.spyOn` / `jest.spyOn` / `vi.mocked(x)` /
  `jest.mocked(x)` chained to a replacing `mock*` call, `x.mock*(...)` on an
  imported binding (also through a TypeScript cast or non-null assertion),
  `jest.replaceProperty`, and node:test `mock.method` with an
  implementation. A spy created in one statement and replaced in another
  (`const spy = vi.spyOn(...)` then `spy.mockReturnValue(...)`, and the same
  for `jest.spyOn`, `vi.mocked`, `jest.mocked` and node:test's
  `fn.mock.mockImplementation(...)`) is read through one hop of the local
  binding on either side (#196 188.4). Inside a test body they reach only
  later reads.

A factory that reaches for the original module (`importOriginal`,
`importActual`, `requireActual`, or its own parameter) replaces every name it
spells - an identifier, a member name, or an identifier-shaped string such as
a quoted or computed key - and every name an object it merges in carries
(below), and nothing else. No factory is an automock; only an opaque one may
replace every export. Vitest's `{ spy: true }` and a spy with no replacement
keep the real code. An object-literal key in an assertion names a property;
it does not read the binding of the same name.

First-party means a `./` or `../` specifier that stays inside the repository
and outside dependency/build output, or an alias of one (#196 188.6,
`aliases.py`): an `@/` or `~/` specifier, the same alias string naming the
same module, and a specifier the base side's root `tsconfig.json` maps
through `compilerOptions.paths`, which names the module at the path it maps
to. Other bare specifiers are packages and builtins - faking network, time
and the filesystem is hygiene - and other aliases (`#imports`, root-relative
`/src`, a bare specifier `baseUrl` alone resolves, bundler and runner alias
configuration) resolve through configuration this scan does not read.

A setup file the runner loads before every test file is the conftest
analogue, read by `setup_files.py` with this file's scan (#218).

A partial factory, one that builds on the real module, may replace every name
it spells and every name an object it merges in carries (#196 188.5): a
spread in its own body's object literals, an `Object.assign` argument, or a
name it returns. A name bound outside the factory is read one hop, to
`vi.hoisted(...)` returning an object literal or to an object literal; what
stays unreadable makes the factory opaque, so it may replace every export.

Silent rather than guessed: `__mocks__` directories and runner config files
(`jest.config.*`, `vitest.config.*`); installations other than `vi.mock` in
hooks, helpers and `describe` bodies; a namespace or `require()` object
passed whole under a whole-module mock; plain assignment to a module object's
member; template-literal keys; cast types that contain parentheses;
non-literal specifiers; re-exports and two hops; and oracles the frontend
does not represent (interaction matchers, `.resolves`, snapshots).
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass

from checkwash.frontends.javascript.aliases import ALIAS_PREFIXES, Aliases
from checkwash.frontends.javascript.bindings import CALL, NAME, Bindings
from checkwash.frontends.javascript.frontend import (
    _call_argument_spans,
    _code_positions,
)
from checkwash.frontends.javascript.paths import is_js_test_file
from checkwash.ir.model import judged_as_test
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
# What a partial factory merges in from a name (#196 188.5): `name` or
# `name.member`, through `await`, parentheses, a cast or a non-null `!`.
_SOURCE = re.compile(
    r"\(?\s*(?:await\s+)?(" + NAME + r")(?:\s*\??\.\s*" + NAME + r")*\s*!?"
    + r"(?:\s+(?:as|satisfies)\s+[^()]*)?\s*\)?"
)
_ASSIGN = re.compile(r"(?<![\w$.#])Object\s*\.\s*assign\s*\(")
_RETURN = re.compile(r"(?<![\w$.#])return(?![\w$])")
_FUNCTION = re.compile(r"\s*(?:async\s+)?function(?![\w$])")
_CAST_TAIL = re.compile(r"(.*\))\s+(?:as|satisfies)\s+[^()]*", re.DOTALL)
# `): Type {` or `): Type =>`: a TypeScript return annotation, then the body.
_RETURN_TYPE = re.compile(
    r"\)\s*:\s*(?!\s|(?:return|throw|yield|await|new)(?![\w$]))[\w$.<>\[\]|&,\s]+?\s*(?:(=>)\s*|(?=\{))"
)
_REAL_CALL = re.compile(r"(" + NAME + r"(?:\s*\.\s*" + NAME + r")*)\s*(?:<[^;]*?>)?\s*\(", re.DOTALL)
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


def _module_path(path: str) -> str | None:
    """A module's key from its normalized path: extension-insensitive, `index` its directory."""
    for extension in _EXTENSIONS:
        if path.endswith(extension) and len(path) > len(extension):
            path = path[:-len(extension)]
            break
    return path[:-len("/index")] if path.endswith("/index") else path


def module_key(test_path: str, specifier: str, aliases: Aliases | None = None) -> str | None:
    """The first-party module a specifier names, extension-insensitive.

    A `./` or `../` specifier names the repository module it reaches from the
    test file. A specifier the base side's root tsconfig.json maps through
    `paths` names the module at the path it maps to, and an `@/` or `~/`
    specifier it does not map is a key of its own, so the same alias string
    in a mock and an import is one module (#196 188.6). Any other bare name
    is a package or a builtin, or an alias resolved through configuration
    this scan does not read. A specifier that leaves the repository root, or
    lands in dependency or build output, names nothing the project owns.
    `./billing`, `./billing.js` and `./billing.ts` are one module, as are
    `./src` and `./src/index.js`, and `@/billing` and `@/billing/index.ts`.
    """
    if any(char in specifier for char in "?#\\"):
        return None
    if specifier.startswith(("./", "../")):
        directory = test_path.replace("\\", "/").rpartition("/")[0]
        path = posixpath.normpath(posixpath.join(directory, specifier))
    else:
        target = aliases.target(specifier) if aliases is not None else None
        if target is not None:
            if "\\" in target:
                return None
            path = posixpath.normpath(target)
        elif specifier.startswith(ALIAS_PREFIXES):
            rest = posixpath.normpath(specifier[2:])
            if rest in {".", ".."} or rest.startswith(("../", "/")) or is_artifact(rest):
                return None
            return specifier[:2] + _module_path(rest)
        else:
            return None
    if path in {".", ".."} or path.startswith(("../", "/")) or is_artifact(path):
        return None
    return _module_path(path)


def _possibly_one(module: str, other: str) -> bool:
    """Can two keys name one module? Equal keys do. An alias the tsconfig
    does not map names whatever runner configuration maps it to, so it may
    be any key whose path ends with its own: `@/billing` may be
    `src/billing` or `~/billing` (#196 188.6). Only the base side's
    installations are asked, so a respelled mock stays silent rather than
    guessed new; a consumed read still needs one key."""
    if module == other:
        return True
    return any(alias.startswith(ALIAS_PREFIXES) and (key == alias[2:] or key.endswith("/" + alias[2:]))
               for alias, key in ((module, other), (other, module)))


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


def _closer(masked: str, opening: int, limit: int) -> int | None:
    """Where the bracket at `opening` closes, if it closes before `limit`."""
    closing = {"(": ")", "[": "]", "{": "}"}
    stack = []
    for index in range(opening, limit):
        char = masked[index]
        if char in closing:
            stack.append(closing[char])
        elif char in ")]}":
            if not stack or stack.pop() != char:
                return None
            if not stack:
                return index
    return None


def _element_end(masked: str, start: int, limit: int, *, statement: bool = False) -> int:
    """Where an element that starts at `start` ends: at the first `,` or
    unmatched closer at its own depth. A `return` value also ends at a `;`
    and, once it has begun, at a line break outside brackets."""
    depth = 0
    for index in range(start, limit):
        char = masked[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if not depth:
                return index
            depth -= 1
        elif not depth and (char == "," or statement and (
                char == ";" or char == "\n" and masked[start:index].strip())):
            return index
    return limit


def _annotated_bodies(masked: str, first: int, last: int) -> list[tuple[int, int]]:
    """Spans of the function bodies between `first` and `last` that a
    TypeScript return annotation keeps out of the bindings' function scopes,
    which take a body only right after the parameters: a method's block
    (`fetch(url: URL): Promise<ArrayBuffer> { ... }`), or an arrow's block or
    expression (`(o): Wrapped => ({ ...o })`) (#196 188.5)."""
    spans = []
    for match in _RETURN_TYPE.finditer(masked, first, last):
        body = match.end()
        if masked.startswith("{", body):
            closing = _closer(masked, body, last)
            if closing is not None:
                spans.append((body, closing))
        elif match.group(1):
            spans.append((body, _element_end(masked, body, last)))
    return spans


def _token_names(tokens) -> frozenset[str]:
    """The names an initializer's tokens spell, as `_Side._spelled` reads a
    factory: identifiers, member names and identifier-shaped strings."""
    names = set()
    for token in tokens:
        name = token[1:-1] if token[:1] in {"'", '"'} else token
        if _IDENT.fullmatch(name):
            names.add(name)
    return frozenset(names)


def _object_literal(tokens) -> bool:
    """Is this initializer one object literal, perhaps cast (`as const`)?"""
    if not tokens or tokens[0] != "{":
        return False
    depth = 0
    for index, token in enumerate(tokens):
        if token in {"(", "[", "{"}:
            depth += 1
        elif token in {")", "]", "}"}:
            depth -= 1
            if not depth:
                return index + 1 == len(tokens) or tokens[index + 1] in {"as", "satisfies"}
    return False


def _spreads(tokens) -> bool:
    return any(tokens[index:index + 3] == (".", ".", ".") for index in range(len(tokens) - 2))


def _returns_object(callback) -> bool:
    """Does a `vi.hoisted` callback return one object literal: `() => ({...})`,
    or a body whose own `return`s each return one?"""
    depth = 0
    for index, token in enumerate(callback):
        if not depth and token == "=>":
            body = callback[index + 1:]
            return body[:2] == ("(", "{") or body[:1] == ("{",) and _block_returns_object(body)
        if not depth and token == "function":
            opening = callback.index("(", index) if "(" in callback[index:] else None
            if opening is None:
                return False
            rest = callback[opening:]
            level = 0
            for offset, inner in enumerate(rest):
                level += inner in {"(", "[", "{"}
                level -= inner in {")", "]", "}"}
                if not level:
                    body = rest[offset + 1:]
                    return body[:1] == ("{",) and _block_returns_object(body)
            return False
        if token in {"(", "[", "{"}:
            depth += 1
        elif token in {")", "]", "}"}:
            depth -= 1
    return False


def _block_returns_object(body) -> bool:
    depth, found = 0, False
    for index, token in enumerate(body):
        if token in {"(", "[", "{"}:
            depth += 1
        elif token in {")", "]", "}"}:
            depth -= 1
            if not depth:
                break
        elif token == "return" and depth == 1:
            following = body[index + 1:index + 3]
            if following[:1] != ("{",) and following != ("(", "{"):
                return False
            found = True
    return found


def _real_module(value: str, parameter: str | None) -> bool:
    """Is this value the real module itself: `importOriginal()`, the factory's
    parameter called by another name, `vi.importActual(...)` or
    `jest.requireActual(...)`, through `await`, parentheses or a cast? A call
    that only takes the real module as an argument is not."""
    value = value.strip()
    while True:
        if value.startswith("(") and _closer(value, 0, len(value)) == len(value) - 1:
            value = value[1:-1].strip()
        elif re.match(r"await(?![\w$])", value):
            value = value[5:].strip()
        elif (cast := _CAST_TAIL.fullmatch(value)) is not None:
            value = cast.group(1).strip()
        else:
            break
    call = _REAL_CALL.match(value)
    if call is None:
        return False
    callee = re.sub(r"\s+", "", call.group(1))
    if callee.rsplit(".", 1)[-1] not in {"importOriginal", "importActual", "requireActual"} and callee != parameter:
        return False
    return _closer(value, call.end() - 1, len(value)) == len(value) - 1


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

    def __init__(self, path: str, data: bytes, aliases: Aliases | None = None):
        self.path = path
        self.aliases = aliases
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
            module = module_key(self.path, specifier, self.aliases)
            return _Binding(module, export, -1, 0) if module else None
        parsed = _module_expression(value)
        if parsed is None:
            return None
        specifier, export, loader = parsed
        if loader == "require" and bindings.resolve("require", position).kind != "require":
            return None
        module = module_key(self.path, specifier, self.aliases)
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
                if install is None and (len(parts) == 2 or parts[1] == "mock"):
                    install = self._spy_install(parts[0], len(parts) == 3, owner, start, end)
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
            if install is None and member is None:
                install = self._spy_install(name, False, owner, cast.start(), arguments[1])
            if install is not None:
                found.append(install)
        return found

    def _spy_install(self, name, through_mock, owner, start, end) -> _Install | None:
        """`spy.mockReturnValue(v)` on a spy created in another statement.

        One hop through the local binding, on either side (#196 188.4):
        `const spy = vi.spyOn(billing, "invoiceTotal")` or `jest.spyOn`, and
        `vi.mocked(x)` / `jest.mocked(x)`, which replace nothing until a
        `mock*` call; node:test's `mock.method(billing, "invoiceTotal")`
        without an implementation, replaced through `fn.mock.mock*(...)`.
        The replacement takes effect where that call runs. A rebound name is
        refused, not guessed at.
        """
        bindings = self.bindings
        found = self._declaration(name, start)
        if found is None or not isinstance(found[1], tuple) or bindings._written((name,), start):
            return None
        scope, value = found
        if "(" not in value or value[-1] != ")":
            return None
        opening = value.index("(")
        callee = value[:opening]
        if not callee or any((token != ".") if index % 2 else not _IDENT.fullmatch(token)
                             for index, token in enumerate(callee)):
            return None
        api = self._api(list(callee[::2]), bindings.scopes[scope].declarations[name][0])
        args: list[list[str]] = [[]]
        depth = 0
        for token in value[opening + 1:-1]:
            if token in {"(", "[", "{"}:
                depth += 1
            elif token in {")", "]", "}"}:
                depth -= 1
            if token == "," and depth == 0:
                args.append([])
            else:
                args[-1].append(token)
        if api in {("vi", "mocked"), ("jest", "mocked")} and not through_mock:
            target = args[0]
            if len(target) == 1 and _IDENT.fullmatch(target[0]):
                return self._member_install(target[0], None, owner, start, end)
            if len(target) == 3 and target[1] == "." and _IDENT.fullmatch(target[0]) and _IDENT.fullmatch(target[2]):
                return self._member_install(target[0], target[2], owner, start, end)
            return None
        if api in {("vi", "spyOn"), ("jest", "spyOn")} and not through_mock or (
                api == ("mock", "method") and through_mock and len(args) == 2):
            if (len(args) < 2 or len(args[0]) != 1 or not _IDENT.fullmatch(args[0][0])
                    or len(args[1]) != 1 or args[1][0][:1] not in {"'", '"'}
                    or not _IDENT.fullmatch(args[1][0][1:-1])):
                return None
            return self._member_install(args[0][0], args[1][0][1:-1], owner, start, end)
        return None

    def _member_install(self, name, member, owner, start, end) -> _Install | None:
        binding = self._binding(name, start) if name else None
        path = _path(binding, member) if binding is not None else ()
        if not path:
            return None  # replacing a whole namespace object is not a member
        return _Install(binding.module, path, None, False, owner, start,
                        self.text[start:end], (start, end))

    def _spelled(self, first: int, last: int) -> frozenset[str]:
        """Every name a factory spells, so every export it may replace itself:
        identifiers and member names (`actual.invoiceTotal = ...`) and
        identifier-shaped string literals (`"invoiceTotal": ...`,
        `["invoiceTotal"]: ...`). Comments and template literals stay opaque."""
        bindings = self.bindings
        names = {match.group() for match in _REFERENCE.finditer(bindings.masked, first, last)}
        names.update(token[1:-1] for token, start, _end in bindings.tokens
                     if first <= start < last and token[:1] in {"'", '"'} and _IDENT.fullmatch(token[1:-1]))
        return frozenset(names)

    def _factory_names(self, first: int, last: int) -> frozenset[str] | None:
        """What a partial factory may replace (#196 188.5): every name it
        spells, and the names each object it merges in carries, read one hop.
        None when a merged object stays unreadable: the factory is then
        opaque, and may replace every export."""
        parameter = _PARAMETER.match(self.bindings.masked, first)
        parameter = (parameter.group(1) or parameter.group(2)) if parameter else None
        sources = self._merge_sources(first, last)
        if sources is None:
            return None
        names = set(self._spelled(first, last))
        for start, end in sources:
            found = self._merged(start, end, (first, last), parameter)
            if found is None:
                return None
            names |= found
        return frozenset(names)

    def _merge_sources(self, first: int, last: int) -> list[tuple[int, int]] | None:
        """Spans of what a factory merges into the module it returns: each
        spread in an object literal, each `Object.assign` argument, and each
        value it returns that is no object literal, all in the factory's own
        body (a nested function's objects are no part of the module). None
        when the factory is no function literal whose body this reads."""
        body = self._body(first, last)
        if body is None:
            return None
        start, results = body
        bindings, masked = self.bindings, self.bindings.masked
        # Every `{` opens a scope, so an object literal's scope does not
        # always chain to the arrow whose body it is: a position is the
        # factory's own unless a function nested in its body holds it. The
        # body's own scope starts at `start` (an arrow's expression) or just
        # after it (a block's brace).
        nested = [(scope.start, scope.end) for scope in bindings.scopes
                  if scope.function and start + 1 < scope.start < last]
        nested += _annotated_bodies(masked, start, last)

        def mine(position: int) -> bool:
            return not any(opening <= position <= closing for opening, closing in nested)

        found = []
        stack: list[int] = []
        index = first
        while index < last:
            char = masked[index]
            if char in "([{":
                stack.append(index)
            elif char in ")]}":
                if stack:
                    stack.pop()
            elif masked.startswith("...", index):
                if stack and masked[stack[-1]] == "{" and mine(index) and self._object_brace(stack, last):
                    found.append((index + 3, _element_end(masked, index + 3, last)))
                index += 3
                continue
            index += 1
        for call in _ASSIGN.finditer(masked, first, last):
            if not mine(call.start()):
                continue
            arguments = _call_argument_spans(self.text, self.code, call.end() - 1, last)
            if arguments is None:
                return None
            found.extend(arguments[0])
        return found + results

    def _object_brace(self, stack: list[int], last: int) -> bool:
        """Is the brace on top of `stack` an object literal? A destructuring
        pattern's rest element (`const { a, ...rest } = x`, a parameter
        `({ a, ...rest }) =>`) merges nothing."""
        masked = self.bindings.masked
        closing = _closer(masked, stack[-1], last)
        if closing is None:
            return False
        after = masked[closing + 1:last].lstrip()
        if after[:1] == "=" and after[:2] not in {"==", "=>"} or re.match(r"(?:of|in)(?![\w$])", after):
            return False
        if len(stack) > 1 and masked[stack[-2]] == "(":
            parens = _closer(masked, stack[-2], last)
            if parens is not None and masked[parens + 1:last].lstrip().startswith(("=>", "{")):
                return False
        return True

    def _body(self, first: int, last: int) -> tuple[int, list[tuple[int, int]]] | None:
        """(where the factory's body starts, the values it returns as spans):
        an arrow's expression body, or each `return` of its own body. An
        object literal is left out, since its spreads are read where they
        are written. None when the factory is no function literal."""
        masked, bindings = self.bindings.masked, self.bindings
        depth, arrow = 0, None
        for index in range(first, last - 1):
            char = masked[index]
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            elif not depth and masked.startswith("=>", index):
                arrow = index
                break
        if arrow is not None:
            body = arrow + 2
            while body < last and masked[body].isspace():
                body += 1
            if body >= last:
                return None
            if masked[body] != "{":
                return body, self._result(body, last)
            block = body
        else:
            function = _FUNCTION.match(masked, first)
            opening = masked.find("(", function.end(), last) if function else -1
            parameters = _closer(masked, opening, last) if opening >= 0 else None
            block = masked.find("{", parameters, last) if parameters is not None else -1
            if block < 0:
                return None
        closing = _closer(masked, block, last)
        if closing is None:
            return None
        own = bindings._function_scope(bindings.scope(block + 1))
        hidden = _annotated_bodies(masked, block + 1, closing)
        found = []
        for keyword in _RETURN.finditer(masked, block, closing):
            if any(opening <= keyword.start() <= end for opening, end in hidden):
                continue  # a nested function's return, behind a return annotation
            if bindings._function_scope(bindings.scope(keyword.start())) == own:
                found.extend(self._result(keyword.end(),
                                          _element_end(masked, keyword.end(), closing, statement=True)))
        return block, found

    def _result(self, start: int, end: int) -> list[tuple[int, int]]:
        """One returned value, unless it is an object literal or `Object.assign`."""
        value = self.bindings.masked[start:end].strip()
        while value.startswith("(") and _closer(value, 0, len(value)) == len(value) - 1:
            value = value[1:-1].strip()
        if not value or value.startswith("{") or _ASSIGN.match(value):
            return []
        return [(start, end)]

    def _declared(self, name: str, position: int):
        """(scope, value) of the declaration `name` denotes at `position`,
        whether or not it is initialized there: a factory runs when its
        module is first imported, after the code it reads has run."""
        bindings = self.bindings
        scope = bindings.scope(position)
        while True:
            found = bindings.scopes[scope].declarations.get(name)
            if found is not None:
                return scope, found[1]
            parent = bindings.scopes[scope].parent
            if parent is None:
                return None
            scope = parent

    def _merged(self, start: int, end: int, factory: tuple[int, int],
                parameter: str | None) -> frozenset[str] | None:
        """The names one merged source may replace: none for the real module
        or an object written in the factory, whose names are spelled there,
        and one hop for a name bound outside it, to `vi.hoisted` returning
        an object literal or to an object literal. None when unreadable."""
        raw = self.bindings.masked[start:end]
        operand = raw.strip()
        if not operand or operand.startswith("{"):
            return frozenset()
        if _real_module(operand, parameter):
            return frozenset()
        match = _SOURCE.fullmatch(operand)
        if match is None:
            return None
        name = match.group(1)
        position = start + len(raw) - len(raw.lstrip()) + match.start(1)
        found = self._declared(name, position)
        if found is None:
            return None
        scope, value = found
        bindings = self.bindings
        inside = factory[0] <= bindings.scopes[scope].start < factory[1]
        if any(path[0] == name and bindings._binding_scope(name, at) == scope
               for path, at, _scope in bindings.writes):
            return None  # rebound, or a member assigned: not the object as written
        if not isinstance(value, tuple):
            # `const { invoiceTotal, ...rest } = await importOriginal()`: what
            # is left of the real module adds no name.
            rest = re.compile(r"(?:const|let|var)\s*\{[^{}]*\.\.\.\s*" + re.escape(name)
                              + r"\s*\}\s*=\s*([^;\n]+)").search(bindings.masked, *factory)
            return frozenset() if inside and rest and _real_module(rest.group(1), parameter) else None
        tokens = value[1:] if value[:1] == ("await",) else value
        if _real_module(" ".join(tokens), parameter):
            return frozenset()
        if inside:
            return frozenset() if _object_literal(tokens) else None
        if (len(tokens) > 4 and tokens[1:4] == (".", "hoisted", "(") and tokens[-1] == ")"
                and self._runner(tokens[0], position) == "vi"):
            callback = tokens[4:-1]
            return _token_names(callback) if _returns_object(callback) and not _spreads(callback) else None
        if _object_literal(tokens) and not _spreads(tokens):
            return _token_names(tokens)
        return None

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
        module = module_key(self.path, literal.group(2), self.aliases) if literal is not None else None
        if module is None:
            return None
        names = None
        if len(args) > 1 and method not in {"setMock", "module"}:
            factory = self.bindings.masked[spans[1][0]:spans[1][1]]
            if factory.strip().startswith("{"):
                if _SPY_OPTION.search(factory):
                    return None  # Vitest `{ spy: true }` keeps every real implementation
            elif _uses_original(factory):
                names = self._factory_names(*spans[1])
        if runner == "vi" and method == "mock":
            # Vitest hoists `vi.mock` to the top of the file wherever it is
            # written: 3.2 and 4.1 apply it to every test in the file (4.1
            # warns), and 5.0 refuses the file. `jest.mock` hoists only within
            # its own block, so in a test body it stays ordered (#196 188.1).
            owner = 0
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
                if not path:
                    # A namespace or require() object read whole, as in
                    # `compute(billing)`, names no export; only a member of it
                    # does. A named or default import names one in any use
                    # (#196 188.3, as Python's row 90).
                    continue
                for install in self.installs:
                    if self._covers(install, binding, path, position, callback):
                        target = f"{binding.module}:{'.'.join(path) or '*'}"
                        found.setdefault(target, (install, binding.module, path))
                        break
        return found

    def replaces(self, module: str, path: tuple[str, ...],
                 other_tests: list[tuple[int, int]] = ()) -> bool:
        """Did this side already replace it for one unit? Every installation
        counts - at module level, in a hook, a describe body, a helper or the
        unit itself - except one written inside another test, which never ran
        for this one (#196 188.2, as Python). A hoisted module mock runs for
        the whole file wherever it is written."""
        for install in self.installs:
            if not _possibly_one(install.module, module):
                continue
            if not install.hoisted and any(start <= install.position < end for start, end in other_tests):
                continue
            if install.member is not None:
                if path[:len(install.member)] == install.member:
                    return True
            elif install.names is None or (path and path[0] in install.names):
                return True
        return False


def module_mock_events(ir, changes, read_tsconfig=None) -> list[tuple[str, str, str, str, tuple[int, int]]]:
    """(path, unit, target, text, span) for each new stand-in an existing JS oracle reads.

    `read_tsconfig` reads the base side's root tsconfig.json, whose `paths`
    resolve alias specifiers on both sides (#196 188.6). It is called once,
    and only when a mock or an import spells a specifier that is not relative.
    """
    files = {file.path: file for file in ir.files if judged_as_test(file)}
    aliases = Aliases(read_tsconfig)
    events: set[tuple[str, str, str, str, tuple[int, int]]] = set()
    for change in changes:
        path = change.path.replace("\\", "/")
        file = files.get(path)
        if (file is None or not is_js_test_file(path, change.before, change.after) or change.before is None
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
        head = _Side(path, change.after, aliases)
        if not head.installs:
            continue
        base = (_Side((change.old_path or change.path).replace("\\", "/"), change.before, aliases)
                if _TRIGGER.search(change.before) else None)
        base_tests = [unit.before.span for unit in file.units if unit.before is not None]
        for unit in units:
            own = unit.before.span
            # The base side's other tests, less any that contain this unit
            # (a node:test subtest runs inside its parent's body).
            other_tests = [span for span in base_tests
                           if span != own and not span[0] <= own[0] <= own[1] <= span[1]]
            for target, (install, module, target_path) in head.consumed(unit.after).items():
                # Condition 2: a target the base side already replaced for this
                # unit - at module level, in a hook, a describe body, a helper
                # or the unit itself - moved; it was not installed by this diff.
                if base is not None and base.replaces(module, target_path, other_tests):
                    continue
                events.add((path, unit.qualname, target, install.text, install.span))
    return sorted(events)
