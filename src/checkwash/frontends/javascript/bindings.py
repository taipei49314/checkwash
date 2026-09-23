"""Bounded static JS import bindings and lexical shadows, without execution.

This is not a JavaScript interpreter. Flat imports/destructuring, simple aliases,
block scopes, function parameters and direct writes are resolved. Unknown values
never acquire assertion strength merely by using an assertion's name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

NAME = r"[A-Za-z_$][\w$]*"
CALL = re.compile(r"(?<![\w$.#])(?P<callee>" + NAME + r"(?:\s*\.\s*" + NAME + r")*)\s*\(")
_TOKEN = re.compile(r"(?P<quote>['\"])(?:\\.|(?!(?P=quote)).)*(?P=quote)|" + NAME + r"|=>|===|!==|==|!=|\?\.|\+\+|--|[+*/-]=|[^\s]", re.DOTALL)
_IDENT = re.compile(NAME + r"\Z")


@dataclass(frozen=True)
class Value:
    kind: str
    method: str = ""


UNKNOWN = Value("unknown")


@dataclass
class Scope:
    start: int
    end: int
    parent: int | None
    function: bool = False
    declarations: dict[str, tuple[int, Value | tuple[str, ...]]] = field(default_factory=dict)


class Bindings:
    def __init__(self, text: str, code: bytearray, import_code: bytearray):
        self.text = text
        self.masked = "".join(c if code[i] else " " for i, c in enumerate(text))
        imports = "".join(c if import_code[i] else " " for i, c in enumerate(text))
        self.tokens = [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(imports)]
        self.pairs: dict[int, int] = {}
        self.scopes = [Scope(0, len(text), None, True)]
        self.scope_at: list[int] = []
        self.body_scopes: dict[int, int] = {}
        self.enclosing: list[int | None] = []
        self.writes: list[tuple[tuple[str, ...], int, int]] = []
        self.initializers: set[int] = set()
        self.parameter_tokens: set[int] = set()
        self.context_parameters: list[tuple[int, str, int]] = []
        stack: list[int] = []
        scopes = [0]
        for i, (token, start, end) in enumerate(self.tokens):
            self.scope_at.append(scopes[-1])
            self.enclosing.append(stack[-1] if stack else None)
            if token in {"(", "[", "{"}:
                stack.append(i)
                if token == "{":
                    self.body_scopes[i] = len(self.scopes)
                    self.scopes.append(Scope(end, len(text), scopes[-1]))
                    scopes.append(len(self.scopes) - 1)
            elif token in {")", "]", "}"} and stack:
                opening = stack.pop()
                if self.tokens[opening][0] != {")": "(", "]": "[", "}": "{"}[token]:
                    continue
                self.pairs[opening] = i
                self.pairs[i] = opening
                if token == "}":
                    self.scopes[scopes.pop()].end = start
        self._imports(code)
        self._functions()
        self._variables()
        self._assignments()
        # Parameter shadows must exist before CommonJS resolution, but runner
        # authority must wait until local variables and writes are known.
        for scope, name, position in self.context_parameters:
            if self._test_callback(position):
                self._declare(scope, name, Value("context"))

    def token(self, i: int) -> str:
        return self.tokens[i][0] if 0 <= i < len(self.tokens) else ""

    def _declare(self, scope: int, name: str, value: Value | tuple[str, ...], ready: int = -1) -> None:
        if _IDENT.fullmatch(name):
            self.scopes[scope].declarations[name] = (ready, value)

    @staticmethod
    def module(name: str) -> Value:
        if name in {"assert", "node:assert", "assert/strict", "node:assert/strict"}:
            return Value("node")
        if name == "node:test":
            return Value("node_test")
        if name in {"@jest/globals", "vitest"}:
            return Value("jest")
        return UNKNOWN

    @staticmethod
    def member(value: Value, name: str) -> Value:
        if value.kind in {"node", "node_namespace", "node_context"}:
            return Value("node") if name == "strict" else Value("node_method", name)
        if value.kind == "jest" and name == "expect":
            return Value("expect")
        if value.kind == "node_test" and name in {"test", "it"}:
            return Value("runner")
        if value.kind == "context" and name == "assert":
            return Value("node_context")
        return UNKNOWN

    def _pattern(self, first: int, last: int) -> list[tuple[str, str]]:
        """Flat binding patterns: return (export/property, local name)."""
        result = []
        i = first
        while i < last:
            name = self.token(i)
            if _IDENT.fullmatch(name):
                local = self.token(i + 2) if self.token(i + 1) in {":", "as"} else name
                result.append((name, local))
            while i < last and self.token(i) != ",":
                i += 1
            i += 1
        return result

    def _parts(self, first: int, last: int) -> list[tuple[int, int]]:
        """Split a binding list at commas outside nested patterns/defaults."""
        result = []
        start = first
        while first < last:
            if self.token(first) == ",":
                result.append((start, first))
                start = first + 1
            elif self.token(first) in {"(", "[", "{"} and first in self.pairs:
                first = self.pairs[first]
            first += 1
        result.append((start, last))
        return result

    def _binding_names(self, first: int, last: int) -> list[str]:
        """Only bound names, excluding property keys and default expressions."""
        while first < last and self.token(first) == ".":
            first += 1
        if first >= last:
            return []
        token = self.token(first)
        if token in {"{", "["} and first in self.pairs:
            result = []
            for start, end in self._parts(first + 1, min(last, self.pairs[first])):
                if token == "{":
                    cursor = start
                    while cursor < end and self.token(cursor) not in {":", "="}:
                        if self.token(cursor) in {"(", "[", "{"} and cursor in self.pairs:
                            cursor = self.pairs[cursor]
                        cursor += 1
                    if self.token(cursor) == ":":
                        start = cursor + 1
                result.extend(self._binding_names(start, end))
            return result
        return [token] if _IDENT.fullmatch(token) else []

    def _imports(self, code: bytearray) -> None:
        for i, (token, start, _) in enumerate(self.tokens):
            if token != "import" or not code[start] or self.token(i + 1) in {"(", "."}:
                continue
            end = i + 1
            while end < len(self.tokens) and self.token(end) not in {"from", ";"}:
                if self.tokens[end][1] - start > 1000:
                    break
                end += 1
            if self.token(end) != "from" or self.token(end + 1)[:1] not in {"'", '"'}:
                continue
            module = self.module(self.token(end + 1)[1:-1])
            scope = self.scope_at[i]
            if _IDENT.fullmatch(self.token(i + 1)):
                default = Value("runner") if module.kind == "node_test" else module
                self._declare(scope, self.token(i + 1), default)
            for j in range(i + 1, end):
                if self.token(j) == "*" and self.token(j + 1) == "as":
                    self._declare(scope, self.token(j + 2), Value("node_namespace") if module.kind == "node" else module)
                if self.token(j) == "{" and j in self.pairs:
                    for exported, local in self._pattern(j + 1, self.pairs[j]):
                        self._declare(scope, local, self.member(module, exported))

    def _expression_end(self, start: int, limit: int | None = None) -> int:
        i = start
        limit = len(self.tokens) if limit is None else limit
        while i < limit:
            token = self.token(i)
            if token in {";", ",", "}", ")"}:
                break
            if i > start and "\n" in self.text[self.tokens[i - 1][2]:self.tokens[i][1]]:
                if token in {"const", "let", "var", "test", "it", "return", "import", "function"}:
                    break
            if token in {"(", "[", "{"} and i in self.pairs:
                i = self.pairs[i]
            i += 1
        return i

    def _functions(self) -> None:
        # Register parameters before resolving variable initializers, so a
        # parameter called require cannot forge a trusted CommonJS import.
        for i, (token, start, _) in enumerate(self.tokens):
            if token == "function":
                cursor = i + 1 + (self.token(i + 1) == "*")
                name = ""
                if _IDENT.fullmatch(self.token(cursor)):
                    name = self.token(cursor)
                    cursor += 1
                if self.token(cursor) != "(" or cursor not in self.pairs:
                    continue
                closing = self.pairs[cursor]
                body = closing + 1
                while body < len(self.tokens) and self.token(body) not in {"{", ";", "=>"}:
                    body += 1
                if body in self.body_scopes:
                    scope = self.body_scopes[body]
                    if name:
                        previous = i - 2 if self.token(i - 1) == "async" else i - 1
                        owner = scope if self.token(previous) in {"=", "(", ",", ":", "return"} else self.scope_at[i]
                        self._declare(owner, name, UNKNOWN)
                    self._parameters(cursor + 1, closing, scope, cursor)
            elif token == "=>":
                previous = i - 1
                if self.token(previous) == ")" and previous in self.pairs:
                    first, last = self.pairs[previous] + 1, previous
                elif _IDENT.fullmatch(self.token(previous)):
                    first, last = previous, previous + 1
                else:
                    continue
                body = i + 1
                if body >= len(self.tokens):
                    continue
                if body in self.body_scopes:
                    scope = self.body_scopes[body]
                else:
                    ending = self._expression_end(body)
                    scope = len(self.scopes)
                    self.scopes.append(Scope(self.tokens[body][1],
                                             self.tokens[ending][1] if ending < len(self.tokens) else len(self.text),
                                             self.scope_at[i], True))
                # A direct test callback receives Node's context. This keeps
                # the established bare test()/t.assert compatibility spelling.
                self._parameters(first, last, scope, first - 1)
            elif token == "catch" and self.token(i + 1) == "(" and i + 1 in self.pairs:
                closing = self.pairs[i + 1]
                if closing + 1 in self.body_scopes:
                    scope = self.body_scopes[closing + 1]
                    self.parameter_tokens.update(range(i + 2, closing))
                    for name in self._binding_names(i + 2, closing):
                        self._declare(scope, name, UNKNOWN)
            elif token == "class" and _IDENT.fullmatch(self.token(i + 1)):
                self._declare(self.scope_at[i], self.token(i + 1), UNKNOWN)
            elif token == "(" and i in self.pairs and self._method_parameters(i):
                closing = self.pairs[i]
                self._parameters(i + 1, closing, self.body_scopes[closing + 1])

    def _method_parameters(self, opening: int) -> bool:
        """Recognize concise method signatures only inside objects/classes.

        A normal call followed by an ASI block is not a method declaration.
        This bounded form has a named method and an immediately following
        body; computed names and TypeScript return annotations stay outside it.
        """
        closing = self.pairs[opening]
        if closing + 1 not in self.body_scopes or not _IDENT.fullmatch(self.token(opening - 1)):
            return False
        owner = self.enclosing[opening]
        if owner is None or self.token(owner) != "{":
            return False
        if self.token(owner - 1) in {"=", "(", "[", ",", ":", "return"}:
            return True
        cursor = owner - 1
        while cursor >= 0 and self.token(cursor) not in {";", "{", "}", "="}:
            if self.token(cursor) == "class":
                return True
            cursor -= 1
        return False

    def _test_callback(self, first: int) -> bool:
        opening = self.enclosing[first] if 0 <= first < len(self.enclosing) else None
        if opening is None or self.token(opening) != "(":
            return False
        previous = opening - 1
        if self.token(previous) in {"skip", "todo", "only"} and self.token(previous - 1) == ".":
            previous -= 2
        return self.resolve(self.token(previous), self.tokens[opening][1]).kind == "runner"

    def _parameters(self, first: int, last: int, scope: int, context_position: int | None = None) -> None:
        self.scopes[scope].function = True
        self.parameter_tokens.update(range(first, last))
        for start, end in self._parts(first, last):
            for local in self._binding_names(start, end):
                self._declare(scope, local, UNKNOWN)
        if context_position is not None and _IDENT.fullmatch(self.token(first)):
            self.context_parameters.append((scope, self.token(first), context_position))

    def _variables(self) -> None:
        for i, (token, _, _) in enumerate(self.tokens):
            if token not in {"const", "let", "var"}:
                continue
            scope = self.scope_at[i]
            if token == "var":
                while self.scopes[scope].parent is not None and not self.scopes[scope].function:
                    scope = self.scopes[scope].parent
            cursor = i + 1
            while cursor < len(self.tokens):
                pattern = self.token(cursor)
                if pattern == "{" and cursor in self.pairs:
                    closing = self.pairs[cursor]
                    names = self._pattern(cursor + 1, closing)
                    assignment = closing + 1
                elif _IDENT.fullmatch(pattern):
                    names = [("", pattern)]
                    assignment = cursor + 1
                else:
                    break
                ending = self._expression_end(assignment + 1) if self.token(assignment) == "=" else assignment
                if self.token(assignment) == "=":
                    self.initializers.add(assignment)
                expression = tuple(self.token(j) for j in range(assignment + 1, ending)) if self.token(assignment) == "=" else ()
                ready = self.tokens[ending - 1][2] if ending > assignment else self.tokens[cursor][2]
                for member, local in names:
                    value = (*expression, ".", member) if member and expression else expression
                    self._declare(scope, local, value or UNKNOWN, ready)
                if self.token(ending) != ",":
                    break
                cursor = ending + 1

    def _assignments(self) -> None:
        for i, (token, start, _) in enumerate(self.tokens):
            if token not in {"=", "+=", "-=", "*=", "/=", "++", "--"}:
                continue
            if i in self.initializers or i in self.parameter_tokens:
                continue
            j = i - 1
            path = []
            while j >= 0 and _IDENT.fullmatch(self.token(j)):
                path.insert(0, self.token(j))
                j -= 1
                if self.token(j) != ".":
                    break
                j -= 1
            if not path or self.token(j) in {"const", "let", "var"}:
                continue
            self.writes.append((tuple(path), start, self.scope(start)))

    def scope(self, position: int) -> int:
        candidates = [(scope.end - scope.start, -index, index) for index, scope in enumerate(self.scopes)
                      if scope.start <= position <= scope.end]
        return min(candidates)[2] if candidates else 0

    def _contains(self, scope: int, position: int) -> bool:
        return self.scopes[scope].start <= position <= self.scopes[scope].end

    def _binding_scope(self, name: str, position: int) -> int:
        scope = self.scope(position)
        while name not in self.scopes[scope].declarations:
            parent = self.scopes[scope].parent
            if parent is None:
                break
            scope = parent
        return scope

    def _function_scope(self, scope: int) -> int:
        while not self.scopes[scope].function and self.scopes[scope].parent is not None:
            scope = self.scopes[scope].parent
        return scope

    def _written(self, path: tuple[str, ...], position: int) -> bool:
        """Track writes to this binding across blocks, not across functions.

        A block does not create a new identity for an outer variable. A local
        declaration with the same spelling does, and writes in a separate
        function are not evidence that that function executed at this read.
        """
        owner = self._binding_scope(path[0], position)
        return any(
            path[:len(written)] == written and at < position
            and self._binding_scope(written[0], at) == owner
            and self._contains(self._function_scope(write_scope), position)
            for written, at, write_scope in self.writes
        )

    def resolve(self, name: str, position: int, seen: frozenset[tuple[int, str]] = frozenset()) -> Value:
        scope = self.scope(position)
        if self._written((name,), position):
            return UNKNOWN
        while True:
            declaration = self.scopes[scope].declarations.get(name)
            if declaration is not None:
                ready, value = declaration
                key = (scope, name)
                if ready > position or key in seen or len(seen) > 12:
                    return UNKNOWN
                if isinstance(value, Value):
                    return value
                return self._value(value, ready, seen | {key})
            parent = self.scopes[scope].parent
            if parent is None:
                break
            scope = parent
        return {"assert": Value("node"), "expect": Value("expect"), "t": Value("context"),
                "test": Value("runner"), "it": Value("runner"), "require": Value("require")}.get(name, UNKNOWN)

    def _value(self, expression: tuple[str, ...], position: int, seen: frozenset[tuple[int, str]]) -> Value:
        if not expression:
            return UNKNOWN
        if len(expression) >= 4 and expression[0:2] == ("require", "(") and expression[3] == ")":
            if self.resolve("require", position, seen).kind != "require":
                return UNKNOWN
            value = self.module(expression[2][1:-1]) if expression[2][:1] in {"'", '"'} else UNKNOWN
            rest = expression[4:]
        else:
            # An alias captures a property at initialization time. A method
            # captured before a later overwrite remains the original function;
            # a capture after that overwrite cannot recreate its authority.
            path = expression[::2]
            if (all(_IDENT.fullmatch(name) for name in path)
                    and all(token == "." for token in expression[1::2])
                    and len(expression) % 2 and self._written(path, position)):
                return UNKNOWN
            value = self.resolve(expression[0], position, seen)
            rest = expression[1:]
        while len(rest) >= 2 and rest[0] == ".":
            value = self.member(value, rest[1])
            rest = rest[2:]
        return UNKNOWN if rest else value

    def callee(self, spelling: str, position: int) -> Value:
        path = tuple(re.sub(r"\s+", "", spelling).split("."))
        if self._written(path, position):
            return UNKNOWN
        value = self.resolve(path[0], position)
        for name in path[1:]:
            value = self.member(value, name)
        return value

    @staticmethod
    def _family(value: Value) -> frozenset[str]:
        if value.kind in {"node", "node_method", "node_namespace", "node_context"}:
            return frozenset({"Node"})
        if value.kind in {"context", "expect", "jest"}:
            return frozenset({value.kind})
        return frozenset()

    def _candidate_families(self, name: str, position: int,
                            seen: frozenset[tuple[int, str]] = frozenset()) -> frozenset[str]:
        """Keep bounded provenance for diagnostics, independently of authority.

        A shadowed assertion still warrants a warning, but another scope's
        unrelated variable with the same spelling is not assertion evidence.
        """
        scope = self.scope(position)
        while True:
            declaration = self.scopes[scope].declarations.get(name)
            if declaration is not None:
                ready, value = declaration
                key = (scope, name)
                if key in seen or len(seen) > 12:
                    return frozenset()
                families = (self._family(value) if isinstance(value, Value) else
                            self._expression_families(value, ready, seen | {key}))
                if families:
                    return families
            parent = self.scopes[scope].parent
            if parent is None:
                break
            scope = parent
        return {"assert": frozenset({"Node"}), "expect": frozenset({"expect"}),
                "t": frozenset({"context"})}.get(name, frozenset())

    def _expression_families(self, expression: tuple[str, ...], position: int,
                             seen: frozenset[tuple[int, str]]) -> frozenset[str]:
        if not expression:
            return frozenset()
        # Conditional aliases remain candidates without granting either arm's
        # strength. Ignore identifiers in unrelated literals/function bodies.
        depth = 0
        question = None
        nested = 0
        for index, token in enumerate(expression):
            if token in {"(", "[", "{"}:
                depth += 1
            elif token in {")", "]", "}"}:
                depth -= 1
            elif depth == 0 and token == "?":
                if question is None:
                    question = index
                else:
                    nested += 1
            elif depth == 0 and token == ":" and question is not None:
                if nested:
                    nested -= 1
                else:
                    return (self._expression_families(expression[question + 1:index], position, seen)
                            | self._expression_families(expression[index + 1:], position, seen))
        if len(expression) >= 4 and expression[:2] == ("require", "(") and expression[3] == ")":
            families = self._family(self.module(expression[2][1:-1]))
            rest = expression[4:]
        else:
            families = self._candidate_families(expression[0], position, seen)
            rest = expression[1:]
        while len(rest) >= 2 and rest[0] == ".":
            member = rest[1]
            families = frozenset(
                "Node" if family == "context" else "expect" if family == "jest" else family
                for family in families
                if family not in {"context", "jest"}
                or (family == "context" and member == "assert")
                or (family == "jest" and member == "expect")
            )
            rest = rest[2:]
        return families

    def candidate(self, spelling: str, position: int) -> str | None:
        root = re.split(r"[.\[?]", spelling, maxsplit=1)[0].strip()
        value = self.resolve(root, position)
        def member(name: str) -> bool:
            return bool(re.match(re.escape(root) + r"\s*(?:\??\.\s*" + name
                                 + r"\b|(?:\?\.)?\s*\[\s*(['\"])" + name + r"\1\s*\])", spelling))
        if value.kind == "context" and not member("assert"):
            return None
        if value.kind == "jest" and not member("expect"):
            return None
        if value.kind in {"node", "node_method", "node_namespace", "node_context", "context"}:
            return "Node"
        if value.kind in {"expect", "jest"}:
            return "expect"
        families = self._candidate_families(root, position)
        for family in families:
            if family == "context" and not member("assert"):
                continue
            if family == "jest" and not member("expect"):
                continue
            return "unresolved"
        return None
