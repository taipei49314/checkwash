"""A JS/TS test path keeps its test obligations whatever role it holds (#197).

SPEC section 2 resolves guardrail, ci, snapshot, lockfile and conftest before
`test`. A JS/TS test path in one of those roles keeps it, and every test rule
judges it beside that role's own rules (ruling 197.Q2). The IR records this
in `FileIR.test_obligations`; `role` stays the public role (197.Q3). Cases a
`.gwcase` fixture cannot state live here: user role globs, renames, and the
IR field itself.
"""

import ast
import datetime
import pathlib

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.ir.model import FileIR, judged_as_test

SOURCE = pathlib.Path(__file__).resolve().parent.parent / "src" / "checkwash"

BEFORE = (
    b'import { test, expect } from "vitest";\n'
    b'import { total } from "./value";\n'
    b'test("total", () => { expect(total()).toBe(78.75); });\n'
    b'test("other", () => { expect(total()).toBe(78.75); });\n'
)
AFTER = (
    b'import { test, expect } from "vitest";\n'
    b'import { total } from "./value";\n'
    b'test("total", () => { expect(total()).toBeTruthy(); });\n'
    b'test.skip("other", () => { expect(total()).toBe(78.75); });\n'
)
WEAKENED = [("ASSERT_WEAKENED", "high", "total"), ("TEST_DISABLED", "high", "other")]
DELETED = [("TEST_DISABLED", "high", "other"), ("TEST_DISABLED", "high", "total")]


def _analyze(changes, roles=None):
    config = Config()
    for role, globs in (roles or {}).items():
        config.roles[role] = list(config.roles.get(role, [])) + globs
    return analyze(changes, config, Contract(), [], datetime.date(2026, 10, 3))


def _summary(findings):
    return [(f.rule, f.severity, f.unit) for f in findings]


@pytest.mark.parametrize("role,glob,path", [
    # #197 members U1 and U2: a user glob covered the test, and v0.5.0 gave
    # zero findings because neither role has rules of its own.
    ("lockfile", "**/locks/**", "src/locks/value.test.ts"),
    ("conftest", "test/support/**", "test/support/value.test.js"),
])
def test_a_user_glob_does_not_withdraw_test_obligations(role, glob, path):
    ir, findings, verdict = _analyze([FileChange(path, "modified", BEFORE, AFTER)], {role: [glob]})
    assert [(file.role, file.test_obligations) for file in ir.files] == [(role, True)]
    assert verdict == "block"
    assert _summary(findings) == WEAKENED
    ir, findings, verdict = _analyze([FileChange(path, "deleted", BEFORE, None)], {role: [glob]})
    assert verdict == "block"
    assert _summary(findings) == DELETED


def test_a_user_test_glob_gives_the_test_role_itself():
    # #197 control U3: the public role is `test`, so there is no other role
    # for the obligations to sit beside.
    ir, findings, verdict = _analyze(
        [FileChange("src/value.test.ts", "modified", BEFORE, b"#!/bin/sh\n" + AFTER)],
        {"test": ["**/*.test.ts"]},
    )
    assert [(file.role, file.test_obligations) for file in ir.files] == [("test", False)]
    assert verdict == "block"
    assert _summary(findings) == WEAKENED


@pytest.mark.parametrize("old,new,role", [
    # #197 rows R1 and R2, relabelled pass by ruling 197.Q2: the runners
    # still collect the destination, and there it is judged as a test.
    ("src/value.test.ts", ".github/workflows/value.test.ts", "ci"),
    ("src/value.test.ts", "test/expected/value.test.ts", "snapshot"),
])
def test_moving_a_test_into_another_role_keeps_it_a_test(old, new, role):
    # A rename reaches the engine as git reports it: modified, with old_path.
    ir, findings, verdict = _analyze([FileChange(new, "modified", BEFORE, BEFORE, old_path=old)])
    assert verdict == "pass"
    assert [(file.path, file.role, file.test_obligations) for file in ir.files] == [(new, role, True)]
    assert all(finding.severity in ("warn", "info") for finding in findings)
    ir, findings, verdict = _analyze([FileChange(new, "modified", BEFORE, AFTER, old_path=old)])
    assert verdict == "block"
    assert set(WEAKENED) <= set(_summary(findings))


def test_moving_a_test_out_of_a_ci_directory_is_not_a_workflow_removal():
    # v0.5.0 read the old path as a deleted workflow that ran tests and
    # blocked. Only YAML there is a workflow (197.Q5), and the units arrive
    # intact at the new path.
    old, new = ".github/workflows/value.test.ts", "src/value.test.ts"
    _ir, findings, verdict = _analyze([FileChange(new, "modified", BEFORE, BEFORE, old_path=old)])
    assert verdict == "pass"
    assert ("CI_WORKFLOW_TOUCHED", "warn", None) in _summary(findings)
    assert all(finding.severity in ("warn", "info") for finding in findings)


@pytest.mark.parametrize("path,role,obligations", [
    # The Python twin (#219, ruling 219.Q1): a file pytest's default
    # collection runs carries obligations beside its role, as a JS/TS test
    # path does.
    ("tests/golden/test_value.py", "snapshot", True),
    # pytest never descends into a dot-directory, so nothing runs it there.
    (".github/workflows/test_value.py", "ci", False),
])
def test_python_tests_carry_obligations_where_pytest_collects_them(path, role, obligations):
    before = b"def test_total():\n    assert total() == 78.75\n"
    after = b"def test_total():\n    assert total()\n"
    ir, _findings, _verdict = _analyze([FileChange(path, "modified", before, after)])
    assert [(file.role, file.test_obligations) for file in ir.files] == [(role, obligations)]
    assert judged_as_test(ir.files[0]) is obligations


@pytest.mark.parametrize("role,obligations,judged", [
    ("test", False, True),
    ("snapshot", True, True),
    ("ci", True, True),
    ("snapshot", False, False),
    ("prod", False, False),
])
def test_judged_as_test_reads_the_role_and_the_obligations(role, obligations, judged):
    file = FileIR(path="x", language="javascript", role=role, status="modified", test_obligations=obligations)
    assert judged_as_test(file) is judged


def _role_compared_with_test(node: ast.Compare) -> bool:
    """`<expr>.role == "test"`, `!= "test"`, or `in`/`not in` a literal holding "test"."""
    if not (isinstance(node.left, ast.Attribute) and node.left.attr == "role"):
        return False
    for operator, comparator in zip(node.ops, node.comparators):
        if isinstance(operator, (ast.Eq, ast.NotEq)) and isinstance(comparator, ast.Constant):
            if comparator.value == "test":
                return True
        if isinstance(operator, (ast.In, ast.NotIn)) and isinstance(comparator, (ast.Tuple, ast.List, ast.Set)):
            if any(isinstance(item, ast.Constant) and item.value == "test" for item in comparator.elts):
                return True
    return False


def test_no_test_rule_reads_the_role_alone():
    # Ruling 197.Q3: `judged_as_test` is the one predicate for test rules. A
    # check on `file.role` alone would skip a JS test that holds another role,
    # which is the #197 failure itself.
    offenders = []
    for path in sorted(SOURCE.rglob("*.py")):
        if path == SOURCE / "ir" / "model.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(
            f"{path.relative_to(SOURCE)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Compare) and _role_compared_with_test(node)
        )
    assert offenders == []
