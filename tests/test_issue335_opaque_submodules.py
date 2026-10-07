"""Issue #335: a git submodule is a directory whose content is unknown.

In range mode, every pass that read the path inventory raised "strict snapshot
inventory cannot inspect a submodule", so a repository whose tree holds a
gitlink got an engine error (exit 2) for nearly any Python change: a rewritten
expected value was not blocked and an added test was not passed.

The inventory now lists a submodule as its path with a trailing slash. A pass
that needs a fact from inside one fails closed with an engine error naming
the path: a read inside it, an import that resolves into it, or a pytest
collection that can reach it on either side. Every other pass proceeds over
the rest of the tree.
"""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.collection_inventory import _DEFAULTS, _reaches, opaque_reached
from checkwash.contract import Contract
from checkwash.engine import _root_importer_changes, analyze
from checkwash.frontends.python.standin_installations import installation_events
from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.gitio.snapshot import GitSnapshot, search_source_mapping
from checkwash.ir.model import IR, DiffGlobals
from checkwash.opaque import opaque_owner, split_inventory
from checkwash.shadow import _selected_provider, find_runtime_subject_shadows

GITLINK = "1111111111111111111111111111111111111111"
SETUP = b"[tool:pytest]\naddopts = -ra\ntestpaths = tests\n"
TOTAL = b"def total():\n    return 78.75\n"
TEST = b"from pkg import total\n\n\ndef test_total():\n    assert total() == 78.75\n"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout.decode().strip()


def _repo(tmp_path, files):
    """A repository whose base commit holds `files` and a gitlink at vendor/lib."""
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "checkwash-test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    files = {".gitmodules": b'[submodule "vendor/lib"]\n\tpath = vendor/lib\n\turl = https://example.invalid/lib.git\n',
             **files}
    for path, data in files.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes(data)
    git(tmp_path, "add", "-A")
    git(tmp_path, "update-index", "--add", "--cacheinfo", f"160000,{GITLINK},vendor/lib")
    git(tmp_path, "commit", "-m", "base")
    return tmp_path


def _commit(repo, files=None, gitlink=None):
    for path, data in (files or {}).items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)
        git(repo, "add", path)
    if gitlink:
        git(repo, "update-index", "--cacheinfo", f"160000,{gitlink},vendor/lib")
    git(repo, "commit", "-m", "head")


def _check(repo):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "PYTHONUTF8": "1"}
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", "HEAD~1..HEAD", "--repo", str(repo),
                             "--format", "json"], env=env, capture_output=True, timeout=60)
    if result.returncode == 2:
        return 2, result.stderr.decode()
    report = json.loads(result.stdout)
    return result.returncode, report["verdict"], [(f["rule"], f["severity"]) for f in report["findings"]]


BASE = {"setup.cfg": SETUP, "src/pkg/__init__.py": TOTAL, "tests/test_total.py": TEST}


# --- the issue's rows ---------------------------------------------------------------------------

def test_a_rewritten_expected_value_still_blocks(tmp_path):
    repo = _repo(tmp_path, BASE)
    _commit(repo, {"tests/test_total.py": TEST.replace(b"== 78.75", b"== 75")})
    assert _check(repo) == (1, "block", [("EXPECTED_VALUE_CHANGED", "high")])


def test_an_added_test_passes(tmp_path):
    repo = _repo(tmp_path, BASE)
    _commit(repo, {"tests/test_more.py": b"from pkg import total\n\n\ndef test_more():\n    assert total() > 0\n"})
    assert _check(repo) == (0, "pass", [])


def test_an_addopts_edit_passes_with_its_warning(tmp_path):
    repo = _repo(tmp_path, BASE)
    _commit(repo, {"setup.cfg": SETUP.replace(b"-ra", b"-ra --showlocals")})
    assert _check(repo) == (0, "pass", [("CI_WORKFLOW_TOUCHED", "warn")])


def test_the_pointer_moved_passes(tmp_path):
    repo = _repo(tmp_path, BASE)
    _commit(repo, gitlink="2" * 40)
    assert _check(repo) == (0, "pass", [])


# --- a fact from inside still fails closed, naming the path --------------------------------------

VENDOR_TEST = b"from vendor.lib.calc import total\n\n\ndef test_vendor():\n    assert total() == 78.75\n"


@pytest.mark.parametrize("files", [
    # an expected value defined inside the submodule
    {"tests/test_vendor.py": b"from vendor.lib.calc import total, expected_total\n\n\n"
                             b"def test_vendor():\n    assert total() == expected_total()\n"},
    # a stand-in installed on a module object from inside it
    {"tests/test_vendor.py": b"from vendor.lib import calc\n\n\ndef test_vendor(monkeypatch):\n"
                             b"    monkeypatch.setattr(calc, 'rate', lambda: 2)\n    assert calc.total() == 78.75\n"},
], ids=["expected_value_inside", "module_object_inside"])
def test_an_import_that_needs_the_submodule_fails_closed(tmp_path, files):
    repo = _repo(tmp_path, {**BASE, "tests/test_vendor.py": VENDOR_TEST})
    _commit(repo, files)
    code, stderr = _check(repo)
    assert code == 2
    assert "cannot inspect the submodule vendor/lib" in stderr


@pytest.mark.parametrize("setup, head, extra", [
    # no testpaths keeps it out
    (b"[tool:pytest]\naddopts = -ra\n", b"[tool:pytest]\naddopts = -ra --showlocals\n", {}),
    # norecursedirs changing over it
    (b"[tool:pytest]\naddopts = -ra\n", b"[tool:pytest]\naddopts = -ra\nnorecursedirs = vendor\n", {}),
    # a path argument naming it
    (SETUP, SETUP.replace(b"-ra", b"-ra --showlocals"), {"Makefile": b"test:\n\tpytest vendor/lib tests\n"}),
], ids=["no_testpaths", "norecursedirs_changed", "path_argument"])
def test_a_collection_that_reaches_the_submodule_fails_closed(tmp_path, setup, head, extra):
    repo = _repo(tmp_path, {**BASE, "setup.cfg": setup, **extra})
    _commit(repo, {"setup.cfg": head})
    code, stderr = _check(repo)
    assert code == 2
    assert "cannot inspect the submodule vendor/lib: pytest's collection can reach it" in stderr


def test_an_import_from_it_that_no_pass_needs_proceeds(tmp_path):
    """A test of the submodule's code still has its own oracle judged."""
    repo = _repo(tmp_path, {**BASE, "tests/test_vendor.py": VENDOR_TEST})
    _commit(repo, {"tests/test_vendor.py": VENDOR_TEST.replace(b"== 78.75", b"== 75")})
    assert _check(repo) == (1, "block", [("EXPECTED_VALUE_CHANGED", "high")])


# --- the snapshot ---------------------------------------------------------------------------------

def test_the_inventory_lists_the_submodule_as_a_directory(tmp_path):
    snapshot = GitSnapshot(_repo(tmp_path, BASE), "HEAD")
    assert snapshot.list_paths() == [".gitmodules", "setup.cfg", "src/pkg/__init__.py", "tests/test_total.py",
                                     "vendor/lib/"]
    assert split_inventory(snapshot.list_paths())[1] == ("vendor/lib",)


def test_a_read_inside_the_submodule_fails_closed(tmp_path):
    repo = _repo(tmp_path, BASE)
    snapshot = GitSnapshot(repo, "HEAD")
    assert snapshot.read("vendor/lib") is None
    assert snapshot.read("vendor/missing.py") is None
    with pytest.raises(EngineError, match="the submodule vendor/lib: vendor/lib/calc.py lies inside it"):
        snapshot.read("vendor/lib/calc.py")
    # once the inventory is listed, the batch read knows it too
    with pytest.raises(EngineError, match="the submodule vendor/lib: vendor/lib/a/b.py lies inside it"):
        GitSnapshot(repo, "HEAD").read_many(["setup.cfg", "vendor/lib/a/b.py"])
    assert GitSnapshot(repo, "HEAD").read_many(["vendor/lib"]) == {"vendor/lib": None}


def test_the_submodule_entry_reads_as_no_file_whatever_git_answers(tmp_path, monkeypatch):
    """git 2.43 answers `HEAD:vendor/lib` with `<spec> missing`; git 2.55, on CI's runners, with
    `<oid> submodule`, which the read took for a malformed blob header. The tree entry decides."""
    from checkwash.gitio import snapshot as snapshot_module

    real = snapshot_module._run

    def git_2_55(repo, args, **kwargs):
        data = kwargs.get("data") or b""
        if args == ["cat-file", "--batch-check"] and data.endswith((b":vendor/lib\n", b":vendor/lib/calc.py\n")):
            return f"{GITLINK} submodule\n".encode("ascii")
        return real(repo, args, **kwargs)

    monkeypatch.setattr(snapshot_module, "_run", git_2_55)
    repo = _repo(tmp_path, {**BASE, "vendor/other/x.py": b""})
    assert GitSnapshot(repo, "HEAD").read("vendor/lib") is None
    listed = GitSnapshot(repo, "HEAD")
    listed.list_paths()
    assert listed.read("vendor/lib") is None
    with pytest.raises(EngineError, match="the submodule vendor/lib: vendor/lib/calc.py lies inside it"):
        GitSnapshot(repo, "HEAD").read("vendor/lib/calc.py")
    # a directory is no file either, beside the submodule or above it, and its read still fails closed
    for directory in ("vendor/other", "vendor"):
        with pytest.raises(EngineError, match="invalid blob header"):
            GitSnapshot(repo, "HEAD").read(directory)


def test_a_missing_path_beside_the_submodule_reads_as_missing(tmp_path):
    """Git lists the submodule among a parent's entries; only an ancestor of the path is its owner."""
    repo = _repo(tmp_path, {**BASE, "vendor/other/x.py": b""})
    assert GitSnapshot(repo, "HEAD").read("vendor/other/missing.py") is None


def test_the_python_inventory_names_the_submodule(tmp_path):
    with pytest.raises(EngineError, match="the submodule vendor/lib: the Python inventory needs its sources"):
        GitSnapshot(_repo(tmp_path, BASE), "HEAD").search([""])


def test_a_sibling_whose_name_extends_the_submodule_is_outside_it():
    assert opaque_owner("vendor/library/x.py", ("vendor/lib",)) is None
    assert opaque_owner("vendor/lib/x.py", ("vendor/lib",)) == "vendor/lib"
    assert split_inventory(["a.py", "vendor/lib/", "b/"]) == (["a.py"], ("b", "vendor/lib"))


# --- what reaches it ------------------------------------------------------------------------------

@pytest.mark.parametrize("root, skipped, reached", [
    (".", _DEFAULTS["norecursedirs"], True),
    ("tests", _DEFAULTS["norecursedirs"], False),
    ("vendor", _DEFAULTS["norecursedirs"], True),
    ("vendor/lib/tests", _DEFAULTS["norecursedirs"], True),
    (".", ("vendor",), False),
    ("*/tests", _DEFAULTS["norecursedirs"], True),
    ("tests/*", _DEFAULTS["norecursedirs"], False),
], ids=["root", "testpath_beside", "testpath_above", "testpath_inside", "norecursedirs", "glob_anywhere",
        "glob_beside"])
def test_what_a_root_reaches(root, skipped, reached):
    assert _reaches(root, "vendor/lib", skipped) is reached


def test_pytest_default_norecursedirs_keep_dot_and_build_directories_out():
    assert not _reaches(".", ".deps/lib", _DEFAULTS["norecursedirs"])
    assert not _reaches(".", "build/lib", _DEFAULTS["norecursedirs"])


def _setup(text):
    return FileChange("setup.cfg", "modified", text[0], text[1])


@pytest.mark.parametrize("before, after, reached", [
    (SETUP, SETUP, None),
    (b"[tool:pytest]\naddopts = -ra\n", SETUP, "vendor/lib"),
    (SETUP, b"[tool:pytest]\naddopts = -ra\n", "vendor/lib"),
    (b"[tool:pytest]\nnorecursedirs = vendor\n", b"[tool:pytest]\nnorecursedirs = vendor build\n", None),
], ids=["kept_out", "before_side_reaches", "after_side_reaches", "kept_out_on_both_sides"])
def test_either_side_counts(before, after, reached):
    assert opaque_reached(("vendor/lib",), {"setup.cfg": after}, [_setup((before, after))]) == reached


def test_a_runner_path_argument_reaches_it_past_testpaths():
    head = {"setup.cfg": SETUP, "Makefile": b"test:\n\tpytest vendor/lib\n"}
    assert opaque_reached(("vendor/lib",), head, []) == "vendor/lib"
    assert opaque_reached(("vendor/lib",), {**head, "Makefile": b"test:\n\tpytest tests\n"}, []) is None


@pytest.mark.parametrize("runners, reached", [
    ({"Makefile": b"test:\n\tpytest tests\n"}, None),
    ({"Makefile": b"test:\n\tpytest tests\n", "tox.ini": b"[testenv]\ncommands = pytest\n"}, "vendor/lib"),
    ({"Makefile": b"test:\n\tpytest $(ARGS)\n"}, None),
    ({"tox.ini": b"[testenv]\ncommands = pytest {posargs:tests}\n"}, None),
    ({"tox.ini": b"[testenv]\ncommands = pytest []\n"}, None),
    ({"Makefile": b"test:\n\tpytest */lib\n"}, "vendor/lib"),
    ({"Makefile": b"test:\n\tpytest tests\n", "noxfile.py": b"def tests(session):\n    session.run('pytest')\n"},
     "vendor/lib"),
    ({"Makefile": b"test:\n\tpytest -c ci/pytest.ini tests\n"}, "vendor/lib"),
], ids=["only_paths_beside_it", "a_bare_run_too", "make_variable", "tox_posargs", "tox_old_posargs", "glob",
        "unparsed_command", "own_config"])
def test_what_a_runner_command_reaches(runners, reached):
    """Every run counts; a variable names no path, and a run this reader cannot resolve reaches."""
    head = {"setup.cfg": b"[tool:pytest]\naddopts = -ra\n", **runners}
    assert opaque_reached(("vendor/lib",), head, []) == reached


def test_a_config_renamed_into_place_was_absent_on_the_base_side():
    moved = b"[pytest]\ntestpaths = tests\n"
    renamed = FileChange("pytest.ini", "modified", moved, moved, old_path="ci/pytest.ini")
    assert opaque_reached(("vendor/lib",), {"pytest.ini": moved}, [renamed]) == "vendor/lib"
    assert opaque_reached(("vendor/lib",), {"pytest.ini": moved}, []) is None


@pytest.mark.parametrize("config, reached", [
    (b"[tool:pytest]\ntestpaths = tests\ntestpaths = other\n", None),
    (b"[tool:pytest]\ntestpaths = tests\ntestpaths = .\n", "vendor/lib"),
    (b"[tool:pytest]\nnorecursedirs = vendor\nnorecursedirs = vendor build\n", None),
    (b"[tool:pytest]\nnorecursedirs = vendor\nnorecursedirs = build\n", "vendor/lib"),
], ids=["testpaths_beside_it_both_ways", "testpaths_one_way", "kept_out_both_ways", "kept_out_one_way"])
def test_a_setting_read_two_ways_counts_both_ways(config, reached):
    """A key given twice is read both ways."""
    assert opaque_reached(("vendor/lib",), {"setup.cfg": config}, []) == reached


def test_a_config_this_reader_cannot_decode_reaches_every_submodule():
    head = {"setup.cfg": b"[tool:pytest]\ntestpaths = \xff\n", "Makefile": b"test:\n\tpytest tests\n"}
    assert opaque_reached(("vendor/lib",), head, []) == "vendor/lib"
    assert opaque_reached(("vendor/lib",), {**head, "setup.cfg": SETUP}, []) is None


# --- each pass that reads the inventory -----------------------------------------------------------

SUBMODULE = ("vendor/lib/",)
# (configs, listed): the controls, with no submodule or one pytest's collection cannot reach
KEPT_OUT = [({}, ()), ({"setup.cfg": b"[tool:pytest]\ntestpaths = tests\n"}, SUBMODULE),
            ({"pytest.ini": b"[pytest]\nnorecursedirs = vendor\n"}, SUBMODULE)]
KEPT_OUT_IDS = ["no_submodule", "testpaths", "norecursedirs"]
INSTALL = b"import app.billing as billing\nbilling.total = lambda: 3\n"


def _installations(conftest, configs, listed=SUBMODULE):
    snapshot = {"app/__init__.py": b"", "app/billing.py": b"def total():\n    return 1\n", conftest: INSTALL,
                "tests/test_total.py": b"from app.billing import total\ndef test_total():\n    assert total() == 3\n",
                **configs}
    return installation_events(IR(base="base", head="head", globals=DiffGlobals()),
                               [FileChange(conftest, "added", None, INSTALL)], Config(),
                               root_reader=snapshot.get, root_path_lister=lambda: sorted([*snapshot, *listed]))


@pytest.mark.parametrize("conftest", ["conftest.py", "vendor/conftest.py"])
def test_a_conftest_whose_tests_the_submodule_may_hold_fails_closed(conftest):
    with pytest.raises(EngineError, match="the submodule vendor/lib: pytest's collection can reach it"):
        _installations(conftest, {})


@pytest.mark.parametrize("conftest, configs, listed", [
    ("conftest.py", *KEPT_OUT[0]), ("tests/conftest.py", {}, SUBMODULE),
    *(("conftest.py", *case) for case in KEPT_OUT[1:]),
], ids=["no_submodule", "conftest_beside_it", *KEPT_OUT_IDS[1:]])
def test_a_conftest_whose_tests_it_cannot_hold_is_judged(conftest, configs, listed):
    assert [event[2] for event in _installations(conftest, configs, listed)] == ["app.billing.total"]


def _shadows(configs, listed=SUBMODULE):
    sources = {"src/billing.py": b"def invoice_total():\n    return 1\n",
               "tests/src/billing.py": b"def invoice_total():\n    return 2\n",
               "tests/conftest.py": b"import pytest\n\n@pytest.fixture\ndef subject():\n"
                                    b"    from src.billing import invoice_total\n    return invoice_total\n",
               "tests/test_invoice.py": b"def test_invoice(subject):\n    assert subject() == 2\n", **configs}
    return find_runtime_subject_shadows(
        [FileChange("tests/src/billing.py", "added", None, sources["tests/src/billing.py"])], Config(),
        head_path_lister=lambda: sorted([*sources, *listed]),
        head_batch_reader=lambda paths: {path: sources.get(path) for path in paths},
        head_searcher=lambda _needles: ["tests/conftest.py"])


def test_a_provider_change_the_submodules_tests_may_import_fails_closed():
    with pytest.raises(EngineError, match="the submodule vendor/lib: pytest's collection can reach it"):
        _shadows({})


@pytest.mark.parametrize("configs, listed", KEPT_OUT, ids=KEPT_OUT_IDS)
def test_a_provider_change_its_tests_cannot_import_is_judged(configs, listed):
    assert len(_shadows(configs, listed)) == 1


def _copies(listed):
    copy = b"def invoice_total():\n    return 2\n"
    sources = {"tests/vendor/lib/billing.py": copy, "setup.cfg": b"[tool:pytest]\ntestpaths = tests\n",
               "tests/conftest.py": b"import pytest\n\n@pytest.fixture\ndef subject():\n"
                                    b"    from vendor.lib.billing import invoice_total\n    return invoice_total\n",
               "tests/test_invoice.py": b"def test_invoice(subject):\n    assert subject() == 2\n"}
    return find_runtime_subject_shadows(
        [FileChange("tests/vendor/lib/billing.py", "added", None, copy)], Config(),
        head_path_lister=lambda: sorted([*sources, *listed]),
        head_batch_reader=lambda paths: {path: sources.get(path) for path in paths},
        head_searcher=lambda _needles: ["tests/conftest.py"])


def test_a_test_side_copy_of_a_submodules_module_fails_closed():
    """The module it shadows would be the submodule's own, which is unknown."""
    with pytest.raises(EngineError, match="the submodule vendor/lib: the import of vendor.lib.billing can resolve"):
        _copies(SUBMODULE)
    # without the submodule, the copy is a new module with no other provider
    assert _copies(()) == []


HELPER = b"def assert_equal(actual, expected):\n    assert actual == expected\n"
WEAKENED_HELPER = HELPER.replace(b"actual == expected", b"actual is not None")


def _importers(configs, listed=SUBMODULE):
    snapshot = {"test_helpers.py": WEAKENED_HELPER, "calc.py": b"def add(a, b):\n    return a + b\n",
                "tests/test_calc.py": b"from calc import add\nfrom test_helpers import assert_equal\n\n"
                                      b"def test_add():\n    assert_equal(add(2, 3), 5)\n", **configs}
    changes, _reads, _modules = _root_importer_changes(
        [FileChange("test_helpers.py", "modified", HELPER, WEAKENED_HELPER)], Config(), snapshot.get,
        lambda needles: search_source_mapping(snapshot, needles), lambda: sorted([*snapshot, *listed]))
    return [change.path for change in changes]


def test_a_root_helpers_importers_the_submodule_may_hold_fail_closed():
    with pytest.raises(EngineError, match="the submodule vendor/lib: pytest's collection can reach it"):
        _importers({})


@pytest.mark.parametrize("configs, listed", KEPT_OUT, ids=KEPT_OUT_IDS)
def test_a_root_helpers_importers_it_cannot_hold_are_read(configs, listed):
    assert _importers(configs, listed) == ["tests/test_calc.py"]


def test_the_engine_checks_a_root_helpers_reach_before_its_search():
    def search(_needles):
        raise AssertionError("the importer search ran before the submodule's reach was checked")

    with pytest.raises(EngineError, match="the submodule vendor/lib: pytest's collection can reach it"):
        analyze([FileChange("test_helpers.py", "modified", HELPER, WEAKENED_HELPER)], Config(), Contract(), [],
                datetime.date(2026, 10, 7), root_reader={"test_helpers.py": WEAKENED_HELPER}.get,
                root_searcher=search, root_path_lister=lambda: ["test_helpers.py", "vendor/lib/"])


# --- imports that resolve into it -----------------------------------------------------------------

def test_an_import_resolving_into_the_submodule_fails_closed():
    with pytest.raises(EngineError, match="the submodule vendor/lib: the import of vendor.lib.calc"):
        _selected_provider("vendor.lib.calc", ("",), {"src/pkg/__init__.py"}, opaque=("vendor/lib",))
    with pytest.raises(EngineError, match="the import of calc can resolve inside it"):
        _selected_provider("calc", ("vendor/lib", "src"), {"src/calc.py"}, opaque=("vendor/lib",))


def test_an_import_an_earlier_root_decides_needs_nothing_from_it():
    assert _selected_provider("calc", ("src", "vendor/lib"), {"src/calc.py"}, opaque=("vendor/lib",)) == (
        "src", "src/calc.py")
    assert _selected_provider("pkg.calc", ("src", "vendor/lib"), {"src/pkg/__init__.py", "src/pkg/calc.py"},
                              opaque=("vendor/lib",)) == ("src", "src/pkg/calc.py")


def test_a_package_that_extends_its_path_reaches_it_past_its_own_modules():
    """pkgutil.extend_path adds every later `pkg` directory on the path, the submodule's too."""
    extends = {"src/pkg/__init__.py": b"from pkgutil import extend_path\n__path__ = extend_path(__path__, __name__)\n"}
    paths = {"src/pkg/__init__.py", "src/pkg/calc.py"}
    roots = ("src", "vendor/lib")
    assert _selected_provider("pkg.calc", roots, paths, extends, opaque=("vendor/lib",)) == ("src", "src/pkg/calc.py")
    with pytest.raises(EngineError, match="the submodule vendor/lib: the import of pkg.rate can resolve inside it"):
        _selected_provider("pkg.rate", roots, paths, extends, opaque=("vendor/lib",))
    # without it, the first regular package decides
    assert _selected_provider("pkg.rate", roots, paths, opaque=("vendor/lib",)) is None


def test_the_startup_context_proof_needs_every_source():
    assert inert_test_execution_context("tests/test_x.py", lambda path: b"", lambda needles: ["vendor/lib/"]) is False
