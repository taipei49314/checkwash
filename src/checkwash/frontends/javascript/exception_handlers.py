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
from checkwash.frontends.javascript.literals import keyword_operand
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
# Handler evidence texts (#431). A catch that reaches no assertion keeps the
# v0.7.0 text exactly. A catch whose reachable assertions are all proved to
# always pass gets its own text, so a pre-existing literal-only catch can never
# offset a newly added swallowing catch in the per-file multiset comparison.
SWALLOWED = "catch assertion"
ALWAYS_PASSING = "catch always-passing assertion"


@dataclass(frozen=True)
class Effects:
    oracle: bool = False
    escapes: bool = False
    supported: bool = True
    terminates: bool = False
    failure_oracle: bool = False


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
        # Protected assertions and catch-side failure evidence are different:
        # a constant passing assertion still remains protected in a try body.
        self.failure_oracles: dict[int, list[int]] = {}
        self.unclassified: dict[int, list[int]] = {}
        for assertion in assertions:
            index = bisect_left(bindings.token_starts, assertion.span[0])
            if index < len(self.tokens) and self.tokens[index][1] == assertion.span[0]:
                synchronous = self.synchronous(index, assertion.span[1])
                if synchronous is None:
                    self.unclassified.setdefault(self.owner(index), []).append(index)
                elif synchronous:
                    self.oracles.setdefault(self.owner(index), []).append(index)
                    if not self.passing_literal(assertion, index):
                        self.failure_oracles.setdefault(self.owner(index), []).append(index)
        for indices in self.oracles.values():
            indices.sort()
        for indices in self.failure_oracles.values():
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
        self.found: dict[int, str] = {}

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

    def literal_call(self, opening: int, arity: int, end_position: int) -> int | None:
        """A complete call containing only direct boolean/null operands.

        No extra message arguments or computed expressions are discarded:
        their evaluation may fail even when the represented predicate passes.
        The caller bounds the whole assertion to 4096 source characters.
        """
        closing = self.pairs.get(opening)
        if (self.token(opening) != "(" or closing is None
                or self.tokens[closing][2] > end_position):
            return None
        first = cursor = opening + 1
        count = 0
        while cursor <= closing:
            if cursor == closing or self.token(cursor) == ",":
                if first == cursor:
                    return closing if cursor == opening + 1 and arity == 0 else None
                # The shared literal reader also peels TypeScript wrappers.
                # A new always-pass proof needs less: only keywords and
                # parentheses, never an ambiguous type/operator tail.
                if any(self.token(i) not in {"true", "false", "null", "(", ")"}
                       for i in range(first, cursor)):
                    return None
                operand = self.bindings.text[self.tokens[first][1]:self.tokens[cursor - 1][2]]
                if keyword_operand(operand) not in {"true", "false", "null"}:
                    return None
                count += 1
                if count > arity:
                    return None
                first = cursor + 1
            elif self.token(cursor) in {"(", "[", "{"}:
                after = self.pairs.get(cursor)
                if after is None or after >= closing:
                    return None
                cursor = after
            cursor += 1
        return closing if count == arity else None

    def passing_literal(self, assertion: Assertion, first: int) -> bool:
        """A narrow proof, not a general JavaScript tautology evaluator.

        Reuse the frontend's resolved API, predicate and polarity. Only true,
        false and null subjects are read through the existing literal reader,
        with call tokens additionally restricted to parentheses and keywords;
        names (including undefined), calls, numbers and strings stay unknown.
        A failed/unknown proof retains the existing active-catch exemption.
        """
        if assertion.span[1] - assertion.span[0] > 4096:
            return False
        subject = keyword_operand(assertion.left or "")
        if subject not in {"true", "false", "null"}:
            return False
        predicates = {
            "is_true": subject == "true", "is_false": subject == "false",
            "is_null": subject == "null", "is_nullish": subject == "null",
            "is_undefined": False, "truthy": subject == "true",
        }
        if (assertion.predicate not in predicates
                or predicates[assertion.predicate] != assertion.positive):
            return False
        path = [self.token(first)]
        cursor = first + 1
        while (step := self.member(cursor)) is not None:
            name, cursor = step
            path.append(name)
        value = self.bindings.callee(".".join(path), self.tokens[first][1])
        if value.kind in {"expect", "jest_expect"}:
            subject_end = self.literal_call(cursor, 1, assertion.span[1])
            if subject_end is None:
                return False
            step = self.member(subject_end + 1)
            if step is not None and step[0] == "not":
                step = self.member(step[1])
            if step is None:
                return False
            matcher, opening = step
            arity = {"toBe": 1, "toBeTruthy": 0, "toBeFalsy": 0,
                     "toBeNull": 0, "toBeUndefined": 0, "toBeDefined": 0}.get(matcher)
        elif value.kind in {"node", "node_method"}:
            method = "strictEqual" if value.strict and value.method == "equal" else value.method
            arity = {"": 1, "ok": 1, "strictEqual": 2}.get(method)
            opening = cursor
        elif value.kind in {"chai_assert", "chai_assert_method"}:
            arity = {"": 1, "ok": 1, "isOk": 1, "isTrue": 1, "isFalse": 1,
                     "isNull": 1, "isUndefined": 1, "isDefined": 1, "exists": 1,
                     "strictEqual": 2}.get(value.method)
            opening = cursor
        else:
            return False
        closing = self.literal_call(opening, arity, assertion.span[1]) if arity is not None else None
        return closing is not None and self.tokens[closing][2] == assertion.span[1]

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
                    and not caught.escapes):
                # `failure_oracles` is a subset of `oracles`, so the first
                # text is exactly the v0.7.0 set and the second is disjoint.
                if not caught.oracle:
                    self.found[first] = SWALLOWED
                elif not caught.failure_oracle:
                    self.found[first] = ALWAYS_PASSING
            # Nested candidates inherit direct-terminal/literal-branch
            # reachability. Their effects cannot donate safety to this try.
            self.flow(opening + 1, closing, owner, depth + 1, True)
            self.flow(catch_opening + 1, catch_closing, owner, depth + 1, True)
            return Effects(supported=False, terminates=guarded.terminates and caught.terminates), after
        if keyword in {"try", "for", "while", "do", "switch", "with"}:
            return Effects(supported=False), last
        end = self.statement_end(first, last)
        oracle = self.contains(self.oracles.get(owner, []), first, end)
        failure_oracle = self.contains(self.failure_oracles.get(owner, []), first, end)
        optional = self.contains(self.optional.get(owner, []), first, end)
        unknown = self.contains(self.unclassified.get(owner, []), first, end)
        return Effects(oracle, keyword == "throw", not optional and not unknown,
                       keyword in {"throw", "return", "break", "continue"}, failure_oracle), end

    def flow(self, first: int, last: int, owner: int, depth: int = 0,
             collect: bool = False) -> Effects:
        if depth >= _MAX_DEPTH:
            return Effects(supported=False)
        key = (first, last, owner, depth)
        if not collect and key in self.cache:
            return self.cache[key]
        cursor = first
        oracle = escapes = terminates = False
        failure_oracle = False
        supported = True
        while cursor < last:
            if self.token(cursor) == ";":
                cursor += 1
                continue
            effect, after = self.statement(cursor, last, owner, depth, collect)
            oracle |= effect.oracle
            failure_oracle |= effect.failure_oracle
            escapes |= effect.escapes
            supported &= effect.supported
            if effect.terminates:
                terminates = True
                break
            if after <= cursor:
                supported = False
                break
            cursor = after
        result = Effects(oracle, escapes, supported, terminates, failure_oracle)
        if not collect:
            self.cache[key] = result
        return result

    def handlers(self) -> tuple[str, ...]:
        for first, last, owner in self.roots:
            self.flow(first, last, owner, collect=True)
        # Stable multiset events preserve formatting/binding respelling. An
        # equal-count exchange of swallowing locations is a named residual.
        return tuple(self.found[index] for index in sorted(self.found))


def swallowing_handlers(bindings: Bindings, assertions: list[Assertion]) -> tuple[str, ...]:
    if not assertions or not any(token == "try" for token, _start, _end in bindings.tokens):
        return ()
    return HandlerReader(bindings, assertions).handlers()
