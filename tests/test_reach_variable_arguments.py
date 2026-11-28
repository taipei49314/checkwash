"""The collection-reach rule: the part of a path argument that expands a variable is no wildcard.

`opaque_reached` (#335) decides whether a pytest run could collect from an
opaque directory: a submodule, a working-tree directory symlink (#414) or,
inside the runtime-provider pass, a committed link to a directory (#551). Its
text has always said that a path argument that expands a variable (`$1`,
`{posargs}`) names no path, and `test_what_a_runner_command_reaches` pins
`$(ARGS)` and `{posargs:tests}`. Nothing made that a rule: `$1` named no path
only because no directory's name starts with it. A Bash array, `pytest
"${tests[@]}"`, holds `[@]`, which the wildcard reader took for a bracket set,
and `$*` holds a star. A wildcard is read from its literal prefix, theirs is
empty, and an empty prefix reaches every directory, whatever norecursedirs
says. So one such line in a workflow ended every run that reached the rule
with exit 2.

Found on 2026-11-27 on pydantic/pydantic-ai, whose `.github/workflows/ci.yml`
runs `pytest "${tests[@]}"`: with #551's question 2 fixed, 68 of 69 sampled
commits ended in `cannot follow directory symlink .claude/skills/<name>:
pytest's collection can reach it`, for a hidden directory no run names. The
0.13.2 CLI answers the same for a submodule.

Ruling (owner, 2026-11-27, 「好，兩個都修」, to the agent's question whether to
fix this reading and the Markdown one, each on its own): `${tests[@]}` and
`$*` read as `$1` and `"$@"` did. A wildcard with no variable in it reaches as
before.

The first commit under the ruling dropped every path argument that holds `$`.
That also dropped what 0.13.2 read rightly: `pytest sub/$1` collects inside
`sub`, and the rule had answered so. Three reviews found it, and then more
runs that each new reading let through where the real run collects from the
directory. The reading is now this:
- only the `[`, `*` and `?` inside a variable expansion (`${...}`, `$name`,
  `$1`, `$@`, `$*`, `$?`, a quoted `${{ ... }}`) are no wildcard. The rest
  of the argument is read as it always was: the directories before the
  variable, a wildcard beside it (`te*$x`), a bracket set around it
  (`[$x]`), and the script's own default word (`${SUITE:-*}`);
- what such an expansion gives is not read, and it may give nothing. A
  path that ends in a part of only such expansions is read as the path
  before it (`tests/${suites[@]}` as `tests`), and a run with an argument
  of only such expansions is judged as the bare `pytest` too: its other
  arguments may be none at all, since the reader takes an unknown option's
  value for a path. So the array and `$*` no longer reach every directory,
  a hidden one included, and still reach what a bare run does. `$1` and
  `"$@"`, which were never read as a wildcard, are read as they were;
- only in a run's own arguments. `pytest || exit $?` is a bare `pytest`
  followed by another command, and the rule's reader takes `exit` and `$?`
  for path arguments, so the run is not judged as the bare run it is. On
  0.13.2 the `?` is a wildcard that reaches every directory, and the check
  ends with exit 2; read as text, it gave a verdict where the bare run
  collects from the directory. A word from the first one that holds an
  operator character on (`pytest -q || exit $?`) is therefore read as on
  0.13.2. So is every word of a line whose words are not known to be the
  command's: one where an operator stands against another word
  (`pytest "${a[@]}" vendor/lib; echo`, which the reader takes for a path
  no directory has), one with a backslash, a `#` inside a word or a
  `$'...'` quote, which the reader splits unlike a shell, and one that is
  not known to end its command: a line with a backtick or a caret at its
  end, a line of a Python file, and in a YAML file every line but those
  of a literal block scalar (`run: |`) and a key's or an entry's own line
  that no deeper line follows.
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


@pytest.mark.parametrize("runner", [
    {".github/workflows/ci.yml": ARRAY_WORKFLOW},
    {"Makefile": b"test:\n\tpytest \"${tests[@]}\"\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest \"${tests[*]}\"\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest \"${tests[0]}\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest $*\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest ${1:?}\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest \"tests/${suites[@]}\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest \"$@\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest $1\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest ${suites[${i}]}\n"},
], ids=["array_in_a_workflow", "array_in_a_makefile", "array_star", "array_element", "dollar_star",
        "required_parameter", "array_under_a_directory", "dollar_at_as_before", "dollar_one_as_before",
        "an_index_written_with_braces"])
@pytest.mark.parametrize("directory", [HIDDEN, PLAIN])
def test_a_path_argument_that_holds_a_variable_names_no_path(runner, directory):
    # Before the ruling the first six rows reached both directories, through
    # a wildcard whose prefix is empty; the last three reached neither. No
    # row names either directory, and the bare run that the first six may be
    # (below) starts from the testpaths, which hold neither.
    assert opaque_reached((directory,), {**SETUP, **runner}, []) is None


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
def test_a_run_whose_arguments_may_all_be_nothing_is_judged_as_the_bare_run(runner):
    # What a variable expands to is not read, and it may be nothing: with an
    # empty array, or one that holds options alone, the run is a bare
    # `pytest`. That run starts from the testpaths and recurses into
    # `tests/vendor`. With no testpaths it starts from the root, recurses
    # into `vendor/lib` and stops at a hidden directory. 0.13.2 reached all
    # of these and the hidden one too; the first form of this change reached
    # none, and gave a verdict where the run collects from the directory.
    # In the last four rows the expansion stands beside another argument,
    # or is an option's value. The reader takes an unknown option's value
    # for a path (`--assert plain`), so a run can be bare whatever else the
    # reader finds on its line, and it is judged as the bare run too.
    assert opaque_reached(("tests/vendor",), {**SETUP, **runner}, []) == "tests/vendor"
    assert opaque_reached((PLAIN,), {**NO_TESTPATHS, **runner}, []) == PLAIN
    assert opaque_reached((HIDDEN,), {**NO_TESTPATHS, **runner}, []) is None


def test_an_expansion_that_holds_a_slash_is_read_as_it_was():
    # `${dir%/*}` is split at its slash before any expansion is looked for,
    # on 0.13.2 and here: the star stands in a part of its own, behind a
    # prefix no directory has, and reaches nothing. The run is not judged as
    # bare either, as it was not.
    runner = {"scripts/test.sh": b"#!/bin/bash\npytest \"${dir%/*}\"\n"}
    assert opaque_reached((PLAIN,), {**NO_TESTPATHS, **runner}, []) is None
    assert opaque_reached(("tests/vendor",), {**SETUP, **runner}, []) is None


@pytest.mark.parametrize("runner", [
    {"scripts/test.sh": b"#!/bin/sh\npytest \"$@\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest $1\n"},
], ids=["dollar_at", "dollar_one"])
def test_a_variable_that_was_never_read_as_a_wildcard_is_read_as_it_was(runner):
    # `"$@"` and `$1` may be nothing too. A run of one of them alone was
    # never judged as bare, on 0.13.2 or here: only what was read as a
    # wildcard is read anew.
    assert opaque_reached(("tests/vendor",), {**SETUP, **runner}, []) is None
    assert opaque_reached((PLAIN,), {**NO_TESTPATHS, **runner}, []) is None


def test_an_array_after_a_directory_may_leave_the_directory_alone():
    # `"tests/${suites[@]}"` with an empty array is `tests/`: the run then
    # collects from `tests` and recurses beneath it as any run from there
    # does, stopping at a hidden directory. 0.13.2 read a wildcard beneath
    # `tests`, which reached the hidden one too; the first form of this
    # change reached only `tests` itself.
    runner = {"scripts/test.sh": b"#!/bin/bash\npytest \"tests/${suites[@]}\"\n"}
    for directory, reached in (("tests", "tests"), ("tests/vendor", "tests/vendor"), ("tests/.cache/lib", None),
                               (PLAIN, None)):
        assert opaque_reached((directory,), {**SETUP, **runner}, []) == reached


@pytest.mark.parametrize("runner", [
    {"Makefile": b"test:\n\tpytest $?\n"},
    {"scripts/test.sh": b"#!/bin/bash\npytest \"${tests[@]:1}\"\n"},
    {"scripts/test.sh": b"#!/bin/sh\npytest ${name%%.*}\n"},
    {".github/workflows/ci.yml": b"jobs:\n  t:\n    steps:\n      - run: pytest \"${{ matrix.tests[0] }}\"\n"},
], ids=["a_special_parameter", "an_array_slice", "a_trimmed_variable", "a_quoted_workflow_expression"])
@pytest.mark.parametrize("directory", [HIDDEN, PLAIN])
def test_a_wildcard_character_inside_an_expansion_is_no_wildcard(runner, directory):
    # Each of these reached both directories before the ruling. The pattern
    # of `${name%%.*}` is what the shell removes, not what it yields.
    assert opaque_reached((directory,), {**SETUP, **runner}, []) is None


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
    # The wildcard is the shell's own, whatever the variable holds, and is
    # read from its literal prefix as on 0.13.2. PowerShell's `$args[0]` is
    # read as a bracket set after the variable, as it was: it fails closed.
    # A bracket set around a variable is a set whatever the variable holds.
    # The word of `${TESTS:-*}` is the script's own text, and the shell
    # expands its star when `TESTS` is unset.
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
def test_a_word_that_is_no_argument_of_the_run_is_read_as_it_was(line, directory):
    # After a control operator a word belongs to another command, and on a
    # line that ends in a backslash the run's arguments go on where the
    # reader does not follow. The reader takes such words for path arguments
    # all the same (`_pytest_cli`), so the run before them is never judged as
    # bare, and the wildcard 0.13.2 reads in them is what ends the check: the
    # first row is a bare `pytest`, which collects from `vendor/lib`. Every
    # row reaches both directories, as on 0.13.2. An operator ends the run's
    # arguments wherever it stands in a word: `pytest -q||exit $?` is the
    # same two commands as `pytest -q || exit $?`. A word with a `;` at its
    # end is such a word: the array before `; echo done` is read as it was,
    # where the run with an empty array is a bare one.
    # The last twenty-one rows name `vendor/lib` beside the array, in a
    # word the reader does not read as that path: an operator stands against
    # it (`vendor/lib;`, `vendor/lib)`, `3;echo`, `$(echo`, a `$(` that
    # closes on the next line, a backtick substitution), also behind a word
    # that starts with an operator (a redirection, a quoted `(a or b)`, a
    # second run on the line), or the line holds text the reader splits
    # unlike a shell: a `#` inside a word, where it ends the line, a
    # `$'...'` or a `$"..."` quote, a backslash. Read as the run's own,
    # the array left each with a verdict where the run collects from the
    # directory, so no word of such a line is the run's own.
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
def test_a_run_with_an_array_is_read_as_the_same_run_without_it(command):
    # The price of the ruling, as `test_what_an_array_holds_is_not_read` is.
    # Each run collects from `vendor/lib` in a way the reader reads of no
    # run: it follows no `cd`, expands no brace list, reads no `-o`
    # setting, `--rootdir` or argument file, and does not know what a
    # variable holds. Without an array each gets a verdict, on 0.13.2 too.
    # With one, 0.13.2 ended the check through the bracket alone; the
    # array is now possibly nothing, and the run is read as the same run
    # without it.
    for line in (command, command + b" \"${extra[@]}\""):
        runner = {"scripts/test.sh": b"#!/bin/bash\nT=vendor/lib\n" + line + b"\n"}
        assert opaque_reached((PLAIN,), {**SETUP, **runner}, []) is None


@pytest.mark.parametrize("line", [
    b"pytest \"${tests[@]}\" | tee log",
    b"pytest \"${tests[@]}\" 2>&1",
    b"pytest \"${tests[@]}\" >log.txt",
    b"pytest \"${tests[@]}\" && echo ok",
    b"pytest \"${tests[@]}\" ;echo done",
    b"pytest \"${tests[@]}\" # the suites",
], ids=["a_pipe", "a_numbered_redirection", "a_redirection_against_its_file", "an_and", "a_semicolon_that_starts_a_word",
        "a_comment_after_a_blank"])
def test_an_operator_that_starts_its_word_ends_the_run_s_arguments_and_leaves_them_the_run_s_own(line):
    # The other side of the rows above. Here the operator is a word of its
    # own or starts one, and a `#` follows a blank, so the words before it
    # are the run's arguments for a shell and for the reader alike: the
    # array is read as the ruling has it, and with the testpaths the bare
    # run it may be reaches neither directory.
    runner = {"scripts/test.sh": b"#!/bin/bash\n" + line + b"\n"}
    for directory in (HIDDEN, PLAIN):
        assert opaque_reached((directory,), {**SETUP, **runner}, []) is None


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
    # Each run names `vendor/lib` in the line after its array, where the
    # reader does not follow, and YAML, PowerShell or cmd joins the two
    # lines. Read as the run's own, the array left the run with a verdict.
    # No word of such a line is the run's own: the bracket reaches both
    # directories, as on 0.13.2. YAML joins lines in more ways than one
    # line shows, so the file is followed line by line, and a line is taken
    # for complete only where that is certain. A line that lies in a folded
    # or a quoted scalar is not, whatever it looks like: a key
    # (`PYTHONPATH=src: pytest ...`), an entry, the header of a literal
    # scalar. Two rows, the last line of a folded scalar and one before a
    # blank line, are complete in fact and are not known to be.
    # From the quoted line after another quoted line on, the rows are what
    # the confirmation review found, and what its changed copies of the
    # reader passed unseen. A quoted scalar is followed to the quote that
    # closes it: over several lines, past an escaped or a doubled quote and
    # past the other quote character, and where a tag or an anchor stands
    # before it, on its key's line or the line before. A line that holds a
    # flow collection is never complete, since a bracket or a comma stands
    # against the command's last word (`vendor/lib}`), and one the reader
    # cannot see the end of on its line ends the reading: no later line is
    # complete. A `#` inside one is such a case, since a parser starts a
    # comment at one that stands against a comma. So does text it cannot
    # place, a node on a document mark's line, a tab before a key, and a
    # character that ends a line for YAML alone (a carriage return ends one
    # for the reader too, and always did). A no-break space is text:
    # a line that starts with it is no comment, and a line or a value of
    # one is not blank. The last eight rows are complete in fact and are
    # not known to be.
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
def test_a_complete_line_of_a_yaml_file_holds_the_run_s_own_arguments(workflow):
    # The other side of the rows above: these lines end their command, and
    # the array is read as the ruling has it. With the testpaths the bare
    # run it may be reaches neither directory. A line of a literal block
    # scalar is one line of the script, and a key's or an entry's own line
    # is complete when no deeper line follows it. A flow collection that
    # closes on its line, with its quoted scalars where a token starts, does
    # not end the reading, nor does an anchor or a dash on a line of its own.
    for directory in (HIDDEN, PLAIN):
        assert opaque_reached((directory,), {**SETUP, ".github/workflows/ci.yml": workflow}, []) is None


@pytest.mark.parametrize("runner", [
    {"noxfile.py": b"import nox\n\n@nox.session\ndef tests(session):\n    session.run('pytest', '${tests[@]}')\n"},
    {"scripts/run.py": b"import os\nos.system('pytest $*')\n"},
], ids=["a_noxfile", "a_python_script"])
def test_a_python_file_is_read_as_it_was(runner):
    # A Python file is no shell text, and no line of it is taken for a shell
    # command's own arguments. Each of these reads as on 0.13.2: reached
    # from the root with no testpaths, and not with them.
    assert opaque_reached((PLAIN,), {**NO_TESTPATHS, **runner}, []) == PLAIN
    assert opaque_reached((PLAIN,), {**SETUP, **runner}, []) is None
    assert opaque_reached((HIDDEN,), {**NO_TESTPATHS, **runner}, []) is None


def test_a_testpath_is_no_argument_and_is_read_as_it_was():
    # The ruling is for the arguments of a run. A testpath is a setting, and
    # pytest expands its wildcard itself.
    files = {"setup.cfg": b"[tool:pytest]\ntestpaths = ${suites[@]}\n", "Makefile": b"test:\n\tpytest\n"}
    assert opaque_reached((HIDDEN,), files, []) == HIDDEN


def test_the_environment_rule_keeps_its_reading_of_an_array():
    # `environment_reached` (D-208) is not ruled and not changed: where a run
    # passes `--collect-in-virtualenv` it reads the array's bracket as the
    # wildcard it was. The testpaths keep a bare run out of `env`, and a
    # named path in the array's place does not reach it, so the bracket is
    # what does.
    files = {**SETUP, "scripts/test.sh": b"#!/bin/bash\npytest --collect-in-virtualenv \"${tests[@]}\"\n"}
    named = {**SETUP, "scripts/test.sh": b"#!/bin/bash\npytest --collect-in-virtualenv tests\n"}
    assert environment_reached(("env",), files, []) == "env"
    assert environment_reached(("env",), named, []) is None
    assert opaque_reached(("env",), files, []) is None


def test_a_shell_command_quoted_in_a_python_file_is_read_as_it_was():
    # The reader takes a usage line in a docstring for a command, on 0.13.2
    # and here. No line of a Python file is a shell command's own, so the
    # array is the wildcard it was, and reaches both directories.
    runner = {"scripts/run.py": b'"""Run the suite.\n\n    pytest "${tests[@]}"\n"""\n'}
    for directory in (HIDDEN, PLAIN):
        assert opaque_reached((directory,), {**SETUP, **runner}, []) == directory


def test_what_an_array_holds_is_not_read():
    # The price of the ruling. `tests=(vendor/lib)` names the submodule, and
    # 0.13.2 reached it, through the bracket alone. The array is now what it
    # is for any content: possibly nothing, so the run is judged as the bare
    # one, which the testpaths keep out of `vendor/lib`. With no testpaths
    # the bare run reaches it.
    workflow = {".github/workflows/ci.yml": STEPS + b"      - run: |\n          tests=(vendor/lib)\n"
                                                    b"          pytest \"${tests[@]}\"\n"}
    assert opaque_reached((PLAIN,), {**SETUP, **workflow}, []) is None
    assert opaque_reached((PLAIN,), {**NO_TESTPATHS, **workflow}, []) == PLAIN


@pytest.mark.parametrize("line, directory", [
    (b"pytest \"tests/${a[0]}x\"", "tests/shared"),
    (b"pytest \"${t[@]}/lib\"", PLAIN),
    (b"pytest \"${t[@]:-.vendor}\"", HIDDEN),
], ids=["text_beside_it_in_one_part", "a_path_after_it", "a_default_word_that_is_a_path"])
def test_what_an_expansion_gives_beside_other_text_is_not_read(line, directory):
    # More of the same price. 0.13.2 reached each directory through the
    # bracket: `tests/${a[0]}x` as a wildcard beneath `tests`, the other two
    # as one that reaches everything. What the expansion gives is not read,
    # so `tests/sharex`-like names, `vendor/lib` and the default `.vendor`
    # are not seen.
    runner = {"scripts/test.sh": b"#!/bin/bash\n" + line + b"\n"}
    assert opaque_reached((directory,), {**SETUP, **runner}, []) is None


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
    # `sub/$1` is a path inside `sub` for any `$1` that names one below it,
    # so the run collects there. 0.13.2 answered so, and the rule does again:
    # only what is inside the expansion is not read for a wildcard. In the
    # last row the wildcard stands in a part of its own, before the variable,
    # and is read from its literal prefix as it was.
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


@pytest.mark.parametrize("opaque", [
    {"gitlink": HIDDEN},
    {"link": (".claude/skills/add-new-model", b"../../.agents/skills/add-new-model")},
], ids=["hidden_submodule", "hidden_directory_link"])
def test_a_workflow_that_passes_pytest_an_array_no_longer_ends_the_run(tmp_path, opaque):
    # A new provider takes the runtime-provider pass to the reach rule. The
    # hidden directory is one no run names, and the run gets the verdict the
    # provider earns. Before the ruling both rows ended with exit 2:
    # "pytest's collection can reach it".
    files = {".github/workflows/ci.yml": ARRAY_WORKFLOW, ".agents/skills/add-new-model/SKILL.md": b"# Add a model\n"}
    code, stdout, stderr = _check(tmp_path, files, **opaque)
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


def test_a_submodule_the_bare_run_recurses_into_fails_closed_for_an_array_that_may_be_empty(tmp_path):
    # The array run is the tree's only one, the tree has no testpaths, and
    # `vendor/lib` is not hidden. With an empty array the run is a bare
    # `pytest`, which recurses from the root into the submodule, so the
    # check ends as on 0.13.2, naming it. The first form of this change gave
    # a verdict here.
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
