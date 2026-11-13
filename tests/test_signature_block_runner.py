"""A PowerShell signature block does not make a script a test runner (ND-02; D-207).

Windows builds of Python sign the `Activate.ps1` that `python -m venv`
writes. The signature ends the script: base64 in lines between `# SIG # Begin
signature block` and `# SIG # End signature block`, and its letters can spell
`tox` or `nox`, two of the runner tokens checkwash looks for anywhere in a
runner-shaped file. So an untracked virtual environment that Git did not
ignore, and a range that committed one, blocked at high: its `Activate.ps1`
read as a test runner whose command was weakened
(`-ErrorAction SilentlyContinue`).

In a PowerShell file the block that ends it is now left out of that search
when every line between its markers is `#`, a space and base64: as
PowerShell reads the file, none of it runs. Any other line, such as `#>
pytest` (which ends a block comment opened above it), a block that does not
end the file, a block without its end marker and every other file are read
as before. The residual, a PowerShell-named file that another program runs
or that runs its own block, is THREATMODEL row 185. The search stays linear
in the text.

The fixture repositories are static inputs: no file in them is run.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from checkwash.roles import _is_runner_script, _mentions_test_runner, _runs_tests

ROOT = Path(__file__).resolve().parents[1]
BODY = (b'param([String] $VenvDir)\r\n'
        b'if (Get-Variable -Name "_PYTHON_VENV_PROMPT_PREFIX" -ErrorAction SilentlyContinue) {\r\n'
        b'    Remove-Variable -Name _PYTHON_VENV_PROMPT_PREFIX -Scope Global\r\n'
        b'}\r\n')
# Base64 lines of the shape Windows writes; two of them spell `tox` and `nox`.
SIGNATURE = (b'# SIG # Begin signature block\r\n'
             b'# MIIvIwYJKoZIhvcNAQcCoIIvFDCCLxACAQExDzANBglghkgBZQMEAgEFADB5Bgor\r\n'
             b'# BgEEAYI3AgEEoGswaTA0BgoTOXwGAQQBgjcCAR4wJgIDAQAABBAfzDtgWUsITrck\r\n'
             b'# 0sYpfvNRAgEAAgEAAgEAAgEAAgEAMDEwDQYJYIZIAWUDBAIBBQAEIBjNOXx4qY7Z\r\n'
             b'# T5Ym1q7sNWB8oDWR8=\r\n'
             b'# SIG # End signature block\r\n')
ACTIVATE = BODY + b'\r\n' + SIGNATURE
# Base64 that spells no runner token.
CLEAN = (b'# SIG # Begin signature block\r\n'
         b'# MIIvIwYJKoZIhvcNAQcCoIIvFDCCLxACAQExDzANBglghkgBZQMEAgEFADB5Bgor\r\n'
         b'# SIG # End signature block\r\n')
END = b"# SIG # End signature block"
# make runs such a block's lines as recipes once `.RECIPEPREFIX := \#` makes
# `#` its recipe prefix (unescaped, `#` starts a comment there) and a `SIG` on
# the PATH lets the marker lines succeed; `# pytest` is then the suite, and
# its failure fails make. GNU Make 4.4.1 ran this shape on Windows, with
# harmless commands in place of the suite (THREATMODEL row 185).
MAKEFILE = (rb".RECIPEPREFIX := \#" + b"\nexport PATH := $(CURDIR)/ci:$(PATH)\ntest:\n"
            b"# SIG # Begin signature block\n# {}\n# SIG # End signature block\n")
SIG_SCRIPT = b"#!/bin/sh\nexit 0\n"


@pytest.fixture(autouse=True)
def plain_git(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("git-home")
    (home / "gitconfig").write_bytes(b"")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True, timeout=60).stdout


def make_repo(tmp_path, files):
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "checkwash-test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "core.autocrlf", "false")
    base = {"pkg.py": b"def total():\n    return 5\n",
            "tests/test_total.py": b"from pkg import total\n\n\ndef test_total():\n    assert total() == 5\n", **files}
    write(root, base)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def write(root, files):
    for path, data in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)


def commit(root, files, message):
    base = git(root, "rev-parse", "HEAD").decode().strip()
    write(root, files)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return base


def check(repo, *args):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1",
           "GREENWASH_TODAY": "2026-11-13", "NO_COLOR": "1"}
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", *args, "--format", "json", "--repo", str(repo)],
                            env=env, capture_output=True, timeout=180, cwd=str(repo))
    return result.returncode, json.loads(result.stdout), result.stderr.decode("utf-8")


def found(report):
    return [(f["rule"], f["path"], f["severity"]) for f in report["findings"]]


# --- the runner search


def ps(data):
    return _runs_tests(data, "env/Scripts/Activate.ps1")


def test_a_signature_that_spells_a_runner_does_not_run_tests():
    assert b"tox" in ACTIVATE.lower() and b"nox" in ACTIVATE.lower()
    assert not ps(ACTIVATE)
    assert not ps(ACTIVATE.replace(b"\r\n", b"\n"))
    assert not _runs_tests(ACTIVATE, "tools/Sign.PSM1")
    assert not _runs_tests(ACTIVATE, "Module/Module.psd1")


@pytest.mark.parametrize("path", ["ci/run.cmd", "ci/run.bat", "ci/run.sh", "Makefile", "ci/test.mk", None])
def test_only_a_powershell_file_has_its_signature_left_out(path):
    # cmd has no `#` comment, and make can take `#` as its recipe prefix.
    assert _runs_tests(ACTIVATE, path)
    assert _runs_tests(MAKEFILE.replace(b"{}", b"pytest"), path)


def test_a_runner_outside_the_block_still_counts():
    assert ps(b"pytest -q\r\n" + SIGNATURE)
    assert ps(ACTIVATE + b"tox -e py311\r\n")


@pytest.mark.parametrize("line", [
    b"pytest -q",
    b"pytest -q  # fast",
    # After `<#` above the block, `#>` ends the block comment and the rest runs.
    b'#> pytest -k "not total"',
    b'# MIIv #> pytest -k "not total"',
    # cmd has no `#` comment: `&` runs what follows.
    b'#&pytest -k "not total"',
    b"#pytest",
], ids=["command", "command-with-comment", "block-comment-end", "block-comment-end-after-base64", "cmd-join",
        "no-space"])
def test_a_runner_on_a_line_that_is_not_base64_is_read(line):
    assert not ps(BODY + CLEAN)
    assert ps(b"<#\r\n" + CLEAN.replace(END, line + b"\r\n" + END))


def test_an_end_marker_line_that_holds_more_is_read():
    assert ps(b"<#\r\n" + CLEAN.replace(END, b"#> pytest -q " + END))


@pytest.mark.parametrize("line", [b"# MIIvIwYJKo ZIhvcNAQ", b"", b"# MIIvIwYJKoZIhvcNAQ ", b"# MIIv=ZIhv",
                                  b"# MIIv==="],
                         ids=["inner-space", "empty", "trailing-space", "padding-inside", "padding-three"])
def test_a_block_with_any_line_that_is_not_base64_is_read(line):
    # Read whole, its base64 spells `tox`.
    assert ps(BODY + SIGNATURE.replace(END, line + b"\r\n" + END))


def test_a_block_without_its_end_marker_is_read():
    # The base64, once read, spells a runner.
    assert ps(BODY + SIGNATURE.replace(END + b"\r\n", b""))
    assert ps(BODY + SIGNATURE.replace(b"\r\n" + END, b"\r\nWrite-Host done"))


def test_a_block_without_its_begin_marker_is_read():
    assert ps(b"# pytest\r\n" + END + b"\r\n")
    assert ps(BODY + SIGNATURE.replace(b"# SIG # Begin signature block\r\n", b""))
    assert ps(BODY + SIGNATURE.replace(b"# SIG # Begin signature block", b"# SIG # Begin signature block 2"))


def test_markers_and_base64_are_matched_as_written():
    # As PowerShell writes them. A lowercase marker, or a letter outside ASCII
    # that lowercases into it (the Kelvin sign), makes the block read.
    lower = SIGNATURE.replace(b"# SIG # Begin", b"# sig # begin").replace(b"# SIG # End", b"# sig # end")
    assert ps(BODY + lower)
    kelvin = ("# MIIv" + chr(0x212A) + "ZIhv").encode("utf-8")
    assert ps(BODY + SIGNATURE.replace(END, kelvin + b"\r\n" + END))


def test_comment_lines_outside_a_block_are_read_as_before():
    # Deliberately generous: a comment that names a runner still counts.
    assert ps(BODY + b"# run tox before pushing\r\n")


def test_only_the_block_that_ends_the_script_is_left_out():
    assert not ps(BODY + SIGNATURE + b"\r\n\r\n")
    assert not ps(BODY + SIGNATURE + b" \t\r\n \r\n")
    # Anything else after it is read, even a character Python strips as space.
    assert ps(BODY + SIGNATURE + bytes([0x1C]) + b"\r\n")
    assert ps(BODY + SIGNATURE + "\u0085".encode("utf-8"))
    assert ps(SIGNATURE + BODY)
    assert ps(SIGNATURE + b"nox -s tests\r\n" + SIGNATURE)
    # An earlier block is read, and the one that ends the script is not.
    assert not ps(b"Write-Host start\r\n" + CLEAN + BODY + SIGNATURE)
    assert ps(b"Write-Host start\r\n" + SIGNATURE + BODY + CLEAN)


def test_the_search_stays_linear_on_many_markers():
    # Begin markers with no end, near the 1,000,000-byte source limit.
    import time

    padding = b"# SIG # Begin signature block\n" * 33_000
    started = time.perf_counter()
    assert not ps(padding)
    assert not ps(padding + END + b"\n")
    assert time.perf_counter() - started < 2.0


def test_the_other_readers_leave_the_signature_out():
    # The opaque-exemption denial reads each side under its own path.
    assert not _mentions_test_runner(SimpleNamespace(before=None, after=ACTIVATE, path="a.ps1", old_path=None))
    assert _mentions_test_runner(SimpleNamespace(before=None, after=ACTIVATE, path="a.sh", old_path=None))
    assert _mentions_test_runner(SimpleNamespace(before=ACTIVATE, after=None, path="b.ps1", old_path="a.sh"))
    assert not _mentions_test_runner(SimpleNamespace(before=ACTIVATE, after=None, path="a.sh", old_path="b.ps1"))
    assert _mentions_test_runner(SimpleNamespace(before=None, after=ACTIVATE, path="a.sh", old_path="b.ps1"))
    assert not _mentions_test_runner(SimpleNamespace(before=None, after=ACTIVATE, path="a.ps1", old_path="b.sh"))
    assert not _is_runner_script("env/Scripts/Activate.ps1", None, ACTIVATE)
    assert _is_runner_script("ci/run.sh", None, ACTIVATE)


# --- a check of the change


def test_an_untracked_signed_activate_script_does_not_block(tmp_path):
    root = make_repo(tmp_path, {})
    write(root, {"env/Scripts/Activate.ps1": ACTIVATE})
    code, report, err = check(root)
    assert code == 0, err
    assert report["verdict"] == "pass"
    assert found(report) == []


def test_a_committed_signed_activate_script_does_not_block(tmp_path):
    root = make_repo(tmp_path, {})
    base = commit(root, {"env/Scripts/Activate.ps1": ACTIVATE}, "add an environment")
    code, report, err = check(root, f"{base}..HEAD")
    assert code == 0, err
    assert found(report) == []


def test_a_signed_runner_script_is_still_read(tmp_path):
    root = make_repo(tmp_path, {"ci/test.ps1": b"pytest -q\r\n\r\n" + SIGNATURE})
    base = commit(root, {"ci/test.ps1": b"pytest -q -ErrorAction SilentlyContinue\r\n\r\n" + SIGNATURE},
                  "weaken the runner")
    code, report, err = check(root, f"{base}..HEAD")
    assert code == 1, err
    assert ("CI_WORKFLOW_TOUCHED", "ci/test.ps1", "high") in found(report)


def test_a_runner_removed_under_a_signature_that_spells_one_is_read_as_removed(tmp_path):
    # The new signature spells `tox`; read whole, the script still ran a suite.
    root = make_repo(tmp_path, {"ci/test.ps1": b"pytest -q\r\n\r\n" + CLEAN})
    base = commit(root, {"ci/test.ps1": b"Write-Host skipped\r\n\r\n" + SIGNATURE}, "drop the runner")
    code, report, err = check(root, f"{base}..HEAD")
    assert code == 1, err
    assert ("CI_WORKFLOW_TOUCHED", "ci/test.ps1", "high") in found(report)


def test_a_runner_after_a_block_comment_end_is_still_read(tmp_path):
    # `<#` opens a block comment above the markers; `#>` ends it, and the rest of that line runs.
    hidden = b"<#\r\n# SIG # Begin signature block\r\n#> pytest -q\r\n# SIG # End signature block\r\n"
    root = make_repo(tmp_path, {"ci/test.ps1": hidden})
    base = commit(root, {"ci/test.ps1": hidden.replace(b"pytest -q", b'pytest -q -k "not total"')},
                  "narrow the hidden runner")
    code, report, err = check(root, f"{base}..HEAD")
    assert code == 1, err
    assert ("CI_WORKFLOW_TOUCHED", "ci/test.ps1", "high") in found(report)


def test_a_script_that_calls_a_signed_script_is_not_its_runner(tmp_path):
    # One hop (THREATMODEL row 89) reads the called script under its own path.
    for sign, expected in ((ACTIVATE, 0), (b"pytest -q\r\n\r\n" + SIGNATURE, 1)):
        root = make_repo(tmp_path / str(expected), {"ci/build.sh": b"#!/bin/sh\nset -e\npwsh ./ci/sign.ps1\n",
                                                    "ci/sign.ps1": sign})
        base = commit(root, {"ci/build.sh": b"#!/bin/sh\nset -e\npwsh ./ci/sign.ps1 || true\n"}, "swallow it")
        code, report, err = check(root, f"{base}..HEAD")
        assert code == expected, err
        if expected:
            assert ("CI_WORKFLOW_TOUCHED", "ci/build.sh", "high") in found(report)
        else:
            assert found(report) == []


def test_a_signed_script_that_calls_the_runner_script_is_promoted(tmp_path):
    # Its signature is not read, so it holds no runner of its own, and the one
    # hop to the runner script makes it one.
    root = make_repo(tmp_path, {"ci/run-tests.sh": b"#!/bin/sh\nset -e\npytest -q\n",
                                "ci/entry.ps1": b"& ./ci/run-tests.sh\r\n\r\n" + SIGNATURE})
    base = commit(root, {"ci/entry.ps1": b"& ./ci/run-tests.sh -ErrorAction SilentlyContinue\r\n\r\n" + SIGNATURE},
                  "quiet the runner")
    code, report, err = check(root, f"{base}..HEAD")
    assert code == 1, err
    assert ("CI_WORKFLOW_TOUCHED", "ci/entry.ps1", "high") in found(report)


def test_a_signed_script_does_not_withhold_the_collection_inventory(tmp_path):
    # The collection inventory sets itself aside for a runner it cannot parse,
    # and the signature read as one: a first pytest config that leaves
    # `tests/test_total.py` out of collection passed at warn.
    root = make_repo(tmp_path, {"scripts/sign.ps1": ACTIVATE, "tests/unit/test_unit.py": (
        b"from pkg import total\n\n\ndef test_unit():\n    assert total() == 5\n")})
    base = commit(root, {"pytest.ini": b"[pytest]\ntestpaths = tests/unit\n"}, "collect the unit tests only")
    code, report, err = check(root, f"{base}..HEAD")
    assert code == 1, err
    assert ("CI_WORKFLOW_TOUCHED", "pytest.ini", "high") in found(report)


def test_a_rename_reads_the_old_side_under_its_old_name(tmp_path):
    # The make file's block is its suite. Renamed to `.ps1` with the suite
    # replaced, its old side is still read as make's, whole.
    root = make_repo(tmp_path, {"ci/test.mk": MAKEFILE.replace(b"{}", b"pytest"), "ci/SIG": SIG_SCRIPT})
    base = git(root, "rev-parse", "HEAD").decode().strip()
    git(root, "mv", "ci/test.mk", "ci/test.ps1")
    commit(root, {"ci/test.ps1": MAKEFILE.replace(b"{}", b"true")}, "rename the runner and replace the suite")
    code, report, err = check(root, f"{base}..HEAD")
    assert code == 1, err
    assert ("CI_WORKFLOW_TOUCHED", "ci/test.ps1", "high") in found(report)


def test_the_hop_reads_a_renamed_script_s_old_side_under_its_old_name(tmp_path):
    # Renamed `.ps1` -> `.sh`: under its old name the old side's signature is
    # left out, so the script holds no runner of its own, and the hop to the
    # runner script makes it one. Thirty shared lines keep Git's rename.
    steps = b"".join(b"Write-Host step%d\r\n" % i for i in range(30))
    short = (b"# SIG # Begin signature block\r\n# BgEEAYI3AgEEoGswaTA0BgoTOXwGAQQBgjcCAR4wJgIDAQAABBAfzDtgWUsITrck\r\n"
             + END + b"\r\n")
    assert b"tox" in short.lower()
    root = make_repo(tmp_path, {"ci/run-tests.sh": b"#!/bin/sh\nset -e\npytest -q\n",
                                "ci/entry.ps1": steps + b"& ./ci/run-tests.sh\r\n" + short})
    base = git(root, "rev-parse", "HEAD").decode().strip()
    git(root, "mv", "ci/entry.ps1", "ci/entry.sh")
    commit(root, {"ci/entry.sh": steps + b"& ./ci/run-tests.sh || true\r\n"}, "rename the entry and swallow the call")
    assert git(root, "diff", "-M", "--name-status", f"{base}..HEAD").decode().startswith("R")
    code, report, err = check(root, f"{base}..HEAD")
    assert code == 1, err
    assert ("CI_WORKFLOW_TOUCHED", "ci/entry.sh", "high") in found(report)


def test_the_residual_a_powershell_named_file_another_program_runs(tmp_path):
    # THREATMODEL row 185: make runs the block's lines (MAKEFILE above), so
    # `# pytest` there is the suite. Named `.ps1` the file is read without its
    # block and passes; named `.mk` it blocks.
    for name, expected in (("ci/test.ps1", 0), ("ci/test.mk", 1)):
        root = make_repo(tmp_path / name.replace("/", "-"), {name: MAKEFILE.replace(b"{}", b"pytest"),
                                                            "ci/SIG": SIG_SCRIPT})
        base = commit(root, {name: MAKEFILE.replace(b"{}", b"true")}, "replace the suite")
        code, report, err = check(root, f"{base}..HEAD")
        assert code == expected, err
        if expected:
            assert ("CI_WORKFLOW_TOUCHED", name, "high") in found(report)
        else:
            assert found(report) == []


def test_the_residual_reaches_a_caller_that_swallows_the_run(tmp_path):
    # Row 185: the file holds no runner, so the hop from its caller finds none.
    root = make_repo(tmp_path, {"ci/test.ps1": MAKEFILE.replace(b"{}", b"pytest"), "ci/SIG": SIG_SCRIPT,
                                "ci/build.sh": b"#!/bin/sh\nset -e\nmake -f ci/test.ps1 test\n"})
    base = commit(root, {"ci/build.sh": b"#!/bin/sh\nset -e\nmake -f ci/test.ps1 test || true\n"}, "swallow the run")
    code, report, err = check(root, f"{base}..HEAD")
    assert code == 0, err
    assert found(report) == []


def test_the_residual_in_a_ci_path_draws_a_warning(tmp_path):
    # Row 185: where the configuration makes the file `ci`, its removed suite
    # is not read as removed.
    path = ".github/workflows/test.ps1"
    root = make_repo(tmp_path, {path: MAKEFILE.replace(b"{}", b"pytest"), "ci/SIG": SIG_SCRIPT})
    base = commit(root, {path: MAKEFILE.replace(b"{}", b"true")}, "replace the suite")
    code, report, err = check(root, f"{base}..HEAD")
    assert code == 0, err
    assert found(report) == [("CI_WORKFLOW_TOUCHED", path, "warn")]


def test_a_signed_script_buys_the_opaque_exemption_as_an_unsigned_one_does(tmp_path):
    # A signed script that runs no suite is an opaque production change, as
    # an unsigned one is (THREATMODEL item 4): beside it an expected value
    # rewritten from 5 to 6 is a warning. Main read the signature as a runner
    # and blocked.
    for label, data in (("signed", ACTIVATE), ("unsigned", BODY)):
        root = make_repo(tmp_path / label, {"tools/deploy.ps1": data})
        base = commit(root, {"tools/deploy.ps1": data.replace(b"Global", b"Script"), "tests/test_total.py": (
            b"from pkg import total\n\n\ndef test_total():\n    assert total() == 6\n")}, "rewrite the expectation")
        code, report, err = check(root, f"{base}..HEAD")
        assert code == 0, err
        assert found(report) == [("EXPECTED_VALUE_CHANGED", "tests/test_total.py", "warn")]
