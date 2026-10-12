"""Three owned static inputs; sources are detector data, never executed."""
import hashlib

SIZE = 1_000_000
PATH = "tests/test_owned_cost.py"
ORDINARY = "ordinary_1mb"
DEEP = "deep_expression_1mb"
SIBLING = "deep_expression_sibling_128"
NAMES = (ORDINARY, DEEP, SIBLING)
PREFIX = b"import app.billing as billing\n"
BEFORE = b"def test_total():\n    observed = billing.total\n    assert billing.total() == 3\n"
AFTER = b"def test_total():\n    billing.total = lambda: 3\n    assert billing.total() == 3\n"
COMMON = {"app/__init__.py": b"", "app/billing.py": b"def total():\n    return 1\n"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def padded(body, tail, size):
    remaining = size - len(PREFIX) - len(body) - len(tail)
    if remaining < 2:
        raise ValueError("generator has no final line padding space")
    return PREFIX + body + b"#" + b" " * (remaining - 2) + b"\n" + tail


def pair(name):
    if name == ORDINARY:
        # Fixed-width real assignments occupy the body. Padding is less than
        # one further statement, not a one-megabyte comment/string stand-in.
        template = b"padding_000000 = 12345678901234567890\n"
        count = (SIZE - len(PREFIX) - max(len(BEFORE), len(AFTER)) - 2) // len(template)
        body = b"".join(f"padding_{n:06d} = 12345678901234567890\n".encode() for n in range(count))
        return padded(body, BEFORE, SIZE), padded(body, AFTER, SIZE)
    if name in (DEEP, SIBLING):
        # Left-associated binary + expression. The deep shape has thousands
        # of real leaves, not a huge trailing pad. No recursion limit change.
        atom = b"'" + b"0123456789abcdef" * 6 + b"'"
        if name == DEEP:
            available = SIZE - len(PREFIX) - max(len(BEFORE), len(AFTER)) - len(b"padding = \n") - 2
            terms = (available + 3) // (len(atom) + 3)
        else:
            terms = 128  # Source-designed sibling; remote parse/reach is evidence.
        body = b"padding = " + b" + ".join([atom] * terms) + b"\n"
        if name == DEEP:
            return padded(body, BEFORE, SIZE), padded(body, AFTER, SIZE)
        return PREFIX + body + BEFORE, PREFIX + body + AFTER
    raise ValueError("unknown owned case")


def metadata(name):
    before, after = pair(name)
    return {"name": name, "path": PATH, "purpose": "OWNED_STATIC_STANDIN_TAIL_PAIR",
                "designated_1mb": name != SIBLING, "sibling_is_not_replacement": name == SIBLING,
                "before": {"bytes": len(before), "sha256": sha(before)},
                "after": {"bytes": len(after), "sha256": sha(after)},
                "parse_status": "UNMEASURED", "nodes": None, "behavior": "NOT_QUALIFIED"}
