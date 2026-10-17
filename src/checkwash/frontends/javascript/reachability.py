"""Which statements of a JS/TS test callback run (#429: Q1, Q3, Q5).

The JS/TS twin of the Python frontend's reachability walk
(`_unreachable_ids`, SPEC §2b). One bounded walker reads the statements of a
test callback's block body. It cuts after an unconditional `return` or
`throw`, and skips a branch whose condition `fold_condition` decides: the
body of `if (false)`, `while (false)` and `for (; false; )`, and the `else`
of `if (true)`. It descends into blocks, loop and `do` bodies,
`try`/`catch`/`finally` blocks and labeled statements. Only a block and a
statically selected branch pass their termination on, as only a statically
selected branch does in Python; a loop, `do`, `try` or labeled body never
does. It never enters a function, arrow or class body, so the `return` of an
iterator callback ends nothing outside it. A literal-decided `&&`/`||`
expression statement drops the assertion it ends with (Q3).

Not a parser. The token stream omits templates and regular expressions, so a
line break next to one, an unpaired bracket, a `with` statement, a
TypeScript-annotated function declaration, or any statement whose end is not
proved stops the walk of its statement list there, and everything after it
keeps today's reading. A callback is not walked at all when its text holds
U+2028 or U+2029, which the shared line-break test does not read, or text the
token stream misreads as code: a template nested in a substitution, JSX, or
an Annex B HTML-like comment. A dead body that is no block is not killed where
its end at a line break is in doubt. A `switch` body is
not read: the walk steps over it and goes on after it.
"""

from __future__ import annotations

import math
import re
from bisect import bisect_left
from collections.abc import Callable

from checkwash.frontends.javascript.bindings import NAME, Bindings
from checkwash.frontends.javascript.literals import (
    _REGEX_LITERAL,
    _string_end,
    _template_end,
    operand_tokens,
    scalar_literal,
)

_MAX_DEPTH = 32
_BRACKETS = {"(": ")", "[": "]", "{": "}"}
_CLOSERS = frozenset(_BRACKETS.values())
_NAME = re.compile(NAME + r"\Z")
# Statement words this walk does not read: a statement starting with one
# ends the walk of its list.
_UNREAD = frozenset({"with", "import", "export", "else", "catch", "finally", "case", "default"})
_JUMPS = frozenset({"return", "throw", "break", "continue"})
_TRIVIA_SPACE = " \t\n\v\f\N{ZERO WIDTH NO-BREAK SPACE}"


def _trivia(text: str) -> bool:
    """Whitespace and comments only: no operand the token stream leaves out."""
    cursor = 0
    while cursor < len(text):
        if text[cursor] in _TRIVIA_SPACE:
            cursor += 1
        elif text.startswith("//", cursor):
            newline = text.find("\n", cursor + 2)
            cursor = len(text) if newline < 0 else newline + 1
        elif text.startswith("/*", cursor):
            closing = text.find("*/", cursor + 2)
            if closing < 0:
                return False
            cursor = closing + 2
        else:
            return False
    return True


def _within(positions: list[int], first: int, last: int) -> bool:
    index = bisect_left(positions, first)
    return index < len(positions) and positions[index] < last


# --- Q5: the literal-only condition folder ---------------------------------------------------

_WORD = re.compile(NAME)
# Operators that bind looser than `&&` and `||`, or that are no part of a
# condition this folder reads.
_LOOSER = frozenset({
    ",", "?", ":", "??", "=", "=>", "...", "+=", "-=", "*=", "/=", "%=", "**=", "<<=", ">>=", ">>>=",
    "&=", "|=", "^=", "&&=", "||=", "??=", "yield",
})
_EQUALITY = frozenset({"===", "!==", "==", "!="})
_RELATIONAL = frozenset({"<", ">", "<=", ">="})
# How deep `!` and parentheses nest before the folder gives up: unknown.
_FOLD_DEPTH = 64
# Tokens after which a `/` can only start a regular expression, and words that
# do so unless they are a property name (`x.new / 2` divides).
_REGEX_AFTER = frozenset({
    "", "(", ",", "=", ":", "[", "{", ";", "?", "&", "|", "^", "~", "+", "-", "*", "%", "<", "=>",
    "==", "===", "!=", "!==", "+=", "-=", "*=", "%=", "&=", "|=", "^=", "<=", ">=", "**=", "<<=",
    ">>=", ">>>=", "&&=", "||=", "??=", "??", "&&", "||", "**", "<<", ">>", ">>>",
})
_REGEX_AFTER_WORDS = frozenset({"return", "typeof", "case", "do", "else", "throw", "void", "delete", "in",
                                "instanceof", "new"})
# Tokens after which a name is read, never bound, and heads whose `(` is no call.
_READ_AFTER = frozenset({"!", "&", "|", "?", "==", "===", "!=", "!==", "=", "return", "typeof", "void", "case"})
_NOT_CALLS = frozenset({"for", "catch", "function", "switch", "with", "if", "while", "async"})
# Tokens after which a line break cannot end a statement in JavaScript or
# TypeScript: the expression is unfinished (`false &&` then `expect(...)`). Not
# `.`, which may end a number (`1.`), and the reserved words only where no `.`,
# `?.` or `#` makes them a property name (`cache.delete`).
_UNFINISHED = frozenset({
    "&", "|", "^", "=", "+", "-", "*", "/", "%", ",", "?", ":", "<", "==", "===", "!=", "!==",
    "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "=>", "in", "instanceof", "typeof", "new", "delete",
    "extends",
})
# Statements whose end is a token they own (`;` or their closing `}`), not a line break.
_COMPOUND = frozenset({"{", "if", "for", "while", "do", "try", "switch", "function", "class", "with"})
# Keywords that start a statement and never continue an expression.
_STATEMENT_KEYWORDS = frozenset({
    "do", "if", "for", "while", "return", "throw", "var", "let", "const", "try", "switch", "break",
    "continue", "with", "debugger", "export", "else", "case", "default", "catch", "finally",
})
# A `with (` or `eval` anywhere in the text, comments and strings included; one
# pass, no backtracking. A comment between `with` and `(` is caught on the tokens.
_SCOPE_CHANGERS = re.compile(r"(?<![\w$])(?:with[\s\N{ZERO WIDTH NO-BREAK SPACE}]*\(|eval(?![\w$]))")


class _Folder:
    """Python's `_static_truth`, over one condition's tokens.

    A value is `(type, value)`: number, bigint, string, boolean, null or
    undefined, or `("truth", bool)` for the result of `&&` and `||`, whose
    truthiness alone is known. None is unknown.
    """

    def __init__(self, tokens: list[str], is_global: Callable[[str], bool]):
        self.tokens = tokens
        self.is_global = is_global
        self.pairs: dict[int, int] = {}
        stack: list[int] = []
        self.balanced = True
        for index, token in enumerate(tokens):
            if token in _BRACKETS:
                stack.append(index)
            elif token in _CLOSERS:
                if not stack or _BRACKETS[tokens[stack[-1]]] != token:
                    self.balanced = False
                    return
                self.pairs[stack.pop()] = index
        self.balanced = not stack

    def _top(self, lo: int, hi: int):
        index = lo
        while index < hi:
            yield index
            index = self.pairs.get(index, index) + 1

    def _split(self, lo: int, hi: int, operator: str) -> list[tuple[int, int]]:
        parts, start = [], lo
        for index in self._top(lo, hi):
            if self.tokens[index] == operator:
                parts.append((start, index))
                start = index + 1
        parts.append((start, hi))
        return parts

    def expression(self, lo: int, hi: int, depth: int = 0):
        if depth > _FOLD_DEPTH or lo >= hi or any(self.tokens[index] in _LOOSER for index in self._top(lo, hi)):
            return None
        for operator, decides in (("||", True), ("&&", False)):
            parts = self._split(lo, hi, operator)
            if len(parts) > 1:
                truths = [self.truth(self.expression(first, last, depth + 1)) for first, last in parts]
                if decides in truths:
                    return ("truth", decides)
                if all(truth is (not decides) for truth in truths):
                    return ("truth", not decides)
                return None
        return self._comparison(lo, hi, depth)

    def _comparison(self, lo: int, hi: int, depth: int):
        operators = [index for index in self._top(lo, hi)
                     if self.tokens[index] in _EQUALITY | _RELATIONAL | {"in", "instanceof"}]
        if not operators:
            return self._unary(lo, hi, depth)
        if len(operators) != 1 or self.tokens[operators[0]] in {"in", "instanceof"}:
            return None
        index = operators[0]
        left, right = self._literal(lo, index), self._literal(index + 1, hi)
        if left is None or right is None:
            return None
        result = _compare(self.tokens[index], left, right)
        return None if result is None else ("boolean", result)

    def _unary(self, lo: int, hi: int, depth: int):
        if lo >= hi or depth > _FOLD_DEPTH:
            return None
        if self.tokens[lo] == "!":
            truth = self.truth(self._unary(lo + 1, hi, depth + 1))
            return None if truth is None else ("boolean", not truth)
        if self.tokens[lo] == "(" and self.pairs.get(lo) == hi - 1:
            return self.expression(lo + 1, hi - 1, depth + 1)
        return self._literal(lo, hi)

    def _literal(self, lo: int, hi: int):
        """A literal, through parentheses; a sign belongs to a number."""
        while hi - lo > 2 and self.tokens[lo] == "(" and self.pairs.get(lo) == hi - 1:
            lo, hi = lo + 1, hi - 1
        if hi - lo == 2 and self.tokens[lo] in {"-", "+"}:
            value = self._literal(lo + 1, hi)
            if value is None or value[0] not in {"number", "bigint"} or (
                    value[0] == "bigint" and self.tokens[lo] == "+"):
                return None
            return value if self.tokens[lo] == "+" else (value[0], -value[1])
        if hi - lo != 1:
            return None
        token = self.tokens[lo]
        if token == "undefined":
            return ("undefined", None) if self.is_global("undefined") else None
        if token == "NaN":
            return ("number", math.nan) if self.is_global("NaN") else None
        if token[:1] == "/" or (_WORD.fullmatch(token) and token not in {"true", "false", "null"}):
            return None
        return scalar_literal(token)

    @staticmethod
    def truth(value) -> bool | None:
        if value is None:
            return None
        kind, content = value
        if kind in {"truth", "boolean"}:
            return content
        if kind in {"null", "undefined"}:
            return False
        if kind == "number":
            return not (content == 0 or math.isnan(content))
        if kind == "bigint":
            return content != 0
        return content != ""


def _compare(operator: str, left, right) -> bool | None:
    """`===`, `!==`, and `==`, `!=`, `<`, `<=`, `>`, `>=` between literals of one primitive type."""
    if left[0] == "truth" or right[0] == "truth":
        return None
    if operator in {"===", "!=="}:
        same = left[0] == right[0] and left[1] == right[1]
        return same if operator == "===" else not same
    if left[0] != right[0]:
        return None  # a coercion this folder does not evaluate
    if operator in {"==", "!="}:
        return (left[1] == right[1]) == (operator == "==")
    kind = left[0]
    if kind not in {"number", "bigint", "string", "boolean"}:
        return None
    a, b = left[1], right[1]
    if kind == "number" and (math.isnan(a) or math.isnan(b)):
        return False
    if kind == "string":
        # JavaScript orders strings by UTF-16 code units.
        a, b = a.encode("utf-16-be", "surrogatepass"), b.encode("utf-16-be", "surrogatepass")
    return {"<": a < b, "<=": a <= b, ">": a > b, ">=": a >= b}[operator]


def fold_condition(source: str, is_global: Callable[[str], bool]) -> bool | None:
    """The truthiness of a condition this folder can decide, else None (#429 Q5).

    Exact and literal-only: literals, `!`, parentheses, `&&` and `||` read as
    Python's `_static_truth` reads `and` and `or` (one false conjunct
    decides an `&&`, one true disjunct an `||`, whatever the others are),
    `===` and `!==` between literals, the other comparisons between literals
    of one primitive type, and `undefined` and `NaN` only where `is_global`
    says the name is the unshadowed global. Anything else is unknown: a
    name, a call, arithmetic, `??`, `?:`, a `const` binding (a residual).
    `_truth()` in `frontend.py` keeps reading liveness options.
    """
    if len(source) > 4096:
        return None
    tokens = operand_tokens(source)
    if not tokens:
        return None
    folder = _Folder(tokens, is_global)
    if not folder.balanced:
        return None
    return folder.truth(folder.expression(0, len(tokens)))


# --- Q1, Q3: the statement walker ------------------------------------------------------------

def _misread_run(text: str, start: int, end: int, before: str, dotted: bool) -> bool:
    """Does the mask misread this run of literals and comments?

    It ends a template at the next backtick, where one nested in a
    substitution may stand: each template is read again as the operand
    reader reads it, its substitutions nested. And it may read a division as
    a regular expression, hiding code: one is trusted only after a token
    after which JavaScript cannot divide (`before`, the token before the run;
    `dotted` when a `.` comes before that). (A U+2028 or U+2029, which ends a
    `//` comment the mask runs on to a line feed, refuses the whole callback
    before this.)
    """
    last = before if before in _REGEX_AFTER or (before in _REGEX_AFTER_WORDS and not dotted) else "?)"
    index = start
    while index < end:
        char = text[index]
        if char == "`":
            shallow = index + 1
            while shallow < len(text) and text[shallow] != "`":
                shallow += 2 if text[shallow] == "\\" else 1
            if _template_end(text, index) != shallow + 1:
                return True  # a template nested in a substitution, or one the reader leaves unread
            index, last = shallow + 1, char
        elif char in "'\"":
            index, last = _string_end(text, index) or index + 1, char
        elif text.startswith("/*", index):
            closing = text.find("*/", index + 2)
            index = end if closing < 0 else closing + 2
        elif text.startswith("//", index):
            newline = text.find("\n", index + 2)
            index = end if newline < 0 else newline + 1
        elif char == "/":
            if last not in _REGEX_AFTER and last not in _REGEX_AFTER_WORDS:
                return True  # after an operand JavaScript may read this `/` as a division
            regex = _REGEX_LITERAL.match(text, index)
            index, last = index + 1 if regex is None else regex.end(), char
        else:
            index += 1
    return False


class Reachability:
    """The spans of each test callback in one file that never run, read on demand."""

    def __init__(self, bindings: Bindings, code: bytearray):
        self.bindings = bindings
        self.code = code
        self.tokens = bindings.tokens
        self.pairs = bindings.pairs
        # Pair every bracket again rather than trust the binder's recovery.
        unpaired: list[int] = []
        stack: list[int] = []
        for index, (token, _start, _end) in enumerate(self.tokens):
            if token in _BRACKETS:
                stack.append(index)
            elif token in _CLOSERS:
                if not stack:
                    unpaired.append(index)
                    continue
                opening = stack.pop()
                if _BRACKETS[self.tokens[opening][0]] != token or self.pairs.get(opening) != index:
                    unpaired.extend((opening, index))
        unpaired.extend(stack)
        self.unpaired = sorted(unpaired)
        self.separators = [match.start() for match in
                           re.finditer("[\N{LINE SEPARATOR}\N{PARAGRAPH SEPARATOR}]", bindings.text)]
        self.dead: list[tuple[int, int]] = []
        self.assertions: dict[int, int] = {}
        # Whether each global the folder reads is spelled only as plain reads in the file.
        self.read_only: dict[str, bool] = {}
        # A `\` outside a string is an identifier escape (`return\u0041` is one name),
        # which the binder splits: no callback in the file is walked.
        self.escaped = any(token == "\\" for token, _start, _end in self.tokens)
        self.hoisted = False
        # Where the token stream first misreads the text as code: from there on
        # the mask may read code where JavaScript reads a comment or a string.
        self.desync = self._first_misread()
        # Line breaks where JavaScript may end a statement that `_end` reads on past.
        self.doubtful = 0

    def token(self, index: int) -> str:
        return self.bindings.token(index)

    def unreachable(self, start: int, end: int, assertions: list[tuple[int, int]]) -> list[tuple[int, int]]:
        """Character spans of the block body `start`..`end` that never run; empty when none is proved.

        `assertions` are the unit's assertion spans: a literal-decided
        `&&`/`||` statement drops one only when it ends the statement.
        """
        starts = self.bindings.token_starts
        first = bisect_left(starts, start)
        opening, closing = first - 1, bisect_left(starts, end)
        if (opening < 0 or closing >= len(self.tokens)
                or self.tokens[opening][0] != "{" or self.tokens[opening][2] != start
                or self.tokens[closing][0] != "}" or self.tokens[closing][1] != end
                or self.pairs.get(opening) != closing
                or _within(self.unpaired, opening, closing + 1)
                or (self.separators and self.separators[0] < end)
                or self.escaped
                or (self.desync is not None and self.desync < end)):
            return []  # a misreading anywhere before the callback's end may shift its tokens
        self.dead, self.hoisted = [], False
        self.assertions = dict(assertions)
        self._list(first, closing, 0)
        return [] if self.hoisted else sorted(self.dead)

    def _first_misread(self) -> int | None:
        """Where the token stream first misreads the file's text as code, or None.

        The shared mask ends a template at its first backtick, so a template
        nested in a substitution leaves its text to be read as code; JSX text
        reads as code too, and Annex B's `<!--` and `-->` comments as
        operators. A misreading shifts what the mask reads as code from there
        on, so no callback that ends after it is walked.
        """
        text, code = self.bindings.text, self.code
        found: list[int] = []
        position = 0
        while position < len(text):
            if code[position]:
                position += 1
                continue
            run = position
            while position < len(text) and not code[position]:
                position += 1
            previous = bisect_left(self.bindings.token_starts, run) - 1
            if _misread_run(text, run, position, self.token(previous) if previous >= 0 else "",
                            self.token(previous - 1) in {".", "?.", "#"}):
                found.append(run)
                break
        for index, (token, start, _end) in enumerate(self.tokens):
            following = self.token(index + 1)
            if (not token.isascii() and token[:1] not in "'\""
                    and not (start == 0 and token == "\N{ZERO WIDTH NO-BREAK SPACE}")):
                found.append(start)  # a name or a space the binder does not read: a non-ASCII name, U+FEFF
                break
            adjacent = index + 1 < len(self.tokens) and self.tokens[index][2] == self.tokens[index + 1][1]
            if adjacent and ((token == "<" and following == "!" and self.token(index + 2) == "--")
                             or (token == "--" and following == ">")):
                found.append(start)
                break
            if token == "<" and index > 0 and (self.token(index - 1) == "}" or (
                    not self.bindings._completes(index - 1)
                    and (_NAME.fullmatch(following) or following in {">", "/"}))):
                found.append(start)  # JSX (after a block too), or a TypeScript `<T>` assertion
                break
            if token in {"/", "/="} and index > 0 and (
                    self.token(index - 1) in {"}", "++", "--"} or not self.bindings._completes(index - 1)
                    or self.bindings._line_break(index)):
                found.append(start)  # a regular expression the mask read as a division
                break
        return min(found) if found else None

    def _kill(self, first: int, after: int) -> None:
        """Statements from token `first` up to token `after` never run.

        Where they hold a `function`, a call before them may run its hoisted
        body, which the binder does not always scope (`function f<T>()`): the
        callback is then refused.
        """
        if first < after:
            self.hoisted = self.hoisted or any(self.token(index) == "function" for index in range(first, after))
            self.dead.append((self.tokens[first][1], self.tokens[after - 1][2]))

    def _gap(self, before: int, index: int) -> str:
        return self.bindings.text[self.tokens[before][2]:self.tokens[index][1]]

    def _list(self, first: int, last: int, depth: int) -> bool:
        """Walk the statements from `first` to `last`; does the list end every run of it?"""
        cursor, explicit = first, True  # did the statement before end on a token, not a line break?
        while cursor < last:
            if self.token(cursor) == ";":
                cursor, explicit = cursor + 1, True
                continue
            statement = self._statement(cursor, last, depth, explicit)
            if statement is None:
                return False  # what follows keeps today's reading
            after, terminates = statement
            if after <= cursor or after > last:
                return False
            if terminates:
                self._kill(after, last)
                return True
            closer = self.token(after - 1)
            explicit = closer == ";" or (closer == "}" and self.token(cursor) in _COMPOUND)
            cursor = after
        return False

    def _statement(self, first: int, last: int, depth: int,
                   explicit: bool = True) -> tuple[int, bool] | None:
        """(the index after the statement at `first`, whether it ends the run), or None when unproved.

        `explicit`: the statement before ended on a `;` or its own `}` (or
        there is none), not at a line break, which TypeScript may read past.
        """
        if depth >= _MAX_DEPTH or first >= last:
            return None
        if first > 0 and not _trivia(self._gap(first - 1, first)):
            return None  # a template or regular expression the tokens omit stands before it
        token = self.token(first)
        if token == ";":
            return first + 1, False  # an empty statement, as the body of `if (x);`
        if token == "{":
            closing = self.pairs.get(first)
            if closing is None or closing >= last:
                return None
            return closing + 1, self._list(first + 1, closing, depth + 1)
        if token == "if":
            return self._if(first, last, depth)
        if token in {"while", "for"}:
            return self._loop(first, last, depth)
        if token == "do":
            return self._do(first, last, depth)
        if token == "try":
            return self._try(first, last, depth)
        if token == "switch":
            closing = self.pairs.get(first + 1) if self.token(first + 1) == "(" else None
            body = self.pairs.get(closing + 1) if closing is not None and self.token(closing + 1) == "{" else None
            return (body + 1, False) if body is not None and body < last else None
        if token == "function" or (token == "async" and self.token(first + 1) == "function"
                                   and not self.bindings._line_break(first + 1)):
            return self._function(first, last)
        if token == "class":
            return self._class(first, last)
        if _NAME.fullmatch(token) and self.token(first + 1) == ":" and token not in _UNREAD:
            body = self._statement(first + 2, last, depth + 1)  # a labeled body keeps its end
            return None if body is None else (body[0], False)
        if token in _UNREAD or token in _CLOSERS:
            return None
        mark = self.doubtful
        end = self._end(first, last)
        if end is None:
            return None
        if token in {"return", "throw"}:
            return end, True
        if token not in _JUMPS and explicit and self.doubtful == mark:
            self._literal_decided(first, end)  # on a boundary a token proves, its every line break proved
        return end, False

    def _fold(self, before: int, after: int) -> bool | None:
        """The truth of the condition between tokens `before` and `after`."""
        position = self.tokens[before][2]
        return fold_condition(self._gap(before, after), lambda name: self._global(name, position))

    def _global(self, name: str, position: int) -> bool:
        """Is `name` the unshadowed global at `position`?"""
        if name not in self.read_only:
            self.read_only[name] = self._only_read(name)
        return self.read_only[name] and self.bindings.is_global((name,), position)

    def _only_read(self, name: str) -> bool:
        """Is every spelling of `name` in the file a read this walk can see?

        The binder scopes declarations, but not everything that binds a name:
        a parameter before a TypeScript type, an enum or namespace, a block's
        function that Annex B hoists, `with`, `eval`, a spelling with a `\\u`
        escape, or text the mask hides.
        So each spelling must be a token, right after an operator, `return`,
        `typeof`, `void` or `case`, or first in an `if` or `while` head or a
        call's arguments, and never before `=`, `=>` or a type's `:`.
        """
        text = self.bindings.text
        if self.separators or "\\u" in text or _SCOPE_CHANGERS.search(text):
            return False  # a line separator, a `\u` escape that may spell the name, `with`, `eval`
        if any(token == "with" and self.token(index + 1) == "("
               for index, (token, _start, _end) in enumerate(self.tokens)):
            return False  # `with /* scope */ (`: the mask blanks the comment
        visible = {start: index for index, (token, start, _end) in enumerate(self.tokens) if token == name}
        for match in re.finditer(r"(?<![\w$])" + name + r"(?![\w$])", text):
            index = visible.get(match.start())
            if index is None:
                return False  # in a string, comment, template or regular expression, or hidden
            before, after = self.token(index - 1), self.token(index + 1)
            if after in {"=", "=>"} or (after == ":" and before not in {"?", "case"}):
                return False
            if before in _READ_AFTER:
                continue
            if before == "(":
                head, closing = self.token(index - 2), self.pairs.get(index - 1)
                if head in {"if", "while"}:
                    continue
                if (closing is not None and (_NAME.fullmatch(head) or head in {")", "]"})
                        and head not in _NOT_CALLS and self.token(index - 3) not in {"function", "*"}
                        and self.token(closing + 1) not in {"{", "=>", ":"}):
                    continue  # a call's first argument
            return False
        return True

    def _if(self, first: int, last: int, depth: int) -> tuple[int, bool] | None:
        head = first + 1
        closing = self.pairs.get(head) if self.token(head) == "(" else None
        if closing is None or closing >= last:
            return None
        truth = self._fold(head, closing)
        mark = self.doubtful
        yes = self._statement(closing + 1, last, depth + 1)
        if yes is None:
            return None
        after, yes_terminates = yes
        # A body that is no block may end at a line break this walk read past;
        # where its end is in doubt it is not killed.
        yes_doubtful = self.doubtful != mark and self.token(closing + 1) != "{"
        no, no_doubtful = None, False
        if after < last and self.token(after) == "else":
            mark = self.doubtful
            no = self._statement(after + 1, last, depth + 1)
            if no is None:
                if truth is False and not yes_doubtful:
                    self._kill(closing + 1, after)
                return None
            no_doubtful = self.doubtful != mark and self.token(after + 1) != "{"
        if truth is False:
            if yes_doubtful:
                return None
            self._kill(closing + 1, after)
            return no if no is not None else (after, False)
        end = no[0] if no is not None else after
        if truth is True:
            if no is not None:
                if no_doubtful:
                    return None
                self._kill(after + 1, end)
            return end, yes_terminates
        return end, False

    def _loop(self, first: int, last: int, depth: int) -> tuple[int, bool] | None:
        head = first + 1
        if self.token(first) == "for" and self.token(head) == "await":
            head += 1
        closing = self.pairs.get(head) if self.token(head) == "(" else None
        if closing is None or closing >= last:
            return None
        truth = None
        if self.token(first) == "while":
            truth = self._fold(head, closing)
        else:
            semicolons = []
            index = head + 1
            while index < closing:
                if self.token(index) == ";":
                    semicolons.append(index)
                index = self.pairs.get(index, index) + 1 if self.token(index) in _BRACKETS else index + 1
            if len(semicolons) == 2:
                # An absent condition is true: `for (;;)` runs its body.
                truth = True if _trivia(self._gap(semicolons[0], semicolons[1])) else self._fold(*semicolons)
            elif semicolons:
                return None
        mark = self.doubtful
        body = self._statement(closing + 1, last, depth + 1)
        if body is None:
            return None
        if truth is False:
            if self.doubtful != mark and self.token(closing + 1) != "{":
                return None  # a body that is no block, whose end is in doubt
            self._kill(closing + 1, body[0])
        return body[0], False

    def _do(self, first: int, last: int, depth: int) -> tuple[int, bool] | None:
        body = self._statement(first + 1, last, depth + 1)
        if body is None:
            return None
        after = body[0]
        closing = self.pairs.get(after + 1) if self.token(after) == "while" and self.token(after + 1) == "(" else None
        if closing is None or closing >= last:
            return None
        end = closing + 1
        return (end + 1 if end < last and self.token(end) == ";" else end), False

    def _try(self, first: int, last: int, depth: int) -> tuple[int, bool] | None:
        blocks: list[tuple[int, int]] = []
        cursor = first + 1
        for word in ("try", "catch", "finally"):
            if word != "try":
                if self.token(cursor) != word:
                    continue
                cursor += 1
                if word == "catch" and self.token(cursor) == "(":
                    parameters = self.pairs.get(cursor)
                    if parameters is None:
                        return None
                    cursor = parameters + 1
            closing = self.pairs.get(cursor) if self.token(cursor) == "{" else None
            if closing is None or closing >= last:
                return None
            blocks.append((cursor, closing))
            cursor = closing + 1
        if len(blocks) < 2:
            return None
        for opening, closing in blocks:
            self._list(opening + 1, closing, depth + 1)
        return cursor, False

    def _function(self, first: int, last: int) -> tuple[int, bool] | None:
        """A function declaration, whose body runs only when it is called."""
        cursor = first + (2 if self.token(first) == "async" else 1)
        if self.token(cursor) == "*":
            cursor += 1
        if _NAME.fullmatch(self.token(cursor)):
            cursor += 1
        closing = self.pairs.get(cursor) if self.token(cursor) == "(" else None
        if closing is None or self.token(closing + 1) != "{":
            return None  # a TypeScript return type or an overload
        body = self.pairs.get(closing + 1)
        return (body + 1, False) if body is not None and body < last else None

    def _class(self, first: int, last: int) -> tuple[int, bool] | None:
        cursor = first + 1
        while cursor < last and self.token(cursor) != "{":
            if self.token(cursor) in {"(", "["}:
                closing = self.pairs.get(cursor)
                if closing is None:
                    return None
                cursor = closing + 1
            elif self.token(cursor) in {";", "}", ")", "]", "class", "function", "=>"}:
                return None  # a heritage holding a class or function: its `{` is not the body
            else:
                cursor += 1
        body = self.pairs.get(cursor) if cursor < last else None
        return (body + 1, False) if body is not None and body < last else None

    def _end(self, first: int, last: int) -> int | None:
        """The index after the simple statement at `first`, with an explicit unknown.

        The shared ASI reading (a line break where the token before completes
        an operand and the one after cannot continue it), proved only where
        the text between the two tokens is whitespace and comments: a
        template or regular expression there is an operand the tokens omit.
        `return`, `throw`, `break` and `continue` end at a line break right
        after the word.
        """
        bindings = self.bindings
        keyword = self.token(first)
        if keyword in _JUMPS:
            if first + 1 >= last:
                return last if _trivia(self._gap(first, last)) else None
            if not _trivia(self._gap(first, first + 1)):
                return None
            if bindings._line_break(first + 1):
                return first + 1
            if self.token(first + 1) == ";":
                return first + 2
            if keyword in {"break", "continue"}:
                if not _NAME.fullmatch(self.token(first + 1)):
                    return None
                label = first + 2
                if label >= last:
                    return last if _trivia(self._gap(first + 1, last)) else None
                if self.token(label) == ";" and _trivia(self._gap(first + 1, label)):
                    return label + 1
                if bindings._line_break(label) and _trivia(self._gap(first + 1, label)):
                    return label
                return None
        cursor = first
        while cursor < last:
            if cursor > first and bindings._line_break(cursor):
                if not _trivia(self._gap(cursor - 1, cursor)):
                    return None
                completes = bindings._completes(cursor - 1)
                if self.token(cursor - 1) in {"++", "--"} and (
                        cursor - 1 == first or bindings._line_break(cursor - 1)
                        or not bindings._completes(cursor - 2)):
                    completes = False  # a prefix update: its operand is on the next line
                if not completes and self.token(cursor) in _STATEMENT_KEYWORDS:
                    return None  # `x!` then `do ...`: TypeScript ends the statement where the binder reads on
                if (completes and not bindings._continues(cursor)
                        and self.token(cursor) not in {"extends", "implements"}):
                    # A `return` or `throw` ended here would cut what follows, but
                    # TypeScript types, class heritage and decorators may go on past
                    # this line break (`as readonly` then `string[]`): not proved.
                    return None if keyword in _JUMPS else cursor
                # Unless an operator leaves the expression unfinished, JavaScript or
                # TypeScript may end the statement here (`x = 1` then `.5`,
                # `x = load() as T` then `[1]`, `x!` then `{`); this reads on.
                if self.token(cursor - 1) not in _UNFINISHED or self.token(cursor - 2) in {".", "?.", "#"}:
                    self.doubtful += 1
            token = self.token(cursor)
            if (cursor > first and token in _STATEMENT_KEYWORDS
                    and self.token(cursor - 1) not in {".", "?.", "#", "as"}):
                return None  # a statement keyword inside the statement: its end was read past
            if token == ";":
                if cursor == first or not (bindings._completes(cursor - 1)
                                           or not _trivia(self._gap(cursor - 1, cursor))):
                    return None
                return cursor + 1
            if token in _BRACKETS:
                closing = self.pairs.get(cursor)
                if closing is None or closing >= last:
                    return None
                cursor = closing + 1
            elif token in _CLOSERS:
                return None
            else:
                cursor += 1
        if bindings._completes(last - 1) or not _trivia(self._gap(last - 1, last)):
            return last
        return None

    def _literal_decided(self, first: int, end: int) -> None:
        """Q3: `false && expect(...)` or `true || expect(...)`, as one expression statement.

        The statement starts on a boundary this walk proved, so its literal
        cannot continue the line before; the assertion is the last operand of
        the last top-level `&&` or `||` and runs to the statement's end; and
        what comes before that operator folds to the value that skips it.
        Ternary, `??` and comma forms are residuals.
        """
        stop = end - 1 if self.token(end - 1) == ";" else end
        operators = []
        index = first
        while index < stop:
            token = self.token(index)
            # The binder spells `&&` and `||` as two adjacent `&` or `|` tokens.
            if (token in {"&", "|"} and index + 1 < stop and self.token(index + 1) == token
                    and self.tokens[index][2] == self.tokens[index + 1][1]):
                operators.append(index)
                index += 2
                continue
            index = self.pairs.get(index, index) + 1 if token in _BRACKETS else index + 1
        if not operators or operators[-1] + 2 >= stop:
            return
        operator = operators[-1]
        start_char, end_char = self.tokens[operator + 2][1], self.tokens[stop - 1][2]
        if self.assertions.get(start_char) != end_char:
            return
        if stop < end and not _trivia(self._gap(stop - 1, stop)):
            return  # an operand the tokens omit continues the statement
        before = first - 1
        source = self.bindings.text[self.tokens[before][2]:self.tokens[operator][1]] if before >= 0 else ""
        position = self.tokens[first][1]
        truth = fold_condition(source, lambda name: self._global(name, position))
        if truth is (self.token(operator) == "|"):
            self.dead.append((start_char, end_char))
