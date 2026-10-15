"""Issue #416: a command started in a subdirectory answers for the whole repository.

The CLI passed `--repo` (default `.`) straight to Git. From a subdirectory Git
answers in two path bases: `diff`, `status` and `cat-file <rev>:<path>` are
root-relative, while `ls-tree`, `git grep` and the working-tree walker see
only the subtree. So `check` and `sweep` mostly hit engine errors, `doctor`
reported nothing installed, `allow` wrote a ledger `check` never reads, and
an unchanged copy of a changed root file could stand in for it.

One resolver in `main()` now runs `check`, `sweep`, `allow`, `doctor` and the
repository-reading `quality` modes from the root Git names, with one stderr
line. The root, a bare repository, `.git` and a directory outside Git keep
`--repo` as given; so do `allow`, `doctor` and `quality` when Git names a
subdirectory but its root cannot be resolved, with one stderr line saying
why. A `--task` path is mapped lexically through Git's prefix
and never through a symlink. These runs compare outputs and use
`os.path.samefile`, never path strings: a temporary directory may be an 8.3
short name, or a symlinked one, while Git prints the long real path.
"""
import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from checkwash.cli import build_parser, main
from checkwash.doctor import run as run_doctor
from checkwash.findings import make_fingerprint
from checkwash.gitio import git as gitio
from checkwash.quality.cli import run as run_quality

ROOT = Path(__file__).resolve().parents[1]
ENV = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1",
       "GREENWASH_TODAY": "2026-01-01", "NO_COLOR": "1"}
WORKFLOW = re.search(
    r"```yaml\n(# \.github/workflows/checkwash\.yml\n.*?)```",
    (ROOT / "README.md").read_text(encoding="utf-8"), re.S,
).group(1)

CALC = b"def add(a, b):\n    return a + b\n"
TEST = b"from pkg.calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
WEAK = TEST.replace(b"assert add(2, 3) == 5", b"assert add(2, 3) > 0")
CJK_TEST = "from pkg.calc import add\n\n\ndef test_總額():\n    assert add(1, 2) == 3\n".encode("utf-8")
FREEZE = b"---\ncheckwash:\n  oracle_freeze: true\n---\n# Task\n"
LOOSE = b"---\ncheckwash:\n  oracle_freeze: false\n---\n# Notes\n"
FINGERPRINT = make_fingerprint("ASSERT_WEAKENED", "tests/test_calc.py", "test_add", "assert add(2, 3) == 5")
NOTE = "checkwash: using the repository root "

# (subdirectory, how it is named): the shell's cwd, as the README and the
# Stop hook run it, or an explicit --repo. `pkg` does not contain the changed
# file; `測試` is a non-ASCII prefix.
CASES = [("tests", "cwd"), ("pkg", "cwd"), ("測試", "cwd"), ("tests", "repo")]


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def _write(root, path, data):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _init(root):
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "subdirectory-test")
    _git(root, "config", "user.email", "subdirectory@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    _git(root, "config", "core.autocrlf", "false")
    return root


@pytest.fixture
def repo(tmp_path):
    """The issue's repository: a manifest, a package, tests, the README gate."""
    root = _init(tmp_path / "repo")
    _write(root, "pyproject.toml", b'[project]\nname = "calc"\nversion = "0.1.0"\n')
    _write(root, "pkg/__init__.py", b"")
    _write(root, "pkg/calc.py", CALC)
    _write(root, "tests/test_calc.py", TEST)
    _write(root, "測試/test_總額.py", CJK_TEST)
    _write(root, ".github/workflows/checkwash.yml", WORKFLOW.encode("utf-8"))
    _commit(root, "base")
    return root


def _plain(tmp_path):
    """A directory outside any Git work tree. Inside one, a run would rightly
    re-root into the enclosing repository, and `allow` would write its ledger."""
    plain = tmp_path / "plain"
    plain.mkdir()
    probe = subprocess.run(["git", "-C", str(plain), "rev-parse", "--is-inside-work-tree"], capture_output=True)
    assert probe.stdout.strip() != b"true", f"pytest's basetemp is inside a Git work tree: {plain}"
    return plain


def _run(cwd, *args):
    """The CLI started in `cwd` with no --repo."""
    return subprocess.run([sys.executable, "-m", "checkwash", *args], cwd=str(cwd),
                          env=ENV, capture_output=True, timeout=120)


def _run_repo(repo, *args, cwd):
    """The CLI with an explicit --repo, started outside the repository."""
    return subprocess.run([sys.executable, "-m", "checkwash", *args, "--repo", str(repo)], cwd=str(cwd),
                          env=ENV, capture_output=True, timeout=120)


def _from(repo, subdir, how, *args):
    if how == "cwd":
        return _run(repo / subdir, *args)
    return _run_repo(repo / subdir, *args, cwd=repo.parent)


def _same(sub, root, prefix):
    """The subdirectory run is the root run, plus one stderr line naming the root."""
    err = sub.stderr.decode("utf-8")
    assert (sub.returncode, sub.stdout) == (root.returncode, root.stdout), err
    assert err.count(NOTE) == 1, err
    assert f"not its subdirectory {prefix}/" in err, err
    assert NOTE not in root.stderr.decode("utf-8")


def _symlink(link, target):
    """A file symlink, or a skip where the host cannot make one."""
    try:
        os.symlink(target, link)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def _frozen(result):
    assert result.returncode == 1, result.stderr.decode("utf-8")
    weakened = [f for f in json.loads(result.stdout)["findings"] if f["rule"] == "ASSERT_WEAKENED"]
    assert weakened, result.stdout
    return "ORACLE_FREEZE" in weakened[0]["escalators"]


# --- the resolver --------------------------------------------------------------------------------

@pytest.mark.parametrize("answer", [b"false\n\n", b"true\n\n"], ids=["no-work-tree", "root"])
def test_the_root_and_a_tree_without_work_tree_keep_repo_as_given(monkeypatch, answer):
    calls = []

    def reply(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, answer, b"")

    monkeypatch.setattr(subprocess, "run", reply)
    assert gitio.resolve_repository_root("some dir") == gitio.RepositoryRoot("some dir")
    assert calls == [["git", "-C", "some dir", "rev-parse", "--is-inside-work-tree", "--show-prefix"]]


@pytest.mark.parametrize("answers", [
    [b"maybe\n\n"],
    [b"true\nsub\n"],
    [b"true\n../\n"],
    [b"true\n\xff/\n"],
    [b"true\nsub/\n", b"relative\n"],
    [b"true\nsub/\n", b"/one\n/two\n"],
    [b"true\nsub/\n", b"\xff\n"],
], ids=["answer", "unterminated-prefix", "dot-dot-prefix", "undecodable-prefix",
        "relative-root", "two-roots", "undecodable-root"])
def test_an_unusable_git_answer_is_a_git_error(monkeypatch, answers):
    replies = list(answers)
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, replies.pop(0), b""))
    with pytest.raises(gitio.GitError):
        gitio.resolve_repository_root("unused")


def test_a_prefix_split_by_a_newline_is_an_unresolved_root(monkeypatch):
    # Git prints the prefix raw: a directory named "a\nb" breaks the line
    # format after Git has confirmed a work tree, so allow, doctor and quality
    # say why they keep --repo instead of falling back silently.
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, b"true\na\nb/\n", b""))
    with pytest.raises(gitio.GitRootUnresolved):
        gitio.resolve_repository_root("unused")


# --- check, sweep and doctor from a subdirectory ----------------------------------------------------

@pytest.mark.parametrize("subdir,how", CASES)
def test_range_check_from_a_subdirectory_is_the_root_run(repo, subdir, how):
    _write(repo, "tests/test_calc.py", WEAK)
    _commit(repo, "weaken")
    args = ("check", "HEAD~1..HEAD", "--format", "json")
    root = _run(repo, *args)
    assert root.returncode == 1, root.stderr
    assert any(f["rule"] == "ASSERT_WEAKENED" for f in json.loads(root.stdout)["findings"])
    _same(_from(repo, subdir, how, *args), root, subdir)


@pytest.mark.parametrize("subdir,how", CASES)
def test_worktree_check_from_a_subdirectory_is_the_root_run(repo, subdir, how):
    _write(repo, "tests/test_calc.py", WEAK)
    args = ("check", "--format", "json")
    root = _run(repo, *args)
    assert root.returncode == 1, root.stderr
    assert json.loads(root.stdout)["verdict"] == "block"
    _same(_from(repo, subdir, how, *args), root, subdir)


def test_a_clean_worktree_from_a_subdirectory_passes(repo):
    # The issue's third row: a committed config or manifest outside the
    # subtree used to fail the strict blob-header check, exit 2.
    args = ("check", "--format", "json")
    root = _run(repo, *args)
    assert root.returncode == 0, root.stderr
    _same(_run(repo / "tests", *args), root, "tests")


def test_hook_json_from_a_subdirectory_gives_the_root_verdict(repo):
    _write(repo, "tests/test_calc.py", WEAK)
    args = ("check", "--format", "hook-json")
    root = _run(repo, *args)
    assert root.returncode == 0, root.stderr
    assert json.loads(root.stdout)["decision"] == "block"
    _same(_run(repo / "測試", *args), root, "測試")


@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_an_unchanged_copy_in_the_subdirectory_cannot_hide_a_root_change(tmp_path, mode):
    # No manifest and no checkwash config, so nothing stopped a subdirectory
    # run early. The subtree inventory answered for the root-relative
    # `test_billing.py` with `sub/test_billing.py`, unchanged on both sides.
    root = _init(tmp_path / "flat")
    _write(root, "billing.py", CALC)
    body = b"from billing import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    _write(root, "test_billing.py", body)
    _write(root, "sub/__init__.py", b"")  # two importable modules, not a basename clash
    _write(root, "sub/test_billing.py", body)
    _commit(root, "base")
    _write(root, "test_billing.py", body.replace(b"== 5", b"> 0"))
    if mode == "range":
        _commit(root, "weaken")
    args = ("check", *(["HEAD~1..HEAD"] if mode == "range" else []), "--format", "json")
    at_root = _run(root, *args)
    assert at_root.returncode == 1, at_root.stderr
    _same(_run(root / "sub", *args), at_root, "sub")


def test_sweep_from_a_subdirectory_is_the_root_sweep(repo):
    _write(repo, "tests/test_calc.py", WEAK)
    _commit(repo, "weaken")
    args = ("sweep", "--limit", "5")
    root = _run(repo, *args)
    payload = json.loads(root.stdout)
    assert (root.returncode, payload["engine_errors"], payload["commits_blocked"]) == (0, 0, 1), payload
    _same(_run(repo / "tests", *args), root, "tests")


@pytest.mark.parametrize("how", ["cwd", "repo"])
def test_doctor_from_a_subdirectory_is_the_root_report(repo, how):
    root = _run(repo, "doctor")
    assert root.returncode == 0, root.stdout
    assert b"1 CI job(s) invoke checkwash" in root.stdout
    _same(_from(repo, "tests", how, "doctor"), root, "tests")


@pytest.mark.parametrize("names", [("GIT_DIR",), ("GIT_DIR", "GIT_WORK_TREE")],
                         ids=["git-dir", "git-dir-and-work-tree"])
def test_doctor_finds_the_root_without_the_callers_git_environment(repo, tmp_path, names):
    # Ruling Q2: doctor resolves the root in its own sanitized Git
    # environment, the one its later queries use. In the caller's, GIT_DIR
    # names another repository, Git does not call `tests/` a subdirectory of
    # this one, and doctor would report on `tests/` alone.
    other = _init(tmp_path / "other")
    _write(other, "README.md", b"another repository\n")
    _commit(other, "other")
    caller = {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}
    root = _run(repo, "doctor")
    assert root.returncode == 0, root.stdout
    assert b"1 CI job(s) invoke checkwash" in root.stdout
    sub = subprocess.run([sys.executable, "-m", "checkwash", "doctor"], cwd=str(repo / "tests"),
                         env={**ENV, **{name: caller[name] for name in names}}, capture_output=True, timeout=120)
    _same(sub, root, "tests")


@pytest.mark.parametrize("command,code", [
    (("check", "HEAD~1..HEAD", "--format", "json"), 2),
    (("sweep",), 2),
    (("check", "--format", "hook-json"), 0),
], ids=["check", "sweep", "hook-json"])
def test_a_missing_repo_is_still_an_engine_error_naming_it(tmp_path, command, code):
    missing = tmp_path / "missing 目錄"
    result = _run_repo(missing, *command, cwd=tmp_path)
    err = result.stderr.decode("utf-8")
    assert result.returncode == code, err
    assert "engine error" in err and "missing 目錄" in err
    if code == 0:  # The hook-json warning (#414) names it too.
        assert "missing 目錄" in json.loads(result.stdout)["systemMessage"]


@pytest.mark.parametrize("spec", ["HEAD", "HEAD..", "...HEAD"], ids=["no-dots", "two-dot", "three-dot"])
def test_a_malformed_range_is_a_usage_error_before_the_lookup(tmp_path, spec):
    # Outside Git the lookup cannot answer. A malformed range still stops as
    # the usage error it was before #416, exit 2 under hook-json too, and is
    # not the lookup's non-blocking engine-error warning (#414).
    result = _run_repo(_plain(tmp_path), "check", spec, "--format", "hook-json", cwd=tmp_path)
    err = result.stderr.decode("utf-8")
    assert (result.returncode, result.stdout) == (2, b""), err
    assert "error: range must be BASE" in err and "engine error" not in err, err


@pytest.mark.parametrize("kind", ["bare", "git-dir"])
def test_a_repository_without_a_work_tree_is_used_as_given(repo, kind):
    # tools/r1_cost_worker.py checks commits of a bare corpus clone.
    _write(repo, "tests/test_calc.py", WEAK)
    _commit(repo, "weaken")
    if kind == "bare":
        target = repo.parent / "bare.git"
        subprocess.run(["git", "clone", "-q", "--bare", str(repo), str(target)], check=True, capture_output=True)
    else:
        target = repo / ".git"
    for args in (("check", "HEAD~1..HEAD", "--format", "json"), ("sweep", "--limit", "5")):
        root = _run(repo, *args)
        other = _run_repo(target, *args, cwd=repo.parent)
        assert (other.returncode, other.stdout) == (root.returncode, root.stdout), other.stderr
        assert NOTE not in other.stderr.decode("utf-8")
    assert root.returncode == 0 and json.loads(root.stdout)["engine_errors"] == 0


@pytest.mark.parametrize("how", ["cwd", "repo"])
def test_a_nested_config_directory_is_named_as_not_read(repo, how):
    # It used to stop the run with exit 2. It is not read now, so the note
    # names it, and the verdict and exit code stay the root's.
    _write(repo, "pkg/.checkwash/config.toml", b'[detectors]\ndisable = ["ASSERT_WEAKENED"]\n')
    _write(repo, "pkg/sub/.greenwash/allow.toml", b"# not read\n")
    _commit(repo, "nested configuration")
    _write(repo, "tests/test_calc.py", WEAK)
    _commit(repo, "weaken")
    args = ("check", "HEAD~1..HEAD", "--format", "json")
    root = _run(repo, *args)
    assert root.returncode == 1, root.stderr
    sub = _from(repo, "pkg/sub", how, *args)
    _same(sub, root, "pkg/sub")
    assert "not read: pkg/sub/.greenwash/, pkg/.checkwash/ " in sub.stderr.decode("utf-8")


# --- the exemption ledger ----------------------------------------------------------------------------

def test_allow_from_a_subdirectory_writes_the_root_ledger(repo):
    _write(repo, "tests/test_calc.py", WEAK)
    sub = repo / "tests"
    first = _run(sub, "check", "--format", "json")
    assert first.returncode == 1, first.stderr
    finding = next(f for f in json.loads(first.stdout)["findings"] if f["rule"] == "ASSERT_WEAKENED")
    recorded = _run(sub, "allow", finding["fingerprint"], "--reason", "reviewed: issue 416")
    assert recorded.returncode == 0, recorded.stderr
    ledger = repo / ".greenwash" / "allow.toml"
    assert ledger.is_file() and not (sub / ".greenwash").exists()
    written = recorded.stdout.decode("utf-8").split("recorded exemption in ", 1)[1].split(" (expires", 1)[0]
    assert os.path.samefile(written, ledger)
    _git(repo, "add", ".greenwash")
    _git(repo, "commit", "-q", "-m", "record exemption")
    exempt = _run(sub, "check", "--format", "json")
    assert exempt.returncode == 0, exempt.stdout
    payload = json.loads(exempt.stdout)
    assert payload["verdict"] == "pass" and any(f["allowlisted"] for f in payload["findings"])


def test_outside_git_allow_and_doctor_use_the_directory_as_given(tmp_path, capsys):
    plain = _plain(tmp_path)
    assert main(["allow", FINGERPRINT, "--reason", "reviewed", "--repo", str(plain)]) == 0
    ledger = os.path.join(str(plain), ".greenwash", "allow.toml")
    recorded = capsys.readouterr()
    assert recorded.out.startswith(f"recorded exemption in {ledger} (expires ")
    assert recorded.err == ""
    assert main(["doctor", "--repo", str(plain)]) == 1
    via_main = capsys.readouterr()
    assert run_doctor(str(plain)) == 1
    assert via_main.out == capsys.readouterr().out
    assert via_main.err == ""


def test_allow_and_doctor_without_git_use_the_directory_as_given(repo, monkeypatch, capsys):
    original = subprocess.run

    def no_git(argv, *args, **kwargs):
        if argv and argv[0] == "git":
            raise FileNotFoundError("git")
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", no_git)
    sub = repo / "tests"
    assert main(["allow", FINGERPRINT, "--reason", "reviewed", "--repo", str(sub)]) == 0
    assert (sub / ".greenwash" / "allow.toml").is_file()
    assert not (repo / ".greenwash").exists()
    assert main(["doctor", "--repo", str(sub)]) == 1
    captured = capsys.readouterr()
    assert "engine error" not in captured.err and NOTE not in captured.err


@pytest.mark.parametrize("failure", ["undecodable-prefix", "failed", "timed-out", "not-a-directory"])
def test_a_subdirectory_without_a_resolved_root_is_reported(repo, monkeypatch, capsys, failure):
    # Git has answered that `tests/` is a subdirectory, then its root cannot
    # be resolved. allow, doctor and quality keep `--repo` as given, as when
    # Git cannot answer at all, and say why in one stderr line; stdout and the
    # exit code are those of the directory as given. check stays an engine
    # error. Outside Git nothing is said (the tests above).
    sub = repo / "tests"
    not_a_directory = str(repo / "pyproject.toml")
    reason = {
        "undecodable-prefix": "git rev-parse returned an undecodable prefix",
        "failed": "git rev-parse --show-toplevel failed: fatal: simulated",
        "timed-out": "git read could not complete",
        "not-a-directory": f"git rev-parse returned an unusable repository root {not_a_directory!r}",
    }[failure]
    note = f"checkwash: could not resolve the repository root: {reason}; using --repo as given\n"
    original = subprocess.run

    def no_root(argv, *args, **kwargs):
        query = argv[3:] if argv[:2] == ["git", "-C"] else None
        if query == ["rev-parse", "--is-inside-work-tree", "--show-prefix"] and failure == "undecodable-prefix":
            return subprocess.CompletedProcess(argv, 0, b"true\n\xff/\n", b"")
        if query == ["rev-parse", "--show-toplevel"] and failure == "failed":
            return subprocess.CompletedProcess(argv, 128, b"", b"fatal: simulated\n")
        if query == ["rev-parse", "--show-toplevel"] and failure == "timed-out":
            raise subprocess.TimeoutExpired(argv, 60)
        if query == ["rev-parse", "--show-toplevel"] and failure == "not-a-directory":
            return subprocess.CompletedProcess(argv, 0, not_a_directory.encode("utf-8") + b"\n", b"")
        return original(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", no_root)
    monkeypatch.setenv("CHECKWASH_TODAY", "2026-01-01")
    assert main(["allow", FINGERPRINT, "--reason", "reviewed", "--repo", str(sub)]) == 0
    recorded = capsys.readouterr()
    ledger = os.path.join(str(sub), ".greenwash", "allow.toml")
    assert recorded.out.startswith(f"recorded exemption in {ledger} (expires "), recorded.out
    assert recorded.err == note
    assert not (repo / ".greenwash").exists()
    code = main(["doctor", "--repo", str(sub)])
    via_main = capsys.readouterr()
    assert run_doctor(str(sub)) == code
    direct = capsys.readouterr()
    assert (via_main.out, via_main.err) == (direct.out, note + direct.err)
    full = ["quality", "--repo", str(sub), "--format", "json"]
    code = main(full)
    via_main = capsys.readouterr()
    expected, expected_code = run_quality(build_parser().parse_args(full), datetime.date(2026, 1, 1))
    direct = capsys.readouterr()
    assert (code, via_main.out, via_main.err) == (expected_code, expected, note + direct.err)
    assert main(["check", "--repo", str(sub), "--format", "json"]) == 2
    assert capsys.readouterr() == ("", f"checkwash engine error: {reason}\n")


# --- --task ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("target", ["tracked", "untracked"])
@pytest.mark.parametrize("where", ["root", "subdirectory"])
@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_a_symlinked_task_file_cannot_choose_the_contract(repo, mode, where, target):
    # SPEC §4c: the contract is read base-side at the task path. Following a
    # head-side symlink there would let it pick another base file without
    # oracle_freeze, or an untracked file the fallback then reads.
    _write(repo, "TASK.md", FREEZE)
    _write(repo, "NOTES.md", LOOSE)
    _commit(repo, "task contract")
    _write(repo, "tests/test_calc.py", WEAK)
    if mode == "range":
        _commit(repo, "weaken")
    else:
        # `git status` would list the type change and refuse the symlink.
        _git(repo, "update-index", "--skip-worktree", "TASK.md")
    if target == "untracked":
        _write(repo, "evil.md", LOOSE)
    (repo / "TASK.md").unlink()
    _symlink(repo / "TASK.md", "NOTES.md" if target == "tracked" else "evil.md")
    cwd, task = (repo, "TASK.md") if where == "root" else (repo / "tests", "../TASK.md")
    rev = ["HEAD~1..HEAD"] if mode == "range" else []
    assert _frozen(_run(cwd, "check", *rev, "--task", task, "--format", "json"))


@pytest.mark.parametrize("how", ["cwd", "repo"])
def test_a_task_path_maps_through_the_prefix(repo, how):
    # A root-relative reading of `TASK.md` from pkg/ would take the decoy.
    _write(repo, "TASK.md", LOOSE)
    _write(repo, "pkg/TASK.md", FREEZE)
    _commit(repo, "contracts")
    _write(repo, "tests/test_calc.py", WEAK)
    _commit(repo, "weaken")
    args = ("check", "HEAD~1..HEAD", "--format", "json")
    if how == "cwd":
        result = _run(repo / "pkg", *args, "--task", "TASK.md")
    else:
        result = _run_repo(repo / "pkg", *args, "--task", str(repo / "pkg" / "TASK.md"), cwd=repo.parent)
    assert _frozen(result)


# --- quality ----------------------------------------------------------------------------------------

def test_quality_range_from_a_subdirectory_is_the_root_review(repo):
    _write(repo, "tests/test_calc.py", WEAK)
    _commit(repo, "weaken")
    args = ("quality", "HEAD~1..HEAD", "--format", "json")
    root = _run(repo, *args)
    assert root.returncode == 0, root.stdout
    _same(_run(repo / "tests", *args), root, "tests")


@pytest.mark.parametrize("args", [("profiles",), ("explain", "QW_RULE_DISABLED")], ids=["profiles", "explain"])
def test_quality_profiles_and_explain_never_ask_git(repo, tmp_path, args):
    outside = _run(_plain(tmp_path), "quality", *args)
    assert (outside.returncode, outside.stderr) == (0, b""), outside.stderr
    inside = _run(repo / "tests", "quality", *args)
    assert (inside.returncode, inside.stdout, inside.stderr) == (0, outside.stdout, b"")


@pytest.mark.parametrize("argv", [["HEAD~1..HEAD"], [], ["doctor"], ["init"]],
                         ids=["range", "worktree", "doctor", "init"])
def test_quality_keeps_its_own_error_payload_outside_git(tmp_path, monkeypatch, capsys, argv):
    plain = _plain(tmp_path)
    monkeypatch.setenv("CHECKWASH_TODAY", "2026-01-01")
    full = ["quality", *argv, "--repo", str(plain), "--format", "json"]
    code = main(full)
    via_main = capsys.readouterr()
    expected, expected_code = run_quality(build_parser().parse_args(full), datetime.date(2026, 1, 1))
    assert (code, via_main.out, via_main.err) == (expected_code, expected, "")
    assert expected_code == 2 and json.loads(expected)


def test_the_temporary_directory_is_outside_any_git_work_tree(tmp_path):
    # Every non-Git case here, and those in tests/test_human_encoding.py and
    # tests/e2e/test_cli.py, holds only while pytest's basetemp is outside a
    # work tree. Inside one, they would rightly re-root into it.
    _plain(tmp_path)
