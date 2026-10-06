"""Bounded static JS import bindings and lexical shadows, without execution.

This is not a JavaScript interpreter. Flat imports/destructuring, simple aliases,
block scopes and function parameters are resolved, and every write is followed:
a name that any write may have reached is unknown, never its first value.
Unknown values never acquire assertion strength merely by using an assertion's
name.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
import heapq
import re

NAME = r"[A-Za-z_$][\w$]*"
CALL = re.compile(r"(?<![\w$.#])(?P<callee>" + NAME + r"(?:\s*\.\s*" + NAME + r")*)\s*\(")
_TOKEN = re.compile(
    r"(?P<quote>['\"])(?:\\.|(?!(?P=quote)).)*(?P=quote)|" + NAME
    + r"|=>|===|!==|==|!=|\?\.|\+\+|--|>>>=|<<=|>>=|\*\*=|&&=|\|\|=|\?\?=|[+*/%&|^-]=|[^\s]",
    re.DOTALL,
)
_IDENT = re.compile(NAME + r"\Z")
# Every assignment operator. Each one rebinds its target to a value this
# model does not compute (#196 189.1).
_ASSIGNMENTS = frozenset({
    "=", "+=", "-=", "*=", "/=", "%=", "**=", "<<=", ">>=", ">>>=", "&=", "|=", "^=", "&&=", "||=", "??=",
})
# Words that leave an expression waiting for its operand, and words that
# continue one across a line break (ASI, #196 189.1).
_OPERATOR_WORDS = frozenset({
    "typeof", "void", "delete", "await", "new", "in", "instanceof", "of", "as", "satisfies", "yield",
    "return", "throw", "case", "extends", "class", "function", "async", "else", "do", "keyof",
})
_CONTINUING_WORDS = frozenset({"in", "instanceof", "as", "satisfies"})
# Identifier-shaped words after which `[` opens an array, not a member access.
_STATEMENT_WORDS = _OPERATOR_WORDS | {"const", "let", "var"}


@dataclass(frozen=True)
class Value:
    kind: str
    method: str = ""
    # node:assert's strict mode (`node:assert/strict`, `assert.strict`), whose
    # equal and deepEqual are the strict comparisons (#198 Q3).
    strict: bool = False
    # A method of chai's `should.not` object, which asserts the negation (#215).
    negated: bool = False


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
        # Each token's start, for bisecting a position into the tokens (#235).
        self.token_starts = [start for _token, start, _end in self.tokens]
        self.pairs: dict[int, int] = {}
        self.scopes = [Scope(0, len(text), None, True)]
        self._scope_index: tuple[int, list[int], list[int]] | None = None
        self.scope_at: list[int] = []
        self.body_scopes: dict[int, int] = {}
        self.enclosing: list[int | None] = []
        self.writes: list[tuple[tuple[str, ...], int, int]] = []
        self.initializers: set[int] = set()
        # (scope, name) -> (ready, source text) of a plain `name = value` declaration.
        self.initializer_text: dict[tuple[int, str], tuple[int, str]] = {}
        # (scope, name) -> (module specifier, export) of an import's local
        # name: "default" for a default import, "*" for a namespace (#226).
        self.import_sources: dict[tuple[int, str], tuple[str, str]] = {}
        # (scope, name) of a function or class declaration (#226).
        self.function_declarations: set[tuple[int, str]] = set()
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
        self.loops = self._loops()
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
        if name in {"assert", "node:assert"}:
            return Value("node")
        if name in {"assert/strict", "node:assert/strict"}:
            return Value("node", strict=True)
        if name == "node:test":
            return Value("node_test")
        # Vitest's expect reads Jest matchers and chai chains, and Vitest
        # re-exports chai's assert. Jest's own expect has no chai chain and
        # @jest/globals no assert, so it is a kind of its own (#198 Q5).
        if name == "vitest":
            return Value("jest")
        if name == "@jest/globals":
            return Value("jest_globals")
        if name == "chai":
            return Value("chai")
        return UNKNOWN

    @staticmethod
    def member(value: Value, name: str) -> Value:
        if value.kind in {"node", "node_namespace", "node_context"}:
            if name == "strict":
                return Value("node", strict=True)
            return Value("node_method", name, strict=value.strict)
        if value.kind == "jest" and name == "expect":
            return Value("expect")
        if value.kind == "jest_globals" and name == "expect":
            return Value("jest_expect")
        if value.kind == "jest" and name == "assert":
            return Value("chai_assert")
        if value.kind == "chai" and name in {"expect", "assert"}:
            return Value("chai_" + name)
        if value.kind == "chai_assert":
            return Value("chai_assert_method", name)
        # chai's should interface (#215): `chai.should()` (or its alias
        # `chai.Should()`) installs the `.should` getter and returns the
        # object whose `equal`, `exist` and `not.*` take the subject first.
        if value.kind == "chai" and name in {"should", "Should"}:
            return Value("chai_should")
        if value.kind == "chai_should":
            return Value("chai_should_not") if name == "not" else Value("chai_should_method", name)
        if value.kind == "chai_should_not":
            return Value("chai_should_method", name, negated=True)
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
            specifier = self.token(end + 1)[1:-1]
            module = self.module(specifier)
            scope = self.scope_at[i]
            if _IDENT.fullmatch(self.token(i + 1)):
                default = Value("runner") if module.kind == "node_test" else module
                self._declare(scope, self.token(i + 1), default)
                if not (self.token(i + 1) == "type" and self.token(i + 2) in {"{", "*"}):
                    self.import_sources[(scope, self.token(i + 1))] = (specifier, "default")
            for j in range(i + 1, end):
                if self.token(j) == "*" and self.token(j + 1) == "as":
                    self._declare(scope, self.token(j + 2),
                                  Value("node_namespace", strict=module.strict) if module.kind == "node" else module)
                    self.import_sources[(scope, self.token(j + 2))] = (specifier, "*")
                if self.token(j) == "{" and j in self.pairs:
                    for exported, local in self._pattern(j + 1, self.pairs[j]):
                        self._declare(scope, local, self.member(module, exported))
                        self.import_sources[(scope, local)] = (specifier, exported)

    def _expression_end(self, start: int, limit: int | None = None) -> int:
        """Index of the token that ends the expression starting at `start`.

        `;`, `,` or an unmatched closer ends it, and so does a line break
        where the token before completes an operand and the token after
        cannot continue it: the statement end JavaScript inserts there (ASI,
        #196 189.1). `const check = expect` with `check(value)` on the next
        line is two statements, not one call; `+`, `.`, `(` or `[` on the
        next line continues the expression, as it does in JavaScript.
        """
        i = start
        limit = len(self.tokens) if limit is None else limit
        while i < limit:
            token = self.token(i)
            if token in {";", ",", "}", ")", "]"}:
                break
            if i > start and self._line_break(i) and self._completes(i - 1) and not self._continues(i):
                break
            if token in {"(", "[", "{"} and i in self.pairs:
                i = self.pairs[i]
            i += 1
        return i

    def _line_break(self, i: int) -> bool:
        """Is there a line break between token `i - 1` and token `i`?"""
        return "\n" in self.text[self.tokens[i - 1][2]:self.tokens[i][1]]

    def _control_head(self, opening: int) -> bool:
        """Is the `(` at `opening` the head of `if`, a loop, `with`, `switch` or `catch`?"""
        keyword = opening - 1
        if self.token(keyword) == "await":
            keyword -= 1
        return (self.token(keyword) in {"if", "for", "while", "with", "switch", "catch"}
                and self.token(keyword - 1) not in {".", "?."})

    def _completes(self, i: int) -> bool:
        """Does token `i` complete an operand, so that a line break after it can end the statement?"""
        token = self.token(i)
        if token in {"]", "}", "++", "--"} or token[:1] in {"'", '"'} or token[:1].isdigit():
            return True
        if token == ")":
            return i not in self.pairs or not self._control_head(self.pairs[i])
        return bool(_IDENT.fullmatch(token)) and token not in _OPERATOR_WORDS

    def _continues(self, i: int) -> bool:
        """Can token `i`, first on its line, continue the expression before it?

        An operator, `.`, `?.`, `(`, `[` or `{` can; a name, a literal, `!`
        or a prefix `++`/`--` cannot, so JavaScript ends the statement first.
        """
        token = self.token(i)
        if token in {"++", "--"}:
            return False
        if token in {"!=", "!=="} or token in _CONTINUING_WORDS:
            return True
        return token[:1] in set("+-*/%<>=&|^?:.,([{")

    def _loops(self) -> list[tuple[int, int]]:
        """Text spans of the loop statements, head and body (#196 189.1).

        A write late in a loop body reaches a read early in it on the next
        iteration, so `_written` cannot order the two by position.
        """
        loops = []
        for i, (token, start, _) in enumerate(self.tokens):
            if token not in {"for", "while", "do"} or self.token(i - 1) in {".", "?."}:
                continue
            if token == "do":
                last = self._statement_last(i + 1)
                if self.token(last + 1) == "while" and last + 2 in self.pairs:
                    last = self.pairs[last + 2]
            else:
                head = i + 1 + (self.token(i + 1) == "await")
                if self.token(head) != "(" or head not in self.pairs:
                    continue
                last = self._statement_last(self.pairs[head] + 1)
            end = self.tokens[last][2] if 0 <= last < len(self.tokens) else len(self.text)
            loops.append((start, end))
        return loops

    def _statement_last(self, first: int) -> int:
        """Index of the last token of the statement that starts at token `first`."""
        if self.token(first) == "{" and first in self.pairs:
            return self.pairs[first]
        end = self._expression_end(first)
        while self.token(end) == ",":
            end = self._expression_end(end + 1)  # `a, b` is one statement
        return end if self.token(end) == ";" else end - 1

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
                        self.function_declarations.add((owner, name))
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
                self.function_declarations.add((self.scope_at[i], self.token(i + 1)))
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
                if pattern in {"{", "["} and cursor in self.pairs:
                    closing = self.pairs[cursor]
                    names = self._declared(cursor)
                    assignment = closing + 1
                elif _IDENT.fullmatch(pattern):
                    names = [("", pattern)]
                    assignment = cursor + 1
                else:
                    break
                if self.token(assignment) == "!" and self.token(assignment + 1) == ":":
                    assignment += 1  # TypeScript's definite assignment, `let x!: T`
                if self.token(assignment) == ":":
                    assignment = self._annotation_end(assignment + 1)
                ending = self._expression_end(assignment + 1) if self.token(assignment) == "=" else assignment
                if self.token(assignment) == "=":
                    self.initializers.add(assignment)
                expression = tuple(self.token(j) for j in range(assignment + 1, ending)) if self.token(assignment) == "=" else ()
                ready = self.tokens[ending - 1][2] if ending > assignment else self.tokens[cursor][2]
                for member, local in names:
                    if member is None:
                        value: Value | tuple[str, ...] = UNKNOWN
                    else:
                        value = ((*expression, ".", member) if member and expression else expression) or UNKNOWN
                    self._declare(scope, local, value, ready)
                    if expression and member == "":
                        self.initializer_text[(scope, local)] = (
                            ready, self.masked[self.tokens[assignment + 1][1]:ready])
                if self.token(ending) != ",":
                    break
                cursor = ending + 1

    def _annotation_end(self, first: int) -> int:
        """Index of the first token after a TypeScript type annotation that starts at `first`.

        `const eps: number = 0.01` declares eps with the initializer after the
        type (#240). The type ends at a top-level `=`, `,`, `;` or unmatched
        closer, outside `<...>` and brackets, or where JavaScript would end
        the statement at a line break: `let eps: number` with a name starting
        the next line.
        """
        i = first
        depth = 0
        while i < len(self.tokens):
            token = self.token(i)
            if token in {")", "]", "}"}:
                break
            if depth == 0 and token in {"=", ",", ";"}:
                break
            if (depth == 0 and i > first and "\n" in self.text[self.tokens[i - 1][2]:self.tokens[i][1]]
                    and _IDENT.fullmatch(token) and self._type_ends(i - 1)):
                break
            if token == "<":
                depth += 1
            elif token == ">" and depth:
                depth -= 1
            elif token in {"(", "[", "{"} and i in self.pairs:
                i = self.pairs[i]
            i += 1
        return i

    def _type_ends(self, i: int) -> bool:
        """Can a type annotation end with token `i`?"""
        token = self.token(i)
        if token in {")", "]", "}", ">"} or token[:1] in {"'", '"'} or token[:1].isdigit():
            return True
        return bool(_IDENT.fullmatch(token)) and token not in {
            "keyof", "typeof", "extends", "infer", "readonly", "unique", "is", "asserts", "in", "as", "new",
            "abstract",
        }

    def _declared(self, opening: int) -> list[tuple[str | None, str]]:
        """(member, local) for every name a declaration's pattern binds.

        A flat object property reads that member of the initializer. An array
        element, a nested pattern, a computed key or a rest element is unknown
        (None), but it still declares its name, so it shadows an outer one:
        `const [eps] = [1e12]` is not the outer `eps` (#196 189.1).
        """
        closing = self.pairs[opening]
        flat: dict[str, str] = {}
        if self.token(opening) == "{":
            for start, end in self._parts(opening + 1, closing):
                key = self.token(start)
                if not _IDENT.fullmatch(key):
                    continue
                if start + 1 == end or self.token(start + 1) == "=":
                    flat[key] = key
                elif (self.token(start + 1) == ":" and _IDENT.fullmatch(self.token(start + 2))
                      and (start + 3 == end or self.token(start + 3) == "=")):
                    flat[self.token(start + 2)] = key
        return [(flat.get(name), name) for name in self._binding_names(opening, closing + 1)]

    def _assignments(self) -> None:
        """Record every write (#196 189.1).

        Every assignment operator, prefix and postfix `++`/`--`, each target
        of a destructuring assignment, and the target of a `for`-`in`/`of`
        head without a declaration. A write to a member (`a.b = `, `a[k] = `)
        is a write to that path; a property of a call result or a private
        field is no binding.
        """
        for i, (token, start, _) in enumerate(self.tokens):
            if i in self.initializers or i in self.parameter_tokens:
                continue
            if token in _ASSIGNMENTS:
                if self._class_field(i):
                    continue
                path, first = self._target_before(i)
                if path is not None and self._declarative(first):
                    continue
                if path is not None:
                    targets = [path]
                elif token == "=" and self.token(i - 1) in {"]", "}"} and i - 1 in self.pairs:
                    targets = self._pattern_targets(self.pairs[i - 1])
                else:
                    continue
            elif token in {"++", "--"}:
                # Postfix needs its operand on the same line; after a line
                # break JavaScript ends the statement and the operator is prefix.
                postfix = self._operand_end(i - 1) and not self._line_break(i)
                targets = [self._path_before(i) if postfix else self._path_after(i)]
            elif token in {"of", "in"}:
                targets = self._loop_targets(i)
            else:
                continue
            for path in targets:
                if path:
                    self.writes.append((path, start, self.scope(start)))

    def _operand_end(self, i: int) -> bool:
        """Can a postfix `++`/`--` apply to the operand that token `i` ends?"""
        token = self.token(i)
        if token == "]":
            return True
        if token == ")":
            return i in self.pairs and not self._control_head(self.pairs[i])
        return bool(_IDENT.fullmatch(token)) and token not in _STATEMENT_WORDS

    def _chain_path(self, elements: list[tuple[str, str]]) -> tuple[str, ...]:
        """The binding path a member chain writes: its leading names.

        `a.b` writes a.b, and `a[k]` or `a.b[k].c` a member of a or a.b. A
        chain whose leading names are called (`f().x`) writes no binding.
        """
        path = []
        for kind, name in elements:
            if kind != "name":
                return () if kind == "call" else tuple(path)
            path.append(name)
        return tuple(path)

    def _path_before(self, i: int, floor: int = 0) -> tuple[str, ...] | None:
        """The path written by the assignment target that ends just before token `i`.

        None when no member chain ends there (an array or object pattern);
        `()` when the chain writes no binding. The target starts at `floor`
        or later: a rest element's `...` is not a member access.
        """
        return self._target_before(i, floor)[0]

    def _target_before(self, i: int, floor: int = 0) -> tuple[tuple[str, ...] | None, int]:
        """`_path_before`, with the index of the target's first token."""
        j = i - 1
        if self.token(j) == "!" and j > floor and self._operand_end(j - 1):
            j -= 1  # TypeScript's non-null `x! = ...`
        elements: list[tuple[str, str]] = []
        while j >= floor:
            token = self.token(j)
            if token in {"]", ")"} and j in self.pairs:
                opening = self.pairs[j]
                if opening <= floor or not self._operand_end(opening - 1):
                    if token == ")" and not elements:
                        return self._parenthesized(opening), opening
                    return None, j
                elements.append(("computed" if token == "]" else "call", ""))
                j = opening - 1
                continue
            if not _IDENT.fullmatch(token) or token in _STATEMENT_WORDS:
                return None, j
            if j > floor and self.token(j - 1) == "#":
                return (), j  # a private field: `this.#x = ...`
            elements.append(("name", token))
            if j - 1 <= floor or self.token(j - 1) not in {".", "?."}:
                break
            j -= 2
        if not elements:
            return None, j
        elements.reverse()
        return self._chain_path(elements), j

    def _declarative(self, first: int) -> bool:
        """Does the name at token `first` follow a word or a string that makes `=` declare, not write?

        `let x = `, a JSX attribute (`<Range max={5} />`, `class="a" max=`),
        a class field modifier (`static x = `, `readonly x = `) or a TS type
        alias (`type X = `). Two names side by side are never one JavaScript
        expression, except after a keyword that takes an operand.
        """
        before = self.token(first - 1)
        if before in {"const", "let", "var", "using"} or before[:1] in {"'", '"'}:
            return True
        return bool(_IDENT.fullmatch(before)) and before not in _OPERATOR_WORDS

    def _parenthesized(self, opening: int) -> tuple[str, ...] | None:
        """The path of a parenthesized target: `(x) = `, `(x as T) = `."""
        closing = self.pairs[opening]
        end = closing
        for k in range(opening + 1, closing):
            if self.token(k) in {"as", "satisfies"} and self.enclosing[k] == opening:
                end = k
                break
        if end == opening + 1:
            return None
        return self._path_before(end)

    def _path_after(self, i: int) -> tuple[str, ...]:
        """The path a prefix `++`/`--` at token `i` writes."""
        j = i + 1
        if self.token(j) == "(" and j in self.pairs:
            return self._parenthesized(j) or ()
        if not _IDENT.fullmatch(self.token(j)) or self.token(j) in _STATEMENT_WORDS:
            return ()
        elements = [("name", self.token(j))]
        j += 1
        while True:
            token = self.token(j)
            if token in {".", "?."} and _IDENT.fullmatch(self.token(j + 1)):
                elements.append(("name", self.token(j + 1)))
                j += 2
            elif token in {"[", "("} and j in self.pairs:
                elements.append(("computed" if token == "[" else "call", ""))
                j = self.pairs[j] + 1
            else:
                break
        return self._chain_path(elements)

    def _pattern_targets(self, opening: int) -> list[tuple[str, ...]]:
        """Every path a destructuring assignment pattern writes: `[a, b.c] = `, `({ d, e: f } = )`."""
        closing = self.pairs[opening]
        targets = []
        for start, end in self._parts(opening + 1, closing):
            while start < end and self.token(start) == ".":
                start += 1  # a rest element
            if self.token(opening) == "{":
                cursor = start
                while cursor < end and self.token(cursor) not in {":", "="}:
                    if self.token(cursor) in {"(", "[", "{"} and cursor in self.pairs:
                        cursor = self.pairs[cursor]
                    cursor += 1
                if self.token(cursor) == ":":
                    start = cursor + 1  # skip the property key
            stop = start
            while stop < end and self.token(stop) != "=":
                if self.token(stop) in {"(", "[", "{"} and stop in self.pairs:
                    stop = self.pairs[stop]
                stop += 1  # stop before a default value
            if start >= stop:
                continue
            if self.token(start) in {"[", "{"} and self.pairs.get(start) == stop - 1:
                targets.extend(self._pattern_targets(start))
            else:
                path = self._path_before(stop, start)
                if path:
                    targets.append(path)
        return targets

    def _loop_targets(self, i: int) -> list[tuple[str, ...]]:
        """The paths a `for (target of/in ...)` head writes, without a declaration."""
        opening = self.enclosing[i] if 0 <= i < len(self.enclosing) else None
        if opening is None or self.token(opening) != "(" or not self._control_head(opening):
            return []
        keyword = opening - 1 - (self.token(opening - 1) == "await")
        first = opening + 1
        if self.token(keyword) != "for" or self.token(first) in {"const", "let", "var", "using"}:
            return []
        if any(self.token(k) == ";" and self.enclosing[k] == opening for k in range(first, i)):
            return []  # `in` inside a three-clause head is the operator
        if self.token(first) in {"[", "{"} and self.pairs.get(first) == i - 1:
            return self._pattern_targets(first)
        path = self._path_before(i, first)
        return [path] if path else []

    def _class_field(self, i: int) -> bool:
        """Is the `=` at token `i` a class field initializer (`class C { eps = 0.01 }`)?"""
        owner = self.enclosing[i] if 0 <= i < len(self.enclosing) else None
        if owner is None or self.token(owner) != "{" or self.token(i) != "=":
            return False
        cursor = owner - 1
        while cursor >= 0 and self.token(cursor) not in {";", "{", "}", "=", "(", ","}:
            if self.token(cursor) == "class":
                return True
            if self.token(cursor) in {")", "]"} and cursor in self.pairs:
                cursor = self.pairs[cursor]  # `extends mixin(A, B)`
            cursor -= 1
        return False

    def scope(self, position: int) -> int:
        """The innermost scope at `position`: the shortest one holding it, the
        latest of equal ones, and the module's outside every scope.

        Answered from an index of the regions between the scopes' bounds,
        built once the scope list is complete, instead of a scan of every
        scope on each call (#235).
        """
        if self._scope_index is None or self._scope_index[0] != len(self.scopes):
            self._scope_index = (len(self.scopes), *self._index_scopes())
        _count, bounds, answers = self._scope_index
        region = bisect_left(bounds, position)
        if region < len(bounds) and bounds[region] == position:
            return answers[2 * region + 1]
        return answers[2 * region]

    def _index_scopes(self) -> tuple[list[int], list[int]]:
        """Every scope's bounds, sorted, and the innermost scope of each region
        they make: the gap before each bound, the bound itself, and the gap
        after the last one. A sweep keeps the scopes that hold the region in a
        heap ordered as `scope` orders them; one that ends before the region
        never holds a later one."""
        bounds = sorted({bound for scope in self.scopes for bound in (scope.start, scope.end)})
        order = sorted(range(len(self.scopes)), key=lambda index: self.scopes[index].start)
        heap: list[tuple[int, int, int]] = []
        answers: list[int] = []

        def innermost(holds) -> int:
            while heap and not holds(self.scopes[-heap[0][1]].end):
                heapq.heappop(heap)
            return -heap[0][1] if heap else 0

        cursor, previous = 0, None
        for bound in bounds:
            answers.append(innermost(lambda end: previous is not None and end > previous))
            while cursor < len(order) and self.scopes[order[cursor]].start == bound:
                index = order[cursor]
                heapq.heappush(heap, (self.scopes[index].end - bound, -index, index))
                cursor += 1
            answers.append(innermost(lambda end: end >= bound))
            previous = bound
        answers.append(0)
        return bounds, answers

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
        """Can a write to this binding, or to a prefix of the path, reach `position`?

        A write in any other function counts wherever it is written: a hook,
        a helper or a callback may run before the read, and unknown is the
        fail-safe answer (#196 189.1). In the read's own function a write
        counts when it comes first, or when a loop in that function runs both
        (the next iteration reads it). A later write in straight-line code
        does not, so a method captured before it is overwritten keeps its
        authority. A block does not create a new identity for an outer
        variable; a local declaration with the same spelling does.
        """
        owner = self._binding_scope(path[0], position)
        reader = self._function_scope(self.scope(position))
        for written, at, write_scope in self.writes:
            if path[:len(written)] != written or self._binding_scope(written[0], at) != owner:
                continue
            if at < position or self._function_scope(write_scope) != reader:
                return True
            if any(start <= position and at <= end and self._function_scope(self.scope(start)) == reader
                   for start, end in self.loops):
                return True
        return False

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
        # An undeclared `should` is the global `chai/register-should` sets to
        # `chai.should()`'s object (#215), and an undeclared `chai` is chai's
        # module: karma-chai's adapter and chai's own suite set the global
        # (#311).
        return {"assert": Value("node"), "expect": Value("expect"), "t": Value("context"),
                "test": Value("runner"), "it": Value("runner"), "require": Value("require"),
                "should": Value("chai_should"), "chai": Value("chai")}.get(name, UNKNOWN)

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
        if value.kind == "chai_should" and rest == ("(", ")"):
            return value  # `chai.should()` returns the should object
        return UNKNOWN if rest else value

    def callee(self, spelling: str, position: int) -> Value:
        path = tuple(re.sub(r"\s+", "", spelling).split("."))
        if self._written(path, position):
            return UNKNOWN
        value = self.resolve(path[0], position)
        for name in path[1:]:
            value = self.member(value, name)
        return value

    def is_global(self, path: tuple[str, ...], position: int) -> bool:
        """Does this dotted spelling still name the JavaScript global here?

        Any declaration of its root in an enclosing scope, initialized yet or
        not, or a write to the path or a prefix of it before `position`, is a
        local or replaced object instead. Globals such as `Math.abs` carry no
        assertion authority; this only gates numeric evidence (issue #179).
        """
        if not path or self._written(path, position):
            return False
        scope = self.scope(position)
        while True:
            if path[0] in self.scopes[scope].declarations:
                return False
            parent = self.scopes[scope].parent
            if parent is None:
                return True
            scope = parent

    def initializer(self, name: str, position: int) -> str | None:
        """Source of the initializer of the `const`/`let`/`var` that `name` reads here.

        The declaration `resolve` would pick, innermost scope first and ready
        before the read, and only while no write can reach the read: a `let`
        that any write `_assignments` records may have changed (any assignment
        operator, `++`/`--`, a destructuring target, a `for`-`in`/`of` head,
        from this function or any other) is unknown, not its first value
        (#196 189.1). Imports, parameters, functions, uninitialized names and
        names bound by an array or nested pattern have no initializer. A plain
        `name = value` declaration returns its text as written, with comments
        blanked, so `0.01 as const` keeps the spaces its reader needs (#240); a
        destructured member returns its `value.member` path.
        """
        if self._written((name,), position):
            return None
        scope = self.scope(position)
        while True:
            declaration = self.scopes[scope].declarations.get(name)
            if declaration is not None:
                ready, value = declaration
                if ready > position or isinstance(value, Value) or not value:
                    return None
                text = self.initializer_text.get((scope, name))
                if text is not None and text[0] == ready:
                    return text[1]
                return "".join(value)
            parent = self.scopes[scope].parent
            if parent is None:
                return None
            scope = parent

    def _declaration_scope(self, name: str, position: int) -> int | None:
        """The scope whose declaration of `name` a read at `position` reads, or None for a global."""
        scope = self._binding_scope(name, position)
        return scope if name in self.scopes[scope].declarations else None

    def imported(self, name: str, position: int) -> tuple[str, str] | None:
        """The module specifier and export `name` reads here, when an import declares it (#226).

        A local declaration that shadows the import, or a write that may
        reach the read, leaves the name unknown, as `initializer` does.
        """
        if self._written((name,), position):
            return None
        scope = self._declaration_scope(name, position)
        return None if scope is None else self.import_sources.get((scope, name))

    def declared_function(self, name: str, position: int) -> bool:
        """Does `name` read a function or class this file declares (#226)?"""
        scope = self._declaration_scope(name, position)
        return scope is not None and (scope, name) in self.function_declarations

    @staticmethod
    def _family(value: Value) -> frozenset[str]:
        if value.kind in {"node", "node_method", "node_namespace", "node_context"}:
            return frozenset({"Node"})
        if value.kind in {"context", "expect", "jest"}:
            return frozenset({value.kind})
        # @jest/globals offers only expect among assertion members, which
        # the `jest` family already keeps.
        if value.kind == "jest_globals":
            return frozenset({"jest"})
        if value.kind in {"chai_expect", "jest_expect"}:
            return frozenset({"expect"})
        if value.kind in {"chai_assert", "chai_assert_method"}:
            return frozenset({"chai"})
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
        # Both Vitest's module and chai's export expect and chai's assert;
        # their other members are not assertion candidates. @jest/globals
        # exports expect only.
        if value.kind in {"jest", "chai"} and not (member("expect") or member("assert")):
            return None
        if value.kind == "jest_globals" and not member("expect"):
            return None
        # A call on chai's should object asserts; calling `should()` itself
        # installs the getter (#215).
        if value.kind in {"chai_should", "chai_should_not"}:
            return "chai" if re.sub(r"\s+", "", spelling) != root else None
        if value.kind in {"node", "node_method", "node_namespace", "node_context", "context"}:
            return "Node"
        if (value.kind in {"expect", "chai_expect", "jest_expect"}
                or (value.kind in {"jest", "chai", "jest_globals"} and member("expect"))):
            return "expect"
        if value.kind in {"jest", "chai", "chai_assert", "chai_assert_method"}:
            return "chai"
        families = self._candidate_families(root, position)
        for family in families:
            if family == "context" and not member("assert"):
                continue
            if family == "jest" and not member("expect"):
                continue
            return "unresolved"
        return None
