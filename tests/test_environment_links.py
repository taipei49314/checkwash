"""A virtual environment's own links in a working-tree run (re-review ND-02 on Linux and macOS; D-208).

On Linux and macOS `python -m venv` links the environment's interpreter
(`bin/python`, `bin/python3`, `bin/python3.X`, and in Python 3.14
`bin/𝜋thon`) and, on 64-bit Linux, `lib64` to `lib`. checkwash follows no
link. In a check without a range and the Stop hook, an environment Git did
not ignore made the change-list read refuse its first link ("strict
snapshot path leaves the repository"), so the run exited 2 and the Stop hook
said the change was not analysed, a weakened test beside it included. Even
an environment Git ignores stopped such a run, under any name but `.venv`
and `venv`, whenever a pass walked the working tree into it: the importer
search and the collection checks refused its `lib64`, and the PreToolUse
hook said an edit to a helper was not analysed.

Now an untracked link directly in `<D>/bin` or `<D>/Scripts` whose name does
not end in `.py` in any case, or `<D>/lib64` linking to `lib` beside a
directory `<D>/lib`, is carried with no bytes and set aside with a note,
unless a detector must read its path (#415's rule together with test,
conftest and test-support paths) or pytest's collection can reach `<D>`,
which refuses. `<D>` is a directory other than the repository root that
holds `pyvenv.cfg` as a regular file and that no compared commit (`HEAD`
and, in the Stop hook, the session base) holds. Non-directory own links in
`<D>/bin` and `<D>/Scripts` are left out of the working tree's listing, and
the walks pass over `<D>/lib64` when it links to `lib` beside a directory
`lib`: its files are those of `lib`. Every other link is read, and refused,
as before; range mode is unchanged, refusing any link a range adds or
changes, or one a pass reads: a committed interpreter link survives a later
`python -m venv` run without `--clear` at that path.

Making a link needs a host that can: on Windows without the privilege the
tests that make one skip. The range test makes its links in the index. The
fixture repositories are static inputs; nothing in them runs, except the
environments `python -m venv` writes for the last tests.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import EngineError, FileChange, LinkSide
from checkwash.config import Config
from checkwash.engine import _set_aside_links
import checkwash.gitio.git as git_module
from checkwash.gitio.git import GitError, environment_of_link, list_session_changes, list_worktree_changes
from checkwash.gitio.snapshot import WorkingTreeSnapshot, environment_lib64
from checkwash.opaque import SymlinkedDirectory

ROOT = Path(__file__).resolve().parents[1]
PKG = b"def total():\n    return 5\n"
HELPERS = b"from pkg import total\n\n\ndef check_total(expected):\n    assert total() == expected\n"
TEST = (b"from pkg import total\nfrom tests.helpers import check_total\n\n\n"
        b"def test_total():\n    assert total() == 5\n\n\n"
        b"def test_total_helper():\n    check_total(5)\n")
WEAKENED = TEST.replace(b"assert total() == 5", b"assert total() >= 0")
EXPECTED_CHANGED = TEST.replace(b"assert total() == 5", b"assert total() == 6")
HELPER_WEAKENED = HELPERS.replace(b"assert total() == expected", b"assert total() is not None")
MARKER = b"home = /usr/bin\ninclude-system-site-packages = false\nversion = 3.12.3\n"
LINKS = ["env/bin/python", "env/bin/python3", "env/bin/python3.12", "env/lib64"]
REFUSED = "strict snapshot path leaves the repository"


@pytest.fixture(autouse=True)
def plain_git(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("git-home")
    (home / "gitconfig").write_bytes(b"")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True, timeout=60).stdout


def write(repo, files):
    for path, data in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)


def link(path, target, directory=False):
    """A symbolic link, or a skip where the host cannot make one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, path, target_is_directory=directory)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "checkwash-test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "core.autocrlf", "false")
    write(root, {"pkg.py": PKG, "tests/__init__.py": b"", "tests/helpers.py": HELPERS,
                 "tests/test_total.py": TEST})
    git(root, "add", "-A")
    git(root, "commit", "-m", "base")
    return root


def environment(repo, name="env", *, marker=True, lib64=True):
    """The layout `python -m venv --without-pip` writes on 64-bit Linux, its links made here.

    The interpreter link names a path outside the repository, as the real one does.
    """
    write(repo, {f"{name}/bin/activate": b"# This file must be used with \"source bin/activate\" *from bash*\n",
                 f"{name}/lib/python3.12/site-packages/.keep": b""})
    if marker:
        write(repo, {f"{name}/pyvenv.cfg": MARKER})
    link(repo / name / "bin" / "python3", str(repo.parent / "outside" / "python3"))
    link(repo / name / "bin" / "python", "python3")
    link(repo / name / "bin" / "python3.12", "python3")
    if lib64:
        link(repo / name / "lib64", "lib", directory=True)
    return repo / name


def cli_env():
    return {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1",
            "GREENWASH_TODAY": "2026-11-13", "NO_COLOR": "1"}


def check(repo, *args, stdin=None, fmt="json"):
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", *args, "--format", fmt,
                             "--repo", str(repo)], env=cli_env(), capture_output=True, timeout=180,
                            input=stdin, cwd=str(repo))
    stdout, stderr = result.stdout.decode("utf-8"), result.stderr.decode("utf-8")
    return result.returncode, (json.loads(stdout) if stdout.strip() else None), stderr


def hook(repo, subcommand, payload):
    result = subprocess.run([sys.executable, "-m", "checkwash", "hook", subcommand, "--repo", str(repo)],
                            env=cli_env(), capture_output=True, timeout=180,
                            input=json.dumps(payload).encode("utf-8"), cwd=str(repo))
    stdout, stderr = result.stdout.decode("utf-8"), result.stderr.decode("utf-8")
    return result.returncode, (json.loads(stdout) if stdout.strip() else None), stderr


def note(path, environment_dir="env"):
    return f"checkwash: skipped the link {path} in the virtual environment {environment_dir}, which checkwash does not follow"


def carried(changes):
    return sorted(change.path for change in changes if change.links)


# --- LinkSide formatting -------------------------------------------------------------------------

def test_link_side_describes_printable_unicode_and_escapes_controls():
    assert LinkSide("env/bin/𝜋thon", "env").described() == "env/bin/𝜋thon in the virtual environment env"
    assert LinkSide("env/bin/py\x1bthon", "env").described() == "'env/bin/py\\x1bthon' in the virtual environment env"
    assert LinkSide("e\x1bnv/bin/python", "e\x1bnv").described() == (
        "'e\\x1bnv/bin/python' in the virtual environment 'e\\x1bnv'"
    )


# --- what the working-tree listings carry -------------------------------------------------------

def test_an_untracked_environments_own_links_are_carried_with_no_bytes(repo):
    environment(repo)
    link(repo / "env" / "bin" / "lib64", "python3")
    changes = list_worktree_changes(str(repo))
    assert carried(changes) == sorted([*LINKS, "env/bin/lib64"])
    for change in changes:
        if change.links:
            assert (change.status, change.before, change.after, change.unread) == ("added", None, None, ())
            assert change.links == (LinkSide(change.path, "env"),)
    # The environment's regular files are changes as before.
    assert {"env/pyvenv.cfg", "env/bin/activate"} <= {change.path for change in changes if not change.links}


def test_the_session_listing_carries_them_too(repo):
    environment(repo)
    head = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    assert carried(list_session_changes(str(repo), head)) == LINKS


def test_the_scripts_directory_of_an_environment_qualifies(repo):
    # `python -m venv --symlinks` on Windows links into `Scripts`.
    write(repo, {"env/pyvenv.cfg": MARKER})
    link(repo / "env" / "Scripts" / "python.exe", str(repo.parent / "outside" / "python.exe"))
    assert environment_of_link(str(repo), "env/Scripts/python.exe") == "env"
    assert carried(list_worktree_changes(str(repo))) == ["env/Scripts/python.exe"]


@pytest.mark.parametrize("name", [".venv", "venv", "tools/py312"])
def test_any_name_and_depth_qualifies(repo, name):
    environment(repo, name)
    assert carried(list_worktree_changes(str(repo))) == [f"{name}/{path[4:]}" for path in LINKS]


def test_an_untracked_sub_environment_under_a_tracked_parent_still_qualifies(repo):
    write(repo, {"tools/lint.py": b"x = 1\n"})
    git(repo, "add", "tools/lint.py")
    git(repo, "commit", "-m", "add tools")
    environment(repo, "tools/py312")
    assert carried(list_worktree_changes(str(repo))) == [f"tools/py312/{path[4:]}" for path in LINKS]


# --- what does not qualify, and is refused as before --------------------------------------------

def test_without_pyvenv_cfg_the_links_are_refused(repo):
    environment(repo, marker=False)
    with pytest.raises(EngineError, match=REFUSED):
        list_worktree_changes(str(repo))


def test_a_pyvenv_cfg_that_is_a_link_does_not_count(repo):
    write(repo, {"elsewhere.cfg": MARKER})
    environment(repo, marker=False)
    link(repo / "env" / "pyvenv.cfg", "../elsewhere.cfg")
    assert environment_of_link(str(repo), "env/bin/python") is None
    with pytest.raises(EngineError, match=REFUSED):
        list_worktree_changes(str(repo))


def test_a_pyvenv_cfg_that_is_a_directory_does_not_count(repo):
    environment(repo, marker=False)
    (repo / "env" / "pyvenv.cfg").mkdir()
    assert environment_of_link(str(repo), "env/bin/python") is None


def test_the_repository_root_is_no_environment(repo):
    write(repo, {"pyvenv.cfg": MARKER, "lib/.keep": b""})
    link(repo / "bin" / "python3", str(repo.parent / "outside" / "python3"))
    link(repo / "lib64", "lib", directory=True)
    assert environment_of_link(str(repo), "bin/python3") is None
    assert environment_of_link(str(repo), "lib64") is None
    with pytest.raises(EngineError, match=REFUSED):
        list_worktree_changes(str(repo))


@pytest.mark.parametrize("path", ["env/lib/python3.12/site-packages/module.py", "env/bin/sub/python3",
                                  "env/python3", "env/include/python3", "env/bin/helper.py",
                                  "env/bin/conftest.PY", "env/BIN/python3", "env/scripts/python.exe"])
def test_a_link_elsewhere_in_the_environment_is_refused(repo, path):
    write(repo, {"env/pyvenv.cfg": MARKER})
    link(repo / path, str(repo.parent / "outside" / "python3"))
    assert environment_of_link(str(repo), path) is None
    with pytest.raises(EngineError, match=REFUSED):
        list_worktree_changes(str(repo))


@pytest.mark.parametrize("kind", ["elsewhere", "outside", "dangling"])
def test_a_lib64_that_does_not_link_to_lib_beside_lib_is_refused(repo, kind):
    write(repo, {"env/pyvenv.cfg": MARKER})
    if kind == "elsewhere":
        write(repo, {"env/lib/.keep": b"", "elsewhere/.keep": b""})
        link(repo / "env" / "lib64", "../elsewhere", directory=True)
    elif kind == "outside":
        (repo.parent / "outside").mkdir()
        write(repo, {"env/lib/.keep": b""})
        link(repo / "env" / "lib64", str(repo.parent / "outside"), directory=True)
    else:
        link(repo / "env" / "lib64", "lib")
    assert environment_of_link(str(repo), "env/lib64") is None
    listed = set(WorkingTreeSnapshot(repo).list_paths())
    assert ("env/lib64" in listed) if kind == "dangling" else ("env/lib64/" in listed)
    with pytest.raises(EngineError, match="nonregular source|leaves the repository"):
        list_worktree_changes(str(repo))


def test_a_regular_file_in_the_scripts_directory_is_no_link(repo):
    write(repo, {"env/pyvenv.cfg": MARKER, "env/bin/python3": b"#!/bin/sh\nexit 0\n"})
    assert environment_of_link(str(repo), "env/bin/python3") is None
    assert carried(list_worktree_changes(str(repo))) == []


@pytest.mark.parametrize("tracked_dir", ["tests", "suite"])
def test_planting_pyvenv_cfg_in_a_tracked_directory_is_refused(repo, tracked_dir):
    if tracked_dir == "suite":
        write(repo, {"suite/check_total.py": TEST})
        git(repo, "add", "suite/check_total.py")
        git(repo, "commit", "-m", "add suite")
    write(repo, {f"{tracked_dir}/pyvenv.cfg": MARKER})
    link(repo / tracked_dir / "bin" / "plugins", str(repo.parent / "outside"), directory=True)
    assert environment_of_link(str(repo), f"{tracked_dir}/bin/plugins") == tracked_dir
    with pytest.raises(EngineError, match=REFUSED):
        list_worktree_changes(str(repo))


def test_if_git_cannot_say_whether_head_holds_the_environment_the_link_is_refused(repo, monkeypatch):
    environment(repo)
    real_run = git_module._run

    def fail_ls_tree(repo_arg, args):
        if "ls-tree" in args:
            raise GitError("ls-tree unavailable")
        return real_run(repo_arg, args)

    monkeypatch.setattr(git_module, "_run", fail_ls_tree)
    with pytest.raises(EngineError, match=REFUSED):
        list_worktree_changes(str(repo))


def test_a_tracked_environment_link_is_read_as_before(repo):
    environment(repo, lib64=False)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "the environment, committed")
    os.remove(repo / "env" / "bin" / "python3.12")
    link(repo / "env" / "bin" / "python3.12", "python")
    # Git lists it as modified, not untracked, so it is not carried.
    with pytest.raises(GitError, match="blob header does not match its regular tree entry"):
        list_worktree_changes(str(repo))


def test_a_staged_environment_link_is_read_as_before(repo):
    # Staged, the link is about to be committed: Git lists it as added, not untracked.
    environment(repo, lib64=False)
    git(repo, "add", "env")
    with pytest.raises(EngineError, match=REFUSED):
        list_worktree_changes(str(repo))


def test_a_link_the_session_base_holds_is_read_as_before(repo):
    # Committed at the session base, then untracked: not new to the session.
    environment(repo, lib64=False)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "the environment, committed")
    since = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    git(repo, "rm", "-r", "--cached", "-q", "env")
    git(repo, "commit", "-m", "untrack the environment")
    with pytest.raises(GitError, match="blob header does not match its regular tree entry"):
        list_session_changes(str(repo), since)
    with pytest.raises(EngineError, match=REFUSED):
        list_worktree_changes(str(repo), absent_at=(since,))


# --- the engine: set aside, or refused where a detector must read the path ---------------------

def linked(path, environment_dir="env"):
    return FileChange(path, "added", None, None, links=(LinkSide(path, environment_dir),))


def test_the_engine_sets_aside_a_link_no_detector_must_read():
    other = FileChange("pkg.py", "modified", PKG, PKG + b"\n")
    nested = linked("tests/.venv/bin/python3", "tests/.venv")
    readable, set_aside = _set_aside_links([other, *map(linked, LINKS), nested], Config(), [])
    assert readable == [other]
    assert [change.path for change in set_aside] == [*LINKS, "tests/.venv/bin/python3"]


@pytest.mark.parametrize("path,env_dir", [
    ("env/bin/run-tests.sh", "env"),
    ("env/bin/helper.py", "env"),
    ("env/bin/conftest.PY", "env"),
    ("env/bin/pytest.ini", "env"),
    ("env/bin/pyproject.toml", "env"),
    ("env/bin/Makefile", "env"),
    ("env/bin/value.test.js", "env"),
    ("tests/bin/plugins", "tests"),
    ("tests/bin/test_patch.txt", "tests"),
    ("test/bin/plugins", "test"),
    ("__tests__/bin/plugins", "__tests__"),
    ("__mocks__/bin/plugins", "__mocks__"),
])
def test_the_engine_refuses_a_link_whose_path_a_detector_reads(path, env_dir):
    with pytest.raises(EngineError, match="checkwash does not follow a link, and a detector must read this path"):
        _set_aside_links([linked(path, env_dir)], Config(), [])


def test_the_engine_refuses_a_link_the_task_scope_leaves_out():
    # An out-of-scope file is bound to its content (SCOPE_DRIFT), which a link does not have;
    # generated-output paths such as `.venv/**` skip SCOPE_DRIFT as regular files there do.
    with pytest.raises(EngineError, match="a detector must read this path"):
        _set_aside_links([linked("env/bin/python3")], Config(), ["src/**"])
    readable, set_aside = _set_aside_links([linked(".venv/bin/python3", ".venv")], Config(), ["src/**"])
    assert readable == [] and [change.path for change in set_aside] == [".venv/bin/python3"]


def test_the_engine_refuses_a_link_the_config_makes_ci():
    config = Config()
    config.roles["ci"] = [*config.roles["ci"], "env/**"]
    with pytest.raises(EngineError, match="a detector must read this path"):
        _set_aside_links([linked("env/bin/python3")], config, [])


def test_the_engine_refuses_a_link_package_json_lists_as_a_jest_setup_file():
    setup_pkg = b'{"jest":{"setupFiles":["./env/bin/setup.js"]}}'
    with pytest.raises(EngineError, match="env/bin/setup.js.*a detector must read this path"):
        _set_aside_links([linked("env/bin/setup.js")], Config(), [],
                         root_reader=lambda p: setup_pkg if p == "package.json" else None)
    readable, set_aside = _set_aside_links([linked("env/bin/setup.js")], Config(), [],
                                           root_reader=lambda p: b'{"jest":{}}' if p == "package.json" else None)
    assert readable == [] and [change.path for change in set_aside] == ["env/bin/setup.js"]

    # The base package.json is asked after the first pass, so an earlier JS link does not read it first.
    def boom(_path):
        raise EngineError("package.json read too early")

    with pytest.raises(EngineError, match="env/bin/run-tests.sh.*a detector must read this path"):
        _set_aside_links([linked("env/bin/setup.js"), linked("env/bin/run-tests.sh")], Config(), [],
                         root_reader=boom)


@pytest.mark.parametrize("files,changes", [
    ({"pyproject.toml": b'[tool.pytest.ini_options]\ntestpaths = ["myenv"]\n'}, []),
    ({}, [FileChange("pytest.ini", "added", None, b"[pytest]\ntestpaths = *\n")]),
    ({"pytest.ini": b"[pytest]\naddopts = myenv\n"}, []),
    ({"pytest.ini": b"[pytest]\naddopts = --collect-in-virtualenv\n"}, []),
    ({"scripts/test.sh": b"#!/bin/sh\npytest myenv\n"}, []),
    ({".github/workflows/ci.yml": (
        b"name: ci\non: push\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n"
        b"      - run: pytest --collect-in-virtualenv\n"
    )}, []),
    ({"scripts/test.sh": b"#!/bin/sh\npytest -o testpaths=myenv\n"}, []),
    ({"scripts/test.sh": b"#!/bin/sh\npytest . myenv\n"}, []),
    ({"scripts/test.sh": b"#!/bin/sh\necho running && pytest \\\n  myenv\n"}, []),
    ({"scripts/test.sh": b"#!/bin/sh\nPYTEST_ADDOPTS=myenv pytest\n"}, []),
    ({".github/workflows/ci.yml": (
        b'name: ci\non: push\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n'
        b'      - run: "pytest myenv"\n'
    )}, []),
    ({".github/workflows/ci.yml": (
        b"name: ci\non: push\njobs:\n  t:\n    runs-on: ubuntu-latest\n    steps:\n"
        b"      - working-directory: myenv\n        run: pytest\n"
    )}, []),
    ({"pyproject.toml": b'[tool.pytest]\ntestpaths = ["myenv"]\naddopts = ["-z"]\n'}, []),
    ({"pytest.ini": b"[pytest]\ntestpaths = []m]yenv\n"}, []),
    ({"tox.ini": b"[tox]\n[testenv]\ncommands = pytest {toxinidir}/myenv\n"}, []),
    ({"pytest.ini": b"[pytest]\naddopts = --pyargs pkg\n"}, []),
])
def test_the_engine_refuses_an_environment_pytest_collection_can_reach(files, changes):
    with pytest.raises(EngineError, match="myenv/bin/python3.*pytest's collection can reach this environment"):
        _set_aside_links(
            [*changes, linked("myenv/bin/python3", "myenv")],
            Config(),
            [],
            root_reader=files.get,
            root_path_lister=lambda: sorted(files),
            root_batch_reader=lambda paths: {p: files[p] for p in paths if p in files},
        )


def test_the_engine_allows_an_environment_pytest_collection_skips():
    files = {
        "pyproject.toml": b'[tool.pytest.ini_options]\ntestpaths = ["tests"]\n',
        "scripts/test.sh": b"#!/bin/sh\npytest tests\n",
    }
    readable, set_aside = _set_aside_links(
        [linked("myenv/bin/python3", "myenv")],
        Config(),
        [],
        root_reader=files.get,
        root_path_lister=lambda: [*sorted(files), SymlinkedDirectory("other/")],
        root_batch_reader=lambda paths: {p: files[p] for p in paths if p in files},
    )
    assert readable == [] and [c.path for c in set_aside] == ["myenv/bin/python3"]


# --- the working tree's walks and lib64 ------------------------------------------------------------

def test_the_walks_leave_out_an_environments_own_links(repo):
    environment(repo)
    snapshot = WorkingTreeSnapshot(repo)
    listed = snapshot.list_paths()
    assert not {*LINKS, "env/lib64/"} & set(listed)
    assert {"env/bin/activate", "env/pyvenv.cfg", "env/lib/python3.12/site-packages/.keep"} <= set(listed)
    assert environment_lib64(str(repo / "env"), "lib64")
    snapshot.search(["check_total"])  # the importer search: no refusal
    snapshot.search([""])  # the inventory: no refusal


def test_a_real_lib64_directory_is_walked_and_listed(repo):
    write(repo, {"src/lib64/mod.py": b"MARKER_TOKEN = 1\n",
                 "env/pyvenv.cfg": MARKER,
                 "env/lib/.keep": b"",
                 "env/lib64/inside.py": b"MARKER_TOKEN = 2\n"})
    snapshot = WorkingTreeSnapshot(repo)
    assert not environment_lib64(str(repo / "env"), "lib64")
    assert {"src/lib64/mod.py", "env/lib64/inside.py"} <= set(snapshot.list_paths())
    assert {"src/lib64/mod.py", "env/lib64/inside.py"} <= set(snapshot.search(["MARKER_TOKEN"]))


def test_the_inventory_keeps_any_other_link(repo):
    write(repo, {"env/pyvenv.cfg": MARKER})
    link(repo / "env" / "bin" / "helper.py", "../../pkg.py")
    link(repo / "env" / "python3", str(repo.parent / "outside" / "python3"))
    link(repo / "tools" / "bin" / "python3", str(repo.parent / "outside" / "python3"))
    listed = set(WorkingTreeSnapshot(repo).list_paths())
    assert {"env/bin/helper.py", "env/python3", "tools/bin/python3"} <= listed


def test_a_directory_link_in_scripts_stays_opaque_in_the_inventory(repo):
    write(repo, {"env/pyvenv.cfg": MARKER, "elsewhere/.keep": b""})
    link(repo / "env" / "bin" / "toolsdir", "../../elsewhere", directory=True)
    assert carried(list_worktree_changes(str(repo))) == ["env/bin/toolsdir"]
    snapshot = WorkingTreeSnapshot(repo)
    assert "env/bin/toolsdir/" in snapshot.list_paths()
    with pytest.raises(EngineError, match="cannot follow directory symlink"):
        snapshot.search(["check_total"])
    write(repo, {"pkg.py": b"def total():\n    return 2 + 3\n"})
    code, payload, stderr = check(repo)
    assert (code, payload["verdict"]) == (0, "pass") and note("env/bin/toolsdir") in stderr
    write(repo, {"tests/helpers.py": HELPER_WEAKENED})
    code_helper, payload_helper, stderr_helper = check(repo)
    assert code_helper == 2 and payload_helper is None and "env/bin/toolsdir" in stderr_helper


@pytest.mark.parametrize("variant", ["no marker", "another text", "lib is a link", "at the root"])
def test_any_other_directory_link_stays_opaque(repo, variant):
    write(repo, {"elsewhere/.keep": b""})
    if variant == "at the root":
        write(repo, {"pyvenv.cfg": MARKER, "lib/.keep": b""})
        link(repo / "lib64", "lib", directory=True)
        expected = "lib64/"
    else:
        if variant != "no marker":
            write(repo, {"env/pyvenv.cfg": MARKER})
        if variant == "lib is a link":
            link(repo / "env" / "lib", "../elsewhere", directory=True)
        else:
            write(repo, {"env/lib/.keep": b""})
        link(repo / "env" / "lib64", "../elsewhere" if variant == "another text" else "lib", directory=True)
        expected = "env/lib64/"
    snapshot = WorkingTreeSnapshot(repo)
    assert expected in snapshot.list_paths()
    with pytest.raises(EngineError, match="cannot follow directory symlink"):
        snapshot.search(["check_total"])


# --- the command line -----------------------------------------------------------------------------

def test_an_honest_change_beside_an_environment_passes_with_a_note_per_link(repo):
    environment(repo)
    write(repo, {"pkg.py": b"def total():\n    return 2 + 3\n"})
    code, payload, stderr = check(repo)
    assert "engine error" not in stderr, stderr
    assert (code, payload["verdict"]) == (0, "pass")
    assert "unread" not in payload
    for path in LINKS:
        assert note(path) in stderr


def test_a_set_aside_link_earns_no_repair_evidence_and_is_absent_from_ir(repo):
    environment(repo)
    write(repo, {"tests/test_total.py": EXPECTED_CHANGED})
    code, payload, stderr = check(repo)
    assert "engine error" not in stderr, stderr
    rules = {finding["rule"] for finding in payload["findings"]}
    assert "EXPECTED_VALUE_CHANGED" in rules
    assert "REPAIR_EVIDENCE" not in rules
    code_ir, ir_payload, stderr_ir = check(repo, "--emit-ir")
    assert code_ir == 0, stderr_ir
    ir_paths = {entry["path"] for entry in ir_payload["files"]}
    assert not (set(LINKS) & ir_paths)


@pytest.mark.parametrize("name", ["env", ".venv"])
def test_a_weakened_test_beside_an_environment_blocks(repo, name):
    environment(repo, name)
    write(repo, {"tests/test_total.py": WEAKENED})
    code, payload, stderr = check(repo)
    assert "engine error" not in stderr, stderr
    assert (code, payload["verdict"]) == (1, "block")
    assert "ASSERT_WEAKENED" in {finding["rule"] for finding in payload["findings"]}


def test_a_weakened_helper_beside_an_environment_blocks(repo):
    # The importer search walks the environment, and passes over its lib64.
    environment(repo)
    write(repo, {"tests/helpers.py": HELPER_WEAKENED})
    code, payload, stderr = check(repo)
    assert "engine error" not in stderr, stderr
    assert (code, payload["verdict"]) == (1, "block")


def test_a_first_pytest_config_beside_an_environment_blocks(repo):
    # The collection checks list the working tree, and pass over its lib64.
    environment(repo)
    write(repo, {"pytest.ini": b"[pytest]\ntestpaths = tests\npython_files = nothing_*.py\n"})
    code, payload, stderr = check(repo)
    assert "engine error" not in stderr, stderr
    assert (code, payload["verdict"]) == (1, "block")


@pytest.mark.parametrize("ignored", [False, True])
def test_a_new_provider_beside_an_environment_gets_a_verdict(repo, ignored):
    # test_issue455's provider-pass fixture: a new provider of `src.billing`
    # takes the runtime-provider pass to the phase that reads every dot-less
    # path of the working tree's inventory, which leaves out the
    # environment's non-directory links, untracked or ignored.
    write(repo, {"src/billing.py": b"def invoice_total():\n    return 1\n",
                 "tests/test_billing.py": (b"from src.billing import invoice_total\n\n\n"
                                           b"def test_invoice_total():\n    assert invoice_total() == 1\n"),
                 **({".gitignore": b"/env/\n"} if ignored else {})})
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "billing")
    environment(repo)
    write(repo, {"tests/src/billing.py": b"def invoice_total():\n    return 2\n"})
    code, payload, stderr = check(repo)
    assert "engine error" not in stderr, stderr
    assert code == 0 and payload["verdict"] == "pass"
    assert ("skipped the link" in stderr) is not ignored


def test_an_ignored_environment_beside_a_weakened_helper_blocks(repo):
    # Ignored, the environment is in no listing, but the walks still met its lib64.
    write(repo, {".gitignore": b"/env/\n"})
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "ignore the environment")
    environment(repo)
    write(repo, {"tests/helpers.py": HELPER_WEAKENED})
    code, payload, stderr = check(repo)
    assert "engine error" not in stderr, stderr
    assert (code, payload["verdict"]) == (1, "block")
    assert "skipped the link" not in stderr


def test_a_link_a_detector_must_read_stops_the_run(repo):
    environment(repo)
    link(repo / "env" / "bin" / "run-tests.sh", str(repo.parent / "outside" / "run-tests.sh"))
    code, payload, stderr = check(repo)
    assert code == 2 and payload is None
    assert "strict snapshot cannot read the link env/bin/run-tests.sh in the virtual environment env" in stderr
    assert "skipped the link" not in stderr


@pytest.mark.parametrize("how", ["testpaths", "runner", "planted_in_tests"])
def test_an_environment_pytest_collects_stops_the_run(repo, how):
    if how == "planted_in_tests":
        write(repo, {"tests/pyvenv.cfg": MARKER})
        link(repo / "tests" / "bin" / "plugins", str(repo.parent / "outside"), directory=True)
        code, payload, stderr = check(repo)
        assert code == 2 and payload is None
        assert REFUSED in stderr
        return
    if how == "testpaths":
        write(repo, {"pyproject.toml": b'[tool.pytest.ini_options]\ntestpaths = ["tests", "myenv"]\n'})
    else:
        write(repo, {"scripts/test.sh": b"#!/bin/sh\npytest myenv\n"})
    git(repo, "add", "-A")
    git(repo, "commit", "-m", how)
    environment(repo, "myenv")
    code, payload, stderr = check(repo)
    assert code == 2 and payload is None
    assert "strict snapshot cannot read the link myenv/bin/python in the virtual environment myenv" in stderr
    assert "pytest's collection can reach this environment" in stderr
    assert "skipped the link" not in stderr


def test_the_stop_hook_blocks_a_weakened_test_beside_an_environment(repo):
    environment(repo)
    write(repo, {"tests/test_total.py": WEAKENED})
    stop = json.dumps({"session_id": "s-1", "hook_event_name": "Stop", "stop_hook_active": False}).encode()
    code, payload, stderr = check(repo, "--hook-input", "stdin", stdin=stop, fmt="hook-json")
    assert code == 0
    assert payload["decision"] == "block" and "ASSERT_WEAKENED" in payload["reason"]
    assert "not analysed" not in json.dumps(payload)


def test_the_stop_hook_reports_a_must_read_link_as_not_analysed(repo):
    environment(repo)
    link(repo / "env" / "bin" / "run-tests.sh", str(repo.parent / "outside" / "run-tests.sh"))
    stop = json.dumps({"session_id": "s-1", "hook_event_name": "Stop", "stop_hook_active": False}).encode()
    code, payload, _stderr = check(repo, "--hook-input", "stdin", stdin=stop, fmt="hook-json")
    assert code == 0
    assert "decision" not in payload
    assert "this change was not analysed" in payload["systemMessage"]


def test_the_stop_hook_size_block_wins_over_a_must_read_link(repo):
    environment(repo)
    link(repo / "env" / "bin" / "run-tests.sh", str(repo.parent / "outside" / "run-tests.sh"))
    write(repo, {"tests/test_big.py": b"x = 1\n" * 200_010})
    stop = json.dumps({"session_id": "s-1", "hook_event_name": "Stop", "stop_hook_active": False}).encode()
    code, payload, _stderr = check(repo, "--hook-input", "stdin", stdin=stop, fmt="hook-json")
    assert code == 0
    assert payload["decision"] == "block"
    assert "tests/test_big.py" in payload["reason"]


def test_the_stop_hook_analyses_session_commits_beside_an_untracked_environment(repo):
    code_start, _out, err_start = hook(repo, "session-start",
                                       {"session_id": "s-2", "hook_event_name": "SessionStart", "source": "startup"})
    assert code_start == 0, err_start
    write(repo, {"tests/test_total.py": WEAKENED})
    git(repo, "add", "tests/test_total.py")
    git(repo, "commit", "-m", "weaken test during session")
    environment(repo)
    stop = json.dumps({"session_id": "s-2", "hook_event_name": "Stop", "stop_hook_active": False}).encode()
    code, payload, stderr = check(repo, "--hook-input", "stdin", stdin=stop, fmt="hook-json")
    assert code == 0, stderr
    assert "decision" not in payload
    assert "commits made during this session hold 1 finding(s)" in payload["systemMessage"]


@pytest.mark.parametrize("ignored", [False, True])
def test_the_pre_tool_use_hook_asks_on_a_weakened_helper_beside_an_environment(repo, ignored):
    if ignored:
        write(repo, {".gitignore": b"/env/\n"})
        git(repo, "add", ".gitignore")
        git(repo, "commit", "-m", "ignore env")
    environment(repo)
    weak_event = {
        "session_id": "s-pre", "transcript_path": "", "cwd": str(repo), "permission_mode": "default",
        "hook_event_name": "PreToolUse", "tool_name": "Write", "tool_use_id": "toolu_1",
        "tool_input": {"file_path": str(repo / "tests" / "helpers.py"), "content": HELPER_WEAKENED.decode()},
    }
    code, payload, stderr = hook(repo, "pre-tool-use", weak_event)
    assert code == 0, stderr
    assert payload["hookSpecificOutput"]["permissionDecision"] == "ask"
    assert "ASSERT_WEAKENED" in payload["hookSpecificOutput"]["permissionDecisionReason"]

    honest_event = {**weak_event, "tool_use_id": "toolu_2",
                    "tool_input": {"file_path": str(repo / "tests" / "helpers.py"),
                                   "content": (HELPERS + b"\n").decode()}}
    code_ok, payload_ok, stderr_ok = hook(repo, "pre-tool-use", honest_event)
    assert code_ok == 0, stderr_ok
    assert payload_ok == {}


def test_a_committed_environment_is_refused_when_added_in_a_range(repo):
    # Made in the index, so every host commits the same links (mode 120000).
    base = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    write(repo, {"env/pyvenv.cfg": MARKER})
    git(repo, "add", "env/pyvenv.cfg")
    for path, target in (("env/bin/python3", b"/usr/bin/python3"), ("env/bin/python", b"python3")):
        oid = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=target,
                             capture_output=True, check=True).stdout.decode("ascii").strip()
        git(repo, "update-index", "--add", "--cacheinfo", f"120000,{oid},{path}")
    git(repo, "commit", "-m", "the environment, committed")
    code, payload, stderr = check(repo, f"{base}..HEAD")
    assert code == 2
    assert "strict snapshot batch cannot inspect nonregular source env/bin/python (a symlink)" in stderr


# --- environments `python -m venv` writes ----------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="python -m venv copies the interpreter on Windows")
@pytest.mark.parametrize("weakened", [False, True])
def test_an_environment_python_writes(repo, weakened):
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", "env"], cwd=repo, check=True,
                   capture_output=True, timeout=120)
    if (repo / "env" / ".gitignore").exists():
        os.remove(repo / "env" / ".gitignore")  # Python 3.13 and later ignore it themselves
    links = sorted(path.relative_to(repo).as_posix() for path in (repo / "env").rglob("*") if path.is_symlink())
    assert links and carried(list_worktree_changes(str(repo))) == links
    write(repo, {"tests/test_total.py": WEAKENED} if weakened else {"pkg.py": b"def total():\n    return 2 + 3\n"})
    code, payload, stderr = check(repo)
    assert "engine error" not in stderr, stderr
    assert (code, payload["verdict"]) == ((1, "block") if weakened else (0, "pass"))
