"""Issue #415: a changed side over the 1,000,000-byte source limit.

v0.7.0 exited 2 on any changed path with a side over the limit, whatever it
was (an image, a lockfile, a deletion, an untracked file), and on every run
once a root `uv.lock` or `poetry.lock` at the base was that large. The
message named no file.

Ruling: a side no detector must read (images, data, lockfiles, documentation,
production sources) is carried as unread. It earns no credit and no repair
evidence, so a large file cannot hold another finding at warn (#419), and
analysis continues. A test, conftest, CI, guardrail, snapshot, JS setup or
test-command file that large still refuses with exit 2. So do a Python
module whatever its status and a pytest configuration at any depth, which
the runtime-provider pass reads, a file with no extension, whose only runner
shape is a shebang an unread side would hide, and a file under the root
`scripts/`, which collection reads as a runner. Generated output is set aside
unless it is a Python module, a pytest configuration, a CI file, a runner
script or a file with no extension. An oversized root
lockfile at the base is skipped with a stderr note. Every remaining size
refusal names path, side, size and limit, through the GitError re-raise too.

Large files are generated here, never committed.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import FileChange, SourceOverLimit, UnreadSide
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import _base_root_file, _guard_unread_reads, _set_aside_unread, analyze
from checkwash.gitio import GitSourceOverLimit, list_range_changes, list_worktree_changes, read_base_file
from checkwash.gitio.git import read_blobs
from checkwash.gitio.snapshot import GitSnapshot, WorkingTreeSnapshot

LIMIT = 1_000_000
TODAY = datetime.date(2026, 10, 14)
REFUSAL = "strict snapshot source exceeds the byte limit"
BILLING = b"def compute_invoice_total(items):\n    return sum(items)\n"
FIXED = b"def compute_invoice_total(items):\n    return round(sum(items), 2)\n"
BILLING_JS = b"export const computeInvoiceTotal = (items) => items.reduce((a, b) => a + b, 0);\n"
TEST = (b"from billing import compute_invoice_total\n\n\n"
        b"def test_invoice_total():\n"
        b"    total = compute_invoice_total([10.5, 94.8])\n"
        b"    assert total == 105.3\n")
WEAKENED = TEST.replace(b"assert total == 105.3", b"assert total > 0")


def blob(size, seed):
    """`size` bytes of hex text, distinct per seed.

    Hex holds no test-runner token, and two seeds are too unlike for git to
    pair them as a rename.
    """
    body = hashlib.shake_256(seed.encode()).hexdigest((size + 1) // 2).encode()
    return body[:size - 1] + b"\n"


def unread(path, side, size=LIMIT + 1):
    return UnreadSide(path, side, size, LIMIT)


def described(path, side, size=LIMIT + 1):
    return f"{path} ({side}, {size} > {LIMIT} bytes)"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def _repo(tmp_path, files):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "checkwash-test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.autocrlf", "false")
    _write(tmp_path, files)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-m", "base")
    return tmp_path


def _write(repo, files):
    for path, data in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)


def _commit(repo):
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "head")


def _check(repo, *args):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
           "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-10-14", "NO_COLOR": "1"}
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", *args, "--repo", str(repo)],
                            env=env, capture_output=True, timeout=120)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


def _weakened(payload):
    found = [f for f in payload["findings"] if f["rule"] == "ASSERT_WEAKENED"]
    assert len(found) == 1, payload["findings"]
    return found[0]


def _summary(findings):
    return [(f.rule, f.severity, list(f.escalators), list(f.deescalators), f.path, f.unit)
            for f in findings]


# --- the engine: an unread side earns nothing -------------------------------------------------------

EVIDENCE_CASES = {
    # Readable: the documented evidence, symbol-matched and opaque.
    "py_read": (FileChange("billing.py", "modified", BILLING, FIXED), "warn"),
    "data_read": (FileChange("data/rates.csv", "modified", b"rate,1\n", b"rate,2\n"), "warn"),
    # Unread on either side, or both: no evidence of either kind (#419). A
    # Python module that large refuses instead (PY_MODULES below).
    "js_head_unread": (FileChange("src/billing.js", "modified", BILLING_JS, None,
                                  unread=(unread("src/billing.js", "head"),)), "high"),
    "js_base_unread": (FileChange("src/billing.js", "modified", None, BILLING_JS,
                                  unread=(unread("src/billing.js", "base"),)), "high"),
    "js_both_unread": (FileChange("src/billing.js", "modified", None, None,
                                  unread=(unread("src/billing.js", "base"), unread("src/billing.js", "head"))),
                       "high"),
    "data_unread": (FileChange("data/rates.csv", "modified", None, None,
                               unread=(unread("data/rates.csv", "base"), unread("data/rates.csv", "head"))),
                    "high"),
}


@pytest.mark.parametrize("case", sorted(EVIDENCE_CASES))
def test_an_unread_side_earns_no_repair_evidence(case):
    change, severity = EVIDENCE_CASES[case]
    changes = [FileChange("tests/test_billing.py", "modified", TEST, WEAKENED), change]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY)
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", severity)]
    if severity == "warn":
        assert "REPAIR_EVIDENCE" in findings[0].deescalators
        assert verdict == "pass"
    else:
        assert findings[0].escalators == ["NO_PROD_CHANGE_IN_DIFF"]
        assert findings[0].deescalators == []
        assert verdict == "block"


# The runtime-provider pass reads a module the diff adds, deletes, renames or
# edits: any of them can change which provider a test's import resolves to.
PY_MODULES = {
    "modified_head_unread": (FileChange("billing.py", "modified", BILLING, None,
                                        unread=(unread("billing.py", "head"),)), "billing.py", "head"),
    "modified_base_unread": (FileChange("billing.py", "modified", None, FIXED,
                                        unread=(unread("billing.py", "base"),)), "billing.py", "base"),
    "modified_both_unread": (FileChange("billing.py", "modified", None, None,
                                        unread=(unread("billing.py", "base"), unread("billing.py", "head"))),
                             "billing.py", "base"),
    "package_init": (FileChange("src/app/__init__.py", "modified", None, None,
                                unread=(unread("src/app/__init__.py", "base"),
                                        unread("src/app/__init__.py", "head"))),
                     "src/app/__init__.py", "base"),
    "deleted": (FileChange("src/app/huge.py", "deleted", None, None, unread=(unread("src/app/huge.py", "base"),)),
                "src/app/huge.py", "base"),
    "renamed_out": (FileChange("src/app/huge.txt", "modified", None, None, old_path="src/app/huge.py",
                               unread=(unread("src/app/huge.py", "base"), unread("src/app/huge.txt", "head"))),
                    "src/app/huge.py", "base"),
}


@pytest.mark.parametrize("case", sorted(PY_MODULES))
def test_a_python_module_refuses_whatever_its_status(case):
    change, path, side = PY_MODULES[case]
    changes = [FileChange("tests/test_billing.py", "modified", TEST, WEAKENED), change]
    with pytest.raises(SourceOverLimit) as caught:
        analyze(changes, Config(), Contract(), [], TODAY)
    assert str(caught.value) == f"{REFUSAL}: {described(path, side)}"
    assert caught.value.unread == unread(path, side)


@pytest.mark.parametrize("path", [
    "tests/test_huge.py", "conftest.py", "tests/helpers.py", ".github/workflows/ci.yml",
    "pyproject.toml", "AGENTS.md", "golden/out.txt", "package.json", "scripts/run.sh",
    "web/app.test.js", "jest.setup.js", "app/billing.py",
])
def test_a_path_a_detector_must_read_still_refuses_naming_it(path):
    change = FileChange(path, "added", None, None, unread=(unread(path, "head"),))
    with pytest.raises(SourceOverLimit) as caught:
        analyze([change], Config(), Contract(), [], TODAY)
    assert str(caught.value) == f"{REFUSAL}: {described(path, 'head')}"
    assert caught.value.unread == unread(path, "head")


def test_a_rename_out_of_a_test_path_refuses_naming_its_base_side():
    change = FileChange("archive/old.txt", "modified", None, None, old_path="tests/test_old.py",
                        unread=(unread("tests/test_old.py", "base"), unread("archive/old.txt", "head")))
    with pytest.raises(SourceOverLimit) as caught:
        analyze([change], Config(), Contract(), [], TODAY)
    assert str(caught.value) == f"{REFUSAL}: {described('tests/test_old.py', 'base')}"


@pytest.mark.parametrize("path", [
    "tests/pytest.ini", "pkg/tox.ini", "pkg/setup.cfg", "tests/.pytest.ini", "tests/pytest.toml",
    "tests/.pytest.toml",
])
def test_a_nested_pytest_configuration_refuses_naming_it(path):
    # The provider pass reads a nested configuration for the search order it
    # sets. By role alone these are test (`tests/**`) or production files.
    change = FileChange(path, "modified", None, None, unread=(unread(path, "base"), unread(path, "head")))
    with pytest.raises(SourceOverLimit) as caught:
        analyze([change], Config(), Contract(), [], TODAY)
    assert str(caught.value) == f"{REFUSAL}: {described(path, 'base')}"
    assert caught.value.unread == unread(path, "base")


@pytest.mark.parametrize("path", ["ci/run-tests", "data/fixtures.json"], ids=["extensionless", "suffixed"])
def test_a_file_with_no_extension_refuses_for_the_shebang_it_may_hold(path):
    # `scripts/test` is a runner by its shell shebang alone (THREATMODEL 62),
    # which an unread side hides. A suffixed file is set aside: without a
    # shebang, run as `sh data/fixtures.json`, it was never a runner either.
    change = FileChange(path, "added", None, None, unread=(unread(path, "head"),))
    if path == "ci/run-tests":
        with pytest.raises(SourceOverLimit) as caught:
            _set_aside_unread([change], Config(), [])
        assert str(caught.value) == f"{REFUSAL}: {described(path, 'head')}"
        assert caught.value.unread == unread(path, "head")
    else:
        assert _set_aside_unread([change], Config(), []) == ([], [change])


@pytest.mark.parametrize("path", [
    "build/run-tests", "build/run-tests.sh", "node_modules/.bin/test.cmd", "dist/Jenkinsfile", "dist/app.min.js",
])
def test_generated_output_refuses_where_a_runner_may_hide(path):
    # The provider pass reads a CI, runner-shaped or extensionless file as a
    # control, and the one-hop scan follows `./build/run-tests.sh` from
    # `scripts/ci.sh` (THREATMODEL 89): neither skips generated output. Any
    # other generated file is set aside.
    change = FileChange(path, "modified", None, None, unread=(unread(path, "base"), unread(path, "head")))
    if path == "dist/app.min.js":
        assert _set_aside_unread([change], Config(), []) == ([], [change])
    else:
        with pytest.raises(SourceOverLimit) as caught:
            _set_aside_unread([change], Config(), [])
        assert str(caught.value) == f"{REFUSAL}: {described(path, 'base')}"
        assert caught.value.unread == unread(path, "base")


def test_a_deleted_file_under_scripts_refuses_whatever_its_suffix():
    # Collection reads every root `scripts/` file for the pytest runs a root
    # config governs. Set aside, a deleted run without an option would drop
    # out of the base runs, and the option would read as moved (#196 184.3).
    change = FileChange("scripts/full.txt", "deleted", None, None, unread=(unread("scripts/full.txt", "base"),))
    with pytest.raises(SourceOverLimit) as caught:
        _set_aside_unread([change], Config(), [])
    assert str(caught.value) == f"{REFUSAL}: {described('scripts/full.txt', 'base')}"
    assert caught.value.unread == unread("scripts/full.txt", "base")


@pytest.mark.parametrize("scope", [["data/**"], ["tests/**"]], ids=["in_scope", "out_of_scope"])
def test_scope_drift_needs_the_content_of_an_out_of_scope_path(scope):
    # SCOPE_DRIFT binds an out-of-scope file to its content digests.
    change = FileChange("data/rates.csv", "added", None, None, unread=(unread("data/rates.csv", "head"),))
    contract = Contract(present=True, scope_allow=scope)
    if scope == ["data/**"]:
        _ir, findings, verdict = analyze([change], Config(), contract, [], TODAY)
        assert findings == [] and verdict == "pass"
    else:
        with pytest.raises(SourceOverLimit, match="data/rates.csv"):
            analyze([change], Config(), contract, [], TODAY)


def test_unread_sides_leave_the_verdict_on_the_test_change_unaffected():
    test_change = FileChange("tests/test_billing.py", "modified", TEST, WEAKENED)
    unread_changes = [
        FileChange("assets/logo.png", "added", None, None, unread=(unread("assets/logo.png", "head"),)),
        FileChange("docs/guide.md", "modified", None, None,
                   unread=(unread("docs/guide.md", "base"), unread("docs/guide.md", "head"))),
        FileChange("uv.lock", "modified", b"version = 1\n", None, unread=(unread("uv.lock", "head"),)),
        FileChange("src/app/huge.js", "deleted", None, None, unread=(unread("src/app/huge.js", "base"),)),
    ]
    alone = analyze([test_change], Config(), Contract(), [], TODAY)
    beside = analyze([test_change, *unread_changes], Config(), Contract(), [], TODAY)
    assert _summary(beside[1]) == _summary(alone[1])
    assert beside[2] == alone[2] == "block"


@pytest.mark.parametrize("listed", [True, False], ids=["listed", "not_listed"])
def test_a_setup_file_the_base_manifest_lists_still_refuses(listed):
    # The runner loads it before every test file; setup_file_events reads
    # the stand-ins it installs (#218).
    entry = ["<rootDir>/config/setup-env.js"] if listed else []
    manifest = json.dumps({"jest": {"setupFiles": entry}}).encode("utf-8")
    change = FileChange("config/setup-env.js", "modified", None, None,
                        unread=(unread("config/setup-env.js", "base"), unread("config/setup-env.js", "head")))
    reader = {"package.json": manifest}.get
    if listed:
        with pytest.raises(SourceOverLimit) as caught:
            _set_aside_unread([change], Config(), [], reader)
        assert str(caught.value) == f"{REFUSAL}: {described('config/setup-env.js', 'base')}"
    else:
        assert _set_aside_unread([change], Config(), [], reader) == ([], [change])


# --- context reads: a set-aside path changed, so it is never read as unchanged ---------------------------

FLAGS = b"ENABLED = True\n"
GATED = (b"import pytest\n\nfrom flags import ENABLED\n\n\n"
         b"@pytest.mark.skipif(not ENABLED, reason=\"off\")\n"
         b"def test_enabled():\n"
         b"    assert ENABLED is True\n")
GATED_HEAD = GATED + (b"\n\n@pytest.mark.skipif(not ENABLED, reason=\"off\")\n"
                      b"def test_enabled_again():\n"
                      b"    assert ENABLED is True\n")
FLAG_CHANGES = {
    "unchanged": [],
    "base_unread": [FileChange("flags.py", "modified", None, FLAGS, unread=(unread("flags.py", "base"),))],
    "head_unread": [FileChange("flags.py", "modified", FLAGS, None, unread=(unread("flags.py", "head"),))],
}


@pytest.mark.parametrize("case", sorted(FLAG_CHANGES))
def test_a_context_module_over_the_limit_refuses_before_it_is_read(case):
    # The skip condition's constant is read from flags.py at head. Unchanged,
    # that read is both sides. Over the limit, it is a Python module, so it
    # refuses before any pass reads it: head bytes are not the base side.
    asked = []

    def head_reader(path):
        asked.append(path)
        return FLAGS if path == "flags.py" else None

    changes = [FileChange("tests/test_flag.py", "modified", GATED, GATED_HEAD), *FLAG_CHANGES[case]]
    if case == "unchanged":
        analyze(changes, Config(), Contract(), [], TODAY, head_reader=head_reader)
        assert "flags.py" in asked
        return
    side = case.split("_")[0]
    with pytest.raises(SourceOverLimit) as caught:
        analyze(changes, Config(), Contract(), [], TODAY, head_reader=head_reader)
    assert str(caught.value) == f"{REFUSAL}: {described('flags.py', side)}"
    assert "flags.py" not in asked


@pytest.mark.parametrize("side", ["base", "head"])
def test_the_base_side_of_a_set_aside_root_file(side):
    # tsconfig.json resolves JS aliases as the base side holds it (#196 188.6).
    tsconfig = b'{"compilerOptions": {"paths": {"@/*": ["src/*"]}}}\n'
    before, after = (None, tsconfig) if side == "base" else (tsconfig, None)
    change = FileChange("tsconfig.json", "modified", before, after, unread=(unread("tsconfig.json", side),))
    asked = []

    def root_reader(path):
        asked.append(path)
        return tsconfig

    base = _base_root_file([], root_reader, "tsconfig.json", [change])
    if side == "base":
        with pytest.raises(SourceOverLimit) as caught:
            base()
        assert str(caught.value) == f"{REFUSAL}: {described('tsconfig.json', 'base')}"
    else:
        assert base() == tsconfig
    assert asked == []


def test_the_readers_refuse_a_set_aside_path_and_pass_the_rest():
    change = FileChange("data/moved.csv", "modified", None, None, old_path="data/old.csv",
                        unread=(unread("data/old.csv", "base"), unread("data/moved.csv", "head")))
    snapshot = {"data/moved.csv": b"rate,1\n", "data/old.csv": b"rate,1\n", "billing.py": BILLING}
    read = _guard_unread_reads(snapshot.get, [change])
    read_many = _guard_unread_reads(lambda paths: {path: snapshot.get(path) for path in paths}, [change],
                                    batch=True)
    assert read("billing.py") == BILLING
    assert read_many(["billing.py"]) == {"billing.py": BILLING}
    for path, side in (("data/old.csv", "base"), ("data/moved.csv", "head")):
        with pytest.raises(SourceOverLimit) as caught:
            read(path)
        assert str(caught.value) == f"{REFUSAL}: {described(path, side)}"
        with pytest.raises(SourceOverLimit) as caught:
            read_many(["billing.py", path])
        assert str(caught.value) == f"{REFUSAL}: {described(path, side)}"
    get = snapshot.get
    assert _guard_unread_reads(get, []) is get


# --- the snapshots and the git layer ------------------------------------------------------------------

@pytest.fixture
def sized_repo(tmp_path):
    return _repo(tmp_path, {"at.csv": blob(LIMIT, "at"), "over.csv": blob(LIMIT + 1, "over")})


def test_a_git_read_takes_the_limit_and_names_one_byte_more(sized_repo):
    snapshot = GitSnapshot(sized_repo, "HEAD", side="base")
    assert snapshot.read("at.csv") == blob(LIMIT, "at")
    with pytest.raises(SourceOverLimit) as caught:
        snapshot.read("over.csv")
    assert str(caught.value) == f"{REFUSAL}: {described('over.csv', 'base')}"
    assert snapshot.read("over.csv", unread_oversized=True) == unread("over.csv", "base")


def test_a_git_batch_takes_the_limit_and_names_one_byte_more(sized_repo):
    snapshot = GitSnapshot(sized_repo, "HEAD", side="head")
    assert snapshot.read_many(["at.csv"]) == {"at.csv": blob(LIMIT, "at")}
    with pytest.raises(SourceOverLimit) as caught:
        snapshot.read_many(["at.csv", "over.csv"])
    assert str(caught.value) == f"{REFUSAL}: {described('over.csv', 'head')}"
    assert snapshot.read_many(["at.csv", "over.csv"], unread_oversized=True) == {
        "at.csv": blob(LIMIT, "at"), "over.csv": unread("over.csv", "head")}


def test_a_worktree_read_takes_the_limit_and_names_one_byte_more(sized_repo):
    snapshot = WorkingTreeSnapshot(sized_repo)
    assert snapshot.read("at.csv") == blob(LIMIT, "at")
    with pytest.raises(SourceOverLimit) as caught:
        snapshot.read("over.csv")
    assert str(caught.value) == f"{REFUSAL}: {described('over.csv', 'worktree')}"
    assert snapshot.read("over.csv", unread_oversized=True) == unread("over.csv", "worktree")


def test_the_git_error_keeps_the_named_refusal(sized_repo):
    with pytest.raises(GitSourceOverLimit) as caught:
        read_blobs(str(sized_repo), [("HEAD", "over.csv")], sides={"HEAD": "head"})
    assert str(caught.value) == f"{REFUSAL}: {described('over.csv', 'head')}"
    with pytest.raises(GitSourceOverLimit) as caught:
        read_base_file(str(sized_repo), "HEAD", "over.csv")
    assert str(caught.value) == f"{REFUSAL}: {described('over.csv', 'base')}"
    assert caught.value.unread == unread("over.csv", "base")


def test_range_changes_carry_unread_sides(tmp_path):
    repo = _repo(tmp_path, {"data/old.csv": blob(LIMIT + 1, "old"), "data/gone.csv": blob(LIMIT + 1, "gone"),
                            "data/edit.csv": blob(LIMIT, "edit")})
    git(repo, "mv", "data/old.csv", "data/moved.csv")
    (repo / "data" / "gone.csv").unlink()
    _write(repo, {"data/edit.csv": blob(LIMIT + 1, "edited"), "assets/logo.png": blob(LIMIT + 1, "logo")})
    _commit(repo)
    changes = {c.path: c for c in list_range_changes(str(repo), "HEAD~1", "HEAD")}
    assert sorted(changes) == ["assets/logo.png", "data/edit.csv", "data/gone.csv", "data/moved.csv"]
    moved = changes["data/moved.csv"]
    assert (moved.status, moved.old_path, moved.before, moved.after) == ("modified", "data/old.csv", None, None)
    assert moved.unread == (unread("data/old.csv", "base"), unread("data/moved.csv", "head"))
    gone = changes["data/gone.csv"]
    assert (gone.status, gone.before, gone.unread) == ("deleted", None, (unread("data/gone.csv", "base"),))
    edit = changes["data/edit.csv"]
    assert (edit.status, edit.before, edit.after) == ("modified", blob(LIMIT, "edit"), None)
    assert edit.unread == (unread("data/edit.csv", "head"),)
    logo = changes["assets/logo.png"]
    assert (logo.status, logo.after, logo.unread) == ("added", None, (unread("assets/logo.png", "head"),))


def test_worktree_changes_carry_unread_sides(tmp_path):
    repo = _repo(tmp_path, {"data/big.csv": blob(LIMIT + 1, "big")})
    _write(repo, {"data/big.csv": blob(LIMIT + 2, "bigger"), "assets/new.csv": blob(LIMIT + 1, "new")})
    changes = {c.path: c for c in list_worktree_changes(str(repo))}
    assert sorted(changes) == ["assets/new.csv", "data/big.csv"]
    big = changes["data/big.csv"]
    assert (big.status, big.before, big.after) == ("modified", None, None)
    assert big.unread == (unread("data/big.csv", "base"), unread("data/big.csv", "worktree", LIMIT + 2))
    new = changes["assets/new.csv"]
    assert (new.status, new.after, new.unread) == ("added", None, (unread("assets/new.csv", "worktree"),))


# --- the CLI: the issue's rows ------------------------------------------------------------------------

def _base_files(extra):
    return {"billing.py": BILLING, "tests/test_billing.py": TEST, **extra}


ROWS = {
    # name: (base extra files, head edit, verdict, unread sides named on stderr)
    "image_added": (lambda: {}, lambda repo: _write(repo, {"assets/logo.png": blob(1_500_000, "logo")}),
                    "block", [described("assets/logo.png", "head", 1_500_000)]),
    # A production source that is not Python: no provider pass reads it.
    "js_source_added": (lambda: {}, lambda repo: _write(repo, {"src/billing.js": blob(LIMIT + 1, "billing.js")}),
                        "block", [described("src/billing.js", "head")]),
    "data_deleted": (lambda: {"data/table.csv": blob(LIMIT + 1, "table")},
                     lambda repo: (repo / "data" / "table.csv").unlink(),
                     "block", [described("data/table.csv", "base")]),
    "data_renamed": (lambda: {"data/table.csv": blob(LIMIT + 1, "table")},
                     lambda repo: git(repo, "mv", "data/table.csv", "data/moved.csv"),
                     "block", [described("data/table.csv", "base"), described("data/moved.csv", "head")]),
    "data_edited_over_the_limit": (lambda: {"data/table.csv": blob(LIMIT, "table")},
                                   lambda repo: _write(repo, {"data/table.csv": blob(LIMIT + 1, "edited")}),
                                   "block", [described("data/table.csv", "head")]),
    # Exactly at the limit, the data file is read: the opaque-change evidence
    # it has always earned holds the weakening at warn.
    "data_edited_at_the_limit": (lambda: {"data/table.csv": blob(LIMIT, "table")},
                                 lambda repo: _write(repo, {"data/table.csv": blob(LIMIT, "edited")}),
                                 "pass", []),
}


@pytest.mark.parametrize("row", sorted(ROWS))
def test_a_range_beside_an_oversized_file_gives_a_verdict(tmp_path, row):
    base, edit, verdict, named = ROWS[row]
    repo = _repo(tmp_path, _base_files(base()))
    edit(repo)
    _write(repo, {"tests/test_billing.py": WEAKENED})
    _commit(repo)
    code, stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "json")
    assert "engine error" not in stderr, stderr
    payload = json.loads(stdout)
    assert payload["verdict"] == verdict
    finding = _weakened(payload)
    if verdict == "block":
        assert code == 1
        assert finding["severity"] == "high"
        assert "NO_PROD_CHANGE_IN_DIFF" in finding["escalators"]
    else:
        assert code == 0
        assert finding["severity"] == "warn"
        assert "REPAIR_EVIDENCE" in finding["deescalators"]
    notes = [line for line in stderr.splitlines() if "not read, over the source byte limit" in line]
    assert notes == [f"checkwash: not read, over the source byte limit: {side}; it earns no repair evidence"
                     for side in named]


@pytest.mark.parametrize("fmt", ["json", "hook-json"])
def test_the_worktree_beside_an_untracked_oversized_file_gives_a_verdict(tmp_path, fmt):
    repo = _repo(tmp_path, _base_files({}))
    _write(repo, {"tests/test_billing.py": WEAKENED, "data/dump.csv": blob(1_500_000, "dump")})
    code, stdout, stderr = _check(repo, "--format", fmt)
    assert "engine error" not in stderr, stderr
    payload = json.loads(stdout)
    if fmt == "json":
        assert code == 1
        assert payload["verdict"] == "block"
        assert _weakened(payload)["severity"] == "high"
    else:
        assert code == 0
        assert payload["decision"] == "block"
    note = f"checkwash: not read, over the source byte limit: {described('data/dump.csv', 'worktree', 1_500_000)}"
    assert note in stderr


@pytest.mark.parametrize("name", ["poetry.lock", "uv.lock"])
def test_a_root_lockfile_over_the_limit_at_the_base_is_skipped_with_a_note(tmp_path, name):
    repo = _repo(tmp_path, _base_files({name: blob(1_200_000, name)}))
    _write(repo, {"tests/test_billing.py": TEST + b"# reviewed\n"})
    _commit(repo)
    code, stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "json")
    assert code == 0, stderr
    assert json.loads(stdout)["verdict"] == "pass"
    assert (f"checkwash: skipped {described(name, 'base', 1_200_000)}: over the source byte limit; "
            "the run continues without its declared modules") in stderr.splitlines()


def test_another_manifest_over_the_limit_at_the_base_refuses_naming_it(tmp_path):
    repo = _repo(tmp_path, _base_files({"requirements.txt": blob(LIMIT + 1, "requirements")}))
    _write(repo, {"tests/test_billing.py": TEST + b"# reviewed\n"})
    _commit(repo)
    code, stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "json")
    assert code == 2
    assert stdout == ""
    # The GitError branch: the message survives the re-raise whole.
    assert stderr.splitlines() == [f"checkwash engine error: {REFUSAL}: {described('requirements.txt', 'base')}"]


@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_an_oversized_test_file_still_exits_2_naming_it(tmp_path, mode):
    repo = _repo(tmp_path, _base_files({}))
    _write(repo, {"tests/test_huge.py": blob(LIMIT + 1, "huge")})
    if mode == "range":
        _commit(repo)
        code, stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "json")
        side = "head"
    else:
        code, stdout, stderr = _check(repo, "--format", "json")
        side = "worktree"
    assert code == 2
    assert stdout == ""
    assert f"{REFUSAL}: {described('tests/test_huge.py', side)}" in stderr
