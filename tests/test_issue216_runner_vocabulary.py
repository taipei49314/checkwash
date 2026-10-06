"""Runners named only in command position: `node --test`, mocha, ava, tap, `bun test` and the rest (#216).

checkwash decided whether a command runs the tests from a fixed list of
runner names (`roles._TEST_RUNNER_TOKENS`) that held none of `node --test`,
`mocha`, `ava`, `tap`, `bun test`, `deno test`, `hatch test`, `just test`,
`poe test` or `pdm test`. A shell script whose only runner was one of them
stayed production, so `node --test || true` hid its own swallow and bought
the opaque exemption that held an assertion weakened beside it at warn
(row 87's double effect). The same gap reached workflow steps, manifest
scripts and pre-commit hooks, and gave a pre-commit hook moving from
`pytest` to `hatch test` the false reason "pytest is no longer run".

Ruling (2026-10-03, #196): one shared predicate with 191.5's. The new names
match only in command content (runner-shaped scripts, workflow `run:`,
manifest script values, hook entries) and only in command position, never
as words over arbitrary file content; the opaque-exemption denial keeps
today's tokens; `--test-only` (187.1) is a narrowing token.
"""
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.ci_control_flow import control_flow_weakenings, holds_runner_site
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.roles import (
    _is_runner_script,
    _mentions_test_runner,
    _runs_test_command,
    _test_commands,
)
from checkwash.runner_command import (
    invokes_named_runner,
    invokes_positional_runner,
    invokes_test_runner,
)

TODAY = datetime.date(2026, 10, 5)


# --- the predicate: command position only -----------------------------------------------------


@pytest.mark.parametrize("command", [
    "node --test",
    "node --experimental-test-coverage --test",
    "npx mocha",
    "npx --yes mocha --reporter dot",
    "npm exec mocha",
    "npm exec -- mocha",
    "npm exec -w packages/api mocha",
    "yarn mocha",
    "pnpm dlx ava",
    "bunx tap",
    "bun x tap",
    "npx ava",
    "npx tap",
    "tap",
    "./node_modules/.bin/mocha",
    "bun test",
    "deno test --allow-read",
    "hatch test",
    "just test",
    "just test-unit",
    "poe test",
    "poe test:fast",
    "pdm test",
    "cross-env NODE_ENV=test mocha",
    "nyc mocha",
    "c8 node --test",
    "FOO=1 mocha",
    "bash -c 'mocha'",
    'sh -ec "npx ava"',
    "cd app && npx mocha",
    "if mocha; then :; fi",
    "mocha || true",
    "node --test || true",
    "\t@node --test",
    "\t-node --test",
])
def test_a_runner_in_command_position_runs(command):
    assert invokes_positional_runner(command)
    assert invokes_test_runner(command)
    assert not invokes_named_runner(command)


@pytest.mark.parametrize("command", [
    pytest.param("node --test-only", id="test-only-alone"),
    pytest.param("node app.js --test", id="script-argument"),
    pytest.param('echo "run mocha"', id="echo"),
    pytest.param("echo mocha", id="echo-bare"),
    pytest.param("npm i -D mocha", id="npm-install"),
    pytest.param("yarn add mocha", id="yarn-add"),
    pytest.param("pnpm add tap", id="pnpm-add"),
    pytest.param("bun add tap", id="bun-add"),
    pytest.param("pdm run test", id="pdm-run"),
    pytest.param("hatch run test", id="hatch-run"),
    pytest.param("deno run app.ts", id="deno-run"),
    pytest.param("just build", id="just-build"),
    pytest.param("node scripts/build.js", id="node-script"),
    pytest.param("bash scripts/x.sh", id="shell-script-file"),
    pytest.param("# mocha", id="comment"),
    pytest.param("cat <<EOF\nmocha\nEOF", id="heredoc-body"),
    pytest.param("import { tap } from 'rxjs'", id="rxjs-import"),
    pytest.param("const mocha = 1", id="identifier"),
    pytest.param("x-node --test", id="other-command"),
])
def test_a_runner_name_out_of_command_position_runs_nothing(command):
    assert not invokes_positional_runner(command)
    assert not invokes_test_runner(command)


@pytest.mark.parametrize("command", [
    pytest.param("out=$(mocha || true)", id="substitution"),
    pytest.param("echo `npx tap`", id="backticks"),
    pytest.param("echo $(node --test)", id="substitution-in-echo"),
    pytest.param("bash <<EOF\nnode --test\nEOF\n", id="heredoc-to-bash"),
    pytest.param("sudo bash <<EOF\nava\nEOF\n", id="heredoc-to-wrapped-bash"),
    pytest.param("eval npx mocha", id="eval"),
    pytest.param("bash -o pipefail -c 'mocha || true'", id="shell-option-value"),
    pytest.param("bash -eo pipefail -c 'node --test'", id="shell-option-cluster"),
    pytest.param("nice -n 10 mocha", id="wrapper-option-value"),
    pytest.param("sudo -u ci npx mocha", id="sudo-user"),
    pytest.param("timeout 600 npx mocha", id="timeout"),
    pytest.param("timeout -s KILL 10m tap", id="timeout-options"),
    pytest.param("time -p mocha", id="time-options"),
    pytest.param("exec -a runner mocha", id="exec-name"),
    pytest.param("command mocha", id="command"),
    pytest.param("for f in a b; do tap $f; done", id="loop-body"),
])
def test_a_runner_behind_a_wrapper_a_shell_or_a_substitution_runs(command):
    assert invokes_positional_runner(command)
    assert invokes_test_runner(command)


@pytest.mark.parametrize("command", [
    pytest.param("command -v mocha >/dev/null || npm i -g mocha", id="command-v"),
    pytest.param("sudo -E apt-get install tap", id="sudo-install"),
    pytest.param("cat <<'EOF'\nnode --test\nEOF\n", id="quoted-heredoc-to-cat"),
    pytest.param("x=$(echo just testing)", id="substituted-echo"),
    pytest.param("eval \"$(ssh-agent)\"", id="eval-without-runner"),
])
def test_a_wrapper_or_substitution_that_runs_no_runner_runs_nothing(command):
    assert not invokes_positional_runner(command)


def test_nesting_past_what_the_reader_follows_keeps_its_names():
    import shlex

    nested = "mocha"
    for _ in range(7):
        nested = "sh -c " + shlex.quote(nested)
    assert invokes_positional_runner(nested)
    plain = "make"
    for _ in range(7):
        plain = "sh -c " + shlex.quote(plain)
    assert not invokes_positional_runner(plain)


def test_the_tokens_it_had_keep_their_whole_word_reading():
    # 191.5's predicate is unchanged for its own names.
    assert invokes_test_runner("pytest") and invokes_named_runner("pytest")
    assert invokes_test_runner("cd app && make test")
    assert not invokes_test_runner("echo pytest")
    assert not invokes_test_runner("pip install pytest")


def test_text_the_lexer_cannot_follow_is_split_on_its_separators():
    # An unterminated quote: the lexer gives up, and a name that starts a
    # command still counts.
    assert invokes_positional_runner("npx mocha; echo 'unterminated")
    assert not invokes_positional_runner("echo 'unterminated mocha")


# --- command content: scripts, manifests, the one hop ------------------------------------------


def _script(command):
    return f"#!/usr/bin/env bash\nset -euo pipefail\n{command}\n".encode()


@pytest.mark.parametrize("command", ["node --test", "npx mocha", "bun test", "hatch test"])
def test_a_script_that_runs_a_positional_runner_is_the_test_command(command):
    assert _runs_test_command(_script(command))
    assert _is_runner_script("scripts/test.sh", _script(command), _script(command))


def test_prose_and_identifiers_do_not_make_production_code_a_runner():
    prose = b'// Like mocha, this reporter can tap into the stream.\nexport const tap = (x) => x;\n'
    assert not _runs_test_command(prose)
    assert not _is_runner_script("scripts/tap.sh", prose, prose)


def test_the_opaque_exemption_denial_keeps_the_tokens_it_had():
    # Ruled: `_mentions_test_runner` keeps today's tokens.
    change = FileChange("tools/run", "modified", _script("node --test"), _script("node --test || true"))
    assert not _mentions_test_runner(change)
    assert _mentions_test_runner(FileChange("tools/run", "modified", _script("pytest"), _script("pytest -q")))


def _pkg(scripts):
    body = ",".join(f'"{name}": "{command}"' for name, command in scripts.items())
    return ('{"name": "billing", "scripts": {' + body + "}}").encode()


def test_a_manifest_script_that_runs_a_positional_runner_is_part_of_the_test_command():
    assert _test_commands("package.json", _pkg({"test": "jest", "ci": "mocha", "build": "tsc"})) == {
        "ci": "mocha", "test": "jest"}
    assert _test_commands("package.json", _pkg({"test": "jest", "unit": "node --test test/"})) == {
        "test": "jest", "unit": "node --test test/"}
    # A name in a value that is no command in position stays out.
    assert _test_commands("package.json", _pkg({"test": "jest", "docs": "echo see mocha docs"})) == {
        "test": "jest"}


# --- the diff-level rows of the issue ------------------------------------------------------------

TEST_B = b'''import { test } from "node:test";
import assert from "node:assert";
import { invoiceTotal } from "../src/billing.js";

test("computes invoice total with tax", () => {
  const items = [{ price: 10.0, qty: 3 }, { price: 5.0, qty: 9 }];
  assert.strictEqual(invoiceTotal(items), 78.75);
});
'''
TEST_A = TEST_B.replace(b"assert.strictEqual(invoiceTotal(items), 78.75);", b"assert.ok(invoiceTotal(items));")


def run(*changes):
    _ir, findings, verdict = analyze(list(changes), Config(), Contract(), [], TODAY)
    return verdict, sorted((f.rule, f.severity, tuple(f.escalators), tuple(f.deescalators)) for f in findings)


@pytest.mark.parametrize("command", [
    "node --test", "npx mocha", "npx ava", "npx tap", "bun test", "deno test",
    "hatch test", "just test", "poe test", "pdm test",
])
def test_a_swallowed_runner_script_blocks_beside_a_weakened_assertion(command):
    # R1-R6: the script is the test command, its swallow is a weakening, and
    # it buys no exemption for the assertion weakened beside it.
    verdict, findings = run(
        FileChange("scripts/test.sh", "modified", _script(command), _script(command + " || true")),
        FileChange("test/billing.test.js", "modified", TEST_B, TEST_A),
    )
    assert verdict == "block"
    assert findings == [
        ("ASSERT_WEAKENED", "high", ("NO_PROD_CHANGE_IN_DIFF",), ()),
        ("CI_WORKFLOW_TOUCHED", "high", ("CI_TEST_COMMAND_WEAKENED",), ()),
    ]


def test_a_script_that_stops_running_a_positional_runner_no_longer_invokes_the_suite():
    verdict, findings = run(FileChange("scripts/test.sh", "modified", _script("npx mocha"), _script("echo skipped")))
    assert verdict == "block"
    assert findings == [("CI_WORKFLOW_TOUCHED", "high", ("CI_TEST_COMMAND_WEAKENED",), ())]


def test_a_no_op_branch_around_a_positional_runner_is_a_swallow():
    verdict, findings = run(FileChange("scripts/test.sh", "modified", _script("node --test"),
                                       _script("if ! node --test; then :; fi")))
    assert verdict == "block"
    assert findings == [("CI_WORKFLOW_TOUCHED", "high", ("CI_TEST_COMMAND_WEAKENED",), ())]


def test_a_make_recipe_that_ignores_a_positional_runner_failing_is_a_swallow():
    verdict, findings = run(FileChange("Makefile", "modified", b"test:\n\tnode --test\n", b"test:\n\t-node --test\n"))
    assert verdict == "block"
    assert findings == [("CI_WORKFLOW_TOUCHED", "high", ("CI_TEST_COMMAND_WEAKENED",), ())]


def test_one_hop_reaches_a_script_that_runs_a_positional_runner():
    # Row 89's hop: the entry script only calls the test script.
    heads = {"scripts/run-tests.sh": b"#!/bin/sh -e\nnode --test\n"}
    _ir, findings, verdict = analyze(
        [FileChange("scripts/ci.sh", "modified", b"#!/bin/sh -e\n./scripts/run-tests.sh\n",
                    b"#!/bin/sh -e\n./scripts/run-tests.sh || true\n")],
        Config(), Contract(), [], TODAY, head_reader=heads.get)
    assert verdict == "block"
    assert [(f.rule, f.severity) for f in findings] == [("CI_WORKFLOW_TOUCHED", "high")]


@pytest.mark.parametrize("after", ["pytest", "npx jest", "bun test"])
def test_swapping_a_positional_runner_for_another_runner_is_consolidation(after):
    verdict, findings = run(FileChange("scripts/test.sh", "modified", _script("node --test"), _script(after)))
    assert verdict == "pass"
    assert findings == [("CI_WORKFLOW_TOUCHED", "warn", (), ())]


def _precommit(entry):
    hook = "" if entry is None else (
        "  - repo: local\n    hooks:\n      - id: tests\n        name: tests\n"
        f"        entry: {entry}\n        language: system\n        pass_filenames: false\n")
    return ("repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit\n    rev: v0.6.2\n"
            "    hooks:\n      - id: ruff\n" + hook).encode()


@pytest.mark.parametrize("after", ["hatch test", "just test", "poe test", "pdm test"])
def test_a_hook_moving_from_pytest_to_a_named_task_runner_is_a_swap(after):
    # H1, H2: 191.7's false reason, "pytest is no longer run by any pre-commit hook".
    assert control_flow_weakenings(".pre-commit-config.yaml", _precommit("pytest"), _precommit(after)) == []


def test_removing_the_only_node_test_hook_removes_the_suite():
    # H4
    reasons = control_flow_weakenings(".pre-commit-config.yaml", _precommit("node --test"), _precommit(None))
    assert reasons and "node --test" in reasons[0]


def _workflow(command):
    return ("name: ci\non:\n  pull_request:\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
            f"      - uses: actions/checkout@v4\n      - run: npm ci\n      - run: {command}\n").encode()


@pytest.mark.parametrize("command,ran", [
    ("node --test", True), ("npx mocha", True), ("bun test", True),
    ('echo "run mocha"', False), ("npm i -D mocha", False), ("bun add tap", False),
])
def test_a_workflow_holds_a_runner_site_by_its_run_commands(command, ran):
    assert holds_runner_site(".github/workflows/ci.yml", _workflow(command)) is ran


def test_deleting_a_workflow_whose_suite_is_node_test_removes_a_gate():
    verdict, findings = run(FileChange(".github/workflows/ci.yml", "deleted", _workflow("node --test"), None))
    assert verdict == "block"
    assert findings == [("CI_WORKFLOW_TOUCHED", "high", ("CI_TEST_COMMAND_WEAKENED",), ())]
    # A workflow that only installs mocha ran no suite.
    verdict, findings = run(FileChange(".github/workflows/ci.yml", "deleted", _workflow("npm i -D mocha"), None))
    assert (verdict, findings) == ("pass", [("CI_WORKFLOW_TOUCHED", "warn", (), ())])


def test_a_disabled_node_test_step_still_counts_for_the_deletion_rule():
    # As row 69's token scan counts `pytest` wherever it stands in a deleted
    # workflow, a dead site is a site.
    workflow = _workflow("node --test") + b"        if: false\n"
    assert holds_runner_site(".github/workflows/ci.yml", workflow)
    verdict, _findings = run(FileChange(".github/workflows/ci.yml", "deleted", workflow, None))
    assert verdict == "block"


def test_deleting_a_pre_commit_config_whose_only_suite_is_node_test_removes_a_gate():
    verdict, findings = run(FileChange(".pre-commit-config.yaml", "deleted", _precommit("node --test"), None))
    assert verdict == "block"
    assert findings == [("CI_WORKFLOW_TOUCHED", "high", ("CI_TEST_COMMAND_WEAKENED",), ())]


def test_test_only_narrows_the_test_command():
    # T1 (187.1): node runs only the tests marked `only`.
    verdict, findings = run(FileChange("package.json", "modified", _pkg({"test": "node --test"}),
                                       _pkg({"test": "node --test --test-only"})))
    assert verdict == "block"
    assert findings == [("CI_WORKFLOW_TOUCHED", "high", ("CI_TEST_COMMAND_WEAKENED",), ())]


def test_the_collection_inventory_reads_the_runs_it_had():
    # #173's inventory reads pytest's runs: a step that runs `node --test`
    # beside `pytest` runs no pytest it cannot parse, so it keeps the reading
    # it had (`invokes_named_runner`).
    from checkwash.collection_inventory import _calls

    workflow = _workflow("node --test").replace(b"      - run: npm ci\n", b"      - run: pytest -q\n")
    assert _calls(".github/workflows/ci.yml", workflow) == [("pytest", "-q")]
    # A line that does not lex is read the same way.
    unread = _workflow('node --test "unterminated').replace(b"      - run: npm ci\n", b"      - run: pytest -q\n")
    assert _calls(".github/workflows/ci.yml", unread) == [("pytest", "-q")]
