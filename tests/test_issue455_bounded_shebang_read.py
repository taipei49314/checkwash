"""Issue #455: a verified, bounded read of an oversized side answers the shell-shebang check.

Since #448 checkwash used no byte of a changed side over the 1,000,000-byte
source limit, so it could not tell whether the side starts with a shell
shebang. Every oversized file with no extension refused, a `README`, a
`LICENSE` or an `.envrc` among them, and a suffixed file whose shebang was
only on an unread side, such as `ci/run.txt`, was set aside.

Ruling (owner, 2026-10-18): option (b) with (b1), for extensionless and
suffixed paths alike, with the runtime-provider pass skip. A Git side over
the limit is streamed through `cat-file --batch`: its first 200 bytes are
kept, the rest is hashed and dropped, and the whole is checked against its
object id. The working-tree side keeps the first 200 of the bytes it already
reads. That prefix answers `_shell_shebang` exactly as the whole side would;
the provider pass skips a set-aside dot-less path whose sides hold no shell
shebang. The prefix answers nothing else: no parser, runner check, evidence
or output sees it. A side with no prefix, a Git side over the
64,000,000-byte stream ceiling, keeps the old answer.

Large files are generated here, never committed.
"""
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from checkwash.change import SHEBANG_PREFIX_BYTES, EngineError, FileChange, SourceOverLimit, UnreadSide
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import _guard_unread_reads, _set_aside_unread, analyze
from checkwash.gitio import list_range_changes, list_worktree_changes
from checkwash.gitio import snapshot as snapshots
from checkwash.gitio.git import list_session_changes
from checkwash.gitio.snapshot import GitSnapshot, WorkingTreeSnapshot
from checkwash.roles import _shell_shebang
from checkwash.shadow import find_runtime_subject_shadows

LIMIT = 1_000_000
TODAY = datetime.date(2026, 10, 19)
REFUSAL = "strict snapshot source exceeds the byte limit"
NOTE = "not read, over the source byte limit"
BILLING = b"def compute_invoice_total(items):\n    return sum(items)\n"
TEST = (b"from billing import compute_invoice_total\n\n\n"
        b"def test_invoice_total():\n"
        b"    total = compute_invoice_total([10.5, 94.8])\n"
        b"    assert total == 105.3\n")
WEAKENED = TEST.replace(b"assert total == 105.3", b"assert total > 0")
DOCUMENT = b"Billing service\n\nRelease notes, licence terms and the change log.\n"


def blob(size, seed):
    """`size` bytes of hex text, distinct per seed (as in test_issue415)."""
    body = hashlib.shake_256(seed.encode()).hexdigest((size + 1) // 2).encode()
    return body[:size - 1] + b"\n"


def headed(head, size, seed):
    """`size` bytes that start with `head`, then hex text."""
    return head + blob(size - len(head), seed)


PLAIN = headed(DOCUMENT, LIMIT + 1, "plain")[:SHEBANG_PREFIX_BYTES]
SH = headed(b"#!/bin/sh\nset -e\npython -m pytest\n", LIMIT + 1, "sh")[:SHEBANG_PREFIX_BYTES]
BASH = headed(b"#!/usr/bin/env bash\n", LIMIT + 1, "bash")[:SHEBANG_PREFIX_BYTES]
PYTHON = headed(b"#!/usr/bin/env python3\nimport sys\n", LIMIT + 1, "python")[:SHEBANG_PREFIX_BYTES]


def side(path, name, prefix=PLAIN, size=LIMIT + 1):
    return UnreadSide(path, name, size, LIMIT, prefix=prefix)


def described(path, name, size=LIMIT + 1):
    return f"{path} ({name}, {size} > {LIMIT} bytes)"


def _summary(findings):
    return [(f.rule, f.severity, list(f.escalators), list(f.deescalators), f.path, f.unit)
            for f in findings]


# --- the prefix answers as the whole side does ------------------------------------------------------

SHEBANGS = {
    # name: (the side's first bytes, whether they are a shell shebang)
    "sh": (b"#!/bin/sh\n", True),
    "env_bash": (b"#!/usr/bin/env bash\n", True),
    "spaced_with_a_flag": (b"#! /bin/bash -e\n", True),
    "python": (b"#!/usr/bin/env python3\n", False),
    # A first line longer than the prefix: the interpreter is inside it ...
    "long_first_line": (b"#!/bin/sh " + b"-" * 300 + b"\n", True),
    # ... or past it, where `_shell_shebang` does not look on the whole side either.
    "interpreter_past_the_prefix": (b"#!/usr/bin/env " + b" " * 300 + b"bash\n", False),
    "comment": (b"# not a shebang\n", False),
    "byte_order_mark": (b"\xef\xbb\xbf#!/bin/sh\n", False),
}


@pytest.mark.parametrize("name", sorted(SHEBANGS))
def test_a_prefix_answers_the_shebang_check_as_the_whole_side(name):
    head, expected = SHEBANGS[name]
    full = headed(head, LIMIT + 1, name)
    assert _shell_shebang(full) is expected
    assert _shell_shebang(full[:SHEBANG_PREFIX_BYTES]) is expected


def test_the_prefix_takes_no_part_in_equality_hash_or_repr():
    with_prefix = UnreadSide("README", "head", LIMIT + 1, LIMIT, prefix=SH)
    plain = UnreadSide("README", "head", LIMIT + 1, LIMIT)
    assert plain.prefix is None
    assert with_prefix == plain and hash(with_prefix) == hash(plain)
    assert repr(with_prefix) == repr(plain)
    # The note, the message and the refusal name the four facts only.
    assert (with_prefix.note(), with_prefix.message()) == (plain.note(), plain.message())
    assert str(with_prefix.refusal()) == str(plain.refusal())


# --- the engine: which unread changes are set aside -------------------------------------------------

SET_ASIDE = {
    # Extensionless, dotfiles included, with no shell shebang on any side.
    "readme_added": FileChange("README", "added", None, None, unread=(side("README", "head"),)),
    "license_both_sides": FileChange("LICENSE", "modified", None, None,
                                     unread=(side("LICENSE", "base"), side("LICENSE", "head"))),
    "changelog_head_unread": FileChange("ChangeLog", "modified", b"2026-10-01  First entry.\n", None,
                                        unread=(side("ChangeLog", "head"),)),
    "changelog_base_unread": FileChange("ChangeLog", "modified", None, b"2026-10-19  Trimmed.\n",
                                        unread=(side("ChangeLog", "base"),)),
    "envrc_deleted": FileChange(".envrc", "deleted", None, None, unread=(side(".envrc", "base"),)),
    "readme_renamed": FileChange("docs/README", "modified", None, None, old_path="README",
                                 unread=(side("README", "base"), side("docs/README", "head"))),
    "notes_in_the_worktree": FileChange("NOTES", "added", None, None, unread=(side("NOTES", "worktree"),)),
    # A python shebang is no runner shape (roles.py), at any size.
    "python_shebang_tool": FileChange("bin/tool", "added", None, None, unread=(side("bin/tool", "head", PYTHON),)),
    # Generated output with no extension: the shebang question answered, it
    # is set aside as other generated output is.
    "generated_extensionless": FileChange("build/run-tests", "modified", None, None,
                                          unread=(side("build/run-tests", "base"), side("build/run-tests", "head"))),
    "suffixed_without_a_shebang": FileChange("ci/run.txt", "modified", None, None,
                                             unread=(side("ci/run.txt", "base"), side("ci/run.txt", "head"))),
}


@pytest.mark.parametrize("case", sorted(SET_ASIDE))
def test_an_unread_side_without_a_shell_shebang_is_set_aside(case):
    change = SET_ASIDE[case]
    assert _set_aside_unread([change], Config(), []) == ([], [change])


REFUSED = {
    # name: (change, the path and side the refusal names)
    "extensionless_added": (FileChange("tools/run-tests", "added", None, None,
                                       unread=(side("tools/run-tests", "head", SH),)), ("tools/run-tests", "head")),
    "extensionless_base_side": (FileChange("bin/deploy", "modified", None, None,
                                           unread=(side("bin/deploy", "base", BASH), side("bin/deploy", "head"))),
                                ("bin/deploy", "base")),
    # The side that holds the shebang, not the first unread side.
    "extensionless_head_side": (FileChange("bin/deploy", "modified", None, None,
                                           unread=(side("bin/deploy", "base"), side("bin/deploy", "head", SH))),
                                ("bin/deploy", "head")),
    "extensionless_deleted": (FileChange("bin/deploy", "deleted", None, None,
                                         unread=(side("bin/deploy", "base", SH),)), ("bin/deploy", "base")),
    "dotfile_in_the_worktree": (FileChange(".envrc", "added", None, None, unread=(side(".envrc", "worktree", SH),)),
                                (".envrc", "worktree")),
    # The issue's base-side gap: an existing runner, `sh ci/run.txt`, over the
    # limit, whose head drops the shebang. At normal size it is runner-shaped.
    "suffixed_base_side": (FileChange("ci/run.txt", "modified", None, None,
                                      unread=(side("ci/run.txt", "base", SH), side("ci/run.txt", "head"))),
                           ("ci/run.txt", "base")),
    "suffixed_head_side": (FileChange("ci/run.txt", "modified", b"echo build\n", None,
                                      unread=(side("ci/run.txt", "head", BASH),)), ("ci/run.txt", "head")),
    "renamed_to_a_suffix": (FileChange("ci/run.txt", "modified", None, None, old_path="tools/run",
                                       unread=(side("tools/run", "base", SH), side("ci/run.txt", "head"))),
                            ("tools/run", "base")),
    # The provider pass and the one-hop scan read a runner without an
    # artifact filter, so generated output with a shebang refuses.
    "generated_with_a_shebang": (FileChange("build/run-tests", "modified", None, None,
                                            unread=(side("build/run-tests", "base"),
                                                    side("build/run-tests", "head", SH))),
                                 ("build/run-tests", "head")),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_a_shell_shebang_on_an_unread_side_refuses_naming_that_side(case):
    change, (path, name) = REFUSED[case]
    with pytest.raises(SourceOverLimit) as caught:
        _set_aside_unread([change], Config(), [])
    assert str(caught.value) == f"{REFUSAL}: {described(path, name)}"
    assert caught.value.unread == UnreadSide(path, name, LIMIT + 1, LIMIT)


OTHER_RULES = {
    # name: (path, scope.allow); each side's prefix holds no shebang.
    "root_scripts": ("scripts/test", []),
    "ci_role_name": ("ci/Jenkinsfile", []),
    "makefile_name": ("Makefile", []),
    "test_command_manifest": ("Pipfile", []),
    "guardrail": (".cursorrules", []),
    "out_of_scope": ("data/README", ["src/**"]),
}


@pytest.mark.parametrize("case", sorted(OTHER_RULES))
def test_another_must_read_rule_still_refuses_without_a_shebang(case):
    path, scope = OTHER_RULES[case]
    change = FileChange(path, "added", None, None, unread=(side(path, "head"),))
    with pytest.raises(SourceOverLimit) as caught:
        _set_aside_unread([change], Config(), scope)
    assert str(caught.value) == f"{REFUSAL}: {described(path, 'head')}"


def test_a_side_without_a_prefix_keeps_the_old_answer():
    # A Git side over the stream ceiling keeps no prefix. One such side is
    # enough for an extensionless path to refuse, naming its first unread side
    # as before, and a suffixed path stays set aside.
    readme = FileChange("README", "modified", None, None,
                        unread=(side("README", "base"), UnreadSide("README", "head", LIMIT + 1, LIMIT)))
    with pytest.raises(SourceOverLimit) as caught:
        _set_aside_unread([readme], Config(), [])
    assert str(caught.value) == f"{REFUSAL}: {described('README', 'base')}"
    data = FileChange("data/table.csv", "modified", None, None,
                      unread=(UnreadSide("data/table.csv", "base", LIMIT + 1, LIMIT), side("data/table.csv", "head")))
    assert _set_aside_unread([data], Config(), []) == ([], [data])


BILLING_JS = b"export const computeInvoiceTotal = (items) => items.reduce((a, b) => a + b, 0);\n"
# test_issue415's unread rows, each side now with its prefix: still no
# repair evidence of either kind (#419), so the weakening stays high.
PREFIXED_EVIDENCE = {
    "js_head_unread": FileChange("src/billing.js", "modified", BILLING_JS, None,
                                 unread=(side("src/billing.js", "head"),)),
    "js_base_unread": FileChange("src/billing.js", "modified", None, BILLING_JS,
                                 unread=(side("src/billing.js", "base"),)),
    "js_both_unread": FileChange("src/billing.js", "modified", None, None,
                                 unread=(side("src/billing.js", "base"), side("src/billing.js", "head"))),
    "data_unread": FileChange("data/rates.csv", "modified", None, None,
                              unread=(side("data/rates.csv", "base"), side("data/rates.csv", "head"))),
    "readme_unread": FileChange("README", "modified", None, None,
                                unread=(side("README", "base"), side("README", "head"))),
}


@pytest.mark.parametrize("case", sorted(PREFIXED_EVIDENCE))
def test_an_unread_side_with_its_prefix_earns_no_repair_evidence(case):
    changes = [FileChange("tests/test_billing.py", "modified", TEST, WEAKENED), PREFIXED_EVIDENCE[case]]
    _ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY)
    assert [(f.rule, f.severity) for f in findings] == [("ASSERT_WEAKENED", "high")]
    assert findings[0].escalators == ["NO_PROD_CHANGE_IN_DIFF"]
    assert findings[0].deescalators == []
    assert verdict == "block"


def test_a_set_aside_document_leaves_the_verdict_on_the_test_change_unaffected():
    # The prefix earns nothing: a set-aside change is still no evidence (#419).
    test_change = FileChange("tests/test_billing.py", "modified", TEST, WEAKENED)
    set_aside = [SET_ASIDE[case] for case in ("readme_added", "license_both_sides", "envrc_deleted",
                                              "python_shebang_tool")]
    alone = analyze([test_change], Config(), Contract(), [], TODAY)
    beside = analyze([test_change, *set_aside], Config(), Contract(), [], TODAY)
    assert _summary(beside[1]) == _summary(alone[1])
    assert beside[2] == alone[2] == "block"


# --- the runtime-provider pass skips a set-aside path without a shebang -----------------------------

PROVIDERS = {
    "src/billing.py": b"def invoice_total():\n    return 1\n",
    "tests/src/billing.py": b"def invoice_total():\n    return 2\n",
    "tests/test_billing.py": (b"from src.billing import invoice_total\n\n"
                              b"def test_invoice_total():\n    assert invoice_total() == 2\n"),
    # The head snapshot's copy of the document; phase one would read it.
    "README": b"Billing service\n",
}
NEW_PROVIDER = FileChange("tests/src/billing.py", "added", None, PROVIDERS["tests/src/billing.py"])
README = FileChange("README", "modified", None, None, unread=(side("README", "base"), side("README", "head")))
SHADOWED = [("src/billing.py", "tests/src/billing.py")]


def _recording(asked):
    def read(paths):
        paths = list(paths)
        asked.extend(paths)
        return {path: PROVIDERS.get(path) for path in paths}
    return read


def _shadows(reader, shebang_free):
    hits = find_runtime_subject_shadows(
        [NEW_PROVIDER], Config(),
        head_path_lister=lambda: sorted(PROVIDERS),
        head_batch_reader=reader,
        shebang_free=shebang_free,
    )
    return [(hit.before_provider, hit.after_provider) for hit in hits]


def test_phase_one_reads_a_dot_less_path_for_its_shebang():
    # The control: a new provider beside an existing import reaches phase
    # one, which reads every dot-less path of the inventory.
    asked = []
    assert _shadows(_recording(asked), frozenset()) == SHADOWED
    assert "README" in asked


def test_phase_one_skips_a_set_aside_path_without_a_shebang():
    asked = []
    guarded = _guard_unread_reads(_recording(asked), [README], batch=True)
    # Read through the guard, the set-aside README refuses: its head bytes
    # are not its base side.
    with pytest.raises(SourceOverLimit) as caught:
        _shadows(guarded, frozenset())
    assert str(caught.value) == f"{REFUSAL}: {described('README', 'base')}"
    # Skipped, it is never asked for, and the answer is the same.
    asked.clear()
    assert _shadows(guarded, frozenset({"README"})) == SHADOWED
    assert asked and "README" not in asked


def test_a_run_that_reaches_phase_one_reads_no_set_aside_document():
    asked = []
    read = _recording(asked)

    def read_one(path):
        asked.append(path)
        return PROVIDERS.get(path)

    _ir, _findings, verdict = analyze([NEW_PROVIDER, README], Config(), Contract(), [], TODAY,
                                      root_reader=read_one, root_path_lister=lambda: sorted(PROVIDERS),
                                      root_batch_reader=read)
    assert verdict in ("pass", "block")
    assert "tests/test_billing.py" in asked, "the provider pass read no candidate test"
    assert "README" not in asked


# --- the snapshots and the git layer ----------------------------------------------------------------

def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True).stdout


def _write(repo, files):
    for path, data in files.items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)


def _commit(repo, message="head"):
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)


def _repo(path, files):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "checkwash-test")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "config", "core.autocrlf", "false")
    _write(path, files)
    _commit(path, "base")
    return path


def _base_files(extra=None):
    return {"billing.py": BILLING, "tests/test_billing.py": TEST, **(extra or {})}


def _sides(change):
    return [(unread.path, unread.side, unread.size, unread.prefix) for unread in change.unread]


def test_range_sides_keep_their_verified_prefix(tmp_path):
    readme = headed(DOCUMENT, LIMIT + 1, "readme")
    deploy = headed(b"#!/bin/sh\n", LIMIT + 5, "deploy")
    deploy_head = headed(b"#!/usr/bin/env bash\n", LIMIT + 2, "deploy-head")
    licence = headed(b"Licence\n", LIMIT + 1, "licence")
    news = headed(b"News\n", LIMIT + 3, "news")
    repo = _repo(tmp_path, {"README": readme, "bin/deploy": deploy, "LICENSE": licence})
    (repo / "README").unlink()
    (repo / "LICENSE").unlink()
    _write(repo, {"docs/README": readme, "bin/deploy": deploy_head, "NEWS": news})
    _commit(repo)
    changes = {change.path: change for change in list_range_changes(str(repo), "HEAD~1", "HEAD")}
    assert sorted(changes) == ["LICENSE", "NEWS", "bin/deploy", "docs/README"]
    expected = {
        "LICENSE": [("LICENSE", "base", licence)],
        "NEWS": [("NEWS", "head", news)],
        "bin/deploy": [("bin/deploy", "base", deploy), ("bin/deploy", "head", deploy_head)],
        "docs/README": [("README", "base", readme), ("docs/README", "head", readme)],
    }
    for path, sides in expected.items():
        change = changes[path]
        # The prefix lives on the side, never in the change's bytes.
        assert (change.before, change.after) == (None, None)
        assert _sides(change) == [(name, kind, len(data), data[:SHEBANG_PREFIX_BYTES]) for name, kind, data in sides]
    assert changes["docs/README"].old_path == "README"


def test_worktree_sides_keep_their_prefix(tmp_path):
    base = headed(b"#!/bin/sh\n", LIMIT + 1, "base")
    licence = headed(b"Licence\n", LIMIT + 1, "licence")
    # Far past the 1,000,001 bytes the working-tree read takes.
    worktree = headed(DOCUMENT, 3 * LIMIT, "worktree")
    envrc = headed(b"export APP_ENV=dev\n", LIMIT + 1, "envrc")
    repo = _repo(tmp_path, {"bin/deploy": base, "LICENSE": licence})
    _write(repo, {"bin/deploy": worktree, ".envrc": envrc})
    (repo / "LICENSE").unlink()
    changes = {change.path: change for change in list_worktree_changes(str(repo))}
    assert sorted(changes) == [".envrc", "LICENSE", "bin/deploy"]
    assert _sides(changes["bin/deploy"]) == [("bin/deploy", "base", LIMIT + 1, base[:SHEBANG_PREFIX_BYTES]),
                                             ("bin/deploy", "worktree", 3 * LIMIT, worktree[:SHEBANG_PREFIX_BYTES])]
    assert _sides(changes[".envrc"]) == [(".envrc", "worktree", LIMIT + 1, envrc[:SHEBANG_PREFIX_BYTES])]
    assert _sides(changes["LICENSE"]) == [("LICENSE", "base", LIMIT + 1, licence[:SHEBANG_PREFIX_BYTES])]
    assert all((change.before, change.after) == (None, None) for change in changes.values())


def test_the_working_tree_read_keeps_its_bound(tmp_path, monkeypatch):
    # The prefix comes from the one read of 1,000,001 bytes the side already
    # had; a 3,000,000-byte file is not read further for it.
    data = headed(b"#!/bin/sh\n", 3 * LIMIT, "bound")
    _write(tmp_path, {"bin/deploy": data})
    asked = []
    original = Path.open

    class Recorded:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.handle.close()

        def read(self, size=-1):
            asked.append(size)
            return self.handle.read(size)

        def fileno(self):
            return self.handle.fileno()

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "open", lambda self, *args, **kwargs: Recorded(original(self, *args, **kwargs)))
        unread = WorkingTreeSnapshot(tmp_path).read("bin/deploy", unread_oversized=True)
    assert asked == [LIMIT + 1]
    assert (unread.size, unread.prefix) == (3 * LIMIT, data[:SHEBANG_PREFIX_BYTES])


@pytest.mark.parametrize("size,streamed", [(LIMIT + 5, True), (LIMIT + 6, False)],
                         ids=["at_the_ceiling", "one_byte_over"])
def test_a_git_side_over_the_stream_ceiling_keeps_no_prefix(tmp_path, monkeypatch, size, streamed):
    monkeypatch.setattr(snapshots, "MAX_PREFIX_STREAM_BYTES", LIMIT + 5)
    data = headed(b"#!/bin/sh\n", size, "ceiling")
    repo = _repo(tmp_path, {"bin/deploy": data})
    one = GitSnapshot(repo, "HEAD", side="base").read("bin/deploy", unread_oversized=True)
    many = GitSnapshot(repo, "HEAD", side="head").read_many(["bin/deploy"], unread_oversized=True)["bin/deploy"]
    for unread, name in ((one, "base"), (many, "head")):
        assert unread == UnreadSide("bin/deploy", name, size, LIMIT)
        assert unread.prefix == (data[:SHEBANG_PREFIX_BYTES] if streamed else None)


def _record(data):
    """A `cat-file --batch` record of `data` and its SHA-1 object id."""
    oid = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest().encode("ascii")
    return oid, oid + b" blob " + str(len(data)).encode("ascii") + b"\n" + data + b"\n"


class _Pipe(io.BytesIO):
    """A stream that records the size of every read asked of it."""

    def __init__(self, data):
        super().__init__(data)
        self.asked = []

    def read(self, size=-1):
        self.asked.append(size)
        return super().read(size)


def test_a_streamed_record_keeps_its_prefix_and_holds_no_more_than_a_piece():
    data = headed(b"#!/bin/sh\n", 3 * LIMIT, "stream")
    oid, record = _record(data)
    pipe = _Pipe(record + b"next record")
    assert snapshots._stream_record(pipe, oid, len(data)) == data[:SHEBANG_PREFIX_BYTES]
    # The body in pieces of at most one chunk, then its newline: never whole.
    assert pipe.asked and all(0 < size <= snapshots._STREAM_CHUNK for size in pipe.asked)
    assert pipe.read() == b"next record"


STREAM_FAULTS = {
    # name: (the record as the stream returns it, the refusal)
    "content": (lambda record: record[:-2] + bytes([record[-2] ^ 1]) + record[-1:],
                "strict snapshot blob content does not match its object identity"),
    "truncated": (lambda record: record[:-2], "strict snapshot batch returned incomplete source"),
    "no_newline": (lambda record: record[:-1] + b"X", "strict snapshot batch returned incomplete source"),
    "header": (lambda record: record.replace(b" blob ", b" tree ", 1),
               "strict snapshot batch returned an invalid blob header"),
}


@pytest.mark.parametrize("fault", sorted(STREAM_FAULTS))
def test_a_streamed_record_out_of_protocol_refuses_as_a_full_read_does(fault):
    data = headed(b"#!/bin/sh\n", LIMIT + 1, "fault")
    oid, record = _record(data)
    transform, message = STREAM_FAULTS[fault]
    with pytest.raises(EngineError) as caught:
        snapshots._stream_record(io.BytesIO(transform(record)), oid, len(data))
    assert str(caught.value) == message
    if fault == "content":
        # The bytes that do not hash to the object id refuse a full read the same way.
        with pytest.raises(EngineError) as full:
            snapshots._verify_blob(oid, data[:-1] + bytes([data[-1] ^ 1]))
        assert str(full.value) == message


# --- the git processes the stream adds ---------------------------------------------------------------

def _counted(monkeypatch, call):
    """`call()`'s result and every git process it started, run or streamed.

    `subprocess.run` starts its process through `subprocess.Popen`, so this
    observer sees the batch reads tests/test_perf_git.py counts and the
    stream, which does not go through `run`.
    """
    original = subprocess.Popen
    started = []

    def counting(argv, *args, **kwargs):
        if argv and argv[0] == "git":
            started.append(tuple(str(part) for part in argv))
        return original(argv, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(subprocess, "Popen", counting)
        result = call()
    return result, started


def _batches(started):
    return sum(argv[-2:] == ("cat-file", "--batch") for argv in started)


def test_range_mode_streams_once_per_tree_that_holds_an_oversized_side(tmp_path, monkeypatch):
    def committed(path, size):
        repo = _repo(path, _base_files({"LICENSE": blob(size, "licence")}))
        _write(repo, {"tests/test_billing.py": WEAKENED, "LICENSE": blob(size, "licence-head"),
                      "README": blob(size, "readme"), "NEWS": blob(size, "news")})
        _commit(repo)
        return str(repo)

    at_repo, over_repo = committed(tmp_path / "at", LIMIT), committed(tmp_path / "over", LIMIT + 1)
    at, at_started = _counted(monkeypatch, lambda: list_range_changes(at_repo, "HEAD~1", "HEAD"))
    over, over_started = _counted(monkeypatch, lambda: list_range_changes(over_repo, "HEAD~1", "HEAD"))
    assert not [unread for change in at for unread in change.unread]
    assert sorted((unread.path, unread.side) for change in over for unread in change.unread) == [
        ("LICENSE", "base"), ("LICENSE", "head"), ("NEWS", "head"), ("README", "head")]
    assert all(unread.prefix is not None for change in over for unread in change.unread)
    # The base tree streams LICENSE, the head tree LICENSE, NEWS and README:
    # one more `cat-file --batch` per tree, whatever the number of sides.
    assert len(over_started) == len(at_started) + 2
    assert _batches(over_started) == _batches(at_started) + 2


def test_worktree_mode_streams_in_the_read_an_under_limit_base_side_costs(tmp_path, monkeypatch):
    def edited(path, size):
        repo = _repo(path, _base_files({"LICENSE": blob(size, "licence")}))
        _write(repo, {"tests/test_billing.py": WEAKENED, "LICENSE": blob(size, "licence-worktree"),
                      "README": blob(size, "readme")})
        return str(repo)

    at_repo, over_repo = edited(tmp_path / "at", LIMIT), edited(tmp_path / "over", LIMIT + 1)
    _at, at_started = _counted(monkeypatch, lambda: list_worktree_changes(at_repo))
    over, over_started = _counted(monkeypatch, lambda: list_worktree_changes(over_repo))
    assert sorted((unread.path, unread.side) for change in over for unread in change.unread) == [
        ("LICENSE", "base"), ("LICENSE", "worktree"), ("README", "worktree")]
    assert all(unread.prefix is not None for change in over for unread in change.unread)
    # The base side's stream takes the place of the full read a side under
    # the limit gets; the working-tree sides add no process.
    assert len(over_started) == len(at_started)


def test_the_session_presence_check_streams_nothing(tmp_path, monkeypatch):
    # The managed Stop hook asks HEAD only whether it holds a path committed
    # during the session (#418): no prefix answers that.
    def session(path, size):
        repo = _repo(path, _base_files())
        since = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
        _write(repo, {"README": blob(size, "readme")})
        _commit(repo, "during the session")
        return str(repo), since

    at_repo, at_since = session(tmp_path / "at", LIMIT)
    over_repo, over_since = session(tmp_path / "over", LIMIT + 1)
    _at, at_started = _counted(monkeypatch, lambda: list_session_changes(at_repo, at_since))
    over, over_started = _counted(monkeypatch, lambda: list_session_changes(over_repo, over_since))
    readme, = over
    assert [(unread.path, unread.side) for unread in readme.unread] == [("README", "worktree")]
    # At the limit that check reads the blob whole; over it, no byte.
    assert len(over_started) == len(at_started) - 1


# --- the CLI ---------------------------------------------------------------------------------------

def _check(repo, *args):
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
           "PYTHONUTF8": "1", "GREENWASH_TODAY": "2026-10-19", "NO_COLOR": "1"}
    result = subprocess.run([sys.executable, "-m", "checkwash", "check", *args, "--repo", str(repo)],
                            env=env, capture_output=True, timeout=120)
    return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")


def _notes(stderr):
    return [line for line in stderr.splitlines() if NOTE in line]


def _entry(item):
    return described(item["path"], item["side"], item["size"])


def _assert_verdict(code, stdout, stderr, named):
    """The weakened test blocks; the oversized sides are named, and set aside."""
    assert "engine error" not in stderr, stderr
    payload = json.loads(stdout)
    assert (code, payload["verdict"]) == (1, "block")
    weakened, = [f for f in payload["findings"] if f["rule"] == "ASSERT_WEAKENED"]
    assert weakened["severity"] == "high" and "NO_PROD_CHANGE_IN_DIFF" in weakened["escalators"]
    assert _notes(stderr) == [f"checkwash: {NOTE}: {name}; it earns no repair evidence" for name in named]
    assert sorted(_entry(item) for item in payload["unread"]) == sorted(named)


RANGE_ROWS = {
    # name: (base extra files, head edit, the sides named, in the diff's order)
    "readme_added": (lambda: {}, lambda repo: _write(repo, {"README": headed(DOCUMENT, LIMIT + 1, "readme")}),
                     [described("README", "head")]),
    "license_modified": (lambda: {"LICENSE": headed(DOCUMENT, LIMIT + 1, "licence")},
                         lambda repo: _write(repo, {"LICENSE": headed(DOCUMENT, LIMIT + 2, "licence-head")}),
                         [described("LICENSE", "base"), described("LICENSE", "head", LIMIT + 2)]),
    "changelog_deleted": (lambda: {"ChangeLog": headed(DOCUMENT, LIMIT + 1, "changelog")},
                          lambda repo: (repo / "ChangeLog").unlink(),
                          [described("ChangeLog", "base")]),
    "envrc_renamed": (lambda: {"config/.envrc": headed(b"export APP_ENV=test\n", LIMIT + 1, "envrc")},
                      lambda repo: git(repo, "mv", "config/.envrc", ".envrc"),
                      [described("config/.envrc", "base"), described(".envrc", "head")]),
}


@pytest.mark.parametrize("row", sorted(RANGE_ROWS))
def test_a_range_beside_an_oversized_document_gives_a_verdict(tmp_path, row):
    base, edit, named = RANGE_ROWS[row]
    repo = _repo(tmp_path, _base_files(base()))
    edit(repo)
    _write(repo, {"tests/test_billing.py": WEAKENED})
    _commit(repo)
    _assert_verdict(*_check(repo, "HEAD~1..HEAD", "--format", "json"), named)


# An existing runner the suite runs as `sh ci/run.txt`: its suffix and name
# are not runner-shaped, so only the shebang gives it the shape.
RUNNER = b"#!/bin/sh\nset -e\npython -m pytest\n"

RANGE_REFUSALS = {
    # name: (base extra files, head edit, the side named)
    "extensionless_added": (lambda: {},
                            lambda repo: _write(repo, {"tools/run-tests": headed(b"#!/bin/sh\n", LIMIT + 1, "run")}),
                            described("tools/run-tests", "head")),
    # Both sides unread: the refusal names the one that holds the shebang.
    "env_bash_on_the_head_side": (lambda: {"bin/deploy": headed(DOCUMENT, LIMIT + 1, "deploy")},
                                  lambda repo: _write(repo, {"bin/deploy": headed(b"#!/usr/bin/env bash\n",
                                                                                  LIMIT + 1, "deploy-head")}),
                                  described("bin/deploy", "head")),
    # The issue's base-side gap: `sh ci/run.txt` ran the suite, and the head
    # drops the shebang and the test command, both sides over the limit.
    "suffixed_runner_base_side": (lambda: {"ci/run.txt": headed(RUNNER, LIMIT + 1, "runner")},
                                  lambda repo: _write(repo, {"ci/run.txt": headed(b"set -e\necho skipped\n",
                                                                                  LIMIT + 1, "runner-head")}),
                                  described("ci/run.txt", "base")),
    # The same runner deleted, or renamed: only its base side holds the
    # shebang the streamed prefix shows.
    "suffixed_runner_deleted": (lambda: {"ci/run.txt": headed(RUNNER, LIMIT + 1, "runner")},
                                lambda repo: (repo / "ci" / "run.txt").unlink(),
                                described("ci/run.txt", "base")),
    "suffixed_runner_renamed": (lambda: {"ci/run.txt": headed(RUNNER, LIMIT + 1, "runner")},
                                lambda repo: git(repo, "mv", "ci/run.txt", "ci/run-all.txt"),
                                described("ci/run.txt", "base")),
}


@pytest.mark.parametrize("row", sorted(RANGE_REFUSALS))
def test_a_range_with_a_shell_shebang_on_an_unread_side_exits_2_naming_it(tmp_path, row):
    base, edit, named = RANGE_REFUSALS[row]
    repo = _repo(tmp_path, _base_files(base()))
    edit(repo)
    _write(repo, {"tests/test_billing.py": WEAKENED})
    _commit(repo)
    code, _stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "json")
    assert code == 2
    assert f"SourceOverLimit: {REFUSAL}: {named}" in stderr


WORKTREE_ROWS = {
    # name: (base extra files, working-tree edit, the sides named)
    "readme_modified": (lambda: {"README": headed(DOCUMENT, LIMIT + 1, "readme")},
                        lambda repo: _write(repo, {"README": headed(DOCUMENT, LIMIT + 2, "readme-worktree")}),
                        [described("README", "base"), described("README", "worktree", LIMIT + 2)]),
    "envrc_untracked": (lambda: {},
                        lambda repo: _write(repo, {".envrc": headed(b"export APP_ENV=dev\n", LIMIT + 1, "envrc")}),
                        [described(".envrc", "worktree")]),
    "license_deleted": (lambda: {"LICENSE": headed(DOCUMENT, LIMIT + 1, "licence")},
                        lambda repo: (repo / "LICENSE").unlink(),
                        [described("LICENSE", "base")]),
}


@pytest.mark.parametrize("row", sorted(WORKTREE_ROWS))
def test_the_worktree_beside_an_oversized_document_gives_a_verdict(tmp_path, row):
    base, edit, named = WORKTREE_ROWS[row]
    repo = _repo(tmp_path, _base_files(base()))
    edit(repo)
    _write(repo, {"tests/test_billing.py": WEAKENED})
    _assert_verdict(*_check(repo, "--format", "json"), named)


WORKTREE_REFUSALS = {
    # name: (base extra files, working-tree edit, the side named)
    "extensionless_untracked": (lambda: {},
                                lambda repo: _write(repo, {"tools/run-tests": headed(b"#!/bin/sh\n", LIMIT + 1,
                                                                                     "run")}),
                                described("tools/run-tests", "worktree")),
    # The base side's prefix is streamed from Git, one path at a time.
    "suffixed_runner_base_side": (lambda: {"ci/run.txt": headed(RUNNER, LIMIT + 1, "runner")},
                                  lambda repo: _write(repo, {"ci/run.txt": headed(b"set -e\necho skipped\n",
                                                                                  LIMIT + 1, "runner-worktree")}),
                                  described("ci/run.txt", "base")),
    "suffixed_runner_deleted": (lambda: {"ci/run.txt": headed(RUNNER, LIMIT + 1, "runner")},
                                lambda repo: (repo / "ci" / "run.txt").unlink(),
                                described("ci/run.txt", "base")),
}


@pytest.mark.parametrize("row", sorted(WORKTREE_REFUSALS))
def test_the_worktree_with_a_shell_shebang_on_an_unread_side_exits_2_naming_it(tmp_path, row):
    base, edit, named = WORKTREE_REFUSALS[row]
    repo = _repo(tmp_path, _base_files(base()))
    edit(repo)
    _write(repo, {"tests/test_billing.py": WEAKENED})
    code, _stdout, stderr = _check(repo, "--format", "json")
    assert code == 2
    assert f"SourceOverLimit: {REFUSAL}: {named}" in stderr


@pytest.mark.parametrize("shebang", [False, True], ids=["document", "shell_script"])
def test_the_stop_hook_beside_an_untracked_oversized_extensionless_file(tmp_path, shebang):
    repo = _repo(tmp_path, _base_files())
    head = b"#!/bin/sh\n" if shebang else DOCUMENT
    _write(repo, {"tests/test_billing.py": WEAKENED, "NOTES": headed(head, LIMIT + 1, "notes")})
    code, stdout, stderr = _check(repo, "--format", "hook-json")
    assert code == 0, stderr
    payload = json.loads(stdout)
    assert payload["decision"] == "block"
    reason = payload["reason"]
    if shebang:
        # #456's size block, naming the side that holds the shebang.
        assert reason.startswith("checkwash: this change was not analysed, so the stop is blocked. "), reason
        assert f"A file checkwash must read is over the source byte limit: {described('NOTES', 'worktree')}. " in reason
    else:
        # Set aside: the weakened test blocks the stop, as a finding does.
        assert "ASSERT_WEAKENED" in reason and "checkwash allow" in reason
        assert _notes(stderr) == [f"checkwash: {NOTE}: {described('NOTES', 'worktree')}; it earns no repair evidence"]


MARKER = b"Prefix marker 455: release notes of the billing service\n"


@pytest.mark.parametrize("args", [
    ("--format", "json"), ("--format", "sarif"), ("--format", "term"), ("--format", "hook-json"), ("--emit-ir",),
], ids=["json", "sarif", "term", "hook-json", "emit-ir"])
def test_the_prefix_reaches_no_output(tmp_path, args):
    repo = _repo(tmp_path, _base_files({"README": headed(MARKER, LIMIT + 1, "readme")}))
    _write(repo, {"README": headed(MARKER, LIMIT + 2, "readme-head"), "tests/test_billing.py": WEAKENED})
    _commit(repo)
    _code, stdout, stderr = _check(repo, "HEAD~1..HEAD", *args)
    assert "engine error" not in stderr, stderr
    assert "Prefix marker 455" not in stdout and "Prefix marker 455" not in stderr
    if args in (("--format", "json"), ("--format", "sarif"), ("--format", "term")):
        # The side is named there (#454), by its four facts only.
        assert "README" in stdout


@pytest.mark.parametrize("mode", ["range", "worktree"])
def test_a_run_that_reaches_the_provider_pass_gives_a_verdict_beside_a_set_aside_readme(tmp_path, mode):
    # A new provider beside an existing import takes the provider pass to its
    # first read phase, which reads every dot-less path for a shebang. The
    # README changed and is set aside, so the pass skips it.
    sources = {path: data for path, data in PROVIDERS.items() if path != "tests/src/billing.py"}
    repo = _repo(tmp_path, {**sources, "README": headed(DOCUMENT, LIMIT + 1, "readme")})
    _write(repo, {"tests/src/billing.py": PROVIDERS["tests/src/billing.py"],
                  "README": headed(DOCUMENT, LIMIT + 2, "readme-head")})
    if mode == "range":
        _commit(repo)
        code, stdout, stderr = _check(repo, "HEAD~1..HEAD", "--format", "json")
        side = "head"
    else:
        code, stdout, stderr = _check(repo, "--format", "json")
        side = "worktree"
    assert "engine error" not in stderr, stderr
    assert code in (0, 1)
    assert sorted(_entry(item) for item in json.loads(stdout)["unread"]) == [
        described("README", "base"), described("README", side, LIMIT + 2)]
