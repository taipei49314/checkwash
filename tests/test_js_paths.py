"""Node's actual default test paths must reach the same assertion pipeline."""

import datetime
import json
import os
import subprocess
import sys

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.frontends.javascript.frontend import is_js_test_path as frontend_test_path
from checkwash.frontends.javascript.paths import is_js_test_path
from checkwash.report.context import ReportContext


# This inventory comes from Node's published default discovery patterns, not
# from the implementation's extension set. TypeScript is a candidate even on
# older/configured runners that do not enable type stripping; no execution or
# runner configuration is inferred by the bounded path classifier.
NODE_EXTENSIONS = ("js", "cjs", "mjs", "ts", "cts", "mts")
NODE_PATTERNS = (
    "test.{ext}",
    "test-total.{ext}",
    "total-test.{ext}",
    "total_test.{ext}",
    "total.test.{ext}",
    "test/example.{ext}",
    "test/nested/example.{ext}",
    "packages/billing/test/example.{ext}",
)


@pytest.mark.parametrize("extension", NODE_EXTENSIONS)
@pytest.mark.parametrize("pattern", NODE_PATTERNS)
def test_node_default_discovery_paths_are_recognized(pattern, extension):
    path = pattern.format(ext=extension)
    assert is_js_test_path(path)
    assert frontend_test_path(path)


@pytest.mark.parametrize("path", [
    "tests/total.test.jsx", "src/total.spec.jsx", "tests/total.test.tsx", "src/total.spec.tsx",
    "src/total.spec.js", "src/total.spec.cjs", "src/total.spec.mjs", "src/total.spec.ts",
    "src/total.spec.cts", "src/total.spec.mts", r"packages\billing\test\example.js",
    "TEST/Example.JS", "src/TOTAL.TEST.TSX", "mybuild/test/example.js", "redist/test/example.js",
])
def test_existing_suffixes_separators_and_case_convention_remain_supported(path):
    assert is_js_test_path(path)


@pytest.mark.parametrize("path", [
    "src/example.js", "src/example.ts", "src/example.mts", "src/example.cts",
    "tests/example.js", "src/testing.js", "src/latest.js", "contest/example.js",
    "test-support/example.js", "testdata/example.js", "src/test.example.js",
    "src/test_total.js", "test/example.jsx", "test/example.tsx", "test/example.json",
    "test/example.py", "test/example.js.map", "test/example.js.backup", "test/example",
    "test/", "total.test.js/", "",
    "node_modules/pkg/test/example.js", "test/node_modules/pkg/example.js",
    "packages/pkg/node_modules/pkg/total.test.js", "dist/test/example.js", "build/test.js",
    "test/build/example.js", "test/dist/example.ts", ".git/test/example.js", ".venv/test.js",
    "test/.pytest_cache/example.js", "htmlcov/test/example.js", "NODE_MODULES/pkg/test.js",
])
def test_unrelated_sources_and_generated_dependencies_are_not_test_paths(path):
    assert not is_js_test_path(path)
    assert not frontend_test_path(path)


def _source(body):
    return ('import assert from "node:assert/strict";\n'
            'import { test } from "node:test";\n'
            'test("total", () => {\n  ' + body + '\n});\n').encode()


def _analyze(path, before, after):
    context = ReportContext(collect_locations=False)
    ir, findings, verdict = analyze(
        [FileChange(path, "modified", _source(before), _source(after))],
        Config(), Contract(), [], datetime.date(2026, 9, 23), report_context=context,
    )
    return ir, findings, verdict, context


@pytest.mark.parametrize("path", [
    "test/example.js", "test.js", "test-total.cjs", "total_test.mjs",
    "nested/total-test.ts", "nested/total.test.cts", "packages/api/test/example.mts",
])
def test_node_default_paths_block_real_weakening_through_the_engine(path):
    ir, findings, verdict, context = _analyze(
        path, "assert.strictEqual(total([2, 3]), 5);", "assert.ok(total([2, 3]));",
    )
    assert verdict == "block"
    assert [(finding.rule, finding.severity) for finding in findings] == [("ASSERT_WEAKENED", "high")]
    assert ir.files[0].role == "test"
    assert context.coverage_files == [(path, "before"), (path, "after")]
    assert context.coverage_gaps == []


@pytest.mark.parametrize("path", ["test/example.js", "test.js", "nested/total_test.mts"])
def test_node_default_paths_preserve_unchanged_assertions(path):
    assertion = "assert.strictEqual(total([2, 3]), 5);"
    _ir, findings, verdict, _context = _analyze(path, assertion, assertion + " // explanation")
    assert findings == []
    assert verdict == "pass"


def test_node_default_paths_report_unsupported_assertions_on_both_sides():
    _ir, findings, verdict, context = _analyze(
        "test/example.js", "assert.match(value, /^ready$/);", "assert.match(value, /./);",
    )
    assert findings == []
    assert verdict == "pass"
    assert [(gap.side, gap.callee) for gap in context.coverage_gaps] == [
        ("before", "assert.match"), ("after", "assert.match"),
    ]


@pytest.mark.parametrize("path", ["src/example.js", "src/example.mts", "contest/example.js"])
def test_production_source_is_not_reclassified_by_assertion_shaped_contents(path):
    ir, findings, verdict, context = _analyze(
        path, "assert.strictEqual(total([2, 3]), 5);", "assert.ok(total([2, 3]));",
    )
    assert ir.files[0].role == "prod"
    assert ir.files[0].units == []
    assert findings == []
    assert verdict == "pass"
    assert context.coverage_files == []


@pytest.mark.parametrize("path", ["node_modules/pkg/test/example.js", "build/test.js", "dist/total.test.js"])
def test_generated_paths_stay_out_of_engine_evidence(path):
    ir, findings, verdict, context = _analyze(
        path, "assert.strictEqual(total([2, 3]), 5);", "assert.ok(total([2, 3]));",
    )
    assert ir.files == []
    assert findings == []
    assert verdict == "pass"
    assert context.coverage_files == []


@pytest.mark.parametrize("old,new", [
    ("test/example.js", "src/example.js"),
    ("example.test.js", "src/example.js"),
    ("test-example.mjs", "src/example.mjs"),
    ("packages/api/test/example.cts", "packages/api/src/example.cts"),
    ("test/example.js", "build/test/example.js"),
])
def test_renaming_js_out_of_collection_retains_the_disappeared_test(old, new):
    source = _source("assert.strictEqual(total([2, 3]), 5);")
    context = ReportContext(collect_locations=False)
    ir, findings, verdict = analyze(
        [FileChange(new, "renamed", source, source, old_path=old)],
        Config(), Contract(), [], datetime.date(2026, 9, 23), report_context=context,
    )
    assert verdict == "block"
    assert [(finding.rule, finding.severity, finding.path) for finding in findings] == [
        ("TEST_DISABLED", "high", old),
    ]
    assert (old, "before") in context.coverage_files
    assert any(file.path == old and file.role == "test" for file in ir.files)


@pytest.mark.parametrize("old,new", [
    ("test/example.js", "test/moved.js"),
    ("test/example.js", "src/example.test.js"),
    ("example.test.js", "test/example.js"),
    ("test-example.mts", "example_test.mts"),
    ("src/example.js", "src/renamed.js"),
])
def test_collection_preserving_and_production_moves_remain_benign(old, new):
    source = _source("assert.strictEqual(total([2, 3]), 5);")
    _ir, findings, verdict = analyze(
        [FileChange(new, "renamed", source, source, old_path=old)],
        Config(), Contract(), [], datetime.date(2026, 9, 23),
    )
    assert findings == []
    assert verdict == "pass"


def test_a_move_between_supported_names_does_not_hide_weakening():
    _ir, findings, verdict = analyze(
        [FileChange("src/example.test.js", "renamed",
                    _source("assert.strictEqual(total([2, 3]), 5);"),
                    _source("assert.ok(total([2, 3]));"), old_path="test/example.js")],
        Config(), Contract(), [], datetime.date(2026, 9, 23),
    )
    assert verdict == "block"
    assert [(finding.rule, finding.severity) for finding in findings] == [("ASSERT_WEAKENED", "high")]


@pytest.mark.parametrize("mutation,rule", [("weaken", "ASSERT_WEAKENED"), ("rename", "TEST_DISABLED")])
def test_cli_detects_loss_in_node_test_directory(tmp_path, mutation, rule):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-b", "main")
    git("config", "user.name", "path-test")
    git("config", "user.email", "path-test@example.invalid")
    git("config", "commit.gpgsign", "false")
    path = tmp_path / "test/example.js"
    path.parent.mkdir()
    path.write_bytes(_source("assert.strictEqual(total([2, 3]), 5);"))
    git("add", "--all")
    git("commit", "-m", "exact assertion")
    if mutation == "weaken":
        path.write_bytes(_source("assert.ok(total([2, 3]));"))
        git("commit", "-am", "weaken assertion")
    else:
        (tmp_path / "src").mkdir()
        git("mv", "test/example.js", "src/example.js")
        git("commit", "-m", "move outside test collection")
    result = subprocess.run(
        [sys.executable, "-m", "checkwash", "check", "HEAD~1..HEAD", "--repo", str(tmp_path), "--format", "json"],
        capture_output=True, encoding="utf-8",
        env={**os.environ, "GREENWASH_TODAY": "2026-09-23", "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 1, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["verdict"] == "block"
    assert [(finding["rule"], finding["severity"], finding["path"]) for finding in payload["findings"]] == [
        (rule, "high", "test/example.js"),
    ]
    assert "analysis incomplete" not in result.stderr
