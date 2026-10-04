"""Predicate identity of an assertion, and how two of them relate (#198).

The strength lattice orders forms. It cannot tell `toBeNull()` from
`.to.exist` (both NON_NULL), or `toBeLessThan(80)` from `.to.be.above(80)`
(both BOUND). A frontend that knows which predicate an assertion states
records it in `Assertion.predicate` as one canonical key, and `positive`
says whether the assertion asserts that predicate or its negation:
`toBeDefined()` is `is_undefined` asserted negatively, and so is
`.not.toBeUndefined()`.

`relation` compares two keyed assertions on the same subject from key and
polarity. It never reports an operand change: a rewritten expected value
belongs to EXPECTED_VALUE_CHANGED and a widened tolerance to
TOLERANCE_LOOSENED (one fact, one owner). It reads operands for three things
the keys cannot say. An `===` literal is placed among the presence keys,
because that literal is the predicate: `toBe(5)` is defined, not null and
truthy. When both sides state their expected value as a literal of the same
equality and polarity, the change is that literal's, so the pair compares as
the equality it spells. And two bounds are compared value by value only
when they name the same bound (`_same_bound`).

The keys come in three families: presence (null, undefined, truthiness),
equality and bounds. Keys of two families do not relate by key alone, except
through an `===` literal, so `relation` abstains (None) and the lattice rules
judge the pair as they judge an unkeyed one. Between `<` and `<=` (or `>` and
`>=`) only the bound decides: with one bound on both sides, `< 80` -> `<= 80`
is a widening; with two bounds, or one that was not read, the pair abstains.
A bound whose direction reversed contradicts the old one, except where the
hand-rolled truthy spelling `assert.ok(Math.abs(d) > bound)` left a bound
unread: that replacement cannot be verified (#196 189.3).

Only the JavaScript frontend records keys in this round. The Python
direction key is its own round (196.followup.python-compare-direction).
"""

from __future__ import annotations

import ast
from decimal import Decimal

from checkwash.frontends.javascript.literals import operand_text
from checkwash.ir.model import Assertion, normalize_text

# The relation of a new assertion to the old one on the same subject.
SAME = "same"  # both accept exactly the same values
STRONGER = "stronger"  # the new one accepts a strict subset
WIDENED = "widened"  # the new one accepts a strict superset
OPPOSITE = "opposite"  # the same key with its polarity flipped
CONTRADICTS = "contradicts"  # no value passes both, or a bound changed direction
UNVERIFIABLE = "unverifiable"  # anything the keys cannot establish

# value === null, === undefined, == null, truthy, === true, === false.
PRESENCE = frozenset({"is_null", "is_undefined", "is_nullish", "truthy", "is_true", "is_false"})
# value === expected, value == expected: the operand is never compared here.
EQUALITY = frozenset({"eq_strict", "eq_loose"})
# value < bound, <= bound, > bound, >= bound, for one bound.
BOUNDS = frozenset({"lt", "le", "gt", "ge"})
KEYS = PRESENCE | EQUALITY | BOUNDS

# What each key asserts, and what its negation asserts, for messages.
_SPELLING = {
    "is_null": ("=== null", "!== null"),
    "is_undefined": ("=== undefined", "!== undefined"),
    "is_nullish": ("== null", "!= null"),
    "truthy": ("truthy", "falsy"),
    "is_true": ("=== true", "!== true"),
    "is_false": ("=== false", "!== false"),
    "eq_strict": ("=== expected", "!== expected"),
    "eq_loose": ("== expected", "!= expected"),
    "lt": ("< bound", "not < bound"),
    "le": ("<= bound", "not <= bound"),
    "gt": ("> bound", "not > bound"),
    "ge": (">= bound", "not >= bound"),
}

# The value space each family partitions. Presence: null, undefined, true,
# false, every other falsy value (0, -0, 0n, "", NaN) and every other truthy
# one, plus the literal an `===` side names when one is compared with a
# presence key. Equality, for one expected value: strictly equal, loosely but
# not strictly equal, unequal.
_PRESENCE_UNIVERSE = frozenset({"null", "undefined", "true", "false", "falsy", "truthy"})
_PRESENCE_MEMBERS = {
    "is_null": frozenset({"null"}),
    "is_undefined": frozenset({"undefined"}),
    "is_nullish": frozenset({"null", "undefined"}),
    "truthy": frozenset({"true", "truthy"}),
    "is_true": frozenset({"true"}),
    "is_false": frozenset({"false"}),
}
_EQUALITY_UNIVERSE = frozenset({"strict", "loose", "unequal"})
_EQUALITY_MEMBERS = {"eq_strict": frozenset({"strict"}), "eq_loose": frozenset({"strict", "loose"})}
# Keys whose literal spelling is one equality: `.to.be.null` is
# `.to.equal(null)`, `toBe(true)` is `=== true`, `assert.equal(x, null)` is
# `== null`.
_STRICT_LITERAL = frozenset({"eq_strict", "is_null", "is_undefined", "is_true", "is_false"})
_LOOSE_LITERAL = frozenset({"eq_loose", "is_nullish"})


def describe(assertion: Assertion) -> str:
    """What a keyed assertion asserts, for messages: `=== null`, `falsy`, `< 0.01`."""
    key = assertion.predicate or ""
    spelling = _SPELLING.get(key)
    if spelling is None:
        return key if assertion.positive else f"not {key}"
    text = spelling[0] if assertion.positive else spelling[1]
    if key in EQUALITY:
        operand = assertion.right_literal or assertion.operand_source
        if operand is not None:
            text = text.replace("expected", " ".join(operand.split())[:40])
    elif key in BOUNDS and assertion.operand_source is not None:
        text = text.replace("bound", assertion.operand_source[:40])
    return text


def compared_inside(assertion: Assertion) -> bool:
    """A bound key on a truthy spelling: `assert.ok(Math.abs(d) < bound)`.

    The key and its bound come from the comparison inside the asserted
    value, not from a matcher (#196 189.3); `left` is what the magnitude
    measures (189.2).
    """
    return assertion.predicate in BOUNDS and assertion.form != "compare_ord"


def _bound_evidence(assertion: Assertion) -> tuple[str, object] | None:
    """What says which bound an assertion names: its value, else its text.

    The literal value counts only when it is the bound's own: a hand-rolled
    `Math.abs(total - 78.75) < eps` records its centre, 78.75, as the
    expected value (#196 189.2), and that is not the bound.
    """
    epsilon = assertion.epsilon or ""
    if assertion.epsilon_kind == "abs" and epsilon.startswith("abs="):
        try:
            return "value", Decimal(epsilon[len("abs="):])  # a hand-rolled bound that was read
        except ArithmeticError:
            pass
    if (not compared_inside(assertion) and assertion.right_value is not None
            and assertion.right_literal is not None and assertion.operand_source is not None
            and operand_text(assertion.right_literal) == assertion.operand_source):
        return "literal", assertion.right_value
    if assertion.operand_source is not None:
        return "source", normalize_text(assertion.operand_source)
    return None


def _same_bound(before: Assertion, after: Assertion) -> bool:
    """Do both assertions name one bound? A literal and a name never do."""
    old, new = _bound_evidence(before), _bound_evidence(after)
    return old is not None and old == new


# For one bound B, what each bound key accepts, asserted or negated: values
# below, at and above B, and NaN, which no comparison accepts and every
# negated one does.
_BOUND_UNIVERSE = frozenset({"below", "at", "above", "nan"})
_BOUND_MEMBERS = {
    "lt": frozenset({"below"}),
    "le": frozenset({"below", "at"}),
    "gt": frozenset({"above"}),
    "ge": frozenset({"at", "above"}),
}


def _literal_base(assertion: Assertion) -> str | None:
    """The equality a keyed side spells with a literal expected value, if any."""
    if assertion.form != "compare_eq" or assertion.right_value is None:
        return None
    if assertion.predicate in _STRICT_LITERAL:
        return "eq_strict"
    if assertion.predicate in _LOOSE_LITERAL:
        return "eq_loose"
    return None


def _point(assertion: Assertion) -> str | None:
    """Where an `===` literal sits among the presence values: truthy or falsy.

    `true`, `false`, `null` and `undefined` have keys of their own, so the
    literal here is a number or a string. Any other operand is unknown.
    """
    if assertion.predicate != "eq_strict" or assertion.right_value is None:
        return None
    try:
        value = ast.literal_eval(assertion.right_value)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        return None
    if isinstance(value, bool) or value is None or not isinstance(value, (int, float, str)):
        return None
    return "truthy" if value else "falsy"


def _accepted(key: str, positive: bool, universe: frozenset[str], members: dict[str, frozenset[str]]) -> frozenset[str]:
    return members[key] if positive else universe - members[key]


def _upper(key: str, positive: bool) -> bool:
    """Does this bound assertion keep the value below its bound?

    `not >` keeps it below too (or NaN, which no comparison accepts and every
    negated one does), so a bound changed direction exactly when this differs.
    """
    return (key in {"lt", "le"}) == positive


def relation(before: Assertion, after: Assertion) -> str | None:
    """How the new assertion relates to the old one, or None when the keys cannot tell.

    None: either side has no key, or the keys cannot be compared alone (see
    the module docstring). The caller has established that both assert on
    the same subject.
    """
    old_key, new_key = before.predicate, after.predicate
    if old_key not in KEYS or new_key not in KEYS:
        return None
    old_positive, new_positive = before.positive, after.positive
    old_base, new_base = _literal_base(before), _literal_base(after)
    if old_base is not None and new_base is not None and old_positive == new_positive:
        # Both sides state a literal: what changed between `toBe(5)` and
        # `toBe(null)` is the expected value, which EXPECTED_VALUE_CHANGED
        # reports. Only the equality itself is compared here. A flipped
        # polarity is more than a new value (`.not.toBe(true)` ->
        # `.to.be.false` is stronger), so the keys still decide that.
        old_key, new_key = old_base, new_base
    if old_key == new_key and old_positive != new_positive:
        return OPPOSITE
    if old_key in EQUALITY and new_key in EQUALITY:
        universe, members = _EQUALITY_UNIVERSE, _EQUALITY_MEMBERS
    elif old_key in BOUNDS and new_key in BOUNDS:
        if _upper(old_key, old_positive) != _upper(new_key, new_positive):
            # A hand-rolled truthy spelling whose bound was not read states
            # a direction checkwash cannot pin to a bound (189.3).
            unread = [side for side in (before, after)
                      if compared_inside(side) and side.operand_source is None]
            return UNVERIFIABLE if unread else CONTRADICTS
        if old_key == new_key:
            return SAME
        if _same_bound(before, after):
            universe, members = _BOUND_UNIVERSE, _BOUND_MEMBERS
        else:
            # `< 0.01` -> `<= 0.005` tightens, and two bounds are operand
            # evidence the keys do not weigh. A flipped `.not` on top
            # (`<` -> `not >`) is not the opposite either, and not provable.
            return None if old_positive == new_positive else UNVERIFIABLE
    elif {old_key, new_key} <= PRESENCE:
        universe, members = _PRESENCE_UNIVERSE, _PRESENCE_MEMBERS
    elif {old_key, new_key} <= PRESENCE | {"eq_strict"}:
        # One side is `=== literal`: the literal is one more presence value.
        point = _point(before if old_key == "eq_strict" else after)
        if point is None:
            return None
        universe = _PRESENCE_UNIVERSE | {"point"}
        members = {**_PRESENCE_MEMBERS, "eq_strict": frozenset({"point"})}
        if point == "truthy":
            members["truthy"] = members["truthy"] | {"point"}
    else:
        return None
    old = _accepted(old_key, old_positive, universe, members)
    new = _accepted(new_key, new_positive, universe, members)
    if old == new:
        return SAME
    if new < old:
        return STRONGER
    if old < new:
        return WIDENED
    if not old & new:
        return CONTRADICTS
    return UNVERIFIABLE
