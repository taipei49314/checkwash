"""The expected-value importer search past its hit limit (FB-02; D-206).

A changed test helper, such as `tests/helpers.py`, sends the expected-value
pass looking, by module name, for the unchanged tests that import it. When
64 or more Python files mention that name, the snapshot search stops at its
hit limit, and every check of the change exited 2, which no exemption
releases. The pass is additive and bounded: past its read budget it already
read no importer, without a word.

Now each name has its own search, with every path the diff changes left
out as Git spells it, and its own bounds; the names whose tests fit are read
from the smallest, while the run's budget allows. Past those bounds the
helpers of that name are set aside, with a note, unless the diff renamed
one of them to that name: then the hit limit stops the run. So do a run
that cannot report the note and the root-helper channel, which reviews
removed assertions.

The fixture repositories are static inputs: no file in them is run.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import EngineError, FileChange, SearchHitLimit
from checkwash.config import Config
from checkwash.engine import _root_importer_changes
from checkwash.frontends.python import expected_provenance as P
from checkwash.gitio.snapshot import GitSnapshot, WorkingTreeSnapshot
from checkwash.pretool import ProposedTree, proposed_change

ROOT = Path(__file__).resolve().parents[1]
CALC = b"def double(x):\n    return x * 2\n"
HELPER = b"def check(actual):\n    expected = 4\n    assert actual == expected\n"
WEAKENED = HELPER.replace(b"expected = 4", b"expected = 5")
ADDED = HELPER + b"\n\ndef check_twice(actual):\n    check(actual)\n    check(actual)\n"
CALLER = b"from pkg.calc import double\nfrom .helpers import check\n\n\ndef test_double():\n    check(double(2))\n"
OTHER = b"def make_items():\n    return [1, 2]\n"


def note(reason, helpers="tests/helpers.py"):
    return (f"analysis incomplete: {reason}, so unchanged tests that import {helpers} "
            "were not read for their expected values")


NOTE = note("64 or more unchanged Python files mention `helpers`")


@pytest.fixture(autouse=True)
def plain_git(tmp_path_factory, monkeypatch):
    home = tmp_path_factory.mktemp("git-home")
    (home / "gitconfig").write_bytes(b"")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / "xdg"))


def git(repo, *args, data=None):
    return subprocess.run(["git", "-C", str(repo), *args], input=data, capture_output=True, check=True,
                          timeout=60).stdout


def mentions(count, folder="notes", name="helpers"):
    """Python files that only mention a helper's module name."""
    return {f"{folder}/note_{i:02}.py": f'"""Uses the {name}."""\n'.encode() for i in range(count)}


def commit(repo, files, message):
    for path, data in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD").decode().strip()


def make_repo(tmp_path, unchanged_mentions, extra=None):
    """A helper, one test that imports it, and files that mention its name."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "checkwash-test")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "config", "core.autocrlf", "false")
    base = commit(root, {"pkg/__init__.py": b"", "pkg/calc.py": CALC, "tests/helpers.py": HELPER,
                         "tests/test_calc.py": CALLER, **mentions(unchanged_mentions), **(extra or {})}, "base")
    return root, base


def env():
    # Read at call time, so the isolated Git configuration above applies.
    return {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONUTF8": "1",
            "GREENWASH_TODAY": "2026-11-13", "NO_COLOR": "1"}


def run(repo, args, data=b""):
    result = subprocess.run([sys.executable, "-m", "checkwash", *args, "--repo", str(repo)], input=data,
                            env=env(), capture_output=True, timeout=180, cwd=str(repo))
    # Windows writes stderr in text mode.
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8").replace("\r\n", "\n")


def check(repo, base, fmt="json", head="HEAD"):
    return run(repo, ["check", f"{base}..{head}", "--format", fmt])


def hook_input(event, **fields):
    return json.dumps({"session_id": "s-1", "hook_event_name": event, **fields}).encode("utf-8")


class Searcher:
    """A stand-in for a snapshot search that, like the real ones, can leave paths out."""

    def __init__(self, hits):
        # A list of paths for every name, or the paths for each name.
        self.hits, self.calls = hits, []

    def __call__(self, needles, exclude=frozenset()):
        self.calls.append((tuple(needles), exclude))
        hits = self.hits if isinstance(self.hits, list) else sorted(
            {path for needle in needles for path in self.hits.get(needle, ())})
        paths = [path for path in hits if path not in exclude]
        if len(paths) >= 64:
            raise SearchHitLimit("strict snapshot importer search exceeds the hit limit")
        return paths


NOTES = [f"notes/note_{i:02}.py" for i in range(70)]


def helper_change(path="tests/helpers.py", after=ADDED):
    return FileChange(path=path, status="modified", before=HELPER, after=after)


# --- the pass itself


def test_a_search_at_the_limit_is_set_aside_with_a_note():
    skipped = []
    assert P.importer_changes([helper_change()], Config(), {}.get, Searcher(NOTES), skipped=skipped) == []
    assert skipped == [NOTE]


def test_each_name_has_its_own_search_and_its_own_bounds():
    searcher = Searcher({"helpers": ["tests/test_calc.py"], "utils": NOTES})
    skipped = []
    found = P.importer_changes([helper_change(), helper_change("tests/utils.py")], Config(),
                               {"tests/test_calc.py": CALLER}.get, searcher, skipped=skipped)
    assert [change.path for change in found] == ["tests/test_calc.py"]
    assert skipped == [note("64 or more unchanged Python files mention `utils`", "tests/utils.py")]
    assert [needles for needles, _exclude in searcher.calls] == [("helpers",), ("utils",)]


def test_the_search_leaves_out_every_path_the_diff_changes():
    changes = [helper_change(),
               FileChange(path="tests/moved.py", old_path="tests/old.py", status="modified", before=b"", after=b""),
               FileChange(path="notes/added.py", status="added", before=None, after=b"# helpers\n")]
    searcher = Searcher([])
    P.importer_changes(changes, Config(), {}.get, searcher, skipped=[])
    assert [exclude for _needles, exclude in searcher.calls] == [
        {"tests/helpers.py", "tests/moved.py", "tests/old.py", "notes/added.py"}]


def test_a_helper_renamed_to_another_name_still_stops_the_run_at_the_limit():
    # The new name is the diff's choice, so it could be one every file holds.
    change = FileChange(path="tests/t.py", old_path="tests/factories.py", status="modified", before=HELPER, after=ADDED)
    with pytest.raises(SearchHitLimit):
        P.importer_changes([change], Config(), {}.get, Searcher({"t": NOTES}), skipped=[])


def test_a_name_shared_with_a_helper_renamed_to_it_stops_the_run_at_the_limit():
    changes = [helper_change("tests/a/utils.py"),
               FileChange(path="tests/b/utils.py", old_path="tests/b/factories.py", status="modified",
                          before=HELPER, after=ADDED)]
    with pytest.raises(SearchHitLimit):
        P.importer_changes(changes, Config(), {}.get, Searcher({"utils": NOTES}), skipped=[])


@pytest.mark.parametrize("change", [
    FileChange(path="tests/sub/t.py", old_path="tests/t.py", status="modified", before=HELPER, after=ADDED),
    FileChange(path="tests/t.py", status="deleted", before=HELPER, after=None),
], ids=["moved-keeping-its-name", "deleted"])
def test_a_helper_whose_name_the_base_chose_is_set_aside_at_the_limit(change):
    # A deleted helper, or one moved under the same name, keeps the name its importers use.
    skipped = []
    assert P.importer_changes([change], Config(), {}.get, Searcher({"t": NOTES}), skipped=skipped) == []
    assert skipped == [note("64 or more unchanged Python files mention `t`", change.path)]


def test_a_backslash_in_a_changed_path_is_left_out_as_git_spells_it():
    pads = [f"pad\\{i:02}.py" for i in range(70)]
    changes = [helper_change(), *(FileChange(path=pad, status="added", before=None, after=b"# helpers\n")
                                  for pad in pads)]
    searcher = Searcher(["tests/test_calc.py", *pads])
    found = P.importer_changes(changes, Config(), {"tests/test_calc.py": CALLER}.get, searcher, skipped=[])
    assert [change.path for change in found] == ["tests/test_calc.py"]
    assert set(pads) <= searcher.calls[0][1]


def test_names_are_read_from_the_smallest_while_the_run_allows():
    # 2 + 48 * 3 importers fit in the run's 192 reads; a fourth 48 does not.
    hits = {"helpers": ["tests/test_calc.py", "tests/test_more.py"],
            **{name: [f"tests/test_{name}_{i:02}.py" for i in range(P.MAX_READS)] for name in "abcd"}}
    changes = [helper_change(), *(helper_change(f"tests/{name}.py") for name in "abcd")]
    skipped = []
    found = P.importer_changes(changes, Config(), lambda path: CALLER, Searcher(hits), skipped=skipped)
    paths = {change.path for change in found}
    assert {"tests/test_calc.py", "tests/test_more.py"} <= paths and len(paths) == 2 + 3 * P.MAX_READS
    assert P.MAX_TOTAL_READS == 192
    assert skipped == [note("the run's 192 importer reads are spent", "tests/d.py")]


def test_files_that_are_not_tests_do_not_count_toward_the_read_budget():
    hits = {"helpers": ["tests/test_calc.py", *(f"notes/note_{i:02}.py" for i in range(55))]}
    skipped = []
    found = P.importer_changes([helper_change()], Config(), {"tests/test_calc.py": CALLER}.get, Searcher(hits),
                               skipped=skipped)
    assert [change.path for change in found] == ["tests/test_calc.py"] and skipped == []


def test_without_a_report_the_hit_limit_stops_the_run():
    with pytest.raises(SearchHitLimit):
        P.importer_changes([helper_change()], Config(), {}.get, Searcher(NOTES))


def test_a_search_that_cannot_leave_the_diff_out_still_stops_the_run():
    def searcher(needles):
        raise SearchHitLimit("strict snapshot importer search exceeds the hit limit")

    with pytest.raises(EngineError, match="hit limit"):
        P.importer_changes([helper_change()], Config(), {}.get, searcher, skipped=[])


def test_past_the_read_budget_the_importers_are_set_aside_unread_with_a_note():
    callers = {f"tests/test_{i:02}.py": CALLER for i in range(P.MAX_READS + 1)}
    reads, skipped = [], []
    assert P.importer_changes([helper_change()], Config(), lambda path: reads.append(path) or callers.get(path),
                              Searcher(sorted(callers)), skipped=skipped) == []
    assert skipped == [note(f"more than {P.MAX_READS} unchanged tests mention `helpers`")]
    assert reads == []


def test_more_than_sixteen_helper_names_are_set_aside_with_a_note():
    changes = [helper_change(f"tests/helper_{i:02}.py") for i in range(17)]
    skipped = []
    assert P.importer_changes(changes, Config(), {}.get, Searcher([]), skipped=skipped) == []
    assert skipped == [note("the change touches helpers with more than 16 module names",
                            "tests/helper_00.py, tests/helper_01.py, tests/helper_02.py, tests/helper_03.py "
                            "and 13 more")]


def test_within_its_bounds_the_pass_reads_the_importers_and_notes_nothing():
    skipped = []
    found = P.importer_changes([helper_change()], Config(), {"tests/test_calc.py": CALLER}.get,
                               Searcher(["tests/helpers.py", "tests/test_calc.py"]), skipped=skipped)
    assert [change.path for change in found] == ["tests/test_calc.py"]
    assert skipped == []


def test_at_the_bounds_themselves_nothing_is_set_aside():
    # 48 unchanged tests are read; 16 names are each searched.
    callers = {f"tests/test_{i:02}.py": CALLER for i in range(P.MAX_READS)}
    skipped = []
    found = P.importer_changes([helper_change()], Config(), callers.get, Searcher(sorted(callers)), skipped=skipped)
    assert len(found) == P.MAX_READS and skipped == []
    searcher = Searcher([])
    P.importer_changes([helper_change(f"tests/helper_{i:02}.py") for i in range(16)], Config(), {}.get,
                       searcher, skipped=skipped)
    assert len(searcher.calls) == 16 and skipped == []


def test_a_changed_path_is_never_read_as_an_unchanged_importer():
    # Even from a search that returns it anyway.
    changed = FileChange(path="tests/test_calc.py", status="modified", before=CALLER, after=CALLER + b"\n")
    reads = []
    found = P.importer_changes([helper_change(), changed], Config(),
                               lambda path: reads.append(path) or CALLER,
                               lambda needles, exclude=frozenset(): ["tests/test_calc.py"], skipped=[])
    assert found == [] and reads == []


def test_one_search_without_a_limit_sets_the_helpers_aside_at_64_paths():
    # A run that reports, with a search that cannot leave paths out: the
    # pass's own bound on 64 paths, which only such a search reaches.
    for count, expected in ((63, []), (64, [note("64 or more Python files mention `helpers`")])):
        skipped = []
        P.importer_changes([helper_change()], Config(), {}.get,
                           lambda needles, count=count: [f"notes/note_{i:02}.py" for i in range(count)],
                           skipped=skipped)
        assert skipped == expected


def test_a_path_that_would_not_print_is_shown_by_its_repr():
    path = "tests/he\x1b[0mlpers.py"
    skipped = []
    P.importer_changes([helper_change(path)], Config(), {}.get, Searcher(NOTES), skipped=skipped)
    name = "he\x1b[0mlpers"
    assert skipped == [note(f"64 or more unchanged Python files mention {name!r}", repr(path))]
    assert skipped[0].isprintable()


def test_a_run_without_a_report_keeps_the_engine_error(tmp_path):
    # sweep, bench and demo pass no report context, so nothing would say
    # what was set aside: the hit limit still stops their run.
    import datetime

    from checkwash.contract import Contract
    from checkwash.engine import analyze
    from checkwash.report.context import ReportContext

    root, _base = make_repo(tmp_path, 70)
    snapshot = GitSnapshot(str(root), "HEAD")
    change = FileChange(path="tests/helpers.py", status="modified", before=HELPER, after=ADDED)
    with pytest.raises(SearchHitLimit):
        analyze([change], Config(), Contract(), [], datetime.date(2026, 11, 13),
                root_reader=snapshot.read, root_searcher=snapshot.search)
    context = ReportContext()
    analyze([change], Config(), Contract(), [], datetime.date(2026, 11, 13),
            root_reader=snapshot.read, root_searcher=snapshot.search, report_context=context)
    assert context.importer_gaps == [NOTE]


def test_the_root_helper_channel_still_stops_at_the_limit():
    helper = b"def assert_equal(actual, expected):\n    assert actual == expected\n"
    change = FileChange(path="test_helpers.py", status="modified", before=helper,
                        after=b"def assert_equal(actual, expected):\n    pass\n")
    with pytest.raises(SearchHitLimit):
        _root_importer_changes([change], Config(), {}.get, Searcher([f"tests/test_{i:02}.py" for i in range(70)]))


# --- the snapshot searches


def test_a_git_search_neither_returns_nor_counts_what_it_leaves_out(tmp_path):
    root, _base = make_repo(tmp_path, 63)  # with tests/test_calc.py, 64 files mention it
    snapshot = GitSnapshot(str(root), "HEAD")
    with pytest.raises(SearchHitLimit):
        snapshot.search(["helpers"])
    found = snapshot.search(["helpers"], exclude=frozenset({"tests/test_calc.py"}))
    assert len(found) == 63 and "tests/test_calc.py" not in found
    # The inventory, the empty needle, is never narrowed: 66 nonempty sources.
    with pytest.raises(SearchHitLimit):
        snapshot.search([""], exclude=frozenset({"tests/test_calc.py", "tests/helpers.py", "pkg/calc.py"}))
    assert issubclass(SearchHitLimit, EngineError)


def test_a_working_tree_search_does_not_even_read_what_it_leaves_out(tmp_path, monkeypatch):
    root, _base = make_repo(tmp_path, 63)
    snapshot = WorkingTreeSnapshot(str(root))
    with pytest.raises(SearchHitLimit):
        snapshot.search(["helpers"])
    reads = []
    original = snapshot.read
    monkeypatch.setattr(snapshot, "read", lambda path, **options: reads.append(path) or original(path, **options))
    found = snapshot.search(["helpers"], exclude=frozenset({"tests/test_calc.py"}))
    assert len(found) == 63 and "tests/test_calc.py" not in found + reads
    with pytest.raises(SearchHitLimit):
        snapshot.search([""], exclude=frozenset({"tests/test_calc.py", "tests/helpers.py", "pkg/calc.py"}))


def test_a_proposed_file_the_search_leaves_out_is_not_counted(tmp_path):
    root, _base = make_repo(tmp_path, 62)  # 63 on disk, and the proposed file
    tree = ProposedTree(str(root), proposed_change("tests/test_new.py", None, b"# the helpers\n"))
    with pytest.raises(SearchHitLimit):
        tree.search(["helpers"])
    found = tree.search(["helpers"], exclude=frozenset({"tests/test_new.py"}))
    assert len(found) == 63 and "tests/test_new.py" not in found


def test_a_proposed_edit_to_an_existing_file_the_search_leaves_out_is_not_counted(tmp_path):
    root, _base = make_repo(tmp_path, 63)  # with tests/test_calc.py, 64 on disk
    tree = ProposedTree(str(root), proposed_change("tests/test_calc.py", CALLER, CALLER + b"\n"))
    with pytest.raises(SearchHitLimit):
        tree.search(["helpers"])
    found = tree.search(["helpers"], exclude=frozenset({"tests/test_calc.py"}))
    assert len(found) == 63 and "tests/test_calc.py" not in found


def test_a_hook_note_escapes_what_would_not_print():
    from checkwash.pretool import incomplete_reason

    assert incomplete_reason(["a\u202eb\x1bc"]) == "checkwash: a\\u202eb\\u001bc"
    assert incomplete_reason(["x"], "checkwash: commits made during this session: ") == (
        "checkwash: commits made during this session: x")
    long = incomplete_reason(["y" * 2000])
    assert len(long) == 1200 and long.endswith("y\u2026")


# --- a check of the change


def test_a_helper_edit_beside_64_mentions_gets_a_verdict_and_a_note(tmp_path):
    root, base = make_repo(tmp_path, 70)
    commit(root, {"tests/helpers.py": ADDED}, "add a helper")
    code, out, err = check(root, base)
    assert code == 0, err
    assert json.loads(out)["verdict"] == "pass"
    assert f"checkwash: {NOTE}\n" in err
    assert "engine error" not in err


def test_files_the_diff_adds_cannot_fill_the_search(tmp_path):
    root, base = make_repo(tmp_path, 10)
    commit(root, {"tests/helpers.py": WEAKENED, **mentions(70, "extra")}, "weaken the helper, pad the search")
    code, out, err = check(root, base)
    found = [(f["rule"], f["path"]) for f in json.loads(out)["findings"]]
    assert code == 1, err
    assert ("EXPECTATION_DEFINITION_CHANGED", "tests/test_calc.py") in found
    assert "analysis incomplete" not in err


def test_a_common_helper_beside_a_weakened_one_does_not_hide_it(tmp_path):
    root, base = make_repo(tmp_path, 10, {"tests/utils.py": OTHER, **mentions(70, "lib", "utils")})
    commit(root, {"tests/helpers.py": WEAKENED, "tests/utils.py": OTHER + b"# tidy\n"},
           "weaken one helper, touch a common one")
    code, out, err = check(root, base)
    found = [(f["rule"], f["path"]) for f in json.loads(out)["findings"]]
    assert code == 1, err
    assert ("EXPECTATION_DEFINITION_CHANGED", "tests/test_calc.py") in found
    assert f"checkwash: {note('64 or more unchanged Python files mention `utils`', 'tests/utils.py')}\n" in err


def test_a_helper_moved_to_a_common_name_stops_the_run(tmp_path):
    root, base = make_repo(tmp_path, 10, {"tests/factories.py": OTHER, **mentions(70, "lib", "utils")})
    git(root, "mv", "tests/factories.py", "tests/t.py")
    commit(root, {"tests/helpers.py": WEAKENED, "tests/t.py": OTHER + b"# moved\n"}, "weaken a helper, move another")
    code, out, err = check(root, base)
    assert code == 2, err
    assert "hit limit" in err


def test_padding_with_backslash_names_cannot_fill_the_search(tmp_path):
    # Linux allows "\" in a file name, which Git reports as it is; the search
    # leaves it out by that spelling. Git's plumbing builds the tree, since
    # Windows will not check it out.
    root, base = make_repo(tmp_path, 10)
    pad = git(root, "hash-object", "-w", "--stdin", data=b'"""Uses the helpers."""\n').decode().strip()
    weak = git(root, "hash-object", "-w", "--stdin", data=WEAKENED).decode().strip()
    tests = git(root, "ls-tree", f"{base}:tests").decode().replace(
        git(root, "rev-parse", f"{base}:tests/helpers.py").decode().strip(), weak)
    tests_tree = git(root, "mktree", data=tests.encode()).decode().strip()
    top = [line if not line.endswith("\ttests") else line.rsplit(" ", 1)[0] + f" {tests_tree}\ttests"
           for line in git(root, "ls-tree", base).decode().splitlines()]
    top += [f"100644 blob {pad}\tpad\\{i:02}.py" for i in range(70)]
    tree = git(root, "mktree", data=("\n".join(top) + "\n").encode()).decode().strip()
    head = git(root, "commit-tree", tree, "-p", base, "-m", "weaken the helper, pad with backslash names").decode().strip()
    code, out, err = check(root, base, head=head)
    found = [(f["rule"], f["path"]) for f in json.loads(out)["findings"]]
    assert code == 1, err
    assert ("EXPECTATION_DEFINITION_CHANGED", "tests/test_calc.py") in found


def test_a_helper_weakened_past_the_limit_is_named_not_read(tmp_path):
    # The residual D-206 records: beside 64 or more unchanged files that
    # mention the helper, its importers are not read, and the run says so.
    root, base = make_repo(tmp_path, 70)
    commit(root, {"tests/helpers.py": WEAKENED}, "weaken the helper")
    code, out, err = check(root, base)
    assert code == 0, err
    assert json.loads(out)["verdict"] == "pass"
    assert f"checkwash: {NOTE}\n" in err


def test_the_stop_hook_names_the_helpers_on_a_pass(tmp_path):
    root, _base = make_repo(tmp_path, 70)
    (root / "tests" / "helpers.py").write_bytes(ADDED)
    code, out, err = run(root, ["check", "--format", "hook-json"])
    assert code == 0, err
    assert json.loads(out) == {"systemMessage": "checkwash: " + NOTE}


def test_the_stop_hook_names_helpers_the_session_commits_left_unread(tmp_path):
    root, _base = make_repo(tmp_path, 70)
    code, _out, err = run(root, ["hook", "session-start"], hook_input("SessionStart", source="startup"))
    assert code == 0, err
    commit(root, {"tests/helpers.py": WEAKENED}, "weaken the helper during the session")
    code, out, err = run(root, ["check", "--format", "hook-json", "--hook-input", "stdin"],
                         hook_input("Stop", stop_hook_active=False))
    assert code == 0, err
    assert json.loads(out) == {"systemMessage": "checkwash: commits made during this session: " + NOTE}


def test_the_session_note_keeps_both_the_helpers_and_the_findings(tmp_path):
    root, _base = make_repo(tmp_path, 70, {"tests/test_total.py": b"def test_total():\n    assert 2 + 2 == 4\n"})
    code, _out, err = run(root, ["hook", "session-start"], hook_input("SessionStart", source="startup"))
    assert code == 0, err
    commit(root, {"tests/helpers.py": WEAKENED, "tests/test_total.py": b"def test_total():\n    assert 2 + 2\n"},
           "weaken the helper and a test during the session")
    code, out, err = run(root, ["check", "--format", "hook-json", "--hook-input", "stdin"],
                         hook_input("Stop", stop_hook_active=False))
    assert code == 0, err
    gap, findings = json.loads(out)["systemMessage"].split("\n")
    assert gap == "checkwash: commits made during this session: " + NOTE
    assert findings.startswith("checkwash: commits made during this session hold 1 finding(s)")
    assert "ASSERT_WEAKENED tests/test_total.py" in findings


def test_the_stop_hook_puts_its_own_note_before_the_session_note(tmp_path):
    root, _base = make_repo(tmp_path, 70, {"tests/test_total.py": b"def test_total():\n    assert 2 + 2 == 4\n"})
    code, _out, err = run(root, ["hook", "session-start"], hook_input("SessionStart", source="startup"))
    assert code == 0, err
    commit(root, {"tests/test_total.py": b"def test_total():\n    assert 2 + 2\n"}, "weaken a test during the session")
    (root / "tests" / "helpers.py").write_bytes(ADDED)
    code, out, err = run(root, ["check", "--format", "hook-json", "--hook-input", "stdin"],
                         hook_input("Stop", stop_hook_active=False))
    assert code == 0, err
    # The session's analysis reads the working tree too, so it sets the helper aside as well.
    own, session_gap, session_findings = json.loads(out)["systemMessage"].split("\n")
    assert own == "checkwash: " + NOTE
    assert session_gap == "checkwash: commits made during this session: " + NOTE
    assert session_findings.startswith("checkwash: commits made during this session hold 1 finding(s)")


def test_term_and_sarif_say_the_analysis_is_incomplete(tmp_path):
    root, base = make_repo(tmp_path, 70)
    commit(root, {"tests/helpers.py": ADDED}, "add a helper")
    code, out, _err = check(root, base, "term")
    assert code == 0
    assert out.splitlines()[0].endswith("checkwash: analysis incomplete; no known tampering pattern detected")
    assert f"! {NOTE}" in out.splitlines()
    code, out, _err = check(root, base, "sarif")
    notes = json.loads(out)["runs"][0]["invocations"][0]["toolExecutionNotifications"]
    assert code == 0 and {"level": "warning", "message": {"text": NOTE}} in notes


def test_the_pre_tool_use_hook_names_the_helpers_instead_of_not_analysing_the_edit(tmp_path):
    root, _base = make_repo(tmp_path, 70)
    event = json.dumps({
        "session_id": "s-1", "transcript_path": "", "cwd": str(root), "permission_mode": "default",
        "hook_event_name": "PreToolUse", "tool_name": "Write", "tool_use_id": "toolu_1",
        "tool_input": {"file_path": str(root / "tests" / "helpers.py"), "content": ADDED.decode()},
    }).encode("utf-8")
    code, out, err = run(root, ["hook", "pre-tool-use"], event)
    assert code == 0, err
    assert json.loads(out) == {"systemMessage": "checkwash: " + NOTE}


def test_under_a_blocking_policy_the_pre_tool_use_hook_asks(tmp_path):
    # As it asks for an edit it could not analyse.
    root, _base = make_repo(tmp_path, 70, {".checkwash/config.toml": b'[gate]\non_engine_error = "block"\n'})
    event = json.dumps({
        "session_id": "s-1", "transcript_path": "", "cwd": str(root), "permission_mode": "default",
        "hook_event_name": "PreToolUse", "tool_name": "Write", "tool_use_id": "toolu_1",
        "tool_input": {"file_path": str(root / "tests" / "helpers.py"), "content": ADDED.decode()},
    }).encode("utf-8")
    code, out, err = run(root, ["hook", "pre-tool-use"], event)
    assert code == 0, err
    assert json.loads(out) == {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                                      "permissionDecisionReason": "checkwash: " + NOTE}}
