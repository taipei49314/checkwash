"""Root helper extraction preserves the concrete oracle, not just strength."""

import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import EngineError, FileChange, analyze

HELPER = b"def assert_equal(actual, expected):\n    assert actual == expected\n"
BEFORE = b"from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
AFTER = b"from calc import add\nfrom test_helpers import assert_equal\n\ndef test_add():\n    assert_equal(add(2, 3), 5)\n"


def run(after=AFTER, helper=HELPER, *, before=BEFORE, helper_before=None, head=None, extra=()):
    changes = [FileChange(path="tests/test_calc.py", before=before, after=after, status="modified")]
    if helper is not None or helper_before is not None:
        changes.append(FileChange(path="test_helpers.py", before=helper_before, after=helper,
                                  status="modified" if helper_before is not None else "added"))
    changes.extend(extra)
    return analyze(changes, Config(), Contract(), [], datetime.date(2026, 1, 1),
                   head_reader=(head or {}).get, root_reader=(head or {}).get)


@pytest.mark.parametrize("after,helper", [
    (AFTER, HELPER),
    (AFTER.replace(b"import assert_equal", b"import assert_equal as verify").replace(b"    assert_equal(", b"    verify("), HELPER),
    (AFTER, HELPER.replace(b"actual == expected", b"expected == actual")),
])
def test_transparent_root_extraction_preserves_oracle(after, helper):
    ir, findings, verdict = run(after, helper)
    assert findings == []
    assert verdict == "pass"
    inherited = ir.files[-1].units[0].after.assertions[0]
    assert inherited.inherited
    assert inherited.left == "add(2, 3)"
    assert inherited.right_value == "5"
    assert "assert_equal(" in inherited.text or "verify(" in inherited.text


def test_original_report_extraction_keeps_the_other_test_unchanged():
    companion = b"\ndef test_multiply():\n    assert multiply(2, 3) == 6\n"
    before = BEFORE.replace(b"import add", b"import add, multiply") + companion
    after = AFTER.replace(b"import add", b"import add, multiply") + companion
    _ir, findings, verdict = run(after, before=before)
    assert verdict == "pass"
    assert findings == []


def test_legacy_sibling_channel_does_not_require_strict_callbacks():
    changes = [FileChange(path="tests/test_calc.py", before=BEFORE, after=AFTER, status="modified"),
               FileChange(path="tests/test_helpers.py", before=None, after=HELPER, status="added")]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 1, 1),
                                     head_reader={}.get)
    assert verdict == "pass"
    assert findings == []


def test_ordinary_root_test_does_not_require_reverse_helper_search():
    before = b"def test_equal(actual, expected):\n    assert actual == expected\n"
    after = b"def test_equal(actual, expected):\n    assert actual > 0\n"
    _ir, findings, verdict = analyze(
        [FileChange(path="test_calc.py", before=before, after=after, status="modified")],
        Config(), Contract(), [], datetime.date(2026, 1, 1),
    )
    assert verdict == "block"
    assert any(f.rule == "ASSERT_WEAKENED" for f in findings)


def test_root_expected_argument_cannot_change_while_extracting():
    _ir, findings, verdict = run(AFTER.replace(b"3), 5)", b"3), 4)"))
    assert verdict == "block"
    changed = next(f for f in findings if f.rule == "EXPECTED_VALUE_CHANGED")
    assert changed.severity == "high"
    assert changed.after.text == "assert_equal(add(2, 3), 4)"


def test_root_expected_argument_cannot_change_after_extraction():
    _ir, findings, verdict = run(AFTER.replace(b"3), 5)", b"3), 4)"), before=AFTER, helper_before=HELPER)
    assert verdict == "block"
    assert any(f.rule == "EXPECTED_VALUE_CHANGED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("replacement", [b"subtract(7, 2)", b"sum([1, 4])", b"add(5, 0)"])
def test_root_extraction_cannot_replace_the_original_subject(replacement):
    after = AFTER.replace(b"add(2, 3)", replacement)
    _ir, findings, verdict = run(after)
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("after,helper", [
    (AFTER.replace(b"    assert_equal(", b"    assert_equal.__code__ = (lambda actual, expected: None).__code__\n    assert_equal("), HELPER),
    (AFTER.replace(b"from calc import add", b"from calc import subtract as add"), HELPER),
    (AFTER, HELPER + b"\ndef disable():\n    global assert_equal\n    assert_equal = lambda actual, expected: None\ndisable()\n"),
    (AFTER, HELPER + b"\nassert_equal.__code__ = (lambda actual, expected: None).__code__\n"),
    (AFTER, HELPER.replace(b"actual, expected", b"actual: disable(), expected")),
])
def test_root_extraction_rejects_caller_or_helper_execution_changes(after, helper):
    _ir, findings, verdict = run(after, helper)
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("path", ["test_helpers/__init__.py", "tests/test_helpers/__init__.py"])
def test_root_extraction_rejects_package_module_collision(path):
    _ir, findings, verdict = run(head={path: b"def assert_equal(actual, expected):\n    pass\n"})
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" for f in findings)


def test_root_extraction_rejects_unchanged_caller_mutation_statements():
    mutation = b"    globals().get('assert_equal', lambda *args: None).__code__ = (lambda actual, expected: None).__code__\n"
    _ir, findings, verdict = run(AFTER.replace(b"    assert_equal(", mutation + b"    assert_equal("),
                                 before=BEFORE.replace(b"    assert add(", mutation + b"    assert add("))
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" for f in findings)


def test_root_extraction_rejects_an_unchanged_mutator_hidden_in_an_assert():
    mutation = b"    assert not setattr(assert_equal, '__code__', (lambda actual, expected: None).__code__)\n"
    before = BEFORE.replace(b"from calc import add\n", b"from calc import add\nfrom test_helpers import assert_equal\n")
    before = before.replace(b"    assert add(", mutation + b"    assert add(")
    after = AFTER.replace(b"    assert_equal(", mutation + b"    assert_equal(")
    _ir, findings, verdict = run(after, before=before, helper=None, head={"test_helpers.py": HELPER})
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" and f.severity == "high" for f in findings)


def test_root_extraction_rejects_even_a_simple_unchanged_companion_call_assert():
    mutation = b"    assert disable_helper() == None\n"
    before = BEFORE.replace(b"    assert add(", mutation + b"    assert add(")
    after = AFTER.replace(b"    assert_equal(", mutation + b"    assert_equal(")
    _ir, findings, verdict = run(after, before=before)
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" for f in findings)


@pytest.mark.parametrize("after,helper", [
    (AFTER.replace(b"    assert_equal(add(2, 3), 5)", b"    pass"), HELPER),
    (AFTER, b"def assert_equal(actual, expected):\n    pass\n"),
    (AFTER, HELPER.replace(b"actual == expected", b"actual > 0")),
    (AFTER, HELPER.replace(b"actual == expected", b"actual == actual")),
    (AFTER, HELPER.replace(b"actual == expected", b"int(actual) == expected")),
    (AFTER, HELPER.replace(b"actual, expected", b"actual, expected=5")),
    (AFTER, b"this is not python ["),
    (AFTER, None),
    (AFTER.replace(b"from test_helpers", b"from .test_helpers"), HELPER),
    (AFTER.replace(b"    assert_equal(", b"    return\n    assert_equal("), HELPER),
    (AFTER.replace(b"    assert_equal(", b"    assert_equal = lambda *args: None\n    assert_equal("), HELPER),
    (AFTER.replace(b"\ndef test_add", b"\nassert_equal = lambda *args: None\n\ndef test_add"), HELPER),
    (AFTER.replace(b"    assert_equal(add(2, 3), 5)", b"    if False:\n        assert_equal(add(2, 3), 5)"), HELPER),
    (AFTER.replace(b"    assert_equal(add(2, 3), 5)", b"    assert_equal(add(2, 3), expected=5)"), HELPER),
])
def test_unsupported_or_neutralized_root_helper_earns_no_credit(after, helper):
    _ir, findings, verdict = run(after, helper)
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" and f.severity == "high" for f in findings)


def test_existing_head_helper_and_reverse_inlining():
    _ir, findings, verdict = run(helper=None, head={"test_helpers.py": HELPER})
    assert findings == []
    assert verdict == "pass"
    _ir, findings, verdict = run(BEFORE, helper_before=HELPER, before=AFTER)
    assert findings == []
    assert verdict == "pass"


def test_root_sibling_collision_does_not_guess_even_with_strong_sibling():
    sibling = FileChange(path="tests/test_helpers.py", before=None, after=HELPER, status="added")
    _ir, findings, verdict = run(extra=(sibling,))
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" for f in findings)


def test_unknown_sibling_at_read_budget_exhaustion_earns_no_credit(monkeypatch):
    monkeypatch.setattr("checkwash.engine._MAX_ORACLE_READS", 0)
    _ir, findings, verdict = run()
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" for f in findings)


def test_root_call_limit_refuses_whole_unit():
    calls = b"    assert_equal(add(2, 3), 5)\n" * 65
    after = AFTER[:AFTER.index(b"    assert_equal(")] + calls
    _ir, findings, verdict = run(after)
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" for f in findings)


def helper_only_change(after_helper, callers=None, *, contract=None, extra=()):
    heads = {"tests/test_calc.py": AFTER} if callers is None else callers
    heads = {**heads, "test_helpers.py": after_helper}
    searches, reads = [], []

    def search(needles):
        searches.append(needles)
        return [p for p, data in heads.items() if data is not None and any(n.encode() in data for n in needles)]

    def read(path):
        reads.append(path)
        return heads.get(path)

    result = analyze(
        [FileChange(path="test_helpers.py", before=HELPER, after=after_helper, status="modified"), *extra],
        Config(), contract or Contract(), [], datetime.date(2026, 1, 1), head_reader=read, head_searcher=search,
        root_reader=read, root_searcher=search,
    )
    return result, searches, reads


def test_helper_only_assertion_removal_discovers_unchanged_importer():
    (ir, findings, verdict), searches, reads = helper_only_change(b"def assert_equal(actual, expected):\n    pass\n")
    assert verdict == "block"
    removed = next(f for f in findings if f.rule == "ASSERT_REMOVED")
    assert removed.path == "tests/test_calc.py" and removed.severity == "high"
    assert removed.before.text == "assert_equal(add(2, 3), 5)"
    assert searches == [["test_helpers"]]
    assert reads == ["tests/test_calc.py", "tests/calc.py", "tests/test_helpers.py",
                     "test_helpers/__init__.py", "tests/test_helpers/__init__.py"]
    assert {f.path for f in ir.files} == {"test_helpers.py", "tests/test_calc.py"}


def test_helper_only_change_does_not_claim_unchanged_importer_is_out_of_scope():
    (_ir, findings, verdict), _, _ = helper_only_change(
        b"def assert_equal(actual, expected):\n    pass\n", contract=Contract(scope_allow=["test_helpers.py"]),
    )
    assert verdict == "block"
    assert not any(f.rule == "SCOPE_DRIFT" for f in findings)


@pytest.mark.parametrize("caller", [
    b"from test_helpers import assert_equal\n\ndef test_add():\n    assert 1 == 1\n",
    b"from test_helpers import assert_equal\n\ndef test_add():\n    pass\n",
    b"from .test_helpers import assert_equal\n\ndef test_add():\n    pass\n",
])
def test_unused_or_relative_import_does_not_create_removed_oracle(caller):
    (_ir, findings, verdict), _, _ = helper_only_change(
        b"def assert_equal(actual, expected):\n    pass\n", {"tests/test_calc.py": caller},
    )
    assert verdict == "pass"
    assert findings == []


def test_helper_only_comment_edit_preserves_importer_oracle():
    (_ir, findings, verdict), _, _ = helper_only_change(HELPER + b"\n# clarified helper\n")
    assert verdict == "pass"
    assert findings == []


def test_helper_only_executable_rebinding_still_removes_the_old_oracle():
    (_ir, findings, verdict), _, _ = helper_only_change(
        HELPER + b"\ndef disable():\n    global assert_equal\n    assert_equal = lambda *args: None\ndisable()\n",
    )
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" and f.severity == "high" for f in findings)


def test_root_extraction_allows_comments_docstrings_and_formatting():
    after = AFTER.replace(b"add(2, 3), 5", b"add( 2, 3 ), 5") + b"\n# same oracle\n"
    _ir, findings, verdict = run(after, b'"""Equality helpers."""\n' + HELPER)
    assert verdict == "pass"
    assert findings == []


def test_root_extraction_rejects_preexisting_dynamic_search_path():
    setup = b"import sys\nsys.path.insert(0, 'decoy')\n"
    _ir, findings, verdict = run(setup + AFTER, before=setup + BEFORE)
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" for f in findings)


def test_root_package_absence_must_fit_the_existing_read_budget(monkeypatch):
    monkeypatch.setattr("checkwash.engine._MAX_ORACLE_READS", 2)
    _ir, findings, verdict = run()
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" for f in findings)


def test_root_package_read_error_is_not_treated_as_absence():
    def read(path):
        if path == "test_helpers/__init__.py":
            raise EngineError("package snapshot unavailable")
        return None

    with pytest.raises(EngineError, match="package snapshot unavailable"):
        analyze([FileChange("tests/test_calc.py", "modified", BEFORE, AFTER),
                 FileChange("test_helpers.py", "added", None, HELPER)],
                Config(), Contract(), [], datetime.date(2026, 1, 1), root_reader=read)


@pytest.mark.parametrize("package", [None, b"def assert_equal(actual, expected):\n    pass\n"])
def test_package_absence_is_checked_independently_of_its_oracle_role(package):
    caller = AFTER.replace(b"test_helpers", b"conftest")
    reads = []

    def read(path):
        reads.append(path)
        return package if path == "conftest/__init__.py" else None

    _ir, findings, verdict = analyze(
        [FileChange("tests/test_calc.py", "modified", BEFORE, caller),
         FileChange("conftest.py", "added", None, HELPER)],
        Config(), Contract(), [], datetime.date(2026, 1, 1), root_reader=read,
    )
    assert Config().role_of("conftest/__init__.py") == "prod"
    assert "conftest/__init__.py" in reads
    assert verdict == ("pass" if package is None else "block")
    assert bool(findings) == (package is not None)


def test_comment_only_root_conftest_change_does_not_invent_a_budget_error():
    caller = AFTER.replace(b"test_helpers", b"conftest")
    heads = {"tests/test_calc.py": caller}
    _ir, findings, verdict = analyze(
        [FileChange("conftest.py", "modified", HELPER, HELPER + b"# clarification\n")],
        Config(), Contract(), [], datetime.date(2026, 1, 1), root_reader=heads.get,
        root_searcher=lambda needles: list(heads),
    )
    assert verdict == "pass"
    assert findings == []


def test_reverse_search_never_replaces_an_importer_already_in_real_diff():
    changed = FileChange(path="tests/test_calc.py", before=BEFORE, after=AFTER, status="modified")
    (_ir, findings, verdict), searches, reads = helper_only_change(
        b"def assert_equal(actual, expected):\n    pass\n", extra=(changed,),
    )
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" for f in findings)
    assert "tests/test_calc.py" not in reads


def test_reverse_search_fails_closed_when_candidate_budget_is_exceeded():
    callers = {f"tests/test_{i}.py": AFTER for i in range(9)}
    with pytest.raises(EngineError, match="read budget"):
        helper_only_change(b"def assert_equal(actual, expected):\n    pass\n", callers)


def test_reverse_search_fails_closed_when_search_could_be_truncated():
    callers = {f"tests/test_{i}.py": AFTER for i in range(64)}
    with pytest.raises(EngineError, match="truncated"):
        helper_only_change(b"def assert_equal(actual, expected):\n    pass\n", callers)


def test_reverse_search_requires_the_snapshot_api():
    with pytest.raises(EngineError, match="snapshot importer search"):
        analyze([FileChange(path="test_helpers.py", before=HELPER,
                            after=b"def assert_equal(actual, expected):\n    pass\n", status="modified")],
                Config(), Contract(), [], datetime.date(2026, 1, 1))


def test_reverse_search_and_helper_resolution_share_one_read_budget(monkeypatch):
    monkeypatch.setattr("checkwash.engine._MAX_ORACLE_READS", 2)
    with pytest.raises(EngineError, match="snapshot read budget"):
        helper_only_change(b"def assert_equal(actual, expected):\n    pass\n")


def test_helper_only_change_with_ambiguous_sibling_is_not_a_clean_pass():
    with pytest.raises(EngineError, match="ambiguous sibling"):
        helper_only_change(b"def assert_equal(actual, expected):\n    pass\n",
                           {"tests/test_calc.py": AFTER, "tests/test_helpers.py": HELPER})


def test_root_helper_rename_cannot_hide_removal_at_the_old_import_path():
    with pytest.raises(EngineError, match="renames"):
        analyze([FileChange(path="test_moved.py", old_path="test_helpers.py", before=HELPER,
                            after=HELPER, status="modified")], Config(), Contract(), [],
                datetime.date(2026, 1, 1), head_reader={}.get, head_searcher=lambda needles: [])


def test_helper_only_removal_blocks_in_real_worktree_and_range(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "e2e")
    git("config", "user.email", "e2e@example.invalid")
    git("config", "commit.gpgsign", "false")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_calc.py").write_bytes(AFTER)
    helper = tmp_path / "test_helpers.py"
    helper.write_bytes(HELPER)
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b - 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-m", "test catches existing bug")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}

    def check(*range_args):
        result = subprocess.run(
            [sys.executable, "-m", "checkwash", "check", *range_args, "--repo", str(tmp_path), "--format", "json"],
            env=env, capture_output=True,
        )
        assert result.returncode == 1, result.stderr.decode("utf-8", errors="replace")
        findings = json.loads(result.stdout)["findings"]
        assert any(f["rule"] == "ASSERT_REMOVED" and f["severity"] == "high" for f in findings)
        return findings

    helper.write_text("def assert_equal(actual, expected):\n    pass\n", encoding="utf-8")
    worktree = check()
    git("commit", "-am", "remove assertion without fixing bug")
    assert check("HEAD~1..HEAD") == worktree
    swept = subprocess.run(
        [sys.executable, "-m", "checkwash", "sweep", "--repo", str(tmp_path), "--limit", "1"],
        env=env, capture_output=True,
    )
    assert swept.returncode == 0, swept.stderr.decode("utf-8", errors="replace")
    summary = json.loads(swept.stdout)
    assert summary["engine_errors"] == 0
    assert summary["commits_blocked"] == 1


@pytest.mark.parametrize("after_helper", [None, b"this is not python [", HELPER.replace(b"actual == expected", b"actual > 0")])
def test_helper_only_delete_unparseable_or_weakening_still_blocks(after_helper):
    (_ir, findings, verdict), _, _ = helper_only_change(after_helper)
    assert verdict == "block"
    assert any(f.rule == "ASSERT_REMOVED" and f.severity == "high" for f in findings)


@pytest.mark.parametrize("source", [BEFORE, AFTER])
def test_original_and_refactored_tests_really_catch_same_bug(tmp_path, source):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_calc.py").write_bytes(source)
    (tmp_path / "test_helpers.py").write_bytes(HELPER)
    production = tmp_path / "calc.py"
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}

    def execute():
        return subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"],
                              cwd=tmp_path, capture_output=True, env=env)

    production.write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    clean = execute()
    assert clean.returncode == 0, clean.stdout.decode("utf-8", errors="replace")
    assert b"1 passed" in clean.stdout
    production.write_text("def add(a, b):\n    return a + b - 1\n", encoding="utf-8")
    buggy = execute()
    assert buggy.returncode == 1, buggy.stdout.decode("utf-8", errors="replace")
    assert b"1 failed" in buggy.stdout and b"assert 4 == 5" in buggy.stdout
