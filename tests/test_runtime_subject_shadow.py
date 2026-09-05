"""Matrix for the runtime-subject shadow family (#86 / #95).

The family has two independent axes: how a competing provider wins import
resolution, and where the existing test imports the subject.  Keep the pure
matrix here so adding a spelling cannot quietly weaken the predicate; the
end-to-end .gwcase fixtures below exercise the git-snapshot plumbing.
"""

from __future__ import annotations

import pytest

import checkwash.shadow as shadow_module

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.shadow import (
    HeadSearchResult,
    SearchPlan,
    _active_test_imports,
    _changed_provider,
    _config_search,
    _extends_package_path,
    _pytest_import_root,
    _runner_pythonpath,
    _source_key,
    _sys_path_roots,
    find_runtime_subject_shadows,
)


ROUTES = {
    "package": (
        "app.normalize",
        {"src/app/__init__.py", "src/app/normalize.py"},
        {"src/app/__init__.py", "src/app/normalize.py", "app/__init__.py", "app/normalize.py"},
        ("src", ""),
        ("", "src"),
        "src/app/normalize.py",
        "app/normalize.py",
    ),
    "namespace": (
        "src.billing",
        {"src/billing.py"},
        {"src/billing.py", "tests/src/billing.py"},
        ("tests", ""),
        ("tests", ""),
        "src/billing.py",
        "tests/src/billing.py",
    ),
    "pythonpath": (
        "app.normalize",
        {"src/app/normalize.py", "shadow/app/normalize.py"},
        {"src/app/normalize.py", "shadow/app/normalize.py"},
        ("src", "shadow"),
        ("shadow", "src"),
        "src/app/normalize.py",
        "shadow/app/normalize.py",
    ),
    "sys_path": (
        "app.normalize",
        {"src/app/normalize.py", "standins/app/normalize.py"},
        {"src/app/normalize.py", "standins/app/normalize.py"},
        ("src", "standins"),
        ("standins", "src"),
        "src/app/normalize.py",
        "standins/app/normalize.py",
    ),
    "runner_env": (
        "app.normalize",
        {"src/app/normalize.py", "compat/app/normalize.py"},
        {"src/app/normalize.py", "compat/app/normalize.py"},
        ("src", "compat"),
        ("compat", "src"),
        "src/app/normalize.py",
        "compat/app/normalize.py",
    ),
}


def _import_source(scope: str, module: str) -> bytes:
    package, _, leaf = module.rpartition(".")
    statement = f"from {package} import {leaf}"
    if scope == "module":
        text = f"{statement}\n\n\ndef test_contract():\n    assert {leaf}\n"
    elif scope == "test":
        text = f"def test_contract():\n    {statement}\n    assert {leaf}\n"
    elif scope == "helper":
        text = (
            f"def subject():\n    {statement}\n    return {leaf}\n\n\n"
            "def test_contract():\n    assert subject()\n"
        )
    elif scope == "fixture":
        text = (
            "import pytest\n\n\n@pytest.fixture\n"
            f"def subject():\n    {statement}\n    return {leaf}\n\n\n"
            "def test_contract(subject):\n    assert subject\n"
        )
    else:  # pragma: no cover - the parametrization owns this enum
        raise AssertionError(scope)
    return text.encode()


@pytest.mark.parametrize("route", sorted(ROUTES))
@pytest.mark.parametrize("scope", ["module", "test", "helper", "fixture"])
def test_provider_route_by_live_import_scope_matrix(route, scope):
    (
        module,
        before_paths,
        after_paths,
        before_roots,
        after_roots,
        before_provider,
        after_provider,
    ) = ROUTES[route]
    imports = _active_test_imports(_import_source(scope, module))
    assert module in imports
    contents = {
        path: b"" for path in before_paths | after_paths if path.endswith("/__init__.py")
    }
    contents.update({before_provider: b"buggy", after_provider: b"corrected"})
    hit = _changed_provider(
        module,
        SearchPlan(route, before_roots, after_roots),
        before_paths,
        after_paths,
        contents,
        added_paths={after_provider} if after_provider not in before_paths else set(),
    )
    assert hit == (before_provider, after_provider)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            b"import app.normalize as subject\n\ndef test_x():\n    assert subject\n",
            {"app.normalize"},
        ),
        (
            b"from app.normalize import normalize\n\ndef test_x():\n    assert normalize\n",
            {"app.normalize"},
        ),
        (
            b"from app import normalize\n\ndef test_x():\n    assert normalize\n",
            {"app", "app.normalize"},
        ),
    ],
)
def test_import_spellings_resolve_to_exact_module_candidates(source, expected):
    assert expected <= _active_test_imports(source)


def test_import_in_uncalled_helper_is_not_an_active_subject():
    source = (
        b"def unused():\n    from app import normalize\n    return normalize\n\n\n"
        b"def test_x():\n    assert True\n"
    )
    assert "app.normalize" not in _active_test_imports(source)


def test_unused_module_import_is_not_an_active_subject():
    source = b"import app.normalize as normalize\n\n\ndef test_x():\n    assert True\n"
    assert "app.normalize" not in _active_test_imports(source)


def test_rebound_import_is_not_the_subject_used_by_the_oracle():
    source = (
        b"from app import normalize\n"
        b"normalize = lambda value: value\n\n\n"
        b"def test_x():\n    assert normalize('x') == 'x'\n"
    )
    assert "app.normalize" not in _active_test_imports(source)


def test_rebind_after_the_subject_use_does_not_erase_that_use():
    source = (
        b"def test_x():\n"
        b"    from app import normalize\n"
        b"    assert normalize('x') == 'x'\n"
        b"    normalize = lambda value: value\n"
    )
    assert "app.normalize" in _active_test_imports(source)


def test_assignment_in_a_statically_dead_branch_does_not_rebind_an_import():
    source = (
        b"from app import normalize\n"
        b"if False:\n"
        b"    normalize = lambda value: value\n\n"
        b"def test_x():\n"
        b"    assert normalize('x') == 'x'\n"
    )
    assert "app.normalize" in _active_test_imports(source)


def test_binding_before_import_does_not_hide_the_runtime_import():
    source = (
        b"normalize = None\n"
        b"from app import normalize\n\n\n"
        b"def test_x():\n    assert normalize('x') == 'x'\n"
    )
    assert "app.normalize" in _active_test_imports(source)


def test_test_parameter_shadowing_a_module_import_is_not_a_subject_use():
    source = (
        b"import app.normalize as subject\n\n\n"
        b"def test_x(subject):\n    assert subject('x') == 'x'\n"
    )
    assert "app.normalize" not in _active_test_imports(source)


def test_import_in_autouse_fixture_is_active():
    source = (
        b"import pytest\n\n\n"
        b"@pytest.fixture(autouse=True)\n"
        b"def subject():\n"
        b"    from app import normalize\n"
        b"    normalize('x')\n\n\n"
        b"def test_x():\n    assert True\n"
    )
    assert "app.normalize" in _active_test_imports(source)


def test_direct_parametrize_value_shadows_a_same_named_fixture():
    source = (
        b"import pytest\n\n"
        b"@pytest.fixture\n"
        b"def subject():\n"
        b"    from app import normalize\n"
        b"    return normalize\n\n"
        b"@pytest.mark.parametrize('subject', [lambda value: value])\n"
        b"def test_x(subject):\n"
        b"    assert subject('x') == 'x'\n"
    )
    assert "app.normalize" not in _active_test_imports(source)


def _cross_file_fixture_shadow(
    conftest_path: str,
    conftest_source: bytes,
    test_path: str,
    test_source: bytes,
    *,
    extra_sources: dict[str, bytes] | None = None,
):
    sources = {
        "src/billing.py": b"def invoice_total():\n    return 1\n",
        "tests/src/billing.py": b"def invoice_total():\n    return 2\n",
        conftest_path: conftest_source,
        test_path: test_source,
        **(extra_sources or {}),
    }
    return find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {path: sources.get(path) for path in paths},
        head_searcher=lambda _needles: [conftest_path],
    )


@pytest.mark.parametrize(
    ("conftest_source", "test_source"),
    [
        (
            b"import pytest\n\n@pytest.fixture\ndef subject():\n"
            b"    from src.billing import invoice_total\n"
            b"    return invoice_total\n",
            b"def test_invoice(subject):\n    assert subject() == 2\n",
        ),
        (
            b"import pytest\n\n@pytest.fixture(autouse=True)\ndef subject():\n"
            b"    from src.billing import invoice_total\n"
            b"    invoice_total()\n",
            b"def test_invoice():\n    assert True\n",
        ),
    ],
    ids=("requested", "autouse"),
)
def test_cross_file_conftest_fixture_reaches_the_same_provider_predicate(
    conftest_source, test_source
):
    hits = _cross_file_fixture_shadow(
        "tests/conftest.py",
        conftest_source,
        "tests/test_billing.py",
        test_source,
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/src/billing.py")
    ]


@pytest.mark.parametrize(
    ("conftest_source", "test_source"),
    [
        (
            b"import pytest\n\n@pytest.fixture\ndef subject():\n"
            b"    from src.billing import invoice_total\n"
            b"    return invoice_total\n",
            b"def test_invoice():\n    assert True\n",
        ),
        (
            b"import pytest\n\n@pytest.fixture\ndef subject():\n"
            b"    from src.billing import invoice_total\n"
            b"    return lambda: 2\n",
            b"def test_invoice(subject):\n    assert subject() == 2\n",
        ),
    ],
    ids=("unrequested", "import-unused"),
)
def test_inactive_cross_file_fixture_import_is_an_honest_negative(
    conftest_source, test_source
):
    assert _cross_file_fixture_shadow(
        "tests/conftest.py",
        conftest_source,
        "tests/test_billing.py",
        test_source,
    ) == []


def test_nested_conftest_autouse_fixture_does_not_escape_its_subtree():
    assert _cross_file_fixture_shadow(
        "tests/unit/conftest.py",
        (
            b"import pytest\n\n@pytest.fixture(autouse=True)\ndef subject():\n"
            b"    from src.billing import invoice_total\n"
            b"    invoice_total()\n"
        ),
        "tests/integration/test_billing.py",
        b"def test_invoice():\n    assert True\n",
    ) == []


def test_nearer_fixture_definition_overrides_an_ancestor_with_the_same_name():
    ancestor = (
        b"import pytest\n\n@pytest.fixture(autouse=True)\ndef subject():\n"
        b"    from src.billing import invoice_total\n"
        b"    invoice_total()\n"
    )
    nearer = (
        b"import pytest\n\n@pytest.fixture\ndef subject():\n"
        b"    return lambda: 2\n"
    )
    assert _cross_file_fixture_shadow(
        "tests/conftest.py",
        ancestor,
        "tests/unit/test_billing.py",
        b"def test_invoice(subject):\n    assert subject() == 2\n",
        extra_sources={"tests/unit/conftest.py": nearer},
    ) == []


def test_direct_parametrize_value_shadows_a_cross_file_same_named_fixture():
    conftest = (
        b"import pytest\n\n@pytest.fixture\ndef subject():\n"
        b"    from src.billing import invoice_total\n"
        b"    return invoice_total\n"
    )
    test = (
        b"import pytest\n\n"
        b"@pytest.mark.parametrize('subject', [lambda: 2])\n"
        b"def test_invoice(subject):\n"
        b"    assert subject() == 2\n"
    )
    assert _cross_file_fixture_shadow(
        "tests/conftest.py", conftest, "tests/test_billing.py", test
    ) == []


@pytest.mark.parametrize(
    ("module", "before_paths", "after_paths", "before_roots", "after_roots", "contents"),
    [
        # A duplicate that remains behind the production source never wins.
        (
            "app.normalize",
            {"src/app/normalize.py"},
            {"src/app/normalize.py", "shadow/app/normalize.py"},
            ("src", "shadow"),
            ("src", "shadow"),
            {"src/app/normalize.py": b"buggy", "shadow/app/normalize.py": b"corrected"},
        ),
        # Byte-identical providers do not change the subject the oracle runs.
        (
            "app.normalize",
            {"src/app/normalize.py"},
            {"src/app/normalize.py", "app/normalize.py"},
            ("src", ""),
            ("", "src"),
            {"src/app/normalize.py": b"same", "app/normalize.py": b"same"},
        ),
        # A sibling module is not a provider for the imported subject.
        (
            "app.normalize",
            {"src/app/normalize.py"},
            {"src/app/normalize.py", "app/helpers.py"},
            ("src", ""),
            ("", "src"),
            {"src/app/normalize.py": b"buggy", "app/helpers.py": b"corrected"},
        ),
        # An earlier namespace portion does not beat a later regular package;
        # Python discards the namespace portion when it finds __init__.py.
        (
            "app.normalize",
            {"src/app/__init__.py", "src/app/normalize.py"},
            {"src/app/__init__.py", "src/app/normalize.py", "tests/app/normalize.py"},
            ("tests", "src"),
            ("tests", "src"),
            {
                "src/app/__init__.py": b"",
                "src/app/normalize.py": b"buggy",
                "tests/app/normalize.py": b"corrected",
            },
        ),
    ],
)
def test_exact_honest_provider_negatives(
    module, before_paths, after_paths, before_roots, after_roots, contents
):
    assert _changed_provider(
        module,
        SearchPlan("negative", before_roots, after_roots),
        before_paths,
        after_paths,
        contents,
        added_paths=after_paths - before_paths,
    ) is None


def test_search_path_parsers_preserve_declared_order():
    assert _config_search(
        "pytest.ini", b"[pytest]\npythonpath = shadow src\naddopts = --import-mode=prepend\n"
    ) == (("shadow", "src"), "prepend")
    assert _config_search(
        "pyproject.toml",
        (
            b'[tool.pytest.ini_options]\npythonpath = ["shadow", "src"]\n'
            b'addopts = "--import-mode=append"\n'
        ),
    ) == (("shadow", "src"), "append")
    assert _config_search(
        "tox.ini", b"[pytest]\npythonpath = shadow src\naddopts = --import-mode importlib\n"
    ) == (("shadow", "src"), "importlib")
    assert _config_search(
        "setup.cfg", b"[tool:pytest]\npythonpath = shadow src\n"
    ) == (("shadow", "src"), "prepend")
    assert _sys_path_roots(
        "tests/conftest.py",
        (
            b"import sys\nfrom pathlib import Path\n"
            b'sys.path.insert(0, str(Path(__file__).parent / "standins"))\n'
        ),
    ) == ("tests/standins",)
    assert _sys_path_roots(
        "tests/unit/conftest.py",
        (
            b"import sys\nfrom pathlib import Path\n"
            b"ROOT = Path(__file__).resolve().parents[1]\n"
            b"sys.path[:0] = [str(ROOT / 'standins')]\n"
        ),
    ) == ("tests/standins",)
    assert _sys_path_roots(
        "tests/conftest.py",
        (
            b"import sys\n"
            b"sys.path.insert(0, 'first')\n"
            b"sys.path[:0] = ['second', 'third']\n"
            b"sys.path.insert(0, 'last')\n"
        ),
    ) == ("last", "second", "third", "first")
    assert _runner_pythonpath(
        "scripts/test.sh", b"#!/bin/sh\nPYTHONPATH=shadow:src\npytest -q\n"
    ) == ("shadow", "src")
    assert _runner_pythonpath(
        "scripts/test.sh", b'#!/bin/sh\nPYTHONPATH="shadow:src" pytest -q\n'
    ) == ("shadow", "src")
    assert _runner_pythonpath(
        "scripts/test.cmd", b'@echo off\nset "PYTHONPATH=shadow;src"\npytest -q\n'
    ) == ("shadow", "src")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            b"#!/bin/sh\nPYTHONPATH=shadow\nPYTHONPATH=src\npytest -q\n",
            ("src",),
        ),
        (
            b"#!/bin/sh\nPYTHONPATH=src\nPYTHONPATH=shadow:$PYTHONPATH pytest -q\n",
            ("shadow", "src"),
        ),
        (
            b"#!/bin/sh\nPYTHONPATH=src\npytest -q\nPYTHONPATH=shadow\n",
            ("src",),
        ),
    ],
    ids=("last-persistent", "command-scoped", "post-invocation"),
)
def test_runner_pythonpath_uses_the_environment_at_pytest_invocation(source, expected):
    assert _runner_pythonpath("scripts/test.sh", source) == expected


def test_windows_relative_pythonpath_keeps_directory_separators():
    assert _runner_pythonpath(
        "scripts/test.cmd",
        b'@echo off\nset "PYTHONPATH=.\\shadow;.\\src"\npytest -q\n',
    ) == ("shadow", "src")


def test_unrelated_extend_path_call_does_not_create_a_namespace_package():
    source = (
        b"def extend_path(path, name):\n    return path\n\n"
        b"__path__ = extend_path(__path__, __name__)\n"
    )
    assert not _extends_package_path(source)
    assert not _extends_package_path(
        b"__path__ = extend_path(__path__, __name__)\n"
        b"from pkgutil import extend_path\n"
    )
    assert not _extends_package_path(
        b"from pkgutil import extend_path\n"
        b"extend_path = lambda path, name: path\n"
        b"__path__ = extend_path(__path__, __name__)\n"
    )


def test_pytest_package_import_root_is_not_the_test_directory():
    paths = {"tests/__init__.py", "tests/test_billing.py", "tests/src/billing.py"}
    assert _pytest_import_root("tests/test_billing.py", paths) == ""
    assert _pytest_import_root("loose/test_billing.py", paths) == "loose"


def test_arbitrary_provider_ancestor_is_not_invented_as_an_installed_root():
    assert _changed_provider(
        "normalize",
        SearchPlan("negative", ("",), ("",)),
        {"vendor/private/normalize.py"},
        {"vendor/private/normalize.py", "normalize.py"},
        {
            "vendor/private/normalize.py": b"VALUE = 'baseline'\n",
            "normalize.py": b"VALUE = 'shadow'\n",
        },
        added_paths={"normalize.py"},
    ) is None


def test_repository_inventory_is_lazy_for_an_ordinary_edit():
    def forbidden():
        raise AssertionError("ordinary diffs must not inventory the repository")

    hits = find_runtime_subject_shadows(
        [FileChange("src/app.py", "modified", b"VALUE = 1\n", b"VALUE = 2\n")],
        Config(),
        head_path_lister=forbidden,
    ) == []


def test_inventory_callback_failure_is_not_silently_treated_as_no_shadow():
    def failed_inventory():
        raise OSError("inventory unavailable")

    with pytest.raises(OSError, match="inventory unavailable"):
        find_runtime_subject_shadows(
            [FileChange("app/normalize.py", "added", None, b"VALUE = 2\n")],
            Config(),
            head_path_lister=failed_inventory,
        )


def test_required_batch_read_failure_is_an_engine_error():
    sources = {
        "src/billing.py": b"def invoice_total():\n    return 1\n",
        "tests/src/billing.py": b"def invoice_total():\n    return 2\n",
        "tests/test_billing.py": (
            b"from src.billing import invoice_total\n\n"
            b"def test_invoice_total():\n    assert invoice_total() == 2\n"
        ),
    }

    def failed_batch(_paths):
        raise OSError("snapshot unavailable")

    with pytest.raises(OSError, match="snapshot unavailable"):
        find_runtime_subject_shadows(
            [
                FileChange(
                    "tests/src/billing.py",
                    "added",
                    None,
                    sources["tests/src/billing.py"],
                )
            ],
            Config(),
            head_path_lister=lambda: sorted(sources),
            head_batch_reader=failed_batch,
            head_searcher=lambda _needles: HeadSearchResult(
                ("tests/test_billing.py",), complete=True
            ),
        )


def test_complete_search_missing_blob_is_an_engine_error():
    sources = {
        "src/billing.py": b"def invoice_total():\n    return 1\n",
        "tests/src/billing.py": b"def invoice_total():\n    return 2\n",
        "tests/test_billing.py": (
            b"from src.billing import invoice_total\n\n"
            b"def test_invoice_total():\n    assert invoice_total() == 2\n"
        ),
    }

    def missing_test_blob(paths):
        return {
            path: None if path == "tests/test_billing.py" else sources.get(path)
            for path in paths
        }

    with pytest.raises(
        RuntimeError,
        match="runtime-shadow snapshot read failed: tests/test_billing.py",
    ):
        find_runtime_subject_shadows(
            [
                FileChange(
                    "tests/src/billing.py",
                    "added",
                    None,
                    sources["tests/src/billing.py"],
                )
            ],
            Config(),
            head_path_lister=lambda: sorted(sources),
            head_batch_reader=missing_test_blob,
            head_searcher=lambda _needles: HeadSearchResult(
                ("tests/test_billing.py",), complete=True
            ),
        )


def test_failed_preflight_falls_back_to_complete_inventory():
    sources = {
        "src/billing.py": b"def invoice_total():\n    return 1\n",
        "tests/src/billing.py": b"def invoice_total():\n    return 2\n",
        "tests/test_billing.py": (
            b"from src.billing import invoice_total\n\n"
            b"def test_invoice_total():\n    assert invoice_total() == 2\n"
        ),
    }

    def failed_preflight(_needles):
        raise OSError("grep unavailable")

    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {path: sources.get(path) for path in paths},
        head_searcher=failed_preflight,
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/src/billing.py")
    ]


def test_interesting_snapshot_is_listed_once_and_sources_use_two_bounded_batches():
    sources = {
        "src/billing.py": b"def invoice_total():\n    return 1\n",
        "tests/src/billing.py": b"def invoice_total():\n    return 2\n",
        "tests/test_billing.py": (
            b"from src.billing import invoice_total\n\n"
            b"def test_invoice_total():\n    assert invoice_total() == 2\n"
        ),
    }
    calls = {"list": 0, "batch": 0}

    def list_paths():
        calls["list"] += 1
        return sorted(sources)

    def read_batch(paths):
        calls["batch"] += 1
        return {path: sources.get(path) for path in paths}

    hits = find_runtime_subject_shadows(
        [FileChange("tests/src/billing.py", "added", None, sources["tests/src/billing.py"])],
        Config(),
        head_path_lister=list_paths,
        head_batch_reader=read_batch,
        head_searcher=lambda _needles: ["tests/test_billing.py"],
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/src/billing.py")
    ]
    # Phase one reads the candidate tests; phase two reads only the exact
    # providers those tests actively import. Neither phase is per-file.
    assert calls == {"list": 1, "batch": 2}


def test_provider_collision_is_proved_before_searching_or_reading_tests(monkeypatch):
    sources = {
        "src/app/value.py": b"VALUE = 2\n",
        "tests/test_value.py": (
            b"from app.value import VALUE\n\n"
            b"def test_value():\n    assert VALUE == 2\n"
        ),
    }
    calls = {"list": 0, "search": 0, "batch": 0}

    def list_paths():
        calls["list"] += 1
        return sorted(sources)

    def forbidden_search(_needles):
        calls["search"] += 1
        raise AssertionError("a unique provider needs no content search")

    def forbidden_batch(_paths):
        calls["batch"] += 1
        raise AssertionError("a unique provider needs no snapshot read")

    def forbidden_source_key(_data):
        raise AssertionError("a unique provider needs no source fingerprint")

    monkeypatch.setattr(shadow_module, "_source_key", forbidden_source_key)

    assert find_runtime_subject_shadows(
        [
            FileChange(
                "src/app/value.py",
                "modified",
                b"VALUE = 1\n",
                sources["src/app/value.py"],
            )
        ],
        Config(),
        head_path_lister=list_paths,
        head_batch_reader=forbidden_batch,
        head_searcher=forbidden_search,
    ) == []
    assert calls == {"list": 1, "search": 0, "batch": 0}


def test_complete_search_shortlist_excludes_hundreds_of_decoy_tests():
    sources = {
        f"tests/test_decoy_{index:03}.py": (
            b"def test_decoy():\n    assert True\n"
        )
        for index in range(300)
    }
    sources.update(
        {
            "src/billing.py": b"def total():\n    return 1\n",
            "tests/src/billing.py": b"def total():\n    return 2\n",
            "tests/test_billing.py": (
                b"from src.billing import total\n\n"
                b"def test_total():\n    assert total() == 2\n"
            ),
        }
    )
    batches: list[tuple[str, ...]] = []

    def read_batch(paths):
        batches.append(tuple(paths))
        return {path: sources.get(path) for path in paths}

    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=read_batch,
        head_searcher=lambda _needles: HeadSearchResult(
            ("tests/test_billing.py",), complete=True
        ),
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/src/billing.py")
    ]
    requested = {path for batch in batches for path in batch}
    assert "tests/test_billing.py" in requested
    assert not any(path.startswith("tests/test_decoy_") for path in requested)


def test_complete_empty_search_returns_before_snapshot_reads():
    sources = {
        "src/billing.py": b"def total():\n    return 1\n",
        "tests/src/billing.py": b"def total():\n    return 2\n",
        "tests/test_billing.py": (
            b"from src.billing import total\n\n"
            b"def test_total():\n    assert total() == 2\n"
        ),
    }
    calls = {"search": 0, "batch": 0}

    def complete_empty(_needles):
        calls["search"] += 1
        return HeadSearchResult((), complete=True)

    def forbidden_batch(_paths):
        calls["batch"] += 1
        raise AssertionError("an authoritative empty search needs no source read")

    assert find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=forbidden_batch,
        head_searcher=complete_empty,
    ) == []
    assert calls == {"search": 1, "batch": 0}


def test_legacy_empty_search_is_not_inferred_to_be_complete():
    sources = {
        "src/billing.py": b"def total():\n    return 1\n",
        "tests/src/billing.py": b"def total():\n    return 2\n",
        "tests/test_billing.py": (
            b"from src.billing import total\n\n"
            b"def test_total():\n    assert total() == 2\n"
        ),
    }
    requested: set[str] = set()

    def read_batch(paths):
        requested.update(paths)
        return {path: sources.get(path) for path in paths}

    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=read_batch,
        head_searcher=lambda _needles: [],
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/src/billing.py")
    ]
    assert "tests/test_billing.py" in requested


def test_complete_conftest_match_closes_over_only_its_test_scope():
    sources = {
        "src/billing.py": b"def total():\n    return 1\n",
        "tests/team/src/billing.py": b"def total():\n    return 2\n",
        "tests/team/conftest.py": (
            b"import pytest\n"
            b"from src.billing import total\n\n"
            b"@pytest.fixture(autouse=True)\n"
            b"def exercise_subject():\n    assert total() == 2\n"
        ),
        "tests/team/test_contract.py": b"def test_contract():\n    assert True\n",
        "tests/other/test_sibling.py": b"def test_sibling():\n    assert True\n",
    }
    batches: list[tuple[str, ...]] = []

    def read_batch(paths):
        batches.append(tuple(paths))
        return {path: sources.get(path) for path in paths}

    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "tests/team/src/billing.py",
                "added",
                None,
                sources["tests/team/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=read_batch,
        head_searcher=lambda _needles: HeadSearchResult(
            ("tests/team/conftest.py",), complete=True
        ),
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/team/src/billing.py")
    ]
    requested = {path for batch in batches for path in batch}
    assert "tests/team/test_contract.py" in requested
    assert "tests/other/test_sibling.py" not in requested


def test_explicitly_incomplete_search_retains_the_full_test_inventory():
    sources = {
        "src/billing.py": b"def total():\n    return 1\n",
        "tests/src/billing.py": b"def total():\n    return 2\n",
        "tests/test_decoy.py": b"def test_decoy():\n    assert True\n",
        "tests/test_real.py": (
            b"from src.billing import total\n\n"
            b"def test_total():\n    assert total() == 2\n"
        ),
    }
    requested: set[str] = set()

    def read_batch(paths):
        requested.update(paths)
        return {path: sources.get(path) for path in paths}

    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=read_batch,
        head_searcher=lambda _needles: HeadSearchResult(
            ("tests/test_decoy.py",), complete=False
        ),
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/src/billing.py")
    ]
    assert {"tests/test_decoy.py", "tests/test_real.py"} <= requested


@pytest.mark.parametrize(
    "malformed_path",
    [
        "../tests/test_real.py",
        r"C:\repo\tests\test_real.py",
        r"\\server\repo\tests\test_real.py",
        "/tests/test_real.py",
        "tests/./test_real.py",
        "",
        "tests/\ttest_real.py",
        42,
    ],
    ids=(
        "dotdot",
        "drive-absolute",
        "unc-absolute",
        "posix-absolute",
        "dot-segment",
        "empty",
        "escaped-control",
        "non-string",
    ),
)
def test_malformed_complete_search_path_retains_full_inventory(malformed_path):
    sources = {
        "src/billing.py": b"def total():\n    return 1\n",
        "tests/src/billing.py": b"def total():\n    return 2\n",
        "tests/test_decoy.py": b"def test_decoy():\n    assert True\n",
        "tests/test_real.py": (
            b"from src.billing import total\n\n"
            b"def test_total():\n    assert total() == 2\n"
        ),
    }
    requested: set[str] = set()

    def read_batch(paths):
        requested.update(paths)
        return {path: sources.get(path) for path in paths}

    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=read_batch,
        head_searcher=lambda _needles: HeadSearchResult(
            (malformed_path,), complete=True
        ),
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/src/billing.py")
    ]
    assert {"tests/test_decoy.py", "tests/test_real.py"} <= requested


def test_complete_search_normalizes_valid_backslash_path():
    sources = {
        "src/billing.py": b"def total():\n    return 1\n",
        "tests/src/billing.py": b"def total():\n    return 2\n",
        "tests/test_decoy.py": b"def test_decoy():\n    assert True\n",
        "tests/test_real.py": (
            b"from src.billing import total\n\n"
            b"def test_total():\n    assert total() == 2\n"
        ),
    }
    requested: set[str] = set()

    def read_batch(paths):
        requested.update(paths)
        return {path: sources.get(path) for path in paths}

    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=read_batch,
        head_searcher=lambda _needles: HeadSearchResult(
            (r"tests\test_real.py",), complete=True
        ),
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/src/billing.py")
    ]
    assert "tests/test_real.py" in requested
    assert "tests/test_decoy.py" not in requested


def test_revision_cache_parses_identical_test_content_once(monkeypatch):
    test_source = (
        b"from src.billing import total\n\n"
        b"def test_total():\n    assert total() == 2\n"
    )
    sources = {
        "src/billing.py": b"def total():\n    return 1\n",
        "tests/src/billing.py": b"def total():\n    return 2\n",
        "tests/test_first.py": test_source,
        "tests/test_second.py": test_source,
    }
    calls = {"active": 0, "bindings": 0, "requests": 0, "parse": 0}
    original_active = shadow_module._active_test_imports
    original_bindings = shadow_module._fixture_bindings
    original_requests = shadow_module._test_fixture_requests
    original_parse = shadow_module.parse_python

    def counted_active(*args, **kwargs):
        calls["active"] += 1
        return original_active(*args, **kwargs)

    def counted_bindings(*args, **kwargs):
        calls["bindings"] += 1
        return original_bindings(*args, **kwargs)

    def counted_requests(*args, **kwargs):
        calls["requests"] += 1
        return original_requests(*args, **kwargs)

    def counted_parse(*args, **kwargs):
        calls["parse"] += 1
        return original_parse(*args, **kwargs)

    monkeypatch.setattr(shadow_module, "_active_test_imports", counted_active)
    monkeypatch.setattr(shadow_module, "_fixture_bindings", counted_bindings)
    monkeypatch.setattr(shadow_module, "_test_fixture_requests", counted_requests)
    monkeypatch.setattr(shadow_module, "parse_python", counted_parse)

    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {path: sources.get(path) for path in paths},
        head_searcher=lambda _needles: HeadSearchResult(
            ("tests/test_first.py", "tests/test_second.py"), complete=True
        ),
    )
    assert len(hits) == 1
    assert calls == {"active": 1, "bindings": 1, "requests": 1, "parse": 2}


def test_revision_cache_fingerprints_each_equivalent_provider_content_once(monkeypatch):
    provider = b"def total():\n    return 1\n"
    test_source = (
        b"from src.billing import total\n\n"
        b"def test_total():\n    assert total() == 1\n"
    )
    test_paths = tuple(f"tests/test_contract_{index:03}.py" for index in range(100))
    sources = {
        "src/billing.py": provider,
        "tests/src/billing.py": provider,
        **{path: test_source for path in test_paths},
    }
    calls = {"provider": 0, "source": 0}
    original_provider = shadow_module._provider_execution_key
    original_source = shadow_module._source_key

    def counted_provider(*args, **kwargs):
        calls["provider"] += 1
        return original_provider(*args, **kwargs)

    def counted_source(*args, **kwargs):
        calls["source"] += 1
        return original_source(*args, **kwargs)

    monkeypatch.setattr(shadow_module, "_provider_execution_key", counted_provider)
    monkeypatch.setattr(shadow_module, "_source_key", counted_source)

    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {path: sources.get(path) for path in paths},
        head_searcher=lambda _needles: HeadSearchResult(test_paths, complete=True),
        include_equivalent=True,
    )
    assert len(hits) == 1
    assert hits[0].reportable is False
    assert calls == {"provider": 2, "source": 1}


def test_a_capped_preflight_result_never_becomes_a_candidate_cap():
    sources = {
        f"tests/test_decoy_{index:03}.py": (
            b"SOURCE = 'src'\n\ndef test_decoy():\n    assert True\n"
        )
        for index in range(300)
    }
    sources.update(
        {
            "src/billing.py": b"def invoice_total():\n    return 1\n",
            "tests/src/billing.py": b"def invoice_total():\n    return 2\n",
            "tests/zzzz_billing_test.py": (
                b"from src.billing import invoice_total\n\n"
                b"def test_invoice_total():\n    assert invoice_total() == 2\n"
            ),
        }
    )
    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {path: sources.get(path) for path in paths},
        # Simulate an older/capped caller returning a non-authoritative prefix.
        head_searcher=lambda _needles: ["tests/test_decoy_000.py"],
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/src/billing.py")
    ]


def test_a_capped_non_test_prefix_never_becomes_an_authoritative_no_match():
    sources = {
        f"tools/decoy_{index:03}.py": b"SOURCE = 'src'\n"
        for index in range(300)
    }
    sources.update(
        {
            "src/billing.py": b"def invoice_total():\n    return 1\n",
            "tests/src/billing.py": b"def invoice_total():\n    return 2\n",
            "tests/zzzz_billing_test.py": (
                b"from src.billing import invoice_total\n\n"
                b"def test_invoice_total():\n    assert invoice_total() == 2\n"
            ),
        }
    )
    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "tests/src/billing.py",
                "added",
                None,
                sources["tests/src/billing.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {path: sources.get(path) for path in paths},
        # A legacy cap is exhausted by non-test hits before the real test.
        head_searcher=lambda _needles: [
            f"tools/decoy_{index:03}.py" for index in range(300)
        ],
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/src/billing.py")
    ]


@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        (
            "tests/conftest.py",
            b'import sys\nsys.path.insert(0, "src")\n',
            b'import sys\nsys.path.insert(0, "standins")\n',
        ),
        (
            "scripts/test.sh",
            b"#!/bin/sh\nPYTHONPATH=src pytest -q\n",
            b"#!/bin/sh\nPYTHONPATH=standins pytest -q\n",
        ),
    ],
)
def test_changed_runtime_search_control_selects_existing_standin(path, before, after):
    sources = {
        "src/app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "standins/app/normalize.py": b"def normalize(value):\n    return value.strip().lower()\n",
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'x'\n"
        ),
        path: after,
    }
    hits = find_runtime_subject_shadows(
        [FileChange(path, "modified", before, after)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/app/normalize.py", "standins/app/normalize.py")
    ]


@pytest.mark.parametrize("runner_touched", [False, True])
def test_existing_runner_environment_selects_a_new_standin_provider(runner_touched):
    runner_before = b"#!/bin/sh\nPYTHONPATH=standins:src pytest -q\n"
    runner_after = runner_before + (b"# keep local imports explicit\n" if runner_touched else b"")
    sources = {
        "src/app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "standins/app/normalize.py": b"def normalize(value):\n    return value.lower()\n",
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize('X') == 'x'\n"
        ),
        "scripts/test.sh": runner_after,
    }
    changes = [
        FileChange(
            "standins/app/normalize.py",
            "added",
            None,
            sources["standins/app/normalize.py"],
        )
    ]
    if runner_touched:
        changes.append(
            FileChange("scripts/test.sh", "modified", runner_before, runner_after)
        )
    hits = find_runtime_subject_shadows(
        changes,
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/app/normalize.py", "standins/app/normalize.py")
    ]


def test_unchanged_extensionless_shebang_runner_is_in_the_inventory():
    runner = b"#!/bin/sh\nPYTHONPATH=standins:src pytest -q\n"
    sources = {
        "src/app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "standins/app/normalize.py": b"def normalize(value):\n    return value.lower()\n",
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize('X') == 'x'\n"
        ),
        "scripts/test": runner,
    }
    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "standins/app/normalize.py",
                "added",
                None,
                sources["standins/app/normalize.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/app/normalize.py", "standins/app/normalize.py")
    ]


def test_executable_package_init_change_makes_identical_leaf_reportable():
    sources = {
        "app/__init__.py": b"PROVIDER = 'shadow'\n",
        "app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "src/app/__init__.py": b"PROVIDER = 'production'\n",
        "src/app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'X'\n"
        ),
        "pytest.ini": b"[pytest]\npythonpath = . src\n",
    }
    hits = find_runtime_subject_shadows(
        [
            FileChange("app/__init__.py", "added", None, sources["app/__init__.py"]),
            FileChange("app/normalize.py", "added", None, sources["app/normalize.py"]),
            FileChange(
                "pytest.ini",
                "modified",
                b"[pytest]\npythonpath = src\n",
                sources["pytest.ini"],
            ),
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
    )
    assert len(hits) == 1
    assert hits[0].reportable


def test_equivalent_provider_switch_is_an_honest_negative():
    same_init = b"PROVIDER = 'same'\n"
    same_leaf = b"def normalize(value):\n    return value.strip()\n"
    sources = {
        "app/__init__.py": same_init,
        "app/normalize.py": same_leaf,
        "src/app/__init__.py": same_init,
        "src/app/normalize.py": same_leaf,
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'X'\n"
        ),
        "pytest.ini": b"[pytest]\npythonpath = . src\n",
    }
    hits = find_runtime_subject_shadows(
        [
            FileChange("app/__init__.py", "added", None, same_init),
            FileChange("app/normalize.py", "added", None, same_leaf),
            FileChange(
                "pytest.ini",
                "modified",
                b"[pytest]\npythonpath = src\n",
                sources["pytest.ini"],
            ),
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
        include_equivalent=True,
    )
    # The provider identity changed, so the stand-in is still returned to the
    # engine for repair-evidence exclusion.  Equivalent executable bytes are
    # not themselves an authorised TEST_PATCHES_SUBJECT finding.
    assert len(hits) == 1
    assert not hits[0].reportable


def test_already_winning_equivalent_provider_becomes_visible_when_it_changes():
    same = b"def normalize(value):\n    return value.strip()\n"
    changed = b"def normalize(value):\n    return value.strip().lower()\n"
    sources = {
        "app/__init__.py": b"",
        "app/normalize.py": changed,
        "src/app/__init__.py": b"",
        "src/app/normalize.py": same,
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'x'\n"
        ),
        "pytest.ini": b"[pytest]\npythonpath = . src\n",
    }
    hits = find_runtime_subject_shadows(
        [FileChange("app/normalize.py", "modified", same, changed)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
        include_equivalent=True,
    )
    assert [
        (hit.before_provider, hit.after_provider, hit.finding_path, hit.reportable)
        for hit in hits
    ] == [("app/normalize.py", "app/normalize.py", "app/normalize.py", True)]


def test_already_divergent_winning_provider_edit_is_not_a_shadow_finding():
    sources = {
        "app/__init__.py": b"",
        "app/normalize.py": b"def normalize(value):\n    return value.lower()\n",
        "src/app/__init__.py": b"",
        "src/app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'x'\n"
        ),
        "pytest.ini": b"[pytest]\npythonpath = . src\n",
    }
    assert find_runtime_subject_shadows(
        [
            FileChange(
                "app/normalize.py",
                "modified",
                b"def normalize(value):\n    return value.upper()\n",
                sources["app/normalize.py"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
        include_equivalent=True,
    ) == []


def test_equivalent_provider_and_canonical_changed_together_remain_honest():
    same = b"def normalize(value):\n    return value.strip()\n"
    changed = b"def normalize(value):\n    return value.strip().lower()\n"
    sources = {
        "app/__init__.py": b"",
        "app/normalize.py": changed,
        "src/app/__init__.py": b"",
        "src/app/normalize.py": changed,
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'x'\n"
        ),
        "pytest.ini": b"[pytest]\npythonpath = . src\n",
    }
    hits = find_runtime_subject_shadows(
        [
            FileChange("app/normalize.py", "modified", same, changed),
            FileChange("src/app/normalize.py", "modified", same, changed),
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
        include_equivalent=True,
    )
    assert len(hits) == 1
    assert not hits[0].reportable


def test_already_winning_equivalent_package_init_change_is_visible():
    same_init = b"PROVIDER = 'same'\n"
    changed_init = b"PROVIDER = 'standin'\n"
    leaf = b"def normalize(value):\n    return value.strip()\n"
    sources = {
        "app/__init__.py": changed_init,
        "app/normalize.py": leaf,
        "src/app/__init__.py": same_init,
        "src/app/normalize.py": leaf,
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'X'\n"
        ),
        "pytest.ini": b"[pytest]\npythonpath = . src\n",
    }
    hits = find_runtime_subject_shadows(
        [FileChange("app/__init__.py", "modified", same_init, changed_init)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
        include_equivalent=True,
    )
    assert [(hit.finding_path, hit.after_chain, hit.reportable) for hit in hits] == [
        ("app/normalize.py", ("app/__init__.py",), True)
    ]


def test_deleting_regular_package_boundary_exposes_a_namespace_standin():
    sources = {
        "pytest.ini": b"[pytest]\npythonpath = src\n",
        "src/app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "tests/app/normalize.py": b"def normalize(value):\n    return value.lower()\n",
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize('X') == 'x'\n"
        ),
    }
    hits = find_runtime_subject_shadows(
        [FileChange("src/app/__init__.py", "deleted", b"", None)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert [(hit.finding_path, hit.before_provider, hit.after_provider) for hit in hits] == [
        (
            "src/app/__init__.py",
            "src/app/normalize.py",
            "tests/app/normalize.py",
        )
    ]


@pytest.mark.parametrize(
    ("path", "before", "after"),
    [
        (
            "pytest.ini",
            b"[pytest]\npythonpath = src\n",
            b"[pytest]\npythonpath = . src\n",
        ),
        (
            ".pytest.ini",
            b"[pytest]\npythonpath = src\n",
            b"[pytest]\npythonpath = . src\n",
        ),
        (
            "tox.ini",
            b"[pytest]\npythonpath = src\n",
            b"[pytest]\npythonpath = . src\n",
        ),
        (
            "setup.cfg",
            b"[tool:pytest]\npythonpath = src\n",
            b"[tool:pytest]\npythonpath = . src\n",
        ),
        (
            "pyproject.toml",
            b'[tool.pytest.ini_options]\npythonpath = ["src"]\n',
            b'[tool.pytest.ini_options]\npythonpath = [".", "src"]\n',
        ),
    ],
)
def test_pytest_config_spellings_feed_the_same_provider_predicate(path, before, after):
    sources = {
        "app/__init__.py": b"",
        "app/normalize.py": b"def normalize(value):\n    return value.lower()\n",
        "src/app/__init__.py": b"",
        "src/app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'x'\n"
        ),
        path: after,
    }
    changes = [
        FileChange("app/__init__.py", "added", None, sources["app/__init__.py"]),
        FileChange("app/normalize.py", "added", None, sources["app/normalize.py"]),
        FileChange(path, "modified", before, after),
    ]
    hits = find_runtime_subject_shadows(
        changes,
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/app/normalize.py", "app/normalize.py")
    ]


def test_nested_pytest_config_does_not_control_a_test_outside_its_subtree():
    sources = {
        "app/__init__.py": b"",
        "app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "examples/app/__init__.py": b"",
        "examples/app/normalize.py": b"def normalize(value):\n    return value.lower()\n",
        "examples/pytest.ini": b"[pytest]\npythonpath = . ..\n",
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'X'\n"
        ),
    }
    assert find_runtime_subject_shadows(
        [
            FileChange(
                "examples/pytest.ini",
                "modified",
                b"[pytest]\npythonpath = ..\n",
                sources["examples/pytest.ini"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    ) == []


def test_nested_pytest_config_controls_a_test_inside_its_subtree():
    sources = {
        "app/__init__.py": b"",
        "app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "examples/app/__init__.py": b"",
        "examples/app/normalize.py": b"def normalize(value):\n    return value.lower()\n",
        "examples/pytest.ini": b"[pytest]\npythonpath = . ..\n",
        "examples/tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'x'\n"
        ),
    }
    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "examples/pytest.ini",
                "modified",
                b"[pytest]\npythonpath = ..\n",
                sources["examples/pytest.ini"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("app/normalize.py", "examples/app/normalize.py")
    ]


def test_existing_conftest_root_keeps_new_duplicate_behind_subject():
    sources = {
        "app/__init__.py": b"",
        "app/normalize.py": b"def normalize(value):\n    return value.lower()\n",
        "src/app/__init__.py": b"",
        "src/app/normalize.py": b"def normalize(value):\n    return value.strip()\n",
        "tests/conftest.py": b'import sys\nsys.path.insert(0, "src")\n',
        "tests/test_normalize.py": (
            b"from app.normalize import normalize\n\n"
            b"def test_normalize():\n    assert normalize(' X ') == 'X'\n"
        ),
    }
    changes = [
        FileChange("app/__init__.py", "added", None, sources["app/__init__.py"]),
        FileChange("app/normalize.py", "added", None, sources["app/normalize.py"]),
    ]
    assert find_runtime_subject_shadows(
        changes,
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_normalize.py"],
    ) == []


def test_deduplicated_package_fanout_retains_every_evidence_exclusion_path():
    sources = {
        "app/__init__.py": b"",
        "app/a.py": b"def value():\n    return 'shadow-a'\n",
        "app/b.py": b"def value():\n    return 'shadow-b'\n",
        "src/app/__init__.py": b"",
        "src/app/a.py": b"def value():\n    return 'prod-a'\n",
        "src/app/b.py": b"def value():\n    return 'prod-b'\n",
        "tests/test_app.py": (
            b"from app.a import value as a_value\n"
            b"from app.b import value as b_value\n\n"
            b"def test_values():\n    assert a_value() and b_value()\n"
        ),
        "pytest.ini": b"[pytest]\npythonpath = . src\n",
    }
    changes = [
        FileChange("app/__init__.py", "added", None, sources["app/__init__.py"]),
        FileChange("app/a.py", "added", None, sources["app/a.py"]),
        FileChange("app/b.py", "added", None, sources["app/b.py"]),
        FileChange(
            "pytest.ini",
            "modified",
            b"[pytest]\npythonpath = src\n",
            sources["pytest.ini"],
        ),
    ]
    hits = find_runtime_subject_shadows(
        changes,
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/test_app.py"],
    )
    assert len(hits) == 1
    excluded = {
        hits[0].after_provider,
        *hits[0].after_chain,
        *hits[0].related_evidence_paths,
    }
    assert {"app/__init__.py", "app/a.py", "app/b.py"} <= excluded


def _runner_matrix_sources(runner: bytes) -> dict[str, bytes]:
    return {
        "src/alpha/value.py": b"def value():\n    return 'prod-alpha'\n",
        "src/beta/value.py": b"def value():\n    return 'prod-beta'\n",
        "standins_a/alpha/value.py": b"def value():\n    return 'shadow-alpha'\n",
        "standins_b/beta/value.py": b"def value():\n    return 'shadow-beta'\n",
        "standins/alpha/value.py": b"def value():\n    return 'shadow-alpha'\n",
        "standins/beta/value.py": b"def value():\n    return 'shadow-beta'\n",
        "tests/a/test_alpha.py": (
            b"from alpha.value import value\n\n"
            b"def test_value():\n    assert value() == 'shadow-alpha'\n"
        ),
        "tests/b/test_beta.py": (
            b"from beta.value import value\n\n"
            b"def test_value():\n    assert value() == 'shadow-beta'\n"
        ),
        "scripts/test.sh": runner,
    }


def test_each_pytest_invocation_uses_its_own_environment_and_target_scope():
    before = (
        b"#!/bin/sh\n"
        b"PYTHONPATH=src pytest tests/a\n"
        b"PYTHONPATH=src pytest tests/b\n"
    )
    after = (
        b"#!/bin/sh\n"
        b"PYTHONPATH=standins_a:src pytest tests/a\n"
        b"PYTHONPATH=standins_b:src pytest tests/b\n"
    )
    sources = _runner_matrix_sources(after)
    hits = find_runtime_subject_shadows(
        [FileChange("scripts/test.sh", "modified", before, after)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert {
        (hit.module, hit.before_provider, hit.after_provider, hit.test_path)
        for hit in hits
    } == {
        (
            "alpha.value",
            "src/alpha/value.py",
            "standins_a/alpha/value.py",
            "tests/a/test_alpha.py",
        ),
        (
            "beta.value",
            "src/beta/value.py",
            "standins_b/beta/value.py",
            "tests/b/test_beta.py",
        ),
    }


def test_runner_environment_does_not_escape_the_invoked_test_subtree():
    before = b"#!/bin/sh\nPYTHONPATH=src pytest tests/a\n"
    after = b"#!/bin/sh\nPYTHONPATH=standins:src pytest tests/a\n"
    sources = _runner_matrix_sources(after)
    hits = find_runtime_subject_shadows(
        [FileChange("scripts/test.sh", "modified", before, after)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert [(hit.module, hit.test_path) for hit in hits] == [
        ("alpha.value", "tests/a/test_alpha.py")
    ]


def test_command_scoped_environment_on_echo_is_not_persistent():
    before = b"#!/bin/sh\nPYTHONPATH=src pytest tests/a\n"
    after = (
        b"#!/bin/sh\n"
        b"PYTHONPATH=standins:src echo diagnostics\n"
        b"pytest tests/a\n"
    )
    sources = _runner_matrix_sources(after)
    assert find_runtime_subject_shadows(
        [FileChange("scripts/test.sh", "modified", before, after)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    ) == []


def test_command_scoped_pytest_environment_does_not_leak_to_next_invocation():
    before = (
        b"#!/bin/sh\n"
        b"PYTHONPATH=src\n"
        b"pytest tests/a\n"
        b"pytest tests/b\n"
    )
    after = (
        b"#!/bin/sh\n"
        b"PYTHONPATH=src\n"
        b"PYTHONPATH=standins:src pytest tests/a\n"
        b"pytest tests/b\n"
    )
    sources = _runner_matrix_sources(after)
    hits = find_runtime_subject_shadows(
        [FileChange("scripts/test.sh", "modified", before, after)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert [(hit.module, hit.test_path) for hit in hits] == [
        ("alpha.value", "tests/a/test_alpha.py")
    ]


@pytest.mark.parametrize("with_runner", [False, True], ids=("implicit", "runner"))
def test_one_invocation_uses_one_config_from_its_targets_common_ancestor(with_runner):
    runner = b"#!/bin/sh\nPYTHONPATH=src pytest tests/a tests/b\n"
    sources = _runner_matrix_sources(runner)
    if not with_runner:
        sources.pop("scripts/test.sh")
    sources.update(
        {
            "pytest.ini": b"[pytest]\npythonpath = src\n",
            "tests/a/pytest.ini": b"[pytest]\npythonpath = ../../standins ../../src\n",
        }
    )
    assert find_runtime_subject_shadows(
        [
            FileChange(
                "tests/a/pytest.ini",
                "added",
                None,
                sources["tests/a/pytest.ini"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    ) == []


def test_pytest_ini_precedes_dot_pytest_ini_in_the_same_directory():
    sources = {
        "src/app/value.py": b"VALUE = 'prod'\n",
        "standins/app/value.py": b"VALUE = 'shadow'\n",
        "tests/test_value.py": (
            b"from app.value import VALUE\n\n"
            b"def test_value():\n    assert VALUE == 'prod'\n"
        ),
        "pytest.ini": b"[pytest]\npythonpath = src\n",
        ".pytest.ini": b"[pytest]\npythonpath = standins src\n",
    }
    assert find_runtime_subject_shadows(
        [
            FileChange(
                ".pytest.ini",
                "modified",
                b"[pytest]\npythonpath = src\n",
                sources[".pytest.ini"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    ) == []


def test_empty_higher_precedence_config_can_mask_lower_config_search_roots():
    sources = {
        "app/value.py": b"VALUE = 'shadow'\n",
        "src/app/value.py": b"VALUE = 'prod'\n",
        "tests/test_value.py": (
            b"from app.value import VALUE\n\n"
            b"def test_value():\n    assert VALUE == 'shadow'\n"
        ),
        "pytest.ini": b"",
        ".pytest.ini": b"[pytest]\npythonpath = src\n",
    }
    hits = find_runtime_subject_shadows(
        [FileChange("pytest.ini", "added", None, b"")],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/app/value.py", "app/value.py")
    ]


@pytest.mark.parametrize("name", ["pytest.toml", ".pytest.toml"])
def test_native_pytest_toml_config_spellings_select_the_provider(name):
    before = b"[pytest]\npythonpath = ['src']\n"
    after = b"[pytest]\npythonpath = ['standins', 'src']\n"
    sources = {
        "src/app/value.py": b"VALUE = 'prod'\n",
        "standins/app/value.py": b"VALUE = 'shadow'\n",
        "tests/test_value.py": (
            b"from app.value import VALUE\n\n"
            b"def test_value():\n    assert VALUE == 'shadow'\n"
        ),
        name: after,
    }
    hits = find_runtime_subject_shadows(
        [FileChange(name, "modified", before, after)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/app/value.py", "standins/app/value.py")
    ]


def test_tool_pytest_table_and_last_addopts_import_mode_are_honoured():
    assert _config_search(
        "pyproject.toml",
        (
            b"[tool.pytest]\n"
            b"pythonpath = ['standins', 'src']\n"
            b"addopts = '--import-mode=append --import-mode=prepend'\n"
        ),
    ) == (("standins", "src"), "prepend")


def test_runner_cli_import_mode_overrides_config_mode():
    before = b"#!/bin/sh\nPYTHONPATH=src pytest --import-mode=append tests\n"
    after = b"#!/bin/sh\nPYTHONPATH=src pytest --import-mode=prepend tests\n"
    sources = {
        "src/app/value.py": b"VALUE = 'prod'\n",
        "tests/app/value.py": b"VALUE = 'shadow'\n",
        "tests/test_value.py": (
            b"from app.value import VALUE\n\n"
            b"def test_value():\n    assert VALUE == 'shadow'\n"
        ),
        "scripts/test.sh": after,
    }
    hits = find_runtime_subject_shadows(
        [FileChange("scripts/test.sh", "modified", before, after)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/app/value.py", "tests/app/value.py")
    ]


def test_usefixtures_mark_reaches_a_cross_file_fixture_import():
    conftest = (
        b"import pytest\n\n@pytest.fixture\ndef subject():\n"
        b"    from src.billing import invoice_total\n"
        b"    return invoice_total\n"
    )
    test = (
        b"import pytest\n\n@pytest.mark.usefixtures('subject')\n"
        b"def test_invoice():\n    assert True\n"
    )
    hits = _cross_file_fixture_shadow(
        "tests/conftest.py", conftest, "tests/test_billing.py", test
    )
    assert [(hit.before_provider, hit.after_provider) for hit in hits] == [
        ("src/billing.py", "tests/src/billing.py")
    ]


@pytest.mark.parametrize(
    "decorator_import,decorator",
    [
        ("import pytest", "pytest.mark.parametrize"),
        ("import pytest as pt", "pt.mark.parametrize"),
        ("from pytest import mark as pm", "pm.parametrize"),
    ],
)
def test_class_parametrize_and_mark_aliases_shadow_same_named_fixture(
    decorator_import, decorator
):
    conftest = (
        b"import pytest\n\n@pytest.fixture\ndef subject():\n"
        b"    from src.billing import invoice_total\n"
        b"    return invoice_total\n"
    )
    test = (
        f"{decorator_import}\n\n"
        f"@{decorator}('subject', [lambda: 2])\n"
        "class TestInvoice:\n"
        "    def test_invoice(self, subject):\n"
        "        assert subject() == 2\n"
    ).encode()
    assert _cross_file_fixture_shadow(
        "tests/conftest.py", conftest, "tests/test_billing.py", test
    ) == []


def test_if_not_true_branch_cannot_erase_a_live_import_binding():
    source = (
        b"from app import normalize\n"
        b"if not True:\n"
        b"    normalize = lambda value: value\n\n"
        b"def test_x():\n"
        b"    assert normalize('x') == 'x'\n"
    )
    assert "app.normalize" in _active_test_imports(source)


def test_already_winning_provider_ignores_suffix_match_outside_search_plan():
    before = b"VALUE = 'same'\n"
    after = b"VALUE = 'changed'\n"
    paths = {
        "app/value.py",
        "src/app/value.py",
        "vendor/app/value.py",
    }
    assert _changed_provider(
        "app.value",
        SearchPlan("runner", ("", "src"), ("", "src")),
        paths,
        paths,
        {
            "app/value.py": after,
            "src/app/value.py": b"VALUE = 'canonical'\n",
            "vendor/app/value.py": before,
        },
        added_paths=set(),
        semantic_paths={"app/value.py"},
        before_contents={
            "app/value.py": before,
            "src/app/value.py": b"VALUE = 'canonical'\n",
            "vendor/app/value.py": before,
        },
        allow_equivalent=True,
    ) is None


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (
            b"#!/bin/sh\nPYTHONPATH=src pytest tests/a\n",
            (
                b"#!/bin/sh\n"
                b"PYTHONPATH=src pytest tests/c\n"
                b"PYTHONPATH=standins:src pytest tests/a\n"
            ),
        ),
        (
            (
                b"#!/bin/sh\n"
                b"PYTHONPATH=src pytest tests/a\n"
                b"PYTHONPATH=src pytest tests/b\n"
            ),
            (
                b"#!/bin/sh\n"
                b"PYTHONPATH=src pytest tests/b\n"
                b"PYTHONPATH=standins:src pytest tests/a\n"
            ),
        ),
        (
            b"#!/bin/sh\nPYTHONPATH=src pytest tests/a\n",
            (
                b"#!/bin/sh\n"
                b"PYTHONPATH=src pytest tests/a\n"
                b"PYTHONPATH=standins:src pytest tests/a\n"
            ),
        ),
        (
            b"#!/bin/sh\nPYTHONPATH=src pytest tests/a\n",
            b"#!/bin/sh\nPYTHONPATH=standins:src pytest tests/a\n",
        ),
    ],
    ids=("prepend", "reorder", "duplicate", "changed-pythonpath"),
)
def test_runner_invocations_align_by_oracle_scope_not_position(before, after):
    sources = _runner_matrix_sources(after)
    hits = find_runtime_subject_shadows(
        [FileChange("scripts/test.sh", "modified", before, after)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert [(hit.module, hit.test_path) for hit in hits] == [
        ("alpha.value", "tests/a/test_alpha.py")
    ]


def test_targetless_explicit_runner_discovers_config_from_repository_cwd():
    runner = b"#!/bin/sh\npytest\n"
    sources = {
        "src/app/value.py": b"VALUE = 'prod'\n",
        "standins/app/value.py": b"VALUE = 'shadow'\n",
        "tests/a/test_value.py": (
            b"from app.value import VALUE\n\n"
            b"def test_value():\n    assert VALUE == 'prod'\n"
        ),
        "pytest.ini": b"[pytest]\npythonpath = src\n",
        "tests/a/pytest.ini": b"[pytest]\npythonpath = ../../standins ../../src\n",
        "scripts/test.sh": runner,
    }
    assert find_runtime_subject_shadows(
        [
            FileChange(
                "tests/a/pytest.ini",
                "modified",
                b"[pytest]\npythonpath = ../../src\n",
                sources["tests/a/pytest.ini"],
            )
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    ) == []


def test_shell_glob_target_expands_to_the_proven_test_scope():
    before = b"#!/bin/sh\nPYTHONPATH=src pytest tests/a/test_*.py\n"
    after = b"#!/bin/sh\nPYTHONPATH=standins:src pytest tests/a/test_*.py\n"
    sources = _runner_matrix_sources(after)
    hits = find_runtime_subject_shadows(
        [FileChange("scripts/test.sh", "modified", before, after)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert [(hit.module, hit.test_path) for hit in hits] == [
        ("alpha.value", "tests/a/test_alpha.py")
    ]


@pytest.mark.parametrize(
    ("before_target", "after_target"),
    [
        ("tests/a/test_alpha.py", "tests/a/test_*.py"),
        ("tests/a/test_*.py", "tests/a/test_alpha.py"),
    ],
    ids=("exact-to-glob", "glob-to-exact"),
)
def test_exact_and_equivalent_glob_runner_scopes_align_before_root_comparison(
    before_target, after_target
):
    before = (
        f"#!/bin/sh\nPYTHONPATH=src pytest {before_target}\n".encode()
    )
    after = (
        f"#!/bin/sh\nPYTHONPATH=standins pytest {after_target}\n".encode()
    )
    sources = _runner_matrix_sources(after)
    hits = find_runtime_subject_shadows(
        [FileChange("scripts/test.sh", "modified", before, after)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert [(hit.before_provider, hit.after_provider, hit.test_path) for hit in hits] == [
        (
            "src/alpha/value.py",
            "standins/alpha/value.py",
            "tests/a/test_alpha.py",
        )
    ]


def test_broad_glob_does_not_align_with_a_narrower_exact_scope():
    before = b"#!/bin/sh\nPYTHONPATH=src pytest tests/*/test_*.py\n"
    after = b"#!/bin/sh\nPYTHONPATH=standins pytest tests/a/test_alpha.py\n"
    sources = _runner_matrix_sources(after)
    assert find_runtime_subject_shadows(
        [FileChange("scripts/test.sh", "modified", before, after)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    ) == []


@pytest.mark.parametrize(
    "target",
    ["tests", "tests/*/test_*.py"],
    ids=("literal-directory", "same-broad-glob"),
)
def test_raw_identical_runner_scope_survives_an_unrelated_added_test(target):
    before_runner = f"#!/bin/sh\nPYTHONPATH=src pytest {target}\n".encode()
    after_runner = f"#!/bin/sh\nPYTHONPATH=standins pytest {target}\n".encode()
    unrelated = b"def test_unrelated():\n    assert True\n"
    sources = {
        "src/alpha/value.py": b"def value():\n    return 'prod-alpha'\n",
        "standins/alpha/value.py": b"def value():\n    return 'shadow-alpha'\n",
        "tests/a/test_alpha.py": (
            b"from alpha.value import value\n\n"
            b"def test_value():\n    assert value() == 'shadow-alpha'\n"
        ),
        "tests/c/test_unrelated.py": unrelated,
        "scripts/test.sh": after_runner,
    }
    hits = find_runtime_subject_shadows(
        [
            FileChange(
                "scripts/test.sh", "modified", before_runner, after_runner
            ),
            FileChange(
                "tests/c/test_unrelated.py", "added", None, unrelated
            ),
        ],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
    )
    assert [(hit.before_provider, hit.after_provider, hit.test_path) for hit in hits] == [
        (
            "src/alpha/value.py",
            "standins/alpha/value.py",
            "tests/a/test_alpha.py",
        )
    ]


@pytest.mark.parametrize("size", [200_000, 1_000_000])
def test_pathological_provider_source_key_is_bounded_and_fail_closed(size):
    payload = ("x = " + "+".join(["1"] * (size // 2)) + "\n").encode()
    changed = payload[:-2] + b"2\n"
    assert _source_key(payload) == _source_key(payload)
    assert _source_key(payload) != _source_key(changed)


def test_ordinary_huge_provider_source_key_remains_stable_and_sensitive():
    prefix = b"VALUES = [\n" + (b"    1,\n" * 20_000)
    before = prefix + b"    2,\n]\n"
    after = prefix + b"    3,\n]\n"
    assert len(before) > 100_000
    assert _source_key(before) == _source_key(before)
    assert _source_key(before) != _source_key(after)


def test_provider_source_key_fails_closed_on_an_ordinary_parse_error():
    before = b"def broken(:\n    pass\n"
    after = b"def broken(:\n    return 1\n"
    assert _source_key(before) == _source_key(before)
    assert _source_key(before) != _source_key(after)


def test_plain_modified_prod_returns_before_provider_fingerprinting(monkeypatch):
    def forbidden(_data):
        raise AssertionError("ordinary modified prod must stay on the lazy path")

    monkeypatch.setattr("checkwash.shadow._source_key", forbidden)
    assert find_runtime_subject_shadows(
        [FileChange("app/generated.py", "modified", b"x = 1\n", b"x = 2\n")],
        Config(),
    ) == []


def test_deleted_canonical_provider_can_expose_an_existing_standin():
    canonical = b"def value():\n    return 'prod-alpha'\n"
    runner = b"#!/bin/sh\nPYTHONPATH=src pytest tests/a\n"
    sources = {
        "alpha/value.py": b"def value():\n    return 'shadow-alpha'\n",
        "tests/a/test_alpha.py": (
            b"from alpha.value import value\n\n"
            b"def test_value():\n    assert value() == 'shadow-alpha'\n"
        ),
        "scripts/test.sh": runner,
    }
    hits = find_runtime_subject_shadows(
        [FileChange("src/alpha/value.py", "deleted", canonical, None)],
        Config(),
        head_path_lister=lambda: sorted(sources),
        head_batch_reader=lambda paths: {item: sources.get(item) for item in paths},
        head_searcher=lambda _needles: ["tests/a/test_alpha.py"],
    )
    assert [(hit.finding_path, hit.before_provider, hit.after_provider) for hit in hits] == [
        (
            "src/alpha/value.py",
            "src/alpha/value.py",
            "alpha/value.py",
        )
    ]
