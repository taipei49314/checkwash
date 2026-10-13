"""Owned metadata controls; no real certificate content or host symlink creation."""

import hashlib
import subprocess

import pytest

from checkwash.change import EngineError
from checkwash.gitio import directory_facts as facts
from checkwash.gitio import snapshot as snapshots


def git(repo, *args, data=None):
    completed = subprocess.run(["git", "-C", str(repo), *args], input=data,
                               capture_output=True, timeout=30, check=False)
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return completed.stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "owned directory metadata")
    git(tmp_path, "config", "user.email", "metadata@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.autocrlf", "false")
    return tmp_path


def commit(repo, files, parent=None):
    git(repo, "read-tree", "--empty")
    for path, (mode, data) in sorted(files.items()):
        oid = (data.decode("ascii") if mode == "160000" else
               git(repo, "hash-object", "-w", "--stdin", data=data).decode("ascii").strip())
        git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")
    tree = git(repo, "write-tree").decode("ascii").strip()
    revision = git(repo, "commit-tree", tree, *(["-p", parent] if parent else []),
                   data=b"owned directory metadata\n").decode("ascii").strip()
    git(repo, "update-ref", "refs/heads/main", revision)
    return revision


def linked(target=b"../target/"):
    return {"data/alias": ("120000", target),
            "target/owned.txt": ("100644", b"owned target content, never metadata input\n")}


def pair(repo, before, after=None):
    old = commit(repo, before)
    new = commit(repo, after if after is not None else before, old)
    return snapshots.GitSnapshot(repo, old), snapshots.GitSnapshot(repo, new)


def read_facts(before, after, paths):
    return facts.paired_directory_link_facts(before, after, paths).records


def test_paired_identity_and_ancestors_do_not_read_regular_file_contents(repo, monkeypatch):
    old, new = pair(repo, linked(), {**linked(), "product.py": ("100644", b"changed\n")})
    reads = []
    original = snapshots.GitSnapshot._read_objects

    def capture(self, present):
        reads.append(tuple(path for path, _, _ in present))
        return original(self, present)

    monkeypatch.setattr(snapshots.GitSnapshot, "_read_objects", capture)
    value = read_facts(old, new, ["data/alias"])["data/alias"]
    assert isinstance(value, facts.PairedDirectoryLinkFact)
    assert reads == [("data/alias",), ("data/alias",)]
    for snapshot, side in [(old, value.before), (new, value.after)]:
        assert side.revision == snapshot._rev()
        assert side.root_tree_oid == git(repo, "rev-parse", f"{side.revision}^{{tree}}").strip()
        assert side.link_oid == git(repo, "rev-parse", f"{side.revision}:data/alias").strip()
        assert side.link_mode == b"120000" and side.link_size == len(b"../target/")
        assert side.target_path == "target" and side.target_mode == b"040000"
        assert side.target_oid == git(repo, "rev-parse", f"{side.revision}:target").strip()
        assert [edge.name for edge in side.ancestors] == ["data", "target"]
        assert all(edge.parent_oid == side.root_tree_oid for edge in side.ancestors)
        assert all(edge.mode == b"040000" for edge in side.ancestors)
    assert value.before.root_tree_oid != value.after.root_tree_oid


def test_original_requests_link_shapes_use_owned_target_and_same_tree_metadata(repo):
    paths = ["tests/certs/mtls/client/ca", "tests/certs/valid/ca"]
    files = {paths[0]: ("120000", b"../../expired/ca/"),
             paths[1]: ("120000", b"../expired/ca"),
             "tests/certs/expired/ca/owned.txt": ("100644", b"owned only\n")}
    old, new = pair(repo, files)
    result = read_facts(old, new, paths)
    assert set(result) == set(paths)
    assert all(isinstance(result[path], facts.PairedDirectoryLinkFact) for path in paths)
    assert all(result[path].before.target_path == "tests/certs/expired/ca" for path in paths)


def test_proof_does_not_relax_generic_or_config_readers(repo):
    old, new = pair(repo, linked())
    assert isinstance(read_facts(old, new, ["data/alias"])["data/alias"],
                      facts.PairedDirectoryLinkFact)
    for snapshot in (old, new):
        with pytest.raises(EngineError):
            snapshot.read_many(["data/alias"])
        with pytest.raises(EngineError):
            snapshot.read_config_many(["data/alias"])
        assert snapshot.read("target/owned.txt") == linked()["target/owned.txt"][1]


@pytest.mark.parametrize("target", [b"", b"/target", b"../../target", b"C:/target",
    b"..\\target", b"../target\n", b"../target\r", b"../tar\0get", b"\xff",
    b"../missing", b"../target/owned.txt", b"../second", b"alias",
    b"../through/../target", b"../missing/../target"])
def test_unsupported_target_is_explicit_no_proof(repo, target):
    files = {**linked(target), "second": ("120000", b"target"),
             "through": ("120000", b"target")}
    old, new = pair(repo, files)
    assert read_facts(old, new, ["data/alias"]) == {
        "data/alias": facts.NO_PROOF}


@pytest.mark.parametrize("path", ["missing", "target", "target/owned.txt", "data/alias/child"])
def test_pathnames_never_stand_in_for_link_or_directory_modes(repo, path):
    old, new = pair(repo, linked())
    assert read_facts(old, new, [path]) == {path: facts.NO_PROOF}


def test_gitlink_and_ancestor_gitlink_are_not_directory_proof(repo):
    child = commit(repo, {"owned.txt": ("100644", b"owned\n")})
    files = {**linked(b"../vendor"), "vendor": ("160000", child.encode("ascii"))}
    old, new = pair(repo, files)
    assert read_facts(old, new, ["data/alias", "vendor/alias"]) == {
        "data/alias": facts.NO_PROOF, "vendor/alias": facts.NO_PROOF}


@pytest.mark.parametrize("change", ["link", "target", "missing", "regular"])
def test_changed_pair_does_not_receive_same_identity_proof(repo, change):
    after = linked()
    if change == "link":
        after["data/alias"] = ("120000", b"../target")
    elif change == "target":
        after["target/owned.txt"] = ("100644", b"different target tree\n")
    elif change == "missing":
        del after["data/alias"]
    else:
        after["data/alias"] = ("100644", b"../target/")
    old, new = pair(repo, linked(), after)
    assert read_facts(old, new, ["data/alias"]) == {
        "data/alias": facts.NO_PROOF}


def test_snapshot_freeze_survives_moving_original_ref(repo):
    original = commit(repo, linked())
    frozen = snapshots.GitSnapshot(repo, "refs/heads/main")
    assert frozen._rev() == original
    commit(repo, linked(b"../missing"), original)
    result = read_facts(frozen, snapshots.GitSnapshot(repo, original),
                                               ["data/alias"])["data/alias"]
    assert isinstance(result, facts.PairedDirectoryLinkFact)
    assert result.before.revision == original == result.after.revision


def test_empty_request_has_no_transport_and_duplicate_paths_have_one_result(repo, monkeypatch):
    old, new = pair(repo, linked())
    original = facts._run

    def no_transport(*args, **kwargs):
        pytest.fail("empty request started transport")

    monkeypatch.setattr(facts, "_run", no_transport)
    assert read_facts(old, new, []) == {}
    monkeypatch.setattr(facts, "_run", original)
    assert list(read_facts(old, new, ["data/alias", "data/alias"])) == ["data/alias"]


@pytest.mark.parametrize("paths", ["data/alias", ["../alias"], ["/alias"], ["a//b"],
    ["a\\b"], ["a:b"], ["a\nb"], ["a\0b"], ["a/./b"], [None], ["\ud800"]])
def test_unsafe_requests_are_errors_not_no_proof(repo, paths):
    old, new = pair(repo, linked())
    with pytest.raises(EngineError):
        read_facts(old, new, paths)


@pytest.mark.parametrize("fault", ["header", "truncated", "extra", "hash", "huge-size", "transport"])
def test_tree_transport_and_identity_faults_are_errors(repo, monkeypatch, fault):
    old, new = pair(repo, linked())
    root = git(repo, "rev-parse", f"{old._rev()}^{{tree}}").strip()
    original = facts._run

    def broken(repository, args, *, data=None, **kwargs):
        raw = original(repository, args, data=data, **kwargs)
        if data != root + b"\n":
            return raw
        if fault == "transport":
            raise EngineError("owned metadata transport failure")
        if args == ["cat-file", "--batch-check"]:
            if fault == "header":
                return raw.replace(b" tree ", b" blob ")
            if fault == "huge-size":
                return root + b" tree " + b"9" * 5000 + b"\n"
        if args == ["cat-file", "--batch"]:
            if fault == "truncated":
                return raw[:-1]
            if fault == "extra":
                return raw + b"x"
            if fault == "hash":
                header, _, body = raw.partition(b"\n")
                return header + b"\n" + bytes([body[0] ^ 1]) + body[1:]
        return raw

    monkeypatch.setattr(facts, "_run", broken)
    with pytest.raises(EngineError):
        read_facts(old, new, ["data/alias"])


@pytest.mark.parametrize("fault", ["missing-header", "wrong-oid", "oversize", "blob-hash"])
def test_link_transport_faults_are_errors_even_when_tree_is_valid(repo, monkeypatch, fault):
    old, new = pair(repo, linked())
    link = git(repo, "rev-parse", f"{old._rev()}:data/alias").strip()
    original = facts._run
    original_snapshot = snapshots._run

    def broken(repository, args, *, data=None, **kwargs):
        raw = original(repository, args, data=data, **kwargs)
        if args == ["cat-file", "--batch-check"] and data == link + b"\n":
            if fault == "missing-header":
                return b""
            if fault == "wrong-oid":
                return b"0" * len(link) + raw[len(link):]
            if fault == "oversize":
                return link + b" blob " + str(facts.MAX_SOURCE_BYTES + 1).encode("ascii") + b"\n"
        return raw

    def broken_blob(repository, args, *, data=None, **kwargs):
        raw = original_snapshot(repository, args, data=data, **kwargs)
        if fault == "blob-hash" and args == ["cat-file", "--batch"] and data == link + b"\n":
            header, _, body = raw.partition(b"\n")
            return header + b"\n" + bytes([body[0] ^ 1]) + body[1:]
        return raw

    monkeypatch.setattr(facts, "_run", broken)
    monkeypatch.setattr(snapshots, "_run", broken_blob)
    with pytest.raises(EngineError):
        read_facts(old, new, ["data/alias"])


@pytest.mark.parametrize("fault", ["mode", "duplicate", "unsorted", "invalid-name", "truncated-oid"])
def test_hash_valid_malformed_tree_is_not_metadata_proof(repo, monkeypatch, fault):
    old, new = pair(repo, linked())
    oid = bytes.fromhex("1" * 40)
    def entry(mode, name):
        return mode + b" " + name + b"\0" + oid
    if fault == "mode":
        payload = entry(b"100600", b"a")
    elif fault == "duplicate":
        payload = entry(b"100644", b"a") * 2
    elif fault == "unsorted":
        payload = entry(b"100644", b"z") + entry(b"100644", b"a")
    elif fault == "invalid-name":
        payload = entry(b"100644", b"..")
    else:
        payload = entry(b"100644", b"a")[:-1]
    root = hashlib.sha1(b"tree " + str(len(payload)).encode("ascii") + b"\0" + payload).hexdigest().encode("ascii")
    header = root + b" tree " + str(len(payload)).encode("ascii") + b"\n"
    original = facts._run

    def malformed(repository, args, *, data=None, **kwargs):
        if args[:1] == ["rev-parse"]:
            return root + b"\n"
        if data == root + b"\n":
            return header if args == ["cat-file", "--batch-check"] else header + payload + b"\n"
        return original(repository, args, data=data, **kwargs)

    monkeypatch.setattr(facts, "_run", malformed)
    with pytest.raises(EngineError):
        read_facts(old, new, ["data/alias"])


def test_git_directory_sort_order_is_not_plain_name_order(repo):
    files = {**linked(), "target.ext": ("100644", b"owned\n"),
             "target0": ("100644", b"owned\n")}
    old, new = pair(repo, files)
    assert isinstance(read_facts(old, new, ["data/alias"])["data/alias"],
                      facts.PairedDirectoryLinkFact)


def test_unicode_names_and_real_dotdot_directory_traversal_keep_exact_edges(repo):
    files = {"資料/alias": ("120000", "../目的/child/../".encode("utf-8")),
             "目的/child/owned.txt": ("100644", b"owned\n")}
    old, new = pair(repo, files)
    value = read_facts(old, new, ["資料/alias"])["資料/alias"]
    assert isinstance(value, facts.PairedDirectoryLinkFact)
    assert value.before.target_path == "目的"
    assert [edge.name for edge in value.before.ancestors] == ["資料", "目的", "child"]


def test_pair_budget_and_tree_cache_account_actual_metadata_once_per_side(repo):
    old, new = pair(repo, {**linked(), "data/alias2": ("120000", b"../target/")})
    budget = facts._Budget()
    side = facts._Side(old, budget)
    first = budget.bytes_read
    assert first > 0
    side._tree(side.root)
    assert budget.bytes_read == first
    facts._Side(new, budget)
    assert budget.bytes_read == first * 2
    budget.charge(facts.MAX_BATCH_BYTES - budget.bytes_read)
    with pytest.raises(EngineError):
        budget.charge(1)
    batch = facts.paired_directory_link_facts(old, new, ["data/alias", "data/alias2", "missing"])
    assert batch.records["missing"] == facts.NO_PROOF
    # Root + source parent + target tree, on both sides; no target blob bytes.
    sizes = [int(git(repo, "cat-file", "-s", f"{old._rev()}{suffix}"))
             for suffix in ("^{tree}", ":data", ":target")]
    assert batch.metadata_bytes == 2 * (sum(sizes) + 2 * len(b"../target/"))
    assert batch.before_tree_bytes == batch.after_tree_bytes == sum(sizes)
    assert batch.before_link_bytes == batch.after_link_bytes == 2 * len(b"../target/")
    assert batch.before_tree_entries == batch.after_tree_entries == 5
