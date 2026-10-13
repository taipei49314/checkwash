"""A direct return cutoff inside a proved block callback, without a CFG.

Unknown compound statements and malformed boundaries supply no cutoff. This
reader is built once per file; it does not construct a HandlerReader per unit.
"""

from __future__ import annotations

import re
from bisect import bisect_left

from checkwash.frontends.javascript.bindings import NAME, Bindings

_PAIRS = {"(": ")", "[": "]", "{": "}"}
_COMPOUND = frozenset({
    "if", "else", "for", "while", "do", "switch", "case", "default", "try", "catch",
    "finally", "with", "function", "class", "throw", "break", "continue", "yield",
    "export", "import", "{",
})


def _trivia_only(text: str) -> bool:
    """Recognize a gap without regex backtracking or omitted literal credit."""
    cursor = 0
    while cursor < len(text):
        if text[cursor] in " \t\n\v\f\ufeff":
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


class DirectReturns:
    def __init__(self, bindings: Bindings, code: bytearray):
        self.bindings = bindings
        self.code = code
        self.returns: list[int] = []
        invalid: set[int] = set()
        stack: list[int] = []
        # Independently check pairing instead of trusting recovered callback
        # spans or the statement-end helper's ambiguous end-of-body sentinel.
        for index, (token, start, _end) in enumerate(bindings.tokens):
            if token == "return" and code[start]:
                self.returns.append(index)
            if token in _PAIRS:
                stack.append(index)
            elif token in _PAIRS.values():
                if not stack:
                    invalid.add(index)
                    continue
                opening = stack.pop()
                if (_PAIRS[bindings.token(opening)] != token
                        or bindings.pairs.get(opening) != index):
                    invalid.update((opening, index))
        invalid.update(stack)
        self.invalid = sorted(invalid)
        # Do not incidentally change #363's shared LF-only ASI convention.
        self.unsupported_lines = [match.start() for match in re.finditer("[\u2028\u2029]", bindings.text)]

    @staticmethod
    def contains(positions: list[int], first: int, last: int) -> bool:
        index = bisect_left(positions, first)
        return index < len(positions) and positions[index] < last

    def statement_end(self, first: int, last: int) -> int | None:
        """Existing ASI conventions, with an explicit unknown result.

        Whole-body pairing has already been proved. This does not validate
        arbitrary JS grammar; a missing delimiter or incomplete final operand
        must nevertheless never turn the body-end sentinel into proof.
        """
        bindings = self.bindings
        if bindings.token(first) == "return":
            # Bindings omits regex/template operands. A newline inside or
            # after such an operand is not the restricted return/Expression
            # line break. Only a complete trivia-only leading gap is proof;
            # an omitted operand conservatively keeps the old inventory.
            following = bindings.tokens[first + 1][1]
            gap = bindings.text[bindings.tokens[first][2]:following]
            if not _trivia_only(gap):
                return None
        cursor = first
        while cursor < last:
            if cursor > first and bindings._line_break(cursor):
                if bindings.token(first) == "return" and cursor == first + 1:
                    return cursor
                if bindings._completes(cursor - 1) and not bindings._continues(cursor):
                    return cursor
            token = bindings.token(cursor)
            if token == ";":
                if cursor == first + 1 and bindings.token(first) == "return":
                    return cursor + 1
                return cursor + 1 if cursor > first and bindings._completes(cursor - 1) else None
            if token in _PAIRS:
                closing = bindings.pairs.get(cursor)
                if closing is None or closing >= last:
                    return None
                cursor = closing + 1
            elif token in _PAIRS.values():
                return None
            else:
                cursor += 1
        if first + 1 == last and bindings.token(first) == "return":
            return last
        return last if cursor > first and bindings._completes(cursor - 1) else None

    def cutoff(self, start: int, end: int) -> int | None:
        bindings = self.bindings
        first = bisect_left(bindings.token_starts, start)
        opening = first - 1
        closing = bisect_left(bindings.token_starts, end)
        if (opening < 0 or closing >= len(bindings.tokens)
                or bindings.token(opening) != "{" or bindings.tokens[opening][2] != start
                or bindings.token(closing) != "}" or bindings.tokens[closing][1] != end
                or not self.code[bindings.tokens[opening][1]] or not self.code[end]
                or bindings.pairs.get(opening) != closing
                or self.contains(self.invalid, opening, closing + 1)
                or self.contains(self.unsupported_lines, start, end)
                or not self.contains(self.returns, first, closing)):
            return None
        cursor = first
        while cursor < closing:
            keyword = bindings.token(cursor)
            if keyword == ";":
                cursor += 1
                continue
            if (keyword in _COMPOUND
                    or keyword == "async" and bindings.token(cursor + 1) == "function"
                    or re.fullmatch(NAME, keyword) and bindings.token(cursor + 1) == ":"):
                return None
            # Only plain initialized declarations are skipped in this first
            # proof; destructuring, type annotations and declaration grammar
            # beyond this shape keep the original inventory.
            if keyword in {"const", "let", "var"} and not (
                    re.fullmatch(NAME, bindings.token(cursor + 1))
                    and bindings.token(cursor + 2) == "="):
                return None
            after = self.statement_end(cursor, closing)
            if after is None or after <= cursor:
                return None
            if keyword == "return":
                return bindings.tokens[after][1] if after < closing else end
            cursor = after
        return None
