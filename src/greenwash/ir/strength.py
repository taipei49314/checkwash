"""Assertion strength lattice — the single source of truth (SPEC §3).

Values are frozen. Changing them requires a SPEC version bump and a full
fixture re-run. Agent-read-only.
"""

EXACT_STRUCT = 100
EXACT_VALUE = 90
APPROX = 70
PATTERN = 60
TYPE_SHAPE = 50
BOUND = 40
NON_NULL = 30
TRUTHY = 20
TAUTOLOGY = 10
REMOVED = 0

_NAMES = {
    EXACT_STRUCT: "EXACT_STRUCT",
    EXACT_VALUE: "EXACT_VALUE",
    APPROX: "APPROX",
    PATTERN: "PATTERN",
    TYPE_SHAPE: "TYPE_SHAPE",
    BOUND: "BOUND",
    NON_NULL: "NON_NULL",
    TRUTHY: "TRUTHY",
    TAUTOLOGY: "TAUTOLOGY",
    REMOVED: "REMOVED",
}


def name_of(level: int | None) -> str:
    if level is None:
        return "UNKNOWN"
    return _NAMES.get(level, f"LEVEL_{level}")
