"""Conservative collection reach for pytest arguments containing variables.

The reach check uses the wildcard characters visible in a path argument.
It does not evaluate expansions or infer where an opaque directory's tests
would actually run. These cases pin the 0.13.2 reading of runner text,
including the literal prefix that bounds a wildcard.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.collection_inventory import environment_reached, opaque_reached

SETUP = {"setup.cfg": b"[tool:pytest]\ntestpaths = tests\n"}
NO_TESTPATHS = {"setup.cfg": b"[tool:pytest]\naddopts = -ra\n"}
ARRAY_WORKFLOW = (b"jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: |\n"
                  b"          tests=(tests/a tests/b)\n          pytest \"${tests[@]}\"\n")
# A hidden directory pytest's default norecursedirs skips, and one it recurses into.
HIDDEN, PLAIN = ".vendor/lib", "vendor/lib"
GITLINK = "1" * 40
SOURCES = {
    "src/billing.py": b"def invoice_total():\n    return 1\n",
    "tests/test_billing.py": (b"from src.billing import invoice_total\n\n"
                              b"def test_invoice_total():\n    assert invoice_total() == 2\n"),
}
NEW_PROVIDER = {"tests/src/billing.py": b"def invoice_total():\n    return 2\n"}


@pytest.mark.parametrize("runner, reached", [
    ({".github/workflows/ci.yml": ARRAY_WORKFLOW}, True),
    ({"Makefile": b"test:\n\tpytest \"${tests[@]}\"\n"}, True),
    ({"scripts/test.sh": b"#!/bin/bash\npytest \"${tests[*]}\"\n"}, True),
    ({"scripts/test.sh": b"#!/bin/bash\npytest \"${tests[0]}\"\n"}, True),
    ({"scripts/test.sh": b"#!/bin/sh\npytest $*\n"}, True),
    ({"scripts/test.sh": b"#!/bin/sh\npytest ${1:?}\n"}, True),
    ({"scripts/test.sh": b"#!/bin/bash\npytest \"tests/${suites[@]}\"\n"}, False),
    ({"scripts/test.sh": b"#!/bin/sh\npytest \"$@\"\n"}, False),
    ({"scripts/test.sh": b"#!/bin/sh\npytest $1\n"}, False),
    ({"scripts/test.sh": b"#!/bin/bash\npytest ${suites[${i}]}\n"}, True),
], ids=["array_in_a_workflow", "array_in_a_makefile", "array_star", "array_element", "dollar_star",
        "required_parameter", "array_under_a_directory", "dollar_at_as_before", "dollar_one_as_before",
        "an_index_written_with_braces"])
@pytest.mark.parametrize("directory", [HIDDEN, PLAIN])
def test_a_variable_argument_reaches_from_its_literal_prefix(runner, reached, directory):
    expected = directory if reached else None
    assert opaque_reached((directory,), {**SETUP, **runner}, []) == expected


@pytest.mark.parametrize("runner", [
    {".github/workflows/ci.yml": ARRAY_WORKFLOW},
    {"Makefile": b"test:\n\tpytest \"${tests[@]}\"\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest \"${tests[*]}\"\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest \"${tests[0]}\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest $*\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest ${1:?}\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest ${suites[${i}]}\n"},
    {".github/workflows/ci.yml": b"jobs:\n  t:\n    steps:\n      - run: pytest \"${{ matrix.tests[0] }}\"\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest tests/unit \"${extra[@]}\"\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest -q --assert plain \"${EXTRA[@]}\"\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest -q --splits 2 --group \"${GROUP:?}\"\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest $OPTS \"${extra[@]}\"\n"},
], ids=["array_in_a_workflow", "array_in_a_makefile", "array_star", "array_element", "dollar_star",
        "required_parameter", "an_index_written_with_braces", "a_quoted_workflow_expression",
        "beside_a_path_the_run_names", "beside_an_option_value_read_as_a_path", "as_an_option_value_read_as_a_path",
        "beside_a_plain_variable"])
def test_a_root_wildcard_in_an_argument_can_reach_hidden_directories(runner):
    # An empty literal prefix covers every opaque directory, including ones
    # excluded from the configured testpaths or from default recursion.
    assert opaque_reached(("tests/vendor",), {**SETUP, **runner}, []) == "tests/vendor"
    assert opaque_reached((PLAIN,), {**NO_TESTPATHS, **runner}, []) == PLAIN
    assert opaque_reached((HIDDEN,), {**NO_TESTPATHS, **runner}, []) == HIDDEN


def test_an_expansion_that_holds_a_slash_is_read_as_it_was():
    # The literal segment before the slash does not name either directory.
    runner = {"scripts/test.sh": b"#!/bin/bash\npytest \"${dir%/*}\"\n"}
    assert opaque_reached((PLAIN,), {**NO_TESTPATHS, **runner}, []) is None
    assert opaque_reached(("tests/vendor",), {**SETUP, **runner}, []) is None


@pytest.mark.parametrize("runner", [
    {"scripts/test.sh": b"#!/bin/sh\npytest \"$@\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest $1\n"},
], ids=["dollar_at", "dollar_one"])
def test_a_variable_that_was_never_read_as_a_wildcard_is_read_as_it_was(runner):
    # These arguments contain no wildcard or literal directory name.
    assert opaque_reached(("tests/vendor",), {**SETUP, **runner}, []) is None
    assert opaque_reached((PLAIN,), {**NO_TESTPATHS, **runner}, []) is None


def test_an_array_after_a_literal_directory_reaches_its_hidden_descendants():
    runner = {"scripts/test.sh": b"#!/bin/bash\npytest \"tests/${suites[@]}\"\n"}
    for directory, reached in (("tests", "tests"), ("tests/vendor", "tests/vendor"), ("tests/.cache/lib", "tests/.cache/lib"),
                               (PLAIN, None)):
        assert opaque_reached((directory,), {**SETUP, **runner}, []) == reached


@pytest.mark.parametrize("runner", [
    {"Makefile": b"test:\n\tpytest $?\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest \"${tests[@]:1}\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest ${name%%.*}\n"},
    {".github/workflows/ci.yml": b"jobs:\n  t:\n    steps:\n      - run: pytest \"${{ matrix.tests[0] }}\"\n"},
], ids=["a_special_parameter", "an_array_slice", "a_trimmed_variable", "a_quoted_workflow_expression"])
@pytest.mark.parametrize("directory", [HIDDEN, PLAIN])
def test_a_wildcard_character_inside_an_expansion_reaches_from_its_prefix(runner, directory):
    assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


@pytest.mark.parametrize("runner, directory", [
    ({"scripts/test.sh": b"#!/bin/sh\npytest tests/sh*$x\n"}, "tests/shared"),
    ({"scripts/test.sh": b"#!/bin/sh\npytest vendor/*$x\n"}, PLAIN),
    ({"scripts/test.sh": b"#!/bin/sh\npytest $x*\n"}, HIDDEN),
    ({"scripts/test.sh": b"#!/bin/sh\npytest '*a$'\n"}, HIDDEN),
    ({"scripts/t.ps1": b"pytest $args[0]\r\n"}, HIDDEN),
    ({"scripts/t.ps1": b"pytest $tests[$i]\r\n"}, HIDDEN),
    ({"scripts/test.sh": b"#!/bin/bash\nx=a\npytest tests/sh[$x]red\n"}, "tests/shared"),
    ({"scripts/test.sh": b"#!/bin/sh\npytest ${TESTS:-*}\n"}, HIDDEN),
    ({"scripts/test.sh": b"#!/bin/sh\npytest tests/${SUITE:-*}\n"}, "tests/shared"),
    ({"scripts/test.sh": b"#!/bin/sh\npytest ${TESTS:+*}\n"}, HIDDEN),
    ({"scripts/test.sh": b"#!/bin/sh\npytest ${TESTS:=te*}\n"}, HIDDEN),
], ids=["a_star_before_the_variable", "a_star_beside_the_variable", "a_star_after_the_variable",
        "a_dollar_that_starts_no_expansion", "a_powershell_index", "a_powershell_index_that_is_a_variable",
        "a_bracket_set_around_a_variable", "a_default_that_is_a_wildcard", "a_default_wildcard_under_a_directory",
        "an_alternative_that_is_a_wildcard", "an_assigned_default_that_holds_a_wildcard"])
def test_a_wildcard_outside_the_expansion_is_still_one(runner, directory):
    # Wildcards beside a variable and inside its default are read from the literal prefix.
    assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


@pytest.mark.parametrize("line", [
    b"pytest || exit $?",
    b"pytest -v --cov | tee pytest.log; exit ${PIPESTATUS[0]}",
    b"pytest \"$@\" || exit $?",
    b"pytest tests && echo $*",
    b"pytest tests; echo \"${done[@]}\"",
    b"pytest \"${tests[@]}\" \\\n  vendor/lib",
    b"pytest -q||exit $?",
    b"pytest -q&&exit $?",
    b"pytest -q;exit $?",
    b"pytest -q ;exit $?",
    b"pytest -q;if [ $? -ne 0 ]; then exit 1; fi",
    b"pytest tests||exit $?",
    b"pytest -q |& tee \"${LOGS[0]}\"",
    b"pytest -q >\"${LOG:?}\"",
    b"pytest -q 2>&1 | tee \"${LOGS[0]}\"",
    b"pytest $(ls tests) \"${more[@]}\"",
    b"pytest \"${extra[@]}\"; echo done",
    b"if pytest \"${extra[@]}\"; then echo ok; else exit 1; fi",
    b"pytest $*; echo done",
    b"pytest -q < \"${IN[0]}\"",
    b"pytest `cat list` \"${more[@]}\"",
    b"pytest \"${extra[@]}\" vendor/lib; echo done",
    b"pytest $* vendor/lib;echo done",
    b"pytest $* vendor/lib|tee log",
    b"( cd . && pytest $* vendor/lib)",
    b"if pytest $* vendor/lib; then echo ok; fi",
    b"pytest $* vendor/lib>log.txt",
    b"pytest $* vendor/lib& wait",
    b"pytest \"${extra[@]}\" 3;echo done",
    b"pytest $* $(echo vendor/lib)",
    b"run() { pytest \"${extra[@]}\" vendor/lib; }",
    b"python -m pytest \"${extra[@]}\" vendor/lib; echo done",
    b"pytest \"${extra[@]}\" --base-url=http://localhost/#/ vendor/lib",
    b"pytest $* $'vendor/lib'",
    b"pytest $* $\"vendor/lib\"",
    b"pytest $* $(\necho vendor/lib)",
    b"pytest \"${extra[@]}\" -k \"(test_invoice_total or x)\" vendor/lib; echo done",
    b"pytest \"${extra[@]}\" tests/unit && pytest vendor/lib; echo done",
    b"pytest \"${extra[@]}\" 2>&1 vendor/lib; echo done",
    b"pytest \"${extra[@]}\" `pwd`/vendor/lib",
    b"pytest $* `echo vendor/lib` -q",
    b"pytest \"${extra[@]}\" vendor/my\\ lib",
], ids=["a_bare_run_then_exit_status", "a_piped_run_then_pipestatus", "a_parameter_run_then_exit_status",
        "a_named_run_then_another_command", "a_named_run_then_a_semicolon", "an_array_on_a_line_that_continues",
        "an_or_written_against_a_word", "an_and_written_against_a_word", "a_semicolon_written_against_a_word",
        "a_semicolon_that_starts_a_word", "a_semicolon_then_a_condition", "a_named_run_and_an_or_against_it",
        "a_pipe_with_stderr", "a_redirection", "a_redirection_then_a_pipe", "a_command_substitution",
        "an_array_with_a_semicolon_against_it", "an_array_in_a_condition", "a_star_with_a_semicolon_against_it",
        "a_redirected_input", "a_backtick_substitution", "a_path_with_a_semicolon_against_it",
        "a_path_glued_to_the_next_command", "a_path_with_a_pipe_against_it", "a_path_before_a_closing_parenthesis",
        "a_path_in_a_condition", "a_path_with_a_redirection_against_it", "a_path_with_an_ampersand_against_it",
        "a_path_of_digits_with_a_semicolon_against_it", "a_path_in_a_command_substitution", "a_function_body",
        "a_module_run_with_a_semicolon_against_its_path", "a_hash_inside_a_word", "a_dollar_quoted_path",
        "a_locale_quoted_path", "a_command_substitution_left_open", "a_path_glued_after_a_quoted_parenthesis",
        "a_second_run_with_a_glued_path", "a_path_glued_after_a_redirection", "a_path_behind_a_backtick_substitution",
        "a_backtick_substitution_then_an_option", "a_backslash_inside_the_line"])
@pytest.mark.parametrize("directory", [HIDDEN, PLAIN])
def test_a_wildcard_in_runner_text_keeps_its_reach_across_shell_operators(line, directory):
    # The reader uses the visible arguments even when shell syntax spans more than one command.
    runner = {"scripts/test.sh": b"#!/bin/bash\n" + line + b"\n"}
    assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


@pytest.mark.parametrize("command", [
    b"cd vendor/lib && pytest",
    b"pytest vendor/{lib,other}",
    b"pytest -o testpaths=vendor/lib",
    b"pytest --rootdir vendor/lib",
    b"pytest @args.txt",
    b"pytest $T",
], ids=["a_change_of_directory", "a_brace_list", "testpaths_given_as_an_option", "a_root_directory", "an_argument_file",
        "a_variable_that_holds_the_path"])
def test_an_array_argument_adds_a_wildcard_to_a_run(command):
    for suffix, expected in ((b"", None), (b' "${extra[@]}"', PLAIN)):
        runner = {"scripts/test.sh": b"#!/bin/bash\nT=vendor/lib\n" + command + suffix + b"\n"}
        assert opaque_reached((PLAIN,), {**SETUP, **runner}, []) == expected


@pytest.mark.parametrize("line", [
    b"pytest \"${tests[@]}\" | tee log",
    b"pytest \"${tests[@]}\" 2>&1",
    b"pytest \"${tests[@]}\" >log.txt",
    b"pytest \"${tests[@]}\" && echo ok",
    b"pytest \"${tests[@]}\" ;echo done",
    b"pytest \"${tests[@]}\" # the suites",
], ids=["a_pipe", "a_numbered_redirection", "a_redirection_against_its_file", "an_and", "a_semicolon_that_starts_a_word",
        "a_comment_after_a_blank"])
def test_an_array_before_an_operator_or_comment_keeps_its_reach(line):
    runner = {"scripts/test.sh": b"#!/bin/bash\n" + line + b"\n"}
    for directory in (HIDDEN, PLAIN):
        assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


STEPS = b"jobs:\n  test:\n    steps:\n"


@pytest.mark.parametrize("runner", [
    {".github/workflows/ci.yml": STEPS + b"      - run: >-\n          pytest \"${extra[@]}\"\n          vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run: pytest \"${extra[@]}\"\n          vendor/lib\n"},
    {".gitlab-ci.yml": b"test:\n  script: >\n    pytest \"${extra[@]}\"\n    vendor/lib\n  after_script:\n    - echo done\n"},
    {".gitlab-ci.yml": b"test:\n  script:\n    - pytest \"${extra[@]}\"\n      vendor/lib\n"},
    {"scripts/t.ps1": b"pytest \"${extra[@]}\" `\r\n  vendor/lib\r\n"},
    {"scripts/t.bat": b"pytest \"${extra[@]}\" ^\r\n  vendor/lib\r\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run:\n          pytest \"${extra[@]}\"\n          vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run:\n          >-\n          pytest \"${extra[@]}\"\n          vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run: !!str >-\n          pytest \"${extra[@]}\"\n          vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run: time\n          pytest \"${extra[@]}\"\n          vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run: pytest \"${extra[@]}\"\n          - vendor/lib\n"},
    {".github/workflows/ci.yaml": STEPS + b"      - run: >-\n          pytest \"${extra[@]}\"\n          vendor/lib\n"},
    {".github/workflows/ci.yml.j2": STEPS + b"      - run: >-\n          pytest \"${extra[@]}\"\n          vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run: >-\n          pytest \"${tests[@]}\"\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run: >-\n          pytest \"${tests[@]}\"\n\n          echo done\n"},
    {".github/workflows/ci.yml": STEPS + (b"      - run: >-\n          PYTHONPATH=src: pytest \"${extra[@]}\"\n"
                                          b"          vendor/lib\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - run: \"set -e;\n          FOO=a: pytest ${extra[@]}\n"
                                          b"          vendor/lib\"\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - run: \"set -e;\n      FOO=a: pytest ${extra[@]}\n"
                                          b"      vendor/lib\"\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - run: 'set -e;\n          - pytest ${extra[@]}\n"
                                          b"          vendor/lib'\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - run: \"true\n          x: |\n            pytest ${extra[@]}\n"
                                          b"            vendor/lib\"\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - run: echo start\n          - pytest \"${extra[@]}\"\n"
                                          b"          vendor/lib\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - run: |\n          echo start\n        env:\n          A: >-\n"
                                          b"            pytest \"${extra[@]}\"\n            vendor/lib\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - run: |\n        env: pytest \"${extra[@]}\"\n"
                                          b"          vendor/lib\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - run: pytest \"${extra[@]}\"\n        # the rest of the command\n"
                                          b"          vendor/lib\n")},
    {".github/workflows/ci.yml": STEPS + b"      - run: pytest \"${extra[@]}\"\n\tvendor/lib\n"},
    {".github/workflows/ci.yml~": STEPS + b"      - run: >-\n          pytest \"${extra[@]}\"\n          vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + (b"      - run: \"set -e;\n          echo one;\n"
                                          b"          FOO=a: pytest ${extra[@]}\n          vendor/lib\"\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - run: \"a\\\"\n        FOO=a: pytest ${extra[@]}\n"
                                          b"        vendor/lib\"\n")},
    {".github/workflows/ci.yml": STEPS + b"      - run: 'a\'\'\n        FOO=a: pytest ${extra[@]}\n        vendor/lib'\n"},
    {".github/workflows/ci.yml": STEPS + (b"      - run: \"echo 'hi';\n        FOO=a: pytest ${extra[@]}\n"
                                          b"        vendor/lib\"\n")},
    {".github/workflows/ci.yml": b"--- \"set -e;\nFOO=a: pytest ${extra[@]}\nvendor/lib\"\n"},
    {".github/workflows/ci.yml": STEPS + b"      - {name: t, run: pytest $* vendor/lib}\n"},
    {".github/workflows/ci.yml": STEPS + b"      - name: t\n        with: {a: 1,\n        run: pytest $*\n        vendor/lib}\n"},
    {".github/workflows/ci.yml": STEPS + (b"      - name: t\n        with: {a: \"}\", b: [c,\n        run: pytest $*\n"
                                          b"        vendor/lib]}\n")},
    {".github/workflows/ci.yml": STEPS + b"      - run: [\"x]\", pytest $*\n        vendor/lib]\n"},
    {".github/workflows/ci.yml": STEPS + (b"      - name: t\n        with: {a: 1, # c}\n        run: pytest $*\n"
                                          b"        vendor/lib}\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - name: t\n        with: {a: it's, b: \"x'}\n        run: pytest $*\n"
                                          b"        vendor/lib\"}\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - name: t\n        with: {a: \"x }\n        run: pytest $*\n"
                                          b"        vendor/lib\"}\n")},
    {".github/workflows/ci.yml": (b"jobs:\n  test:\n    steps: [{uses: actions/checkout@v4}, {run: pytest tests/unit},#]\n"
                                  b"    run: pytest $*\n    vendor/lib]\n")},
    {".github/workflows/ci.yml": (b"--- {name: ci, jobs: {test: {steps: [{uses: actions/checkout@v4}, {\n"
                                  b"run: pytest $*\nvendor/lib}]}}}\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - name: t\n        with:\n          {a: 1,\n        run: pytest $*\n"
                                          b"        vendor/lib}\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - run: &a \"echo note: x;\n        FOO=a: pytest ${extra[@]}\n"
                                          b"        vendor/lib\"\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - &a \"echo note: x;\n        FOO=a: pytest ${extra[@]}\n"
                                          b"        vendor/lib\"\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - run: &a\n            \"set -e;\n        FOO=a: pytest ${extra[@]}\n"
                                          b"        vendor/lib\"\n")},
    {".github/workflows/ci.yml": STEPS + b"      -\n        \"set -e;\n    FOO=a: pytest ${extra[@]}\n    vendor/lib\"\n"},
    {".github/workflows/ci.yml": STEPS + (b"      - !!str\n        \"set -e;\n      - pytest ${extra[@]}\n"
                                          b"      vendor/lib\"\n")},
    {".github/workflows/ci.yml": STEPS + b"      - pytest \"${extra[@]}\" --junitxml=a:b\n       vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + b"      - pytest \"${extra[@]}\" # note: x\n       vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run:\n        echo\n      - run: pytest \"${tests[@]}\"\n"},
    {".github/workflows/ci.yml": STEPS + (b"      - name: t\n        with:\n              x: y\r        run: pytest $*\n"
                                          b"          vendor/lib\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - name: t\n        with:\n              x: y\xc2\x85        run: pytest $*\n"
                                          b"          vendor/lib\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - name: t\n        with:\n              x: y\xe2\x80\xa8        run: pytest $*\n"
                                          b"          vendor/lib\n")},
    {".github/workflows/ci.yml": STEPS + (b"      - name: t\n        with:\n              x: y\xe2\x80\xa9        run: pytest $*\n"
                                          b"          vendor/lib\n")},
    {".github/workflows/ci.yml": STEPS + b"      - run: pytest $*\n      \xc2\x85          vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run: pytest $*\n      # c\xc2\x85          vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + (b"      - run: pytest $* --junitxml\n          \xc2\xa0# vendor/lib\n"
                                          b"        shell: bash\n")},
    {".github/workflows/ci.yml": STEPS + b"      - run: pytest $*\n          \xc2\xa0\n        shell: bash\n"},
    {".github/workflows/ci.yml": b"run: \xc2\xa0\n  - pytest $*\n  vendor/lib\n"},
    {".github/workflows/ci.yml": b"- \xc2\xa0\n  - pytest $*\n  vendor/lib\n"},
    {".github/workflows/ci.yml": b"run:\n  \xc2\xa0# x\n  - pytest $*\n  vendor/lib\n"},
    {".github/workflows/ci.yml": STEPS + (b"      - run: pytest $* --junitxml\n          \t# vendor/lib\n"
                                          b"        shell: bash\n")},
    {".github/workflows/ci.yml": b"jobs:\n\trun: pytest \"${tests[@]}\"\nnext: x\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run: !!str |\n          pytest \"${tests[@]}\"\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run:\n          |\n          pytest \"${tests[@]}\"\n"},
    {".github/workflows/ci.yml": STEPS + b"      - run:\n          !!str\n        FOO: pytest \"${tests[@]}\"\n"},
    {".github/workflows/ci.yml": STEPS + (b"      - name: t\n        with: {msg: don't}\n"
                                          b"        run: pytest \"${tests[@]}\"\n")},
    {".github/workflows/ci.yml": STEPS + b"      - [a]: b\n      - run: pytest \"${tests[@]}\"\n"},
    {".github/workflows/ci.yml": STEPS + b"      - &a run: |\n          pytest \"${tests[@]}\"\n"},
    {".github/workflows/ci.yml": STEPS + (b"      - name: t\n        with: {a:\"x\"}\n"
                                          b"        run: pytest \"${tests[@]}\"\n")},
    {".github/workflows/ci.yml": STEPS + b"      - name: t\n        with: [?]\n        run: pytest \"${tests[@]}\"\n"},
], ids=["a_folded_scalar", "a_scalar_that_goes_on_in_a_deeper_line", "a_folded_scalar_before_another_key",
        "a_sequence_entry_that_goes_on", "a_powershell_backtick", "a_batch_caret",
        "a_scalar_on_the_line_after_its_key", "a_folded_header_on_the_line_after_its_key", "a_folded_header_with_a_tag",
        "a_command_in_the_middle_of_a_scalar", "a_deeper_line_that_starts_with_a_dash", "a_yaml_suffix",
        "a_template_of_a_workflow", "the_last_line_of_a_folded_scalar", "a_folded_line_before_a_blank_one",
        "a_folded_line_that_looks_like_a_key", "a_quoted_line_that_looks_like_a_key",
        "a_quoted_line_at_its_key_s_depth", "a_quoted_line_that_looks_like_an_entry",
        "a_quoted_line_that_looks_like_a_literal_header", "a_plain_line_that_looks_like_an_entry",
        "a_folded_scalar_after_a_literal_one", "a_key_after_an_empty_literal_scalar",
        "a_comment_before_the_deeper_line", "a_deeper_line_behind_a_tab", "a_copy_of_a_workflow",
        "a_quoted_line_after_another_quoted_line", "a_quoted_scalar_with_an_escaped_quote",
        "a_quoted_scalar_with_a_doubled_quote", "a_quoted_scalar_that_holds_the_other_quote",
        "a_quoted_scalar_on_a_document_mark_s_line", "a_flow_mapping_as_a_step", "a_flow_mapping_that_goes_on",
        "a_flow_sequence_that_goes_on_after_a_quoted_bracket", "a_flow_sequence_with_a_quoted_bracket",
        "a_flow_mapping_that_goes_on_behind_a_comment", "a_quote_inside_a_plain_scalar_of_a_flow_mapping",
        "a_quoted_scalar_that_goes_on_in_a_flow_mapping", "a_flow_sequence_that_goes_on_behind_a_hash_against_a_comma",
        "a_flow_mapping_on_a_document_mark_s_line", "a_flow_mapping_on_the_line_after_its_key",
        "a_quoted_scalar_after_an_anchor",
        "a_quoted_entry_after_an_anchor_with_a_colon_in_it", "a_quoted_scalar_on_the_line_after_its_key_s_anchor",
        "a_quoted_scalar_on_the_line_after_a_dash", "a_quoted_scalar_on_the_line_after_an_entry_s_tag",
        "a_colon_inside_a_word", "a_colon_inside_a_comment", "text_at_its_key_s_own_depth",
        "a_carriage_return_inside_a_line", "a_next_line_character", "a_line_separator", "a_paragraph_separator",
        "a_deeper_line_behind_a_next_line_character", "a_deeper_line_behind_a_comment_and_a_next_line_character",
        "a_deeper_line_that_starts_with_a_no_break_space",
        "a_deeper_line_of_one_no_break_space", "a_value_of_one_no_break_space", "an_entry_of_one_no_break_space",
        "a_scalar_whose_first_line_starts_with_a_no_break_space", "a_deeper_line_with_a_tab_before_its_hash",
        "a_key_behind_a_tab",
        "a_literal_header_with_a_tag", "a_literal_header_on_the_line_after_its_key",
        "a_key_after_a_tag_on_a_line_of_its_own", "a_step_after_a_flow_mapping_with_a_quote_inside_a_word",
        "a_step_after_a_flow_sequence_that_is_a_key", "a_literal_header_after_its_key_s_anchor",
        "a_step_after_a_flow_mapping_with_a_quote_against_its_colon",
        "a_step_after_a_flow_sequence_that_holds_a_question_mark"])
@pytest.mark.parametrize("directory", [HIDDEN, PLAIN])
def test_a_line_that_goes_on_without_a_backslash_is_read_as_it_was(runner, directory):
    # These multiline runner forms keep the conservative reach of their array argument.
    assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


@pytest.mark.parametrize("workflow", [
    ARRAY_WORKFLOW + b"      - run: echo done\n",
    STEPS + b"      - run: pytest \"${tests[@]}\"\n        env:\n          CI: yes\n",
    STEPS + b"      - run: >-\n          echo started\n      - run: pytest \"${tests[@]}\"\n",
    STEPS + b"      - run: |-\n          pytest \"${tests[@]}\"\n        shell: bash\n",
    STEPS + b"      - name: tests\n        run: pytest \"${tests[@]}\"\n      - run: echo done\n",
    b"test:\n  script:\n    - pytest \"${tests[@]}\"\n    - echo done\n",
    b"test:\n  script:\n    - |\n      pytest \"${tests[@]}\"\n      echo done\n",
    b"\"my: job\":\n  script: pytest \"${tests[@]}\"\n  stage: test\n",
    b"---\ntest:\n  script:\n  - pytest \"${tests[@]}\"\n  - echo done\n",
    STEPS + b"      - run: |2\n            echo indented\n          pytest \"${tests[@]}\"\n",
    STEPS + (b"      - name: t\n        with: {\"python-version\": \"3.12\", cache: [pip, 'x']}  # pinned\n"
             b"        run: pytest \"${tests[@]}\"\n      - run: echo done\n"),
    (b"jobs:\n  test:\n    strategy:\n      matrix:\n        os: [\"ubuntu-latest\", \"windows-latest\"]\n"
     b"    steps:\n      - run: pytest \"${tests[@]}\"\n"),
    STEPS + b"      - &step\n        run: pytest \"${tests[@]}\"\n      - run: echo done\n",
    STEPS + b"      -\n        run: pytest \"${tests[@]}\"\n",
    STEPS + b"      - run: pytest \"${tests[@]}\" | tee log\n",
    STEPS + b"      - name: \"unit tests\"\n        run: pytest \"${tests[@]}\"\n",
], ids=["a_line_of_a_literal_scalar", "a_key_line_before_another_key", "a_step_after_a_folded_scalar",
        "a_literal_scalar_before_another_key", "a_key_line_before_the_next_step", "a_sequence_entry_before_another",
        "a_literal_scalar_as_a_sequence_entry", "a_key_under_a_quoted_key_with_a_colon",
        "an_entry_at_its_key_s_depth_after_a_document_mark", "a_literal_scalar_with_an_indentation_indicator",
        "a_key_after_a_flow_mapping_closed_on_its_line", "a_step_after_a_flow_sequence_closed_on_its_line",
        "a_key_under_an_entry_s_anchor", "a_key_on_the_line_after_its_dash", "a_key_line_with_a_pipe",
        "a_key_after_a_quoted_value"])
def test_an_array_on_a_complete_yaml_line_keeps_its_reach(workflow):
    for directory in (HIDDEN, PLAIN):
        assert opaque_reached((directory,), {**SETUP, ".github/workflows/ci.yml": workflow}, []) == directory


@pytest.mark.parametrize("runner", [
    {"noxfile.py": b"import nox\n\n@nox.session\ndef tests(session):\n    session.run('pytest', '${tests[@]}')\n"},
    {"scripts/run.py": b"import os\nos.system('pytest $*')\n"},
], ids=["a_noxfile", "a_python_script"])
def test_a_python_file_is_read_as_it_was(runner):
    # These two scripts are read as targetless runs under the original runner reader.
    assert opaque_reached((PLAIN,), {**NO_TESTPATHS, **runner}, []) == PLAIN
    assert opaque_reached((PLAIN,), {**SETUP, **runner}, []) is None
    assert opaque_reached((HIDDEN,), {**NO_TESTPATHS, **runner}, []) is None


def test_a_testpath_is_no_argument_and_is_read_as_it_was():
    # A wildcard in the configured testpaths also reaches from its literal prefix.
    files = {"setup.cfg": b"[tool:pytest]\ntestpaths = ${suites[@]}\n", "Makefile": b"test:\n\tpytest\n"}
    assert opaque_reached((HIDDEN,), files, []) == HIDDEN


def test_the_environment_rule_keeps_its_reading_of_an_array():
    # A literal target limits collection. An array written with brackets reaches the environment.
    files = {**SETUP, "scripts/test.sh": b"#!/bin/bash\npytest --collect-in-virtualenv \"${tests[@]}\"\n"}
    named = {**SETUP, "scripts/test.sh": b"#!/bin/bash\npytest --collect-in-virtualenv tests\n"}
    assert environment_reached(("env",), files, []) == "env"
    assert environment_reached(("env",), named, []) is None
    assert opaque_reached(("env",), files, []) == "env"
    assert opaque_reached(("env",), named, []) is None


def test_a_shell_command_quoted_in_a_python_file_is_read_as_it_was():
    # The original runner reader recognizes this usage line and its array wildcard.
    runner = {"scripts/run.py": b'"""Run the suite.\n\n    pytest "${tests[@]}"\n"""\n'}
    for directory in (HIDDEN, PLAIN):
        assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


def test_what_an_array_holds_is_not_read():
    # The brackets alone yield a root wildcard regardless of the assignment or testpaths.
    workflow = {".github/workflows/ci.yml": STEPS + b"      - run: |\n          tests=(vendor/lib)\n"
                                                    b"          pytest \"${tests[@]}\"\n"}
    assert opaque_reached((PLAIN,), {**SETUP, **workflow}, []) == PLAIN
    assert opaque_reached((PLAIN,), {**NO_TESTPATHS, **workflow}, []) == PLAIN


@pytest.mark.parametrize("line, directory", [
    (b"pytest \"tests/${a[0]}x\"", "tests/shared"),
    (b"pytest \"${t[@]}/lib\"", PLAIN),
    (b"pytest \"${t[@]:-.vendor}\"", HIDDEN),
], ids=["text_beside_it_in_one_part", "a_path_after_it", "a_default_word_that_is_a_path"])
def test_text_around_an_array_does_not_hide_its_wildcard(line, directory):
    runner = {"scripts/test.sh": b"#!/bin/bash\n" + line + b"\n"}
    assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


MATRIX_WORKFLOW = (b"jobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
                   b"      - run: pytest sub/${{ matrix.suite }}\n")


@pytest.mark.parametrize("runner, directory", [
    ({"scripts/test.sh": b"#!/bin/sh\npytest sub/$1\n"}, "sub"),
    ({"scripts/test.sh": b"#!/bin/sh\npytest sub/tests/$SUITE\n"}, "sub"),
    ({"scripts/test.sh": b"#!/bin/bash\npytest \"sub/${suites[@]}\"\n"}, "sub"),
    ({"Makefile": b"test:\n\tpytest vendor/lib/$(SUITE)\n"}, PLAIN),
    ({".github/workflows/ci.yml": MATRIX_WORKFLOW}, "sub"),
    ({"scripts/test.sh": b"#!/bin/sh\npytest tests/$1\n"}, "tests"),
    ({"scripts/test.sh": b"#!/bin/sh\npytest .vendor/lib/$1\n"}, HIDDEN),
    ({"scripts/test.sh": b"#!/bin/sh\npytest sub/*/$x\n"}, "sub/a"),
], ids=["a_parameter_inside_it", "a_variable_deeper_inside_it", "an_array_inside_it", "a_make_variable_inside_it",
        "a_workflow_expression_inside_it", "a_parameter_inside_the_testpath", "a_parameter_inside_a_hidden_one",
        "a_wildcard_before_the_variable"])
def test_the_directories_before_a_variable_still_reach(runner, directory):
    # A literal directory before the variable still bounds the possible collection paths.
    assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


@pytest.mark.parametrize("runner, reached", [
    ({"Makefile": b"test:\n\tpytest */lib\n"}, PLAIN),
    ({"Makefile": b"test:\n\tpytest [uv]endor\n"}, PLAIN),
    ({"Makefile": b"test:\n\tpytest vendor/li?\n"}, PLAIN),
    ({"Makefile": b"test:\n\tpytest \"${tests[@]}\" vendor/lib\n"}, PLAIN),
    ({"Makefile": b"test:\n\tpytest \"${tests[@]}\"\n", "tox.ini": b"[testenv]\ncommands = pytest\n"}, PLAIN),
    ({"Makefile": b"test:\n\tpytest \"${tests[@]}\" -c ci/pytest.ini\n"}, PLAIN),
], ids=["star", "bracket_set", "question_mark", "a_named_path_beside_the_variable", "a_bare_run_beside_it",
        "its_own_config"])
def test_what_still_reaches_beside_a_variable(runner, reached):
    # A wildcard with no variable in it, a path the same command names, another
    # run and a run's own config reach as they did.
    assert opaque_reached((PLAIN,), {"setup.cfg": b"[tool:pytest]\naddopts = -ra\n", **runner}, []) == reached


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=True).stdout


def _check(repo, files, *, gitlink=None, link=None):
    """A base commit of `files` with a gitlink or a directory link, then the new provider checked as the head."""
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "checkwash-test")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "core.autocrlf", "false")
    for path, data in {**SOURCES, **SETUP, **files}.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)
    git(repo, "add", "-A")
    if gitlink is not None:
        git(repo, "update-index", "--add", "--cacheinfo", f"160000,{GITLINK},{gitlink}")
    if link is not None:
        # Made in the index, not on disk, so every host commits the same entry, mode 120000.
        oid = git(repo, "hash-object", "-w", "--stdin", data=link[1]).decode("ascii").strip()
        git(repo, "update-index", "--add", "--cacheinfo", f"120000,{oid},{link[0]}")
    git(repo, "commit", "-m", "base")
    for path, data in NEW_PROVIDER.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)
    git(repo, "add", "--", *NEW_PROVIDER)
    git(repo, "commit", "-m", "head")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
           "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-11-27", "NO_COLOR": "1"}
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", "HEAD~1..HEAD", "--format", "json",
                             "--repo", str(repo)], env=env, capture_output=True, timeout=120)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


@pytest.mark.parametrize("opaque, refusal", [
    ({"gitlink": HIDDEN}, "strict snapshot cannot inspect the submodule .vendor/lib"),
    ({"link": (".claude/skills/add-new-model", b"../../.agents/skills/add-new-model")},
     "strict snapshot inventory cannot follow directory symlink .claude/skills/add-new-model"),
], ids=["hidden_submodule", "hidden_directory_link"])
def test_a_workflow_that_passes_pytest_an_array_fails_closed(tmp_path, opaque, refusal):
    files = {".github/workflows/ci.yml": ARRAY_WORKFLOW, ".agents/skills/add-new-model/SKILL.md": b"# Add a model\n"}
    code, stdout, stderr = _check(tmp_path / "array", files, **opaque)
    assert (code, stdout) == (2, "")
    assert f"checkwash engine error: EngineError: {refusal}: pytest's collection can reach it" in stderr

    # Naming the tests directly bounds their reach and exposes the original provider finding.
    files[".github/workflows/ci.yml"] = STEPS + b"      - run: pytest tests\n"
    code, stdout, stderr = _check(tmp_path / "literal", files, **opaque)
    assert "engine error" not in stderr, stderr
    payload = json.loads(stdout)
    assert (code, payload["verdict"]) == (1, "block")
    assert {finding["rule"] for finding in payload["findings"]} == {"TEST_PATCHES_SUBJECT"}


@pytest.mark.parametrize("opaque, runner, refusal", [
    ({"gitlink": PLAIN}, b"#!/bin/sh\npytest vendor/lib/$1\n",
     "strict snapshot cannot inspect the submodule vendor/lib: pytest's collection can reach it"),
    ({"link": (".claude/skills/add-new-model", b"../../.agents/skills/add-new-model")},
     b"#!/bin/sh\npytest .claude/skills/add-new-model/$1\n",
     "strict snapshot inventory cannot follow directory symlink .claude/skills/add-new-model: "
     "pytest's collection can reach it"),
], ids=["submodule", "directory_link"])
def test_a_run_that_names_a_path_inside_it_through_a_variable_still_fails_closed(tmp_path, opaque, runner, refusal):
    # The script's run names a path inside the directory through `$1`, so the
    # check ends as it does on 0.13.2 for the submodule: exit 2, naming it.
    files = {"scripts/test.sh": runner, ".agents/skills/add-new-model/SKILL.md": b"# Add a model\n"}
    code, stdout, stderr = _check(tmp_path, files, **opaque)
    assert (code, stdout) == (2, "")
    assert f"checkwash engine error: EngineError: {refusal}" in stderr


def test_an_array_with_no_configured_testpaths_fails_closed_for_a_submodule(tmp_path):
    code, stdout, stderr = _check(tmp_path, {".github/workflows/ci.yml": ARRAY_WORKFLOW,
                                             "setup.cfg": b"[tool:pytest]\naddopts = -ra\n"}, gitlink=PLAIN)
    assert (code, stdout) == (2, "")
    assert ("checkwash engine error: EngineError: strict snapshot cannot inspect the submodule vendor/lib: "
            "pytest's collection can reach it") in stderr


def test_a_submodule_a_bare_run_recurses_into_still_fails_closed_beside_the_array(tmp_path):
    # `vendor/lib` is not hidden, and the array run is not the only one: a
    # second step runs a bare `pytest`. The tree has no testpaths, so that
    # run recurses from the root into the submodule, and every run counts.
    workflow = ARRAY_WORKFLOW + b"      - run: pytest\n"
    code, stdout, stderr = _check(tmp_path, {".github/workflows/ci.yml": workflow,
                                             "setup.cfg": b"[tool:pytest]\naddopts = -ra\n"}, gitlink=PLAIN)
    assert (code, stdout) == (2, "")
    assert ("checkwash engine error: EngineError: strict snapshot cannot inspect the submodule vendor/lib: "
            "pytest's collection can reach it") in stderr
