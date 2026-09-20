"""A result alias preserves the binding at capture, not at the assertion."""
import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import parse_python
from checkwash.frontends.python.subject_replacements import _subject_call


PREFIX = "from app.billing import total\n"


def findings(before, after):
    sources = {"app/__init__.py": b"", "app/billing.py": b"def total(values):\n    return 0\n",
               "tests/test_billing.py": after.encode()}
    return analyze([FileChange("tests/test_billing.py", "modified", before.encode(), after.encode())],
                   Config(), Contract(), [], datetime.date(2026, 9, 21), root_reader=sources.get,
                   root_path_lister=lambda: sorted(sources),
                   root_batch_reader=lambda paths: {p: sources.get(p) for p in paths})[1]


HONEST = [
    ("    alias = sum\n    got = alias([1, 2])\n    alias = total\n    assert got == 3\n",
     "got = alias([1, 2])", "got = sum([1, 2])"),
    ("    got = sum([1, 2])\n    result = got\n    got = total([1, 2])\n    assert result == 3\n",
     "got = total([1, 2])", "got = sum([1, 2])"),
    ("    from builtins import sum as total\n    got = total([1, 2])\n    assert got == 3\n",
     "got = total([1, 2])", "got = sum([1, 2])"),
]


@pytest.mark.parametrize("body,old,new", HONEST)
def test_honest_capture_refactors_execute_the_same_oracle_and_do_not_patch_subject(body, old, new):
    before = PREFIX + "def test_total():\n" + body
    after = before.replace(old, new)
    # The unused production result may be wrong; neither test consumes it.
    for source in (before, after):
        namespace = {"total": lambda values: 0}
        exec(source.removeprefix(PREFIX), namespace)
        namespace["test_total"]()
    assert not [f for f in findings(before, after) if f.rule == "TEST_PATCHES_SUBJECT"]


def projected(source):
    assertion = parse_python(source.encode(), collect_tests=True).units[0].side.assertions[-1]
    return _subject_call(assertion, ast.parse(source), "test_total")


@pytest.mark.parametrize("body", [
    "    alias = sum\n    got = alias([1, 2])\n    alias = total\n    assert got == 3\n",
    "    got = sum([1, 2])\n    result = got\n    got = total([1, 2])\n    assert result == 3\n",
    "    values = [1, 2]\n    got = total(values)\n    values = [3]\n    assert got == 3\n",
    "    values = [1, 2]\n    items = values\n    got = total(items)\n    values = [3]\n    assert got == 3\n",
    "    values = [1, 2]\n    got = total(values)\n    values.append(3)\n    assert got == 3\n",
    "    global total\n    got = total([1, 2])\n    total = sum\n    assert got == 3\n",
    "    got = total([1, 2])\n    del total\n    assert got == 3\n",
    "    got = total([1, 2])\n    changed = (total := sum)\n    assert got == 3\n",
    "    got = total([1, 2])\n    other = mutate_globals()\n    assert got == 3\n",
    "    got = total([1, 2])\n    globals()['total'] = sum\n    assert got == 3\n",
    "    if enabled:\n        total = sum\n    got = total([1, 2])\n    assert got == 3\n",
    "    got = total([1, 2])\n    if enabled:\n        total = sum\n    assert got == 3\n",
    "    got = total([1, 2])\n    try:\n        total = sum\n    except Exception:\n        pass\n    assert got == 3\n",
    "    got = total([1, 2])\n    for item in values:\n        total = sum\n    assert got == 3\n",
    "    got = total([1, 2])\n    with manager():\n        pass\n    assert got == 3\n",
    "    got = total([1, 2])\n    assert got == 3\n    assert got == 3\n",
    "    got = total([1, 2])\n    def total(values):\n        return 3\n    assert got == 3\n",
])
def test_unstable_or_unproven_capture_is_not_projected(body):
    assert projected(PREFIX + "def test_total():\n" + body) is None


@pytest.mark.parametrize("module,callee", [
    ("from app.billing import total\nalias = sum\nsum = total\n", "alias"),
    ("from app.billing import total\nalias = total\ntotal = sum\n", "alias"),
    ("from app.billing import total\nif enabled:\n    alias = total\n", "alias"),
    ("from app.billing import total\nfrom providers import *\n", "total"),
])
def test_module_capture_binding_changes_are_not_final_value_proofs(module, callee):
    assert projected(module + f"def test_total():\n    got = {callee}([1, 2])\n    assert got == 3\n") is None


@pytest.mark.parametrize("assignment,result", [
    ("    got = total([1, 2])\n", "got"),
    ("    values = [1, 2]\n    got = total(values)\n    result = got\n", "result"),
    ("    got: int = total([1, 2])\n", "got"),
])
def test_stable_local_captures_retain_replacement_detection(assignment, result):
    before = PREFIX + "def test_total():\n" + assignment + f"    assert {result} == 3\n"
    after = before.replace("= total(", "= sum(")
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings(before, after))


def test_direct_asserted_call_does_not_use_the_new_alias_restrictions():
    source = PREFIX + "def test_total():\n    unrelated()\n    assert total([1, 2]) == 3\n"
    assert isinstance(projected(source), ast.Call)
