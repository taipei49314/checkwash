"""Issue #174: a package manifest's test command is read from its parsed
string values, and only that part of the manifest is test-runner config.

`node --test` holds no runner token, so THREATMODEL row 87's token-reading
content gate left package.json as unreadable production: editing its test
command hid the weakening *and* bought the opaque exemption for an assertion
weakened beside it. The key decides now, not the runner vocabulary, and a
dependency or version bump keeps the treatment it had.
"""

import datetime
import json

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.roles import (
    _ci_scan_base,
    _ci_scan_view,
    _test_commands,
    _test_commands_changed,
)

TODAY = datetime.date(2026, 10, 1)


def _pkg(scripts: dict, **fields) -> bytes:
    manifest = {"name": "victim", "version": "1.0.0", **fields, "scripts": scripts}
    return json.dumps(manifest).encode("utf-8")


def _analyze(before: bytes, after: bytes, path: str = "package.json"):
    return analyze(
        [FileChange(path, "modified", before, after)], Config(), Contract(), [], TODAY,
    )


def test_only_named_manifests_define_a_test_command():
    data = _pkg({"test": "node --test"})
    assert _test_commands("src/app.json", data) is None
    assert _test_commands("package.json.orig", data) is None
    assert _test_commands("package.json", data) == {"test": "node --test"}
    assert _test_commands("web\\packages\\api\\package.json", data) == {"test": "node --test"}


def test_the_key_decides_not_the_runner_vocabulary():
    commands = _test_commands("package.json", _pkg({
        "test": "node --test",
        "test:e2e": "playwright test",
        "pretest": "eslint .",
        "posttest": "c8 report",
        "start": "node server.js",
    }))
    assert commands == {"test": "node --test", "test:e2e": "playwright test"}


def test_recognised_runners_and_one_hop_join_in_sorted_order():
    commands = _test_commands("package.json", _pkg({
        "test": "run-s lint unit",
        "lint": "eslint .",
        "unit": "mocha",
        "e2e": "jest --config e2e.config.json",
        "build": "tsc",
    }))
    assert list(commands) == ["e2e", "lint", "test", "unit"]


def test_the_hop_is_exactly_one_and_needs_a_script_runner():
    assert _test_commands("package.json", _pkg({
        "test": "npm run a", "a": "npm run b", "b": "node --test",
    })) == {"a": "npm run b", "test": "npm run a"}
    assert _test_commands("package.json", _pkg({
        "test": "node --test build", "build": "tsc",
    })) == {"test": "node --test build"}


def test_pipfile_scripts_share_the_definition():
    data = (
        b'[packages]\nrequests = "==2.31.0"\n\n'
        b'[scripts]\ntest = "pytest -q"\nserve = "flask run"\n'
        b'smoke = "python -m pytest tests/smoke"\n'
    )
    assert _test_commands("Pipfile", data) == {
        "smoke": "python -m pytest tests/smoke", "test": "pytest -q",
    }


def test_unreadable_or_absent_manifests_define_no_test_command():
    for data in (
        None, b"", b"{ not json", b"[]",
        b'{"scripts": ["test"]}', b'{"scripts": {"test": 1}}',
    ):
        assert _test_commands("package.json", data) == {}
    assert _test_commands("Pipfile", b"[scripts\ntest = ") == {}
    bom = b"\xef\xbb\xbf" + _pkg({"test": "vitest run"})
    assert _test_commands("package.json", bom) == {"test": "vitest run"}


def test_dependency_version_and_order_edits_leave_the_test_command_alone():
    before = _pkg({"test": "node --test"}, dependencies={"decimal.js": "^10.4.3"})
    after = _pkg({"test": "node --test"}, version="1.1.0", dependencies={"decimal.js": "^10.5.0"})
    assert not _test_commands_changed("package.json", before, after)
    reordered = json.dumps({"scripts": {"test": "node --test"}, "name": "victim"}, indent=2)
    assert not _test_commands_changed("package.json", before, reordered.encode("utf-8"))


def test_editing_adding_deleting_or_breaking_the_test_command_changes_it():
    base = _pkg({"test": "node --test"})
    assert _test_commands_changed("package.json", base, _pkg({"test": "node --test || true"}))
    assert _test_commands_changed("package.json", base, None)
    assert _test_commands_changed("package.json", None, base)
    assert _test_commands_changed("package.json", base, b"{ broken")
    assert not _test_commands_changed("package.json", None, _pkg({"start": "node ."}))
    assert not _test_commands_changed("src/app.js", base, _pkg({"test": "x"}))


def test_the_ci_scan_reads_only_the_test_command():
    data = _pkg({"test": "node --test", "prepare": "husky || true"})
    assert _ci_scan_view("package.json", data) == b"node --test"
    # A lone surrogate is valid JSON; it must not become an engine error.
    assert _ci_scan_view("package.json", b'{"scripts": {"test": "x \\ud800"}}') == b"x ?"
    makefile = b"test:\n\tpytest\n"
    assert _ci_scan_view("Makefile", makefile) is makefile


def test_a_dependency_bump_stays_opaque_production():
    ir, findings, verdict = _analyze(
        _pkg({"test": "node --test"}, dependencies={"decimal.js": "^10.4.3"}),
        _pkg({"test": "node --test"}, dependencies={"decimal.js": "^10.5.0"}),
    )
    assert [file.role for file in ir.files] == ["prod"]
    assert ir.globals.prod_opaque_change is True
    assert (findings, verdict) == ([], "pass")


def test_a_test_command_edit_is_ci_and_buys_no_exemption():
    ir, findings, verdict = _analyze(
        _pkg({"test": "node --test"}), _pkg({"test": "node --test || true"}),
    )
    assert [file.role for file in ir.files] == ["ci"]
    assert ir.globals.prod_opaque_change is False
    assert [(f.rule, f.severity) for f in findings] == [("CI_WORKFLOW_TOUCHED", "high")]
    assert verdict == "block"


def test_only_the_test_command_proper_hops():
    # `prepublishOnly` runs the suite, so it is a member, but `build` is not
    # part of what `npm test` runs: only `test` and `test:*` hop.
    before = _pkg({
        "test": "node --test",
        "test:ci": "npm run lint && npm test",
        "lint": "eslint .",
        "build": "babel src -d lib",
        "prepublishOnly": "npm run build && npm test",
    })
    assert list(_test_commands("package.json", before)) == [
        "lint", "prepublishOnly", "test", "test:ci",
    ]
    after = before.replace(b"babel src -d lib", b"babel src -d lib --ignore src/__fixtures__")
    assert not _test_commands_changed("package.json", before, after)


def test_a_script_the_diff_only_starts_calling_is_counted_at_its_base_value():
    build = "babel src -d lib --ignore src/__fixtures__"
    before = _pkg({"build": build, "test": "node --test"})
    after = _pkg({"build": build, "test": "npm run build && node --test"})
    assert _ci_scan_view("package.json", before) == b"node --test"
    assert _ci_scan_base("package.json", before, after) == f"{build}\nnode --test".encode()
    makefile = b"test:\n\tpytest\n"
    assert _ci_scan_base("Makefile", makefile, b"") is makefile


def test_an_unreadable_side_cannot_show_the_test_command_unchanged():
    # Past the read cap, or refused by json/tomllib, is not "no test command":
    # padding planted in an earlier commit must not keep a later edit opaque.
    pad = b" " * 1_000_000
    before = _pkg({"test": "node --test"}) + pad
    after = _pkg({"test": "node --test || true"}) + pad
    assert _test_commands("package.json", before) == {}
    assert _test_commands_changed("package.json", before, after)
    assert not _test_commands_changed("package.json", before, before)
    assert _test_commands_changed("package.json", b"{ broken: 1", b"{ broken: 2")
    assert _test_commands_changed("Pipfile", b"[scripts\ntest = 1", b"[scripts\ntest = 2")
    assert _ci_scan_view("package.json", b"{ broken") == b"{ broken"
    ir, findings, verdict = _analyze(before, after)
    assert [file.role for file in ir.files] == ["ci"]
    assert ir.globals.prod_opaque_change is False
    assert [(f.rule, f.severity) for f in findings] == [("CI_WORKFLOW_TOUCHED", "high")]
    assert verdict == "block"
