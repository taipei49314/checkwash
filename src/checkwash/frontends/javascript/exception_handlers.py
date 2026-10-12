"""Bounded same-function synchronous try/catch evidence for test oracles.

This reads balanced statements and already resolved assertion spans. Unknown
control flow, promise completion and finally behavior supply no evidence.
The fixed depth bound and owner indexes also apply to unsupported input.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
import re

from checkwash.frontends.javascript.bindings import Bindings
from checkwash.ir.model import Assertion

_MAX_DEPTH = 32
_PROMISE_METHODS = {
    "node_method": {"rejects", "doesNotReject"},
    "ava_method": {"throwsAsync", "notThrowsAsync"},
    "tap_method": {"rejects", "resolves", "resolveMatch", "resolveMatchSnapshot",
                   "emits", "expectUncaughtException"},
    "chai_assert_method": {"isFulfilled", "isRejected", "becomes", "doesNotBecome"},
}
_PROMISE_CHAIN = {"resolves", "rejects", "eventually", "fulfilled", "rejected", "rejectedWith"}
_NAME = re.compile(r"[A-Za-z_$][\w$]*\Z")


@dataclass(frozen=True)
class Effects:
    oracle: bool = False
    escapes: bool = False
    supported: bool = True
    terminates: bool = False


class HandlerReader:
    def __init__(self, bindings: Bindings, assertions: list[Assertion]):
        self.bindings = bindings
        self.tokens = bindings.tokens
        self.pairs = bindings.pairs
        boundaries = {index for index, scope in enumerate(bindings.scopes) if scope.function}
        # A TS return annotation can hide an arrow from the bounded binder.
        for index, (token, _start, _end) in enumerate(self.tokens):
            if token == "=>" and bindings.token(index + 1) == "{":
                scope = bindings.body_scopes.get(index + 1)
                if scope is not None:
                    boundaries.add(scope)
        self.boundaries = boundaries
        function = [0] * len(bindings.scopes)
        for index, scope in enumerate(bindings.scopes):
            function[index] = index if index in boundaries else function[scope.parent or 0]
        self.owners = [function[bindings.scope(start)] for _token, start, _end in self.tokens]
        self.roots = [(0, len(self.tokens), 0)]
        for opening, scope in bindings.body_scopes.items():
            closing = self.pairs.get(opening)
            if scope in boundaries and closing is not None:
                self.roots.append((opening + 1, closing, scope))
        self.oracles: dict[int, list[int]] = {}
        self.unclassified: dict[int, list[int]] = {}
        for assertion in assertions:
            index = bisect_left(bindings.token_starts, assertion.span[0])
            if index < len(self.tokens) and self.tokens[index][1] == assertion.span[0]:
                synchronous = self.synchronous(index, assertion.span[1])
                if synchronous is None:
                    self.unclassified.setdefault(self.owner(index), []).append(index)
                elif synchronous:
                    self.oracles.setdefault(self.owner(index), []).append(index)
        for indices in self.oracles.values():
            indices.sort()
        for indices in self.unclassified.values():
            indices.sort()
        # Index only each owner's tokens. Outer callback statements never
        # scan all descendant bodies again; arguments are not method chains.
        self.optional: dict[int, list[int]] = {}
        for index, (token, _start, _end) in enumerate(self.tokens):
            if (token in {"?", "?.", "await"}
                    or (token in {"&", "|"} and self.token(index + 1) == token)):
                self.optional.setdefault(self.owner(index), []).append(index)
        self.cache: dict[tuple[int, int, int, int], Effects] = {}
        self.found: set[int] = set()

    def owner(self, index: int) -> int:
        return self.owners[index]

    def token(self, index: int) -> str:
        return self.bindings.token(index)

    def member(self, index: int) -> tuple[str, int] | None:
        if self.token(index) in {".", "?."} and _NAME.fullmatch(self.token(index + 1)):
            return self.token(index + 1), index + 2
        if (self.token(index) == "[" and self.pairs.get(index) == index + 2
                and self.token(index + 1)[:1] in {"'", '"'}):
            name = self.token(index + 1)[1:-1]
            if _NAME.fullmatch(name):
                return name, index + 3
        return None

    def chain_synchronous(self, cursor: int, end_position: int) -> bool:
        while cursor < len(self.tokens) and self.tokens[cursor][1] < end_position:
            step = self.member(cursor)
            if step is None:
                break
            name, cursor = step
            if name in _PROMISE_CHAIN:
                return False
            if self.token(cursor) == "(":
                closing = self.pairs.get(cursor)
                if closing is None:
                    return False
                cursor = closing + 1
        return True

    def synchronous(self, first: int, end_position: int) -> bool | None:
        """Classify the resolved API and its chain, never its argument text."""
        # Represented should getters can have indexed, parenthesized, literal
        # or new subjects and property matchers with no call at all. Find the
        # chain anchor outside balanced subject/argument expressions.
        cursor = first
        while cursor < len(self.tokens) and self.tokens[cursor][1] < end_position:
            if (self.token(cursor) == "should" and self.token(cursor - 1) in {".", "?."}
                    and self.member(cursor + 1) is not None):
                return self.chain_synchronous(cursor + 1, end_position)
            if self.token(cursor) in {"(", "[", "{"} and cursor in self.pairs:
                cursor = self.pairs[cursor] + 1
            else:
                cursor += 1
        path = [self.token(first)]
        cursor = first + 1
        while (step := self.member(cursor)) is not None:
            name, cursor = step
            path.append(name)
        if self.token(cursor) != "(" or cursor not in self.pairs:
            return None
        value = self.bindings.callee(".".join(path), self.tokens[first][1])
        if value.method in _PROMISE_METHODS.get(value.kind, set()):
            return False
        if (value.kind == "chai_should_method" and value.method in _PROMISE_CHAIN
                or self.bindings.callee(path[0], self.tokens[first][1]).kind == "chai_should"
                and any(name in _PROMISE_CHAIN for name in path[1:])):
            return False
        cursor = self.pairs[cursor] + 1
        return self.chain_synchronous(cursor, end_position)

    @staticmethod
    def contains(indices: list[int], first: int, last: int) -> bool:
        index = bisect_left(indices, first)
        return index < len(indices) and indices[index] < last

    def statement_end(self, first: int, last: int) -> int:
        cursor = first
        while cursor < last:
            if cursor > first and self.bindings._line_break(cursor):
                if self.token(first) in {"return", "throw", "break", "continue"} and cursor == first + 1:
                    return cursor
                if self.bindings._completes(cursor - 1) and not self.bindings._continues(cursor):
                    return cursor
            if self.token(cursor) == ";":
                return cursor + 1
            if self.token(cursor) in {"(", "[", "{"}:
                closing = self.pairs.get(cursor)
                if closing is None or closing >= last:
                    return last
                cursor = closing + 1
            else:
                cursor += 1
        return last

    def declaration_end(self, first: int, last: int) -> int:
        cursor = first + 1
        while cursor < last:
            if self.token(cursor) == "{":
                closing = self.pairs.get(cursor)
                return closing + 1 if closing is not None and closing < last else last
            if self.token(cursor) in {"(", "["} and cursor in self.pairs:
                closing = self.pairs[cursor]
                if self.token(cursor) == "(" and self.token(closing + 1) == ":":
                    # The binder's first-brace rule cannot distinguish a TS
                    # object return type from its body. Stop the entire flow;
                    # the unused body must never become parent-owned effects.
                    return last
                cursor = closing + 1
            else:
                cursor += 1
        return last

    def skip(self, first: int, last: int, depth: int) -> int:
        """Skip an inactive branch without evaluating any of its effects."""
        if depth >= _MAX_DEPTH or first >= last:
            return last
        if self.token(first) == "{":
            closing = self.pairs.get(first)
            return closing + 1 if closing is not None and closing < last else last
        if self.token(first) == "if":
            closing = self.pairs.get(first + 1)
            if self.token(first + 1) != "(" or closing is None:
                return last
            after = self.skip(closing + 1, last, depth + 1)
            return self.skip(after + 1, last, depth + 1) if self.token(after) == "else" else after
        if self.token(first) in {"function", "class"} or (
                self.token(first) == "async" and self.token(first + 1) == "function"):
            return self.declaration_end(first, last)
        return self.statement_end(first, last)

    def try_parts(self, first: int, last: int) -> tuple[int, int, int, int, int] | None:
        opening = first + 1
        closing = self.pairs.get(opening)
        if self.token(opening) != "{" or closing is None or self.token(closing + 1) != "catch":
            return None
        catch_opening = closing + 2
        if self.token(catch_opening) == "(":
            parameters_end = self.pairs.get(catch_opening)
            if parameters_end is None:
                return None
            catch_opening = parameters_end + 1
        catch_closing = self.pairs.get(catch_opening)
        if self.token(catch_opening) != "{" or catch_closing is None or catch_closing >= last:
            return None
        after = catch_closing + 1
        if self.token(after) == "finally":
            return None
        return opening, closing, catch_opening, catch_closing, after

    def statement(self, first: int, last: int, owner: int, depth: int,
                  collect: bool) -> tuple[Effects, int]:
        if depth >= _MAX_DEPTH:
            return Effects(supported=False), last
        keyword = self.token(first)
        if _NAME.fullmatch(keyword) and self.token(first + 1) == ":":
            return Effects(supported=False), last
        if keyword == "{":
            closing = self.pairs.get(first)
            if closing is None or closing >= last:
                return Effects(supported=False), last
            if first + 1 < closing and self.owner(first + 1) != owner:
                return Effects(), closing + 1
            return self.flow(first + 1, closing, owner, depth + 1, collect), closing + 1
        if keyword == "if":
            opening = first + 1
            closing = self.pairs.get(opening)
            if self.token(opening) != "(" or closing is None or closing >= last:
                return Effects(supported=False), last
            yes_first = closing + 1
            yes_after = self.skip(yes_first, last, depth + 1)
            no_first = yes_after + 1 if self.token(yes_after) == "else" else yes_after
            after = self.skip(no_first, last, depth + 1) if no_first != yes_after else yes_after
            condition = [self.token(i) for i in range(opening + 1, closing)]
            if condition == ["true"]:
                effect, _end = self.statement(yes_first, yes_after, owner, depth + 1, collect)
                return effect, after
            if condition == ["false"]:
                if no_first == yes_after:
                    return Effects(), after
                effect, _end = self.statement(no_first, after, owner, depth + 1, collect)
                return effect, after
            return Effects(supported=False), after
        if keyword in {"function", "class"} or (keyword == "async" and self.token(first + 1) == "function"):
            end = self.declaration_end(first, last)
            # Class evaluation can execute static blocks/initializers. A TS
            # return-type brace is not a proved function declaration body.
            opening = self.pairs.get(end - 1)
            supported = (keyword != "class" and end < last and opening is not None
                         and self.bindings.body_scopes.get(opening) in self.boundaries)
            return Effects(supported=supported), end
        if keyword == "try" and collect:
            parts = self.try_parts(first, last)
            if parts is None:
                return Effects(supported=False), last
            opening, closing, catch_opening, catch_closing, after = parts
            guarded = self.flow(opening + 1, closing, owner, depth + 1)
            caught = self.flow(catch_opening + 1, catch_closing, owner, depth + 1)
            if (guarded.supported and caught.supported and guarded.oracle
                    and not caught.oracle and not caught.escapes):
                self.found.add(first)
            # Nested candidates inherit direct-terminal/literal-branch
            # reachability. Their effects cannot donate safety to this try.
            self.flow(opening + 1, closing, owner, depth + 1, True)
            self.flow(catch_opening + 1, catch_closing, owner, depth + 1, True)
            return Effects(supported=False, terminates=guarded.terminates and caught.terminates), after
        if keyword in {"try", "for", "while", "do", "switch", "with"}:
            return Effects(supported=False), last
        end = self.statement_end(first, last)
        oracle = self.contains(self.oracles.get(owner, []), first, end)
        optional = self.contains(self.optional.get(owner, []), first, end)
        unknown = self.contains(self.unclassified.get(owner, []), first, end)
        return Effects(oracle, keyword == "throw", not optional and not unknown,
                       keyword in {"throw", "return", "break", "continue"}), end

    def flow(self, first: int, last: int, owner: int, depth: int = 0,
             collect: bool = False) -> Effects:
        if depth >= _MAX_DEPTH:
            return Effects(supported=False)
        key = (first, last, owner, depth)
        if not collect and key in self.cache:
            return self.cache[key]
        cursor = first
        oracle = escapes = terminates = False
        supported = True
        while cursor < last:
            if self.token(cursor) == ";":
                cursor += 1
                continue
            effect, after = self.statement(cursor, last, owner, depth, collect)
            oracle |= effect.oracle
            escapes |= effect.escapes
            supported &= effect.supported
            if effect.terminates:
                terminates = True
                break
            if after <= cursor:
                supported = False
                break
            cursor = after
        result = Effects(oracle, escapes, supported, terminates)
        if not collect:
            self.cache[key] = result
        return result

    def handlers(self) -> tuple[str, ...]:
        for first, last, owner in self.roots:
            self.flow(first, last, owner, collect=True)
        # Stable multiset events preserve formatting/binding respelling. An
        # equal-count exchange of swallowing locations is a named residual.
        return tuple("catch assertion" for _index in sorted(self.found))


def swallowing_handlers(bindings: Bindings, assertions: list[Assertion]) -> tuple[str, ...]:
    if not assertions or not any(token == "try" for token, _start, _end in bindings.tokens):
        return ()
    return HandlerReader(bindings, assertions).handlers()
