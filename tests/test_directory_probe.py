"""Owned source/Git controls; never original requests verdict qualification."""
import base64
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.directory_probe import DeferredSources, _Ledger, _flat_data, optional_candidates
from checkwash.gitio.directory_facts import PairedDirectoryLinkFact, paired_directory_link_facts
from checkwash.gitio.pytest_configs import PairedPytestConfigs
from checkwash.gitio.snapshot import MAX_BATCH_BYTES, MAX_INVENTORY_PATHS, MAX_SOURCE_BYTES, GitSnapshot
from checkwash.runner_references import reference_closure
from checkwash.shadow import find_runtime_subject_shadows


def fixed_controls():
    rows = json.loads((Path(__file__).parent / "fixtures" / "requests_runner_controls.json").read_text("utf-8"))
    assert len(rows) == 20 and len({row["path"] for row in rows}) == 20
    sources = {}
    for row in rows:
        data = base64.b64decode(row["base64"], validate=True)
        assert len(data) == row["bytes"]
        assert hashlib.sha256(data).hexdigest() == row["sha256"]
        assert hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest() == row["git_blob"]
        sources[row["path"]] = data
    return sources


def close(sources):
    ledger = _Ledger(set(sources))
    return reference_closure(sources, paths=frozenset(sources), reserve_work=ledger.reserve_work,
                             ci_paths=frozenset(path for path in sources if Config().role_of(path) == "ci"))


def test_fixed_twenty_sources_bind_doctest_and_preserve_declared_coverage_and_tox():
    sources = fixed_controls()
    result = close(sources)
    assert result.complete, result.opaque
    assert any(call.source == "Makefile" and call.site.startswith("coverage:") for call in result.calls)
    assert any(call.source == "tox.ini" and call.positional_binding is None and not call.targets
               for call in result.calls)
    assert any(call.source == "tox.ini" and call.positional_binding == () and call.targets == ("tests",)
               for call in result.calls)
    assert all(call.effective_config == "pyproject.toml" for call in result.calls)
    assert all(call.collection_modifiers == ("--doctest-modules",) for call in result.calls)
    assert all(call.source_sha256 == hashlib.sha256(sources[call.source]).hexdigest() for call in result.calls)
    assert {ref.path for ref in result.references if ref.kind == "coverage-config"} == {".coveragerc"}


@pytest.mark.parametrize("command", [
    "pytest --doctest-glob=*.cnf tests", "pytest -p custom tests",
    "pytest -o testpaths=data tests", "pytest --unknown tests",
    "pytest $TARGET", "pytest -c $CONFIG tests",
])
def test_actual_unknown_reference_or_collection_modifier_is_opaque(command):
    assert not close({"run.sh": (command + "\n").encode()}).complete


@pytest.mark.parametrize("config", [
    b"[pytest\n", b"[pytest]\naddopts='unterminated\n",
    b"[pytest]\npython_files=*.cnf\n", b"[pytest]\naddopts=-c other.ini\n",
])
def test_failed_or_unmodeled_config_cannot_supply_negative_proof(config):
    result = close({"pytest.ini": config, "run.sh": b"pytest tests\n"})
    assert not result.complete


def test_cycle_and_reuse_preserve_distinct_outcomes():
    assert not close({"Makefile": b"test: test\n\tpytest tests\n"}).complete
    result = close({"Makefile": b"test:\n\tmake shared\n\tmake shared\nshared:\n\tpytest tests\n"})
    assert result.complete and len(result.calls) == 1


def test_tox_source_environment_modifier_withholds_proof():
    result = close({"tox.ini": b"[testenv]\nsetenv=PYTEST_ADDOPTS=--doctest-glob=*.cnf\ncommands=pytest {posargs:tests}\n"})
    assert not result.complete


def test_target_makefile_is_content_classified_after_source_acquisition():
    sources = {"data/Makefile": b"all:\n\topenssl req -config ca.cnf\n",
               "run.sh": b"pytest tests\n"}
    assert close(sources).complete
    sources["data/Makefile"] = b"all:\n\tpytest --doctest-glob=*.cnf data\n"
    assert not close(sources).complete


@pytest.mark.parametrize("access", [lambda cache: cache["data/alias"],
                                    lambda cache: cache.get("data/alias", b"fallback")])
def test_required_barrier_propagates_original_error_without_caching_or_default(access):
    calls = []
    error = EngineError("original strict nonregular source")
    def required(path):
        calls.append(path)
        raise error
    cache = DeferredSources({"test.py": b"source"}, {"data/alias"}, required)
    for _ in range(2):
        with pytest.raises(EngineError) as caught:
            access(cache)
        assert caught.value is error
    assert calls == ["data/alias", "data/alias"] and "data/alias" not in cache
    assert set(cache) == {"test.py"}


def test_logical_equal_blob_paths_do_not_deduplicate_the_old_byte_obligation():
    ledger = _Ledger({str(index) for index in range(68)})
    with pytest.raises(EngineError, match="byte limit"):
        for index in range(68):
            ledger.source("after", str(index), 990_000)


def test_metadata_and_late_source_share_the_remaining_original_allowance():
    ledger = _Ledger({"alias"})
    ledger.reserve_bytes(MAX_BATCH_BYTES - 2)
    ledger.reserve_bytes(1)
    with pytest.raises(EngineError, match="byte limit"):
        ledger.source("before", "named-config", 2)


def test_initial_deferred_path_count_is_not_subtracted():
    ledger = _Ledger({str(index) for index in range(MAX_INVENTORY_PATHS)})
    with pytest.raises(EngineError, match="read limit"):
        ledger.reserve_work(1)


def test_repeated_same_logical_cache_access_does_not_charge_again():
    ledger = _Ledger({"one", "two"})
    ledger.source("after", "one", 7)
    ledger.source("after", "one", 7)
    ledger.source("after", "two", 7)
    ledger.source("before", "one", 7)
    assert ledger.bytes == 21


@pytest.mark.parametrize("children", [None, (("helper.py", b"100644", b"oid"),),
                                       (("owned.txt", b"100644", b"oid"),),
                                       (("nested", b"40000", b"oid"),),
                                       (("other", b"120000", b"oid"),)])
def test_incomplete_nonflat_or_possible_collection_children_withhold_proof(children):
    side = SimpleNamespace(children=children)
    assert not _flat_data(PairedDirectoryLinkFact(side, side))


def git(repo, *args, data=None):
    run = subprocess.run(["git", "-C", str(repo), *args], input=data,
                         capture_output=True, timeout=30, check=False)
    assert run.returncode == 0, run.stderr
    return run.stdout


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "owned directory probe")
    git(tmp_path, "config", "user.email", "probe@example.invalid")
    git(tmp_path, "config", "commit.gpgsign", "false")
    git(tmp_path, "config", "core.autocrlf", "false")
    return tmp_path


def commit(repo, files, parent=None):
    git(repo, "read-tree", "--empty")
    for path, (mode, data) in sorted(files.items()):
        oid = git(repo, "hash-object", "-w", "--stdin", data=data).decode().strip()
        git(repo, "update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")
    tree = git(repo, "write-tree").decode().strip()
    return git(repo, "commit-tree", tree, *(["-p", parent] if parent else []), data=b"owned\n").decode().strip()


ALIAS = "tests/certs/valid/ca"


def source_pair(repo, extras=None, fixed=False, conftests=None, conftest_path="tests/conftest.py"):
    before = {"src/billing.py": ("100644", b"def total():\n    return 3\n"),
              "tests/test_total.py": ("100644", b"from src.billing import total\ndef test_total():\n    assert total() == 3\n"),
              ALIAS: ("120000", b"../expired/ca"),
              "tests/certs/expired/ca/owned.cnf": ("100644", b"owned data, not a certificate\n"),
              "Makefile": ("100644", b"test:\n\tpytest tests\n")}
    if fixed:
        before.update({path: ("100644", data) for path, data in fixed_controls().items()})
    before.update(extras or {})
    path = "tests/src/billing.py"
    data = b"def total():\n    return 3  # stand-in\n"
    after = {**before, path: ("100644", data)}
    changes = [FileChange(path, "added", None, data)]
    if conftests is not None:
        left_data, right_data = conftests
        conftest = conftest_path
        for files, source in ((before, left_data), (after, right_data)):
            if source is None:
                files.pop(conftest, None)
            else:
                files[conftest] = ("100644", source)
        if left_data != right_data:
            status = "added" if left_data is None else "deleted" if right_data is None else "modified"
            changes.append(FileChange(conftest, status, left_data, right_data))
    old = commit(repo, before)
    new = commit(repo, after, old)
    left, right = GitSnapshot(repo, old), GitSnapshot(repo, new)
    evidence = PairedPytestConfigs(left, right).prepare()
    return right, evidence, changes


def shadow(view, evidence, changes, reader=None):
    return find_runtime_subject_shadows(changes, Config(), head_path_lister=view.list_paths,
        head_batch_reader=reader or view.read_many, config_evidence=evidence, include_equivalent=True)


@pytest.mark.parametrize("fixed", [False, True])
def test_real_shadow_caller_keeps_positive_provider_detection_and_skips_only_alias_probe(repo, fixed):
    view, evidence, changes = source_pair(repo, fixed=fixed)
    hits = shadow(view, evidence, changes)
    assert [(hit.test_path, hit.before_provider, hit.after_provider) for hit in hits] == [
        ("tests/test_total.py", "src/billing.py", "tests/src/billing.py")]
    assert ALIAS in view.list_paths()
    with pytest.raises(EngineError, match="nonregular"):
        view.read_many([ALIAS])


@pytest.mark.parametrize("command", [f"pytest {ALIAS}", f"pytest -c {ALIAS} tests",
                                      f"pytest --cov-config {ALIAS} tests",
                                      "pytest --doctest-glob=*.cnf tests"])
def test_real_shadow_explicit_or_unmodeled_reference_still_refuses(repo, command):
    view, evidence, changes = source_pair(repo, {"Makefile": ("100644", ("test:\n\t" + command + "\n").encode())})
    with pytest.raises(EngineError, match="nonregular"):
        shadow(view, evidence, changes)


@pytest.mark.parametrize("path,mode,data", [
    ("tests/certs/expired/ca/helper.py", "100644", b"def hidden(): pass\n"),
    ("tests/certs/expired/ca/deep/owned.cnf", "100644", b"owned\n"),
    ("tests/certs/expired/ca/other", "120000", b"owned.cnf"),
])
def test_real_shadow_flat_metadata_veto_restores_strict_reader(repo, path, mode, data):
    view, evidence, changes = source_pair(repo, {path: (mode, data)})
    with pytest.raises(EngineError, match="nonregular"):
        shadow(view, evidence, changes)


def test_custom_reader_cannot_borrow_the_git_metadata_capability(repo):
    view, evidence, changes = source_pair(repo)
    reader = lambda paths: view.read_many(paths)
    assert optional_candidates(evidence, reader, {ALIAS}, Config(), [], [], []) == set()
    with pytest.raises(EngineError, match="nonregular"):
        shadow(view, evidence, changes, reader)


def test_metadata_byte_preflight_failure_occurs_before_link_or_tree_payload(repo, monkeypatch):
    view, evidence, _changes = source_pair(repo)
    from checkwash.gitio import directory_facts as module
    original = module._run
    commands = []
    def traced(repo, args, **kwargs):
        commands.append(args)
        return original(repo, args, **kwargs)
    monkeypatch.setattr(module, "_run", traced)
    def reject(_size):
        raise EngineError("owned remaining allowance exhausted")
    with pytest.raises(EngineError, match="remaining allowance"):
        paired_directory_link_facts(evidence.snapshots["before"], view, [ALIAS], reserve_bytes=reject)
    assert any("--batch-check" in args for args in commands)
    assert not any("--batch" in args for args in commands)


def test_child_inventory_is_complete_verified_and_target_regular_payload_is_not_read(repo, monkeypatch):
    view, evidence, _changes = source_pair(repo)
    original = GitSnapshot._read_objects
    reads = []
    def capture(self, present):
        reads.extend(path for path, _oid, _size in present)
        return original(self, present)
    monkeypatch.setattr(GitSnapshot, "_read_objects", capture)
    fact = paired_directory_link_facts(evidence.snapshots["before"], view, [ALIAS]).records[ALIAS]
    assert isinstance(fact, PairedDirectoryLinkFact)
    assert [name for name, _mode, _oid in fact.after.children] == ["owned.cnf"]
    assert reads == [ALIAS, ALIAS]


@pytest.mark.parametrize("command", ['"./data/alias"', '"make" ci', "'./data/alias'"])
def test_quoted_workflow_executable_cannot_disappear_before_dialect_validation(command):
    source = "jobs:\n  test:\n    steps:\n    - run: " + json.dumps(command) + "\n"
    result = close({".github/workflows/test.yml": source.encode()})
    assert not result.complete


@pytest.mark.parametrize("variant", ["upper-reference", "upper-child"])
def test_platform_case_variants_never_establish_negative_alias_proof(repo, variant):
    extras = ({"Makefile": ("100644", ("test:\n\tpytest " + ALIAS.upper() + "\n").encode())}
              if variant == "upper-reference" else
              {"tests/certs/expired/ca/helper.PY": ("100644", b"def hidden(): pass\n")})
    view, evidence, changes = source_pair(repo, extras)
    with pytest.raises(EngineError, match="nonregular"):
        shadow(view, evidence, changes)


@pytest.mark.parametrize("hook", [
    "repo: local\n  hooks: [{id: missing}]",
    "repo: local\n  hooks: [{id: run, entry: './data/alias'}]",
    "repo: https://example.invalid/remote\n  hooks: [{id: run, entry: 'pytest --doctest-glob=*.cnf tests'}]",
])
def test_source_visible_precommit_missing_or_opaque_entry_withholds_proof(hook):
    result = close({".pre-commit-config.yaml": ("repos:\n- " + hook + "\n").encode()})
    assert not result.complete


def test_remote_precommit_dependency_without_entry_is_not_an_invented_test_command():
    result = close({".pre-commit-config.yaml": b"repos:\n- repo: https://example.invalid/lint\n  hooks:\n  - id: lint\n    additional_dependencies: [pytest]\n"})
    assert result.complete and result.calls == ()


@pytest.mark.parametrize("content", [None, b"[run\nmalformed\n"])
def test_new_named_coverage_input_failure_cannot_become_empty_reference_proof(repo, content):
    extras = {"Makefile": ("100644", b"coverage:\n\tpytest --cov-config .coveragerc tests\n")}
    if content is not None:
        extras[".coveragerc"] = ("100644", content)
    view, evidence, changes = source_pair(repo, extras)
    with pytest.raises(EngineError, match="required source read failed|coverage config could not be parsed"):
        shadow(view, evidence, changes)


@pytest.mark.parametrize("content", [b"[run]\nplugins=owned_plugin\n", b"[run]\nsource=data/alias\n"])
def test_parseable_unknown_coverage_settings_do_not_establish_omission_proof(repo, content):
    extras = {"Makefile": ("100644", b"coverage:\n\tpytest --cov-config .coveragerc tests\n"),
              ".coveragerc": ("100644", content)}
    view, evidence, changes = source_pair(repo, extras)
    with pytest.raises(EngineError, match="nonregular"):
        shadow(view, evidence, changes)


@pytest.mark.parametrize("command", ["data/alias", "./data/alias", "python data/alias"])
def test_workflow_direct_script_reference_reaches_strict_parser(command):
    source = "jobs:\n  test:\n    steps:\n    - run: " + json.dumps(command) + "\n"
    result = close({".github/workflows/test.yml": source.encode()})
    assert not result.complete


def test_literal_quoted_pip_arguments_are_not_invented_pytest_invocations():
    source = b"jobs:\n  setup:\n    steps:\n    - run: python -m pip uninstall -y 'charset_normalizer' 'chardet'\n"
    result = close({".github/workflows/setup.yml": source})
    assert result.complete and result.calls == ()


def test_pip_prefix_does_not_hide_a_following_selected_command():
    source = b"jobs:\n  test:\n    steps:\n    - run: python -m pip install owned && python data/alias\n"
    assert not close({".github/workflows/test.yml": source}).complete


@pytest.mark.parametrize("selected", [False, True])
def test_make_python_only_recipe_scope_is_content_based_and_selected_body_is_strict(selected):
    command = b"\tpython setup.py check && echo owned\n"
    source = b"arbitrary_name:\n" + command + (b"\tpytest tests\n" if selected else b"")
    source += b"actual_test:\n\tpytest tests\n"
    result = close({"Makefile": source})
    assert result.complete is not selected


@pytest.mark.parametrize("command", [ALIAS, "python " + ALIAS,
                                      "python '" + ALIAS.upper() + "'"])
def test_unselected_make_recipe_literal_alias_still_forces_required_read(repo, command):
    data = ("unrelated:\n\t" + command + "\ntest:\n\tpytest tests\n").encode()
    view, evidence, changes = source_pair(repo, {"Makefile": ("100644", data)})
    with pytest.raises(EngineError, match="nonregular"):
        shadow(view, evidence, changes)


def test_unselected_setup_recipe_does_not_require_arbitrary_python_cfa(repo):
    data = b"anything:\n\tpython setup.py check && echo owned\ntest:\n\tpytest tests\n"
    view, evidence, changes = source_pair(repo, {"Makefile": ("100644", data)})
    assert len(shadow(view, evidence, changes)) == 1


@pytest.mark.parametrize("live", [False, True])
def test_strictly_read_certificate_recipe_uses_existing_content_gate_not_basename(repo, live):
    data = b"all:\n\topenssl x509 -CA ../ca/ca.crt\n" + (b"\tpytest tests\n" if live else b"")
    view, evidence, changes = source_pair(repo, {"tests/certs/valid/server/Makefile": ("100644", data)})
    if live:
        with pytest.raises(EngineError, match="nonregular"):
            shadow(view, evidence, changes)
    else:
        assert len(shadow(view, evidence, changes)) == 1


@pytest.mark.parametrize("opaque", [
    b"def broken(:\n",
    b"pytest_plugins = ['owned_plugin']\n",
    b"def pytest_collect_file(file_path, parent):\n    return None\n",
    b"def pytest_pycollect_makeitem(collector, name, obj):\n    return None\n",
    b"def pytest_generate_tests(metafunc):\n    pass\n",
    b"def pytest_configure(config):\n    pass\n",
    b"def pytest_addoption(parser):\n    pass\n",
    b"collect_ignore = ['test_total.py']\n",
])
@pytest.mark.parametrize("side", ["before", "after"])
def test_paired_conftest_opacity_restores_original_required_read(repo, opaque, side):
    ordinary = b"def owned_helper():\n    return 3\n"
    sources = (opaque, ordinary) if side == "before" else (ordinary, opaque)
    view, evidence, changes = source_pair(repo, conftests=sources)
    with pytest.raises(EngineError, match="nonregular"):
        shadow(view, evidence, changes)


@pytest.mark.parametrize("source", [
    b"import pytest\n@pytest.fixture\ndef owned_fixture():\n    return 3\n",
    b"def pytest_runtest_setup(item):\n    pass\n",
])
def test_ordinary_fixture_and_runtime_hook_do_not_blanket_veto_deferral(repo, source):
    view, evidence, changes = source_pair(repo, conftests=(source, source))
    assert len(shadow(view, evidence, changes)) == 1


@pytest.mark.parametrize("sources", [
    (None, b"def helper():\n    return 3\n"),
    (b"def helper():\n    return 3\n", None),
    (b"def helper():\n    return 3\n", b"def helper():\n    return 4\n"),
])
def test_changed_conftest_uses_each_existing_side_without_inventing_absent_bytes(repo, sources):
    view, evidence, changes = source_pair(repo, conftests=sources)
    assert len(shadow(view, evidence, changes)) == 1


def test_unchanged_conftest_keeps_both_logical_source_charges(repo, monkeypatch):
    from checkwash import directory_probe as module
    source = b"def owned_helper():\n    return 3\n"
    view, evidence, changes = source_pair(repo, conftests=(source, source))
    original = module._Ledger.source
    new_charges = []
    def charged(self, side, path, size, link_bytes=0):
        first = (side, path) not in self.logical
        prior = self.bytes
        original(self, side, path, size, link_bytes)
        if path == "tests/conftest.py" and first:
            new_charges.append((side, path, self.bytes - prior))
    monkeypatch.setattr(module._Ledger, "source", charged)
    assert len(shadow(view, evidence, changes)) == 1
    assert sorted(new_charges) == [
        ("after", "tests/conftest.py", len(source)),
        ("before", "tests/conftest.py", len(source)),
    ]


def test_conftest_parser_exception_is_not_converted_to_absence(repo, monkeypatch):
    from checkwash import directory_probe as module
    source = b"def owned_helper():\n    return 3\n"
    view, evidence, changes = source_pair(repo, conftests=(source, source))
    failure = EngineError("owned conftest parser failure")
    def broken(*args, **kwargs):
        raise failure
    monkeypatch.setattr(module, "parse_python", broken)
    with pytest.raises(EngineError) as caught:
        shadow(view, evidence, changes)
    assert caught.value is failure


@pytest.mark.parametrize("path", ["tests/certs/conftest.py",
                                 "tests/certs/valid/conftest.py",
                                 "tests/certs/expired/conftest.py"])
@pytest.mark.parametrize("opaque", [b"pytest_plugins = ['owned_plugin']\n",
                                  b"def pytest_collect_file(file_path, parent):\n    return None\n"])
@pytest.mark.parametrize("side", ["before", "after"])
def test_alias_and_target_ancestor_opacity_is_checked_on_both_sides(repo, path, opaque, side):
    ordinary = b"def owned_helper():\n    return 3\n"
    sources = (opaque, ordinary) if side == "before" else (ordinary, opaque)
    view, evidence, changes = source_pair(repo, conftests=sources, conftest_path=path)
    with pytest.raises(EngineError, match="nonregular"):
        shadow(view, evidence, changes)


def test_unchanged_alias_ancestor_not_selected_by_existing_test_still_withholds_proof(repo):
    view, evidence, changes = source_pair(repo, {
        "tests/certs/conftest.py": ("100644", b"pytest_plugins = ['owned_plugin']\n")})
    with pytest.raises(EngineError, match="nonregular"):
        shadow(view, evidence, changes)


def test_ancestor_selection_includes_root_and_is_limited_to_literal_ancestors():
    from checkwash.directory_probe import _ancestor_conftests, _conftest_index
    paths = {"conftest.py", "tests/conftest.py", "tests/certs/conftest.py",
             "tests/certs/valid/conftest.py", ALIAS + "/conftest.py",
             "tests/other/conftest.py", "unrelated/conftest.py"}
    charges = []
    index = _conftest_index(paths, lambda _count: None)
    assert _ancestor_conftests(ALIAS, index, charges.append) == paths - {
        "tests/other/conftest.py", "unrelated/conftest.py"}
    assert charges == [1] * 5


def test_unrelated_malformed_conftest_is_not_acquired_for_alias_proof(repo, monkeypatch):
    path = "unrelated/conftest.py"
    view, evidence, changes = source_pair(repo, {path: ("100644", b"def broken(:\n")})
    original = GitSnapshot.read_many
    requests = []
    def record(self, paths):
        requested = list(paths)
        requests.extend(requested)
        return original(self, requested)
    monkeypatch.setattr(GitSnapshot, "read_many", record)
    assert len(shadow(view, evidence, changes)) == 1
    assert path not in requests


@pytest.mark.parametrize("mode,data", [("120000", b"missing.py"),
                                      ("100644", b"#" * (MAX_SOURCE_BYTES + 1))],
                         ids=["nonregular-link", "oversize-source"])
def test_new_ancestor_source_keeps_strict_mode_and_original_size_limit(repo, mode, data):
    view, evidence, changes = source_pair(repo, {
        "tests/certs/expired/conftest.py": (mode, data)})
    with pytest.raises(EngineError, match="nonregular|byte limit"):
        shadow(view, evidence, changes)


def test_new_ancestor_byte_preflight_precedes_required_payload_read(repo, monkeypatch):
    from checkwash import directory_probe as module
    path = "tests/certs/expired/conftest.py"
    view, evidence, changes = source_pair(repo, {
        path: ("100644", b"def helper():\n    return 3\n")})
    original_read = GitSnapshot.read_many
    original_charge = module._Ledger.source
    requests = []
    failure = EngineError("owned remaining byte allowance")
    def read(self, paths):
        requested = list(paths)
        requests.extend(requested)
        return original_read(self, requested)
    def charge(self, side, selected, size, link_bytes=0):
        if selected == path:
            raise failure
        return original_charge(self, side, selected, size, link_bytes)
    monkeypatch.setattr(GitSnapshot, "read_many", read)
    monkeypatch.setattr(module._Ledger, "source", charge)
    with pytest.raises(EngineError) as caught:
        shadow(view, evidence, changes)
    assert caught.value is failure and path not in requests


@pytest.mark.parametrize("path", ["tests/certs/Conftest.py", "TESTS/CERTS/EXPIRED/Conftest.PY"])
@pytest.mark.parametrize("opaque", [False, True])
def test_casefold_ancestor_candidate_uses_actual_git_path_and_existing_opacity(repo, path, opaque, monkeypatch):
    source = (b"pytest_plugins = ['owned_plugin']\n" if opaque else
              b"import pytest\n@pytest.fixture\ndef owned_fixture():\n    return 3\n")
    view, evidence, changes = source_pair(repo, {path: ("100644", source)})
    original = GitSnapshot.read_many
    requests = []
    def record(self, paths):
        selected = list(paths)
        requests.extend((self.revision, selected_path) for selected_path in selected)
        return original(self, selected)
    monkeypatch.setattr(GitSnapshot, "read_many", record)
    if opaque:
        with pytest.raises(EngineError, match="nonregular"):
            shadow(view, evidence, changes)
    else:
        assert len(shadow(view, evidence, changes)) == 1
    assert (evidence.snapshots["before"].revision, path) in requests
    if not opaque:
        assert (evidence.snapshots["after"].revision, path) in requests


def test_casefold_index_keeps_all_actual_spellings_and_is_reused_without_inventory_rescan():
    from checkwash.directory_probe import _ancestor_conftests, _conftest_index
    class Once:
        def __init__(self):
            self.iterations = 0
        def __iter__(self):
            self.iterations += 1
            assert self.iterations == 1
            return iter(("Conftest.PY", "tests/certs/conftest.py", "TESTS/CERTS/Conftest.py",
                         "unrelated/conftest.py", "tests/test_total.py"))
    paths = Once()
    charges = []
    index = _conftest_index(paths, charges.append)
    assert charges == [1] * 5
    expected = {"Conftest.PY", "tests/certs/conftest.py", "TESTS/CERTS/Conftest.py"}
    assert _ancestor_conftests(ALIAS, index, lambda _count: None) == expected
    assert _ancestor_conftests("tests/certs/expired/ca", index, lambda _count: None) == expected
    assert paths.iterations == 1
