"""Stand-in installation family: spelling x scope acceptance matrix (#91).

Issues #85, #88, and #91 are one operation with different surface syntax:
replace the first-party callable reached by an existing oracle with a stand-in.
The matrix keeps the operation, the execution scope, and the honest controls
separate so another spelling cannot silently become the next bypass.

``sys.modules`` replacement is covered where it can affect a later import.
Fixture and test-body cells use a literal runtime import after the swap; the
test-module cell puts the swap before its import. Separate controls pin the
already-captured-binding cases as non-operative. Dynamic import targets and
path-dependent import order remain named residuals.
"""

from __future__ import annotations

import ast
import datetime
import textwrap

import pytest

import checkwash.frontends.python.frontend as python_frontend
from checkwash.cli import (
    _contained_regular_worktree_path,
    _search_worktree_duplicate_paths,
    _search_worktree_paths,
)
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.detectors.test_patches import detect as detect_test_patches
from checkwash.engine import (
    EngineError,
    FileChange,
    _safe_repo_path,
    _standin_module_paths,
    analyze,
)
from checkwash.findings import make_fingerprint
from checkwash.frontends.python.frontend import parse_python
from checkwash.gitio.git import GitError, grep_head_paths, head_path_exists
from checkwash.ir.model import (
    Assertion,
    DiffGlobals,
    FileIR,
    IR,
    Unit,
    UnitSide,
    to_jsonable,
)
from checkwash.pyenv import known_baseline
from checkwash.standins import StandinInstall

TODAY = datetime.date(2026, 1, 1)

PRELUDE = """\
import sys
import types
from unittest import mock

import pytest
from app import billing


def _reference(items, tax):
    return 105.3


_standin_module = types.ModuleType("app.billing")
_standin_module.invoice_total = _reference
_mp = pytest.MonkeyPatch()
"""

SYS_MODULES_PRELUDE = """\
import sys
import types


def _reference(items, tax):
    return 105.3


_standin_module = types.ModuleType("app.billing")
_standin_module.invoice_total = _reference
"""

REACHING_TEST = """\
from app import billing


def test_total():
    result = billing.invoice_total([10.0, 90.0], 0.053)
    assert result == 105.3
"""

RUNTIME_REACHING_TEST = """\
import importlib


def test_total():
    billing = importlib.import_module("app.billing")
    assert billing.invoice_total([10.0, 90.0], 0.053) == 105.3
"""

UNREACHED_TEST = """\
from app import billing


def test_currency():
    assert billing.currency_symbol() == "$"
"""

UNREACHED_MODULE_TEST = """\
from app import profile


def test_display_name():
    assert profile.display_name("Ada") == "Ada"
"""

SPELLINGS = {
    "attribute": "billing.invoice_total = _reference",
    "builtin_setattr": 'setattr(billing, "invoice_total", _reference)',
    "vars_mapping": 'vars(billing)["invoice_total"] = _reference',
    "dict_mapping": 'billing.__dict__["invoice_total"] = _reference',
    "monkeypatch_setattr": '_mp.setattr(billing, "invoice_total", _reference)',
    "monkeypatch_setitem": (
        '_mp.setitem(vars(billing), "invoice_total", _reference)'
    ),
    "patch_object": 'mock.patch.object(billing, "invoice_total", _reference).start()',
    "patch_string": (
        'mock.patch("app.billing.invoice_total", _reference).start()'
    ),
    "sys_modules": 'sys.modules["app.billing"] = _standin_module',
}

SCOPES = (
    "root_conftest_module",
    "tests_conftest_module",
    "root_conftest_fixture",
    "tests_conftest_fixture",
    "root_conftest_hook",
    "tests_conftest_hook",
    "test_module",
    "test_fixture",
    "test_body",
)


def _indent(line: str, amount: int = 4) -> str:
    return " " * amount + line


def _source(
    scope: str, install: str | None, *, spelling: str | None = None
) -> tuple[str, str]:
    """Return ``(path, source)`` for one matrix side."""
    module_swap = spelling == "sys_modules"
    prelude = SYS_MODULES_PRELUDE if module_swap else PRELUDE
    if scope in ("root_conftest_module", "tests_conftest_module"):
        path = "conftest.py" if "root" in scope else "tests/conftest.py"
        tail = f"\n{install}\n" if install else "\n"
        return path, prelude + tail
    if scope in ("root_conftest_fixture", "tests_conftest_fixture"):
        body = [_indent(install)] if install else []
        body.append("    yield")
        return (
            "conftest.py" if "root" in scope else "tests/conftest.py",
            prelude
            + ("\nimport pytest\n" if module_swap else "")
            + "\n@pytest.fixture(autouse=True)\n"
            + "def _subject_adapter():\n"
            + "\n".join(body)
            + "\n",
        )
    if scope in ("root_conftest_hook", "tests_conftest_hook"):
        body = _indent(install) if install else "    pass"
        return (
            "conftest.py" if "root" in scope else "tests/conftest.py",
            prelude + "\ndef pytest_sessionstart(session):\n" + body + "\n",
        )
    if scope == "test_module":
        if module_swap:
            installed = f"{install}\n" if install else ""
            return (
                "tests/test_billing.py",
                prelude
                + "\n"
                + installed
                + "from app.billing import invoice_total\n\n"
                + "def test_invoice_total():\n"
                + "    assert invoice_total([], 0) == 105.3\n",
            )
        tail = f"\n{install}\n" if install else "\n"
        return (
            "tests/test_billing.py",
            prelude
            + tail
            + "\ndef test_invoice_total():\n"
            + "    assert billing.invoice_total([], 0) == 105.3\n",
        )
    if scope == "test_fixture":
        body = [_indent(install)] if install else []
        body.append("    yield")
        if module_swap:
            oracle = (
                "\ndef test_invoice_total():\n"
                '    billing = importlib.import_module("app.billing")\n'
                "    assert billing.invoice_total([], 0) == 105.3\n"
            )
            prelude += "\nimport importlib\nimport pytest\n"
        else:
            oracle = (
                "\ndef test_invoice_total():\n"
                "    assert billing.invoice_total([], 0) == 105.3\n"
            )
        return (
            "tests/test_billing.py",
            prelude
            + "\n@pytest.fixture(autouse=True)\n"
            + "def _subject_adapter():\n"
            + "\n".join(body)
            + "\n"
            + oracle,
        )
    if scope == "test_body":
        body = [_indent(install)] if install else []
        if module_swap:
            prelude += "\nimport importlib\n"
            body.append('    billing = importlib.import_module("app.billing")')
        body.append("    assert billing.invoice_total([], 0) == 105.3")
        return (
            "tests/test_billing.py",
            prelude + "\ndef test_invoice_total():\n" + "\n".join(body) + "\n",
        )
    raise AssertionError(scope)


def _run(
    path: str,
    before: str | None,
    after: str,
    *,
    third_party: set[str] | None = None,
    owned_modules: set[str] | None = None,
    head: dict[str, str] | None = None,
    unreadable: set[str] | None = None,
    existing: set[str] | None = None,
):
    known = known_baseline() | {"app", "pytest"} | set(third_party or ())
    if head is None and path.endswith("conftest.py"):
        head = {"tests/test_billing.py": REACHING_TEST}
    encoded_head = {
        candidate: source.encode("utf-8") for candidate, source in (head or {}).items()
    }

    def read_head(candidate: str) -> bytes | None:
        if candidate in (unreadable or set()):
            return None
        return encoded_head.get(candidate)

    analyze_kwargs = {}
    if encoded_head or existing is not None:
        existing_paths = set(encoded_head) if existing is None else existing
        analyze_kwargs["head_exists"] = (
            lambda candidate: candidate in existing_paths
        )

    _ir, findings, verdict = analyze(
        [
            FileChange(
                path=path,
                status="added" if before is None else "modified",
                before=before.encode("utf-8") if before is not None else None,
                after=after.encode("utf-8"),
            )
        ],
        Config(),
        Contract(),
        [],
        TODAY,
        known_modules=known,
        self_modules={"app"} if owned_modules is None else owned_modules,
        head_reader=read_head if encoded_head else None,
        head_searcher=(
            lambda needles: [
                candidate
                for candidate, data in sorted(encoded_head.items())
                if any(needle.encode("utf-8") in data for needle in needles)
            ]
        )
        if encoded_head
        else None,
        **analyze_kwargs,
    )
    return verdict, [f for f in findings if not f.allowlisted]


CELLS = [(spelling, scope) for spelling in SPELLINGS for scope in SCOPES]


@pytest.mark.parametrize("spelling,scope", CELLS, ids=lambda value: value)
def test_spelling_scope_matrix(spelling: str, scope: str):
    install = SPELLINGS[spelling]
    path, before = _source(scope, None, spelling=spelling)
    _, after = _source(scope, install, spelling=spelling)
    head = (
        {"tests/test_billing.py": RUNTIME_REACHING_TEST}
        if spelling == "sys_modules" and "conftest" in scope
        else None
    )
    verdict, findings = _run(path, before, after, head=head)
    expected_rule = (
        "TEST_PATCHES_SUBJECT"
        if scope.startswith("test_")
        else "CONFTEST_PATCHES_PROD"
    )
    hits = [f for f in findings if f.rule == expected_rule]
    assert len(hits) == 1, (
        f"{spelling} x {scope}: stand-in missed; "
        f"verdict={verdict}, findings={[f.rule for f in findings]}"
    )
    assert hits[0].severity == "high"
    assert "NO_PROD_CHANGE_IN_DIFF" in hits[0].escalators
    assert verdict == "block"

CONFTEST_SCOPES = [scope for scope in SCOPES if "conftest" in scope]


@pytest.mark.parametrize(
    "spelling,scope",
    [(spelling, scope) for spelling in SPELLINGS for scope in CONFTEST_SCOPES],
    ids=lambda value: value,
)
def test_conftest_install_requires_an_oracle_reaching_the_same_target(
    spelling: str, scope: str
):
    """A first-party assignment alone is not enough to block a conftest.

    The target and scope are identical to the positive matrix.  Only the
    unchanged test oracle differs: it reaches another attribute of the same
    first-party module.
    """
    path, before = _source(scope, None, spelling=spelling)
    _, after = _source(scope, SPELLINGS[spelling], spelling=spelling)
    verdict, findings = _run(
        path,
        before,
        after,
        head={
            "tests/test_billing.py": (
                UNREACHED_MODULE_TEST if spelling == "sys_modules" else UNREACHED_TEST
            )
        },
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert not hits, (spelling, scope, [f.rule for f in findings])
    assert verdict == "pass", (spelling, scope, verdict, [f.rule for f in findings])


@pytest.mark.parametrize("scope", ["test_module", "test_fixture", "test_body"])
def test_imported_subject_binding_replaced(scope: str):
    """Issue #88 plus the same binding replacement at enclosing scopes."""
    prelude = """\
import pytest
from app.billing import invoice_total


def _reference(items, tax):
    return 105.3
"""
    if scope == "test_module":
        before = prelude + "\n\ndef test_total():\n    assert invoice_total([], 0) == 105.3\n"
        after = prelude + "\ninvoice_total = _reference\n\ndef test_total():\n    assert invoice_total([], 0) == 105.3\n"
    elif scope == "test_fixture":
        before_fixture = "\n@pytest.fixture(autouse=True)\ndef adapter():\n    yield\n"
        after_fixture = (
            "\n@pytest.fixture(autouse=True)\ndef adapter():\n"
            "    global invoice_total\n"
            "    invoice_total = _reference\n"
            "    yield\n"
        )
        tail = "\n\ndef test_total():\n    assert invoice_total([], 0) == 105.3\n"
        before, after = prelude + before_fixture + tail, prelude + after_fixture + tail
    else:
        before = prelude + "\n\ndef test_total():\n    assert invoice_total([], 0) == 105.3\n"
        after = (
            prelude
            + "\n\ndef test_total():\n"
            + "    invoice_total = _reference\n"
            + "    assert invoice_total([], 0) == 105.3\n"
        )

    verdict, findings = _run("tests/test_billing.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (scope, verdict, [f.rule for f in findings])
    assert hits[0].severity == "high"
    assert verdict == "block"


NEGATIVE_SOURCES = {
    "stdlib": (
        "import time\n\ndef test_clock():\n    assert time.time() > 0\n",
        "import time\n\ndef test_clock():\n    time.time = lambda: 1\n    assert time.time() > 0\n",
        set(),
    ),
    "third_party": (
        "import requests\n\ndef test_http():\n    assert requests.get(\"https://example.test\").ok\n",
        "import requests\n\ndef test_http():\n    requests.get = lambda *_: object()\n    assert requests.get(\"https://example.test\").ok\n",
        {"requests"},
    ),
    "local_object": (
        "class Client:\n    def send(self):\n        return True\n\ndef test_client():\n    client = Client()\n    assert client.send()\n",
        "class Client:\n    def send(self):\n        return True\n\ndef test_client():\n    client = Client()\n    client.send = lambda: True\n    assert client.send()\n",
        set(),
    ),
    "unreached_first_party": (
        "from app import billing\n\ndef test_total():\n    assert billing.invoice_total([], 0) == 105.3\n",
        "from app import billing\n\ndef test_total():\n    billing.RETRY_DELAY = 0\n    assert billing.invoice_total([], 0) == 105.3\n",
        set(),
    ),
    "self_assignment": (
        "from app import billing\n\ndef test_total():\n    assert billing.invoice_total([], 0) == 105.3\n",
        "from app import billing\n\ndef test_total():\n    billing.invoice_total = billing.invoice_total\n    assert billing.invoice_total([], 0) == 105.3\n",
        set(),
    ),
}


@pytest.mark.parametrize("control", sorted(NEGATIVE_SOURCES))
def test_honest_and_non_subject_controls_stay_silent(control: str):
    before, after, third_party = NEGATIVE_SOURCES[control]
    verdict, findings = _run(
        "tests/test_control.py",
        textwrap.dedent(before),
        textwrap.dedent(after),
        third_party=third_party,
    )
    hits = [
        f
        for f in findings
        if f.rule in {"TEST_PATCHES_SUBJECT", "CONFTEST_PATCHES_PROD"}
    ]
    assert not hits, (control, [f.rule for f in findings])
    assert verdict == "pass", (control, verdict, [f.rule for f in findings])


def test_spelling_change_for_same_existing_install_is_not_a_new_standin():
    """Newness is semantic target identity, not surface spelling."""
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        + '    _mp.setattr(billing, "invoice_total", _reference)\n'
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = (
        PRELUDE
        + "\ndef test_total():\n"
        + "    billing.invoice_total = _reference\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run("tests/test_control.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, [f.rule for f in findings]
    assert verdict == "pass", (verdict, [f.rule for f in findings])


@pytest.mark.parametrize(
    "target,third_party",
    [
        ("time", set()),
        ("requests", {"requests"}),
    ],
)
def test_conftest_dependency_stubs_stay_silent(target: str, third_party: set[str]):
    imports = "import time\n" if target == "time" else "import requests\n"
    attr = "sleep" if target == "time" else "get"
    before = imports
    after = imports + f'{target}.{attr} = lambda *a, **k: None\n'
    verdict, findings = _run(
        "conftest.py", before, after, third_party=third_party
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert not hits, (target, [f.rule for f in findings])
    assert verdict == "pass", (target, verdict, [f.rule for f in findings])


@pytest.mark.parametrize(
    "import_line,subject",
    [
        ("from app import billing as ledger", "ledger.invoice_total"),
        ("import app.billing as ledger", "ledger.invoice_total"),
        ("from app.billing import invoice_total as total", "total"),
        ("from . import billing", "billing.invoice_total"),
    ],
)
def test_alias_and_imported_binding_resolve_to_the_canonical_subject(
    import_line: str, subject: str
):
    before = (
        f"{import_line}\n\n"
        "def _reference(items, tax):\n"
        "    return 105.3\n\n"
        "def test_total():\n"
        f"    assert {subject}([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n",
        f"def test_total():\n    {subject} = _reference\n",
    )
    verdict, findings = _run("tests/test_alias.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (import_line, verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize("requested", [False, True])
def test_non_autouse_conftest_fixture_only_applies_when_requested(requested: bool):
    before = (
        PRELUDE
        + "\n@pytest.fixture\n"
        + "def subject_adapter():\n"
        + "    yield\n"
    )
    after = before.replace(
        "def subject_adapter():\n",
        "def subject_adapter():\n"
        '    setattr(billing, "invoice_total", _reference)\n',
    )
    params = "subject_adapter" if requested else ""
    head = {
        "tests/test_billing.py": (
            "from app import billing\n\n"
            f"def test_total({params}):\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    }
    verdict, findings = _run(
        "tests/conftest.py", before, after, head=head
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert bool(hits) is requested, (requested, verdict, [f.rule for f in findings])
    assert verdict == ("block" if requested else "pass")


@pytest.mark.parametrize(
    "request_style,expected",
    [
        ("parameter_dependency", True),
        ("usefixtures", True),
        ("autouse_dependency", True),
        ("unrequested_dependency", False),
    ],
)
def test_conftest_fixture_dependency_closure_controls_installation(
    request_style: str, expected: bool
):
    """Only an active path through pytest's fixture graph runs the install."""
    autouse = request_style == "autouse_dependency"
    before = (
        PRELUDE
        + "\n@pytest.fixture\n"
        + "def standin(monkeypatch):\n"
        + "    yield\n\n"
        + ("@pytest.fixture(autouse=True)\n" if autouse else "@pytest.fixture\n")
        + "def adapter(standin):\n"
        + "    return None\n"
    )
    after = before.replace(
        "def standin(monkeypatch):\n",
        "def standin(monkeypatch):\n"
        '    monkeypatch.setattr(billing, "invoice_total", _reference)\n',
    )
    if request_style == "parameter_dependency":
        decorator, parameter = "", "adapter"
    elif request_style == "usefixtures":
        decorator, parameter = '@pytest.mark.usefixtures("adapter")\n', ""
    else:
        decorator, parameter = "", ""
    head = {
        "tests/test_billing.py": (
            "import pytest\n"
            "from app import billing\n\n"
            f"{decorator}"
            f"def test_total({parameter}):\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    }
    verdict, findings = _run("tests/conftest.py", before, after, head=head)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert bool(hits) is expected, (
        request_style,
        verdict,
        [f.rule for f in findings],
    )
    assert verdict == ("block" if expected else "pass")


def test_same_file_fixture_dependency_reaches_existing_test_unit():
    before = (
        PRELUDE
        + "\n@pytest.fixture\n"
        + "def standin(monkeypatch):\n"
        + "    yield\n\n"
        + "@pytest.fixture\n"
        + "def adapter(standin):\n"
        + "    return None\n\n"
        + "def test_total(adapter):\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def standin(monkeypatch):\n",
        "def standin(monkeypatch):\n"
        '    monkeypatch.setattr(billing, "invoice_total", _reference)\n',
    )
    verdict, findings = _run("tests/test_fixture_dependency.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_test_fixture_imported_binding_without_global_is_only_a_local():
    before = """\
import pytest
from app.billing import invoice_total


def _reference(items, tax):
    return 105.3


@pytest.fixture(autouse=True)
def adapter():
    yield


def test_total():
    assert invoice_total([], 0) == 105.3
"""
    after = before.replace(
        "def adapter():\n",
        "def adapter():\n    invoice_total = _reference\n",
    )
    verdict, findings = _run("tests/test_fixture_local.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, [f.rule for f in findings]
    assert verdict == "pass"


@pytest.mark.parametrize("global_binding", [False, True])
def test_conftest_imported_binding_never_rebinds_the_consumer_module(
    global_binding: bool,
):
    before = """\
import pytest
from app.billing import invoice_total


def _reference(items, tax):
    return 105.3


@pytest.fixture(autouse=True)
def adapter():
    yield
"""
    declaration = "    global invoice_total\n" if global_binding else ""
    after = before.replace(
        "def adapter():\n",
        "def adapter():\n"
        + declaration
        + "    invoice_total = _reference\n",
    )
    head = {
        "tests/test_billing.py": (
            "from app.billing import invoice_total\n\n"
            "def test_total():\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    }
    verdict, findings = _run("tests/conftest.py", before, after, head=head)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert not hits, (global_binding, [f.rule for f in findings])
    assert verdict == "pass"


def test_patch_object_create_true_is_still_a_structured_install():
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n",
        "def test_total():\n"
        '    mock.patch.object(billing, "invoice_total", _reference, create=True).start()\n',
    )
    verdict, findings = _run("tests/test_create.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "operation",
    [
        'monkeypatch.delitem(vars(billing), "invoice_total", raising=False)',
        'monkeypatch.setattr(billing, "invoice_total", billing.invoice_total)',
        'monkeypatch.setitem(vars(billing), "invoice_total", billing.invoice_total)',
        'mock.patch.object(billing, "invoice_total", lambda *_: 105.3)',
    ],
)
def test_delete_and_restore_operations_are_not_standin_installs(operation: str):
    before = (
        "from unittest import mock\n\n"
        "from app import billing\n\n"
        "def test_total(monkeypatch):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total(monkeypatch):\n",
        f"def test_total(monkeypatch):\n    {operation}\n",
    )
    verdict, findings = _run("tests/test_restore.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (operation, [f.rule for f in findings])
    assert verdict == "pass", (operation, verdict, [f.rule for f in findings])


@pytest.mark.parametrize(
    "import_line,third_party",
    [
        ("import time as billing", set()),
        ("import requests as billing", {"requests"}),
    ],
)
def test_same_local_and_attribute_names_do_not_make_external_code_first_party(
    import_line: str, third_party: set[str]
):
    before = (
        f"{import_line}\n\n"
        "def test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n",
        "def test_total():\n    billing.invoice_total = lambda *_: 105.3\n",
    )
    verdict, findings = _run(
        "tests/test_external.py", before, after, third_party=third_party
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (import_line, [f.rule for f in findings])
    assert verdict == "pass", (import_line, verdict, [f.rule for f in findings])


@pytest.mark.parametrize(
    "imports,install,expected",
    [
        (
            "import app.billing\nfrom app import billing",
            "app.billing.invoice_total = _reference",
            True,
        ),
        (
            "import importlib\nfrom app import billing",
            'setattr(importlib.import_module("app.billing"), "invoice_total", _reference)',
            True,
        ),
        (
            "from app import billing",
            'setattr(_resolve("app.billing"), "invoice_total", _reference)',
            False,
        ),
    ],
)
def test_static_attribute_chains_are_supported_but_dynamic_targets_are_residual(
    imports: str, install: str, expected: bool
):
    before = (
        f"{imports}\n\n"
        "def _reference(items, tax):\n"
        "    return 105.3\n\n"
        "def _resolve(name):\n"
        "    return billing\n\n"
        "def test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n", f"def test_total():\n    {install}\n"
    )
    verdict, findings = _run("tests/test_target_shape.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (install, verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize("has_reaching_oracle", [False, True])
def test_conftest_oracle_inventory_is_not_a_silent_sixteen_file_prefix(
    has_reaching_oracle: bool,
):
    path, before = _source("root_conftest_module", None, spelling="attribute")
    _, after = _source(
        "root_conftest_module", SPELLINGS["attribute"], spelling="attribute"
    )
    noise = (
        "from app import profile\n\n"
        'SEARCH_DECOY = "invoice_total"\n\n'
        "def test_profile():\n"
        '    assert profile.display_name("Ada") == "Ada"\n'
    )
    head = {
        f"tests/test_a{index:02d}_noise.py": noise
        for index in range(17 if has_reaching_oracle else 18)
    }
    if has_reaching_oracle:
        head["tests/test_zz_reaching_oracle.py"] = REACHING_TEST
    verdict, findings = _run(path, before, after, head=head)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert bool(hits) is has_reaching_oracle, (
        has_reaching_oracle,
        verdict,
        [f.rule for f in findings],
    )
    assert verdict == ("block" if has_reaching_oracle else "pass")


@pytest.mark.parametrize(
    "hook,spelling,expected",
    [
        ("pytest_sessionstart", "attribute", True),
        ("pytest_runtest_setup", "attribute", True),
        ("pytest_sessionfinish", "attribute", False),
        ("pytest_sessionstart", "sys_modules", True),
        ("pytest_runtest_setup", "sys_modules", False),
        ("pytest_sessionfinish", "sys_modules", False),
    ],
)
def test_pytest_hook_lifecycle_controls_live_installation(
    hook: str, spelling: str, expected: bool
):
    prelude = SYS_MODULES_PRELUDE if spelling == "sys_modules" else PRELUDE
    argument = "session" if hook != "pytest_runtest_setup" else "item"
    before = prelude + f"\ndef {hook}({argument}):\n    pass\n"
    after = (
        prelude
        + f"\ndef {hook}({argument}):\n"
        + _indent(SPELLINGS[spelling])
        + "\n"
    )
    verdict, findings = _run("conftest.py", before, after)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert bool(hits) is expected, (hook, spelling, verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


def test_runtest_setup_module_swap_reaches_a_later_runtime_import():
    before = SYS_MODULES_PRELUDE + "\ndef pytest_runtest_setup(item):\n    pass\n"
    after = (
        SYS_MODULES_PRELUDE
        + "\ndef pytest_runtest_setup(item):\n"
        + _indent(SPELLINGS["sys_modules"])
        + "\n"
    )
    runtime_test = (
        "import importlib\n\n"
        "def test_total():\n"
        '    billing = importlib.import_module("app.billing")\n'
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "conftest.py",
        before,
        after,
        head={"tests/test_billing.py": runtime_test},
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize("scope", ["test", "fixture"])
def test_explicit_original_restore_before_oracle_cancels_the_install(scope: str):
    if scope == "test":
        before = (
            PRELUDE
            + "\ndef test_total():\n"
            + "    assert billing.invoice_total([], 0) == 105.3\n"
        )
        after = before.replace(
            "def test_total():\n",
            "def test_total():\n"
            "    original = billing.invoice_total\n"
            "    billing.invoice_total = _reference\n"
            "    billing.invoice_total = original\n",
        )
        path, head = "tests/test_restore_order.py", None
        rule = "TEST_PATCHES_SUBJECT"
    else:
        before = (
            PRELUDE
            + "\n@pytest.fixture(autouse=True)\n"
            + "def adapter():\n"
            + "    yield\n"
        )
        after = before.replace(
            "def adapter():\n",
            "def adapter():\n"
            "    original = billing.invoice_total\n"
            "    billing.invoice_total = _reference\n"
            "    billing.invoice_total = original\n",
        )
        path, head = "tests/conftest.py", {"tests/test_billing.py": REACHING_TEST}
        rule = "CONFTEST_PATCHES_PROD"
    verdict, findings = _run(path, before, after, head=head)
    hits = [f for f in findings if f.rule == rule]
    assert not hits, (scope, [f.rule for f in findings])
    assert verdict == "pass"


def test_moving_an_existing_restore_after_an_existing_oracle_expands_reach():
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        + "    original = billing.invoice_total\n"
        + "    billing.invoice_total = _reference\n"
        + "    billing.invoice_total = original\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    billing.invoice_total = original\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    assert billing.invoice_total([], 0) == 105.3\n"
        "    billing.invoice_total = original\n",
    )

    verdict, findings = _run("tests/test_restore_window.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "scope,live",
    [("test", False), ("test", True), ("fixture", False), ("fixture", True)],
)
def test_patch_context_must_still_be_entered_when_the_oracle_runs(
    scope: str, live: bool
):
    if scope == "test":
        inner = (
            "        assert billing.invoice_total([], 0) == 105.3\n"
            if live
            else "        pass\n"
        )
        after_test = "" if live else "    assert billing.invoice_total([], 0) == 105.3\n"
        before = (
            PRELUDE
            + "\ndef test_total():\n"
            + "    assert billing.invoice_total([], 0) == 105.3\n"
        )
        after = (
            PRELUDE
            + "\ndef test_total():\n"
            + '    with mock.patch.object(billing, "invoice_total", _reference, create=True):\n'
            + inner
            + after_test
        )
        path, head, rule = "tests/test_patch_context.py", None, "TEST_PATCHES_SUBJECT"
    else:
        body = "        yield\n" if live else "        pass\n    yield\n"
        before = (
            PRELUDE
            + "\n@pytest.fixture(autouse=True)\n"
            + "def adapter():\n"
            + "    yield\n"
        )
        after = (
            PRELUDE
            + "\n@pytest.fixture(autouse=True)\n"
            + "def adapter():\n"
            + '    with mock.patch.object(billing, "invoice_total", _reference, create=True):\n'
            + body
        )
        path = "tests/conftest.py"
        head = {"tests/test_billing.py": REACHING_TEST}
        rule = "CONFTEST_PATCHES_PROD"
    verdict, findings = _run(path, before, after, head=head)
    hits = [f for f in findings if f.rule == rule]
    assert bool(hits) is live, (scope, live, verdict, [f.rule for f in findings])
    assert verdict == ("block" if live else "pass")


@pytest.mark.parametrize(
    "scope,timing,expected",
    [
        ("fixture", "after", True),
        ("same_file_fixture", "after", True),
        ("test", "after", True),
        ("test", "before", False),
        ("test", "before_with_unused_after", False),
    ],
)
def test_sys_modules_install_depends_on_runtime_import_order(
    scope: str, timing: str, expected: bool
):
    """A late literal import is operative; an already captured object is not."""
    conftest_before = (
        SYS_MODULES_PRELUDE
        + "\nimport pytest\n\n@pytest.fixture(autouse=True)\n"
        + "def standin_module():\n"
        + "    yield\n"
    )
    conftest_after = conftest_before.replace(
        "def standin_module():\n",
        "def standin_module():\n"
        '    sys.modules["app.billing"] = _standin_module\n',
    )
    runtime_test = (
        "import importlib\n\n"
        "def test_total():\n"
        '    billing = importlib.import_module("app.billing")\n'
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    if scope == "fixture":
        path, before, after, head = (
            "tests/conftest.py",
            conftest_before,
            conftest_after,
            {"tests/test_billing.py": runtime_test},
        )
        rule = "CONFTEST_PATCHES_PROD"
    elif scope == "same_file_fixture":
        before = (
            SYS_MODULES_PRELUDE
            + "\nimport importlib\nimport pytest\n"
            + "\n@pytest.fixture(autouse=True)\n"
            + "def standin_module():\n"
            + "    yield\n"
            + "\ndef test_total():\n"
            + '    billing = importlib.import_module("app.billing")\n'
            + "    assert billing.invoice_total([], 0) == 105.3\n"
        )
        after = before.replace(
            "def standin_module():\n",
            "def standin_module():\n"
            '    sys.modules["app.billing"] = _standin_module\n',
        )
        path, head, rule = (
            "tests/test_runtime_fixture_import.py",
            None,
            "TEST_PATCHES_SUBJECT",
        )
    else:
        prelude = SYS_MODULES_PRELUDE + "\nimport importlib\n"
        before = (
            prelude
            + "\ndef test_total():\n"
            + '    billing = importlib.import_module("app.billing")\n'
            + "    assert billing.invoice_total([], 0) == 105.3\n"
        )
        if timing == "after":
            after_body = (
                '    sys.modules["app.billing"] = _standin_module\n'
                '    billing = importlib.import_module("app.billing")\n'
            )
        elif timing == "before":
            after_body = (
                '    billing = importlib.import_module("app.billing")\n'
                '    sys.modules["app.billing"] = _standin_module\n'
            )
        else:
            after_body = (
                '    billing = importlib.import_module("app.billing")\n'
                '    sys.modules["app.billing"] = _standin_module\n'
                '    unused = importlib.import_module("app.billing")\n'
            )
        after = (
            prelude
            + "\ndef test_total():\n"
            + after_body
            + "    assert billing.invoice_total([], 0) == 105.3\n"
        )
        path, head, rule = "tests/test_runtime_import.py", None, "TEST_PATCHES_SUBJECT"
    verdict, findings = _run(path, before, after, head=head)
    hits = [f for f in findings if f.rule == rule]
    assert bool(hits) is expected, (scope, timing, verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


def test_undeclared_import_root_is_unknown_and_does_not_block():
    """Absence from the external deny set is not repository ownership proof."""
    before = (
        "import vendor_unknown as billing\n\n"
        "def test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n",
        "def test_total():\n    billing.invoice_total = lambda *_: 105.3\n",
    )
    verdict, findings = _run("tests/test_unknown_owner.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (verdict, [f.rule for f in findings])
    assert verdict == "pass"


def test_readable_conventional_source_path_is_positive_ownership_evidence():
    before = (
        "import localpkg.billing as billing\n\n"
        "def test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n",
        "def test_total():\n    billing.invoice_total = lambda *_: 105.3\n",
    )
    verdict, findings = _run(
        "tests/test_local_owner.py",
        before,
        after,
        owned_modules=set(),
        head={"src/localpkg/billing.py": "def invoice_total(*args): return 105.3\n"},
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_searched_test_candidate_read_failure_is_an_engine_error():
    path, before = _source("root_conftest_module", None, spelling="attribute")
    _, after = _source(
        "root_conftest_module", SPELLINGS["attribute"], spelling="attribute"
    )
    candidate = "tests/test_billing.py"
    with pytest.raises(
        EngineError,
        match=r"head reader could not read searched test candidate: tests/test_billing\.py",
    ):
        _run(
            path,
            before,
            after,
            head={candidate: REACHING_TEST},
            unreadable={candidate},
        )


def test_worktree_search_returns_matches_beyond_sixty_four_paths(tmp_path):
    for index in range(67):
        path = tmp_path / "tests" / f"test_{index:02d}.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f'ORACLE = "invoice_total-{index}"\n', encoding="utf-8")
    hits = _search_worktree_paths(str(tmp_path), ["invoice_total"])
    assert len(hits) == 67
    assert "tests/test_66.py" in hits
    duplicate_hits = _search_worktree_duplicate_paths(
        str(tmp_path), ["invoice_total"]
    )
    assert len(duplicate_hits) == 64
    assert "tests/test_66.py" not in duplicate_hits


def test_worktree_search_finds_a_match_after_the_first_megabyte(tmp_path):
    path = tmp_path / "tests" / "test_late_oracle.py"
    path.parent.mkdir(parents=True)
    # Start five bytes before a 64 KiB boundary, after one MiB, so this also
    # pins the overlap needed for a fixed string split across two reads.
    path.write_bytes(b"x" * (64 * 1024 * 17 - 5) + b"invoice_total")
    assert _search_worktree_paths(str(tmp_path), ["invoice_total"]) == [
        "tests/test_late_oracle.py"
    ]
    assert _search_worktree_duplicate_paths(
        str(tmp_path), ["invoice_total"]
    ) == []


def test_worktree_ownership_reads_do_not_follow_file_symlinks(tmp_path):
    repo = tmp_path / "repo"
    link = repo / "src" / "app.py"
    link.parent.mkdir(parents=True)
    outside = tmp_path / "outside.py"
    outside.write_text("invoice_total = True\n", encoding="utf-8")
    try:
        link.symlink_to(outside)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    assert _contained_regular_worktree_path(str(repo), "src/app.py") is None
    assert _search_worktree_paths(str(repo), ["invoice_total"]) == []
    assert _search_worktree_duplicate_paths(str(repo), ["invoice_total"]) == []


def test_worktree_search_read_failure_is_an_engine_error(tmp_path, monkeypatch):
    path = tmp_path / "tests" / "test_unreadable.py"
    path.parent.mkdir(parents=True)
    path.write_text("invoice_total = True\n", encoding="utf-8")
    real_open = open

    def fail_target(candidate, *args, **kwargs):
        if str(candidate) == str(path):
            raise PermissionError("denied by test")
        return real_open(candidate, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fail_target)
    with pytest.raises(
        EngineError,
        match=r"could not read worktree search candidate: tests/test_unreadable\.py",
    ):
        _search_worktree_paths(str(tmp_path), ["invoice_total"])


def test_range_search_propagates_real_git_failures(monkeypatch):
    failure = GitError("fatal range failure", returncode=128)
    monkeypatch.setattr(
        "checkwash.gitio.git._run",
        lambda *_a, **_k: (_ for _ in ()).throw(failure),
    )
    with pytest.raises(GitError, match="fatal range failure"):
        grep_head_paths("repo", "bad-revision", ["invoice_total"])


def test_range_search_treats_git_exit_one_as_no_match(monkeypatch):
    no_match = GitError("no match", returncode=1)
    monkeypatch.setattr(
        "checkwash.gitio.git._run",
        lambda *_a, **_k: (_ for _ in ()).throw(no_match),
    )
    assert grep_head_paths("repo", "HEAD", ["invoice_total"]) == []


def test_worktree_walk_failure_is_an_engine_error(tmp_path, monkeypatch):
    def denied(_path):
        raise PermissionError("walk denied")

    monkeypatch.setattr("os.scandir", denied)
    with pytest.raises(EngineError, match="could not walk worktree search path"):
        _search_worktree_paths(str(tmp_path), ["invoice_total"])


def _fixture_install_source(name: str = "adapter", *, autouse: bool = False):
    marker = "(autouse=True)" if autouse else ""
    before = (
        PRELUDE
        + f"\n@pytest.fixture{marker}\n"
        + f"def {name}(monkeypatch):\n"
        + "    yield\n"
    )
    after = before.replace(
        f"def {name}(monkeypatch):\n",
        f"def {name}(monkeypatch):\n"
        '    monkeypatch.setattr(billing, "invoice_total", _reference)\n',
    )
    return before, after


@pytest.mark.parametrize("shadow", ["parametrize", "same_file", "nested_conftest"])
def test_nearest_fixture_provider_or_parametrize_shadows_conftest_install(shadow: str):
    before, after = _fixture_install_source()
    if shadow == "parametrize":
        test_source = (
            "import pytest\nfrom app import billing\n\n"
            '@pytest.mark.parametrize("adapter", [object()])\n'
            "def test_total(adapter):\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
        head = {"tests/test_billing.py": test_source}
    else:
        local_conftest = (
            "import pytest\n\n@pytest.fixture\ndef adapter():\n    return object()\n"
        )
        test_source = (
            "from app import billing\n\n"
            "def test_total(adapter):\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
        if shadow == "same_file":
            test_source = local_conftest + "\n" + test_source
            head = {"tests/test_billing.py": test_source}
        else:
            head = {
                "tests/sub/conftest.py": local_conftest,
                "tests/sub/test_billing.py": test_source,
            }
    verdict, findings = _run("conftest.py", before, after, head=head)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert not hits, (shadow, verdict, [f.rule for f in findings])
    assert verdict == "pass"


@pytest.mark.parametrize("indirect", ["True", '["adapter"]'])
def test_indirect_parametrize_still_requests_the_conftest_fixture(indirect: str):
    before, after = _fixture_install_source()
    test_source = (
        "import pytest\nfrom app import billing\n\n"
        f'@pytest.mark.parametrize("adapter", [object()], indirect={indirect})\n'
        "def test_total(adapter):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "conftest.py", before, after, head={"tests/test_billing.py": test_source}
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert len(hits) == 1, (indirect, verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_nested_autouse_fixture_can_activate_root_standin_dependency():
    before, after = _fixture_install_source("standin")
    head = {
        "tests/sub/conftest.py": (
            "import pytest\n\n"
            "@pytest.fixture(autouse=True)\n"
            "def adapter(standin):\n"
            "    return None\n"
        ),
        "tests/sub/test_billing.py": REACHING_TEST,
    }
    verdict, findings = _run("conftest.py", before, after, head=head)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "after",
    [
        PRELUDE + "\nif False:\n    billing.invoice_total = _reference\n",
        (
            PRELUDE
            + "\n@pytest.fixture(autouse=True)\n"
            + "def adapter():\n"
            + "    yield\n"
            + "    billing.invoice_total = _reference\n"
        ),
        (
            PRELUDE
            + "\n_original = billing.invoice_total\n"
            + "billing.invoice_total = _reference\n"
            + "billing.invoice_total = _original\n"
        ),
        PRELUDE + '\nvars(billing)["invoice_total"] = vars(billing)["invoice_total"]\n',
    ],
    ids=["dead_branch", "yield_teardown", "module_restore", "mapping_self_assignment"],
)
def test_non_live_conftest_installations_stay_silent(after: str):
    verdict, findings = _run("conftest.py", PRELUDE, after)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert not hits, (verdict, [f.rule for f in findings])
    assert verdict == "pass"


def test_patch_context_requires_subject_oracle_inside_same_lifetime():
    before = PRELUDE + "\ndef test_total():\n    assert billing.invoice_total([], 0) == 105.3\n"
    after = (
        PRELUDE
        + "\ndef test_total():\n"
        + '    with mock.patch.object(billing, "invoice_total", _reference):\n'
        + "        billing.invoice_total([], 0)\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run("tests/test_context_lifetime.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (verdict, [f.rule for f in findings])
    assert verdict == "pass"


def test_expanding_patch_context_to_persistent_start_is_a_new_reach():
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        '    with mock.patch.object(billing, "invoice_total", _reference):\n'
        "        assert billing.invoice_total([], 0) == 105.3\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = (
        PRELUDE
        + "\ndef test_total():\n"
        '    mock.patch.object(billing, "invoice_total", _reference).start()\n'
        "    assert billing.invoice_total([], 0) == 105.3\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run("tests/test_context_expansion.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_subject_reach_requires_module_and_attribute_on_same_chain():
    before = (
        "from app import billing\n"
        "from app.billing import invoice_total\n\n"
        "def test_currency():\n"
        "    assert billing.currency_symbol() == invoice_total\n"
    )
    after = before.replace(
        "def test_currency():\n",
        "def test_currency():\n    billing.invoice_total = lambda *_: 105.3\n",
    )
    verdict, findings = _run("tests/test_anchor.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (verdict, [f.rule for f in findings])
    assert verdict == "pass"


def test_relative_self_module_wins_over_stdlib_name_collision():
    before = (
        "from . import time\n\n"
        "def test_total():\n"
        "    assert time.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n",
        "def test_total():\n    time.invoice_total = lambda *_: 105.3\n",
    )
    verdict, findings = _run("tests/test_relative.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_conftest_fixture_scope_local_import_is_resolved():
    before = (
        "import pytest\n\ndef _reference(*args):\n    return 105.3\n\n"
        "@pytest.fixture(autouse=True)\n"
        "def adapter(monkeypatch):\n"
        "    yield\n"
    )
    after = before.replace(
        "def adapter(monkeypatch):\n",
        "def adapter(monkeypatch):\n"
        "    from app import billing\n"
        '    monkeypatch.setattr(billing, "invoice_total", _reference)\n',
    )
    local_import_oracle = (
        "def test_total():\n"
        "    from app import billing\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "conftest.py",
        before,
        after,
        head={"tests/test_billing.py": local_import_oracle},
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_test_scope_local_imported_binding_is_resolved():
    before = (
        "def _reference(*args):\n    return 105.3\n\n"
        "def test_total():\n"
        "    from app.billing import invoice_total\n"
        "    assert invoice_total([], 0) == 105.3\n"
        "\ndef unrelated_helper():\n"
        "    import time as invoice_total\n"
        "    return invoice_total.time()\n"
    )
    after = before.replace(
        "    assert invoice_total([], 0) == 105.3\n",
        "    invoice_total = _reference\n"
        "    assert invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_local_import.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"

    module_before = (
        "import importlib\n"
        "import sys\n"
        "import types\n"
        "from operator import setitem as put\n\n"
        "_fake = types.ModuleType('app.billing')\n"
        "_fake.invoice_total = lambda *_: 105.3\n\n"
        "def test_total():\n"
        "    billing = importlib.import_module('app.billing')\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    module_after = module_before.replace(
        "    billing = importlib.import_module('app.billing')\n",
        "    put(sys.modules, 'app.billing', _fake)\n"
        "    billing = importlib.import_module('app.billing')\n",
    )
    verdict, findings = _run(
        "tests/test_local_setitem_alias.py", module_before, module_after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize("before_yield,expected", [(True, True), (False, False)])
def test_runtest_call_hookwrapper_respects_yield_boundary(
    before_yield: bool, expected: bool
):
    before = (
        PRELUDE
        + "\n@pytest.hookimpl(hookwrapper=True)\n"
        + "def pytest_runtest_call(item):\n"
        + "    yield\n"
    )
    lines = (
        ['    billing.invoice_total = _reference', "    yield"]
        if before_yield
        else ["    yield", '    billing.invoice_total = _reference']
    )
    after = (
        PRELUDE
        + "\n@pytest.hookimpl(hookwrapper=True)\n"
        + "def pytest_runtest_call(item):\n"
        + "\n".join(lines)
        + "\n"
    )
    verdict, findings = _run("conftest.py", before, after)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert bool(hits) is expected, (
        before_yield,
        verdict,
        [f.rule for f in findings],
    )
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "pytest_import,decorator,carrier",
    [
        ("import pytest as pt", "@pt.fixture(autouse=True)", "adapter"),
        (
            "from pytest import fixture as fx",
            "@fx(autouse=True, name='adapter')",
            "fixture_carrier",
        ),
    ],
)
def test_fixture_registration_uses_definition_time_import_provenance(
    pytest_import: str, decorator: str, carrier: str
):
    before = (
        "from app import billing\n"
        + pytest_import
        + "\n\ndef _reference(*args):\n    return 105.3\n\n"
        + decorator
        + "\ndef "
        + carrier
        + "():\n    yield\n"
    )
    after = before.replace(
        "():\n    yield\n",
        "():\n    billing.invoice_total = _reference\n    yield\n",
    )
    verdict, findings = _run("tests/conftest.py", before, after)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "pytest_import,decorator,carrier",
    [
        ("import pytest as pt", "@pt.hookimpl", "pytest_runtest_setup"),
        (
            "from pytest import hookimpl as hi",
            "@hi(specname='pytest_runtest_setup')",
            "install_adapter",
        ),
    ],
)
def test_hook_registration_uses_alias_and_literal_specname(
    pytest_import: str, decorator: str, carrier: str
):
    before = (
        "from app import billing\n"
        + pytest_import
        + "\n\ndef _reference(*args):\n    return 105.3\n\n"
        + decorator
        + "\ndef "
        + carrier
        + "(item):\n    pass\n"
    )
    after = before.replace(
        "(item):\n    pass\n",
        "(item):\n    billing.invoice_total = _reference\n",
    )
    verdict, findings = _run("tests/conftest.py", before, after)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize("rebind_before,expected", [(False, True), (True, False)])
def test_fixture_alias_proof_is_taken_when_the_decorator_executes(
    rebind_before: bool, expected: bool
):
    fake = (
        "class FakePytest:\n"
        "    @staticmethod\n"
        "    def fixture(*args, **kwargs):\n"
        "        return lambda function: function\n\n"
    )
    imported = "import pytest as pt\n"
    rebind = "pt = FakePytest()\n"
    prefix = fake + imported + (rebind if rebind_before else "")
    suffix = "" if rebind_before else rebind
    before = (
        "from app import billing\n"
        "def _reference(*args):\n    return 105.3\n\n"
        + prefix
        + "@pt.fixture(autouse=True)\n"
        "def adapter():\n    yield\n"
        + suffix
    )
    after = before.replace(
        "def adapter():\n",
        "def adapter():\n    billing.invoice_total = _reference\n",
    )
    verdict, findings = _run("tests/conftest.py", before, after)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert bool(hits) is expected, (verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


def test_rebound_fixture_carrier_is_not_an_active_registration():
    before = (
        PRELUDE
        + "\n@pytest.fixture(autouse=True)\n"
        "def adapter():\n    yield\n"
        "adapter = lambda: None\n"
    )
    after = before.replace(
        "def adapter():\n",
        "def adapter():\n    billing.invoice_total = _reference\n",
    )
    verdict, findings = _run("tests/conftest.py", before, after)
    assert not [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert verdict == "pass"


@pytest.mark.parametrize(
    "install",
    [
        "mocker.patch('app.billing.invoice_total', _reference)",
        "mocker.patch.object(billing, 'invoice_total', _reference)",
    ],
)
def test_pytest_mocker_patch_is_an_immediate_test_install(install: str):
    before = (
        PRELUDE
        + "\ndef test_total(mocker):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        f"    {install}\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_mocker.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "install",
    [
        "mocker.patch('app.billing.invoice_total', _reference)",
        "mocker.patch.object(billing, 'invoice_total', _reference)",
    ],
)
def test_pytest_mocker_patch_is_an_immediate_fixture_install(install: str):
    before = (
        PRELUDE
        + "\n@pytest.fixture(autouse=True)\n"
        "def adapter(mocker):\n"
        "    yield\n"
    )
    after = before.replace(
        "    yield\n", f"    {install}\n    yield\n"
    )
    verdict, findings = _run("tests/conftest.py", before, after)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "signature,decorator,local_rebind,expected",
    [
        ("mocker", "", "", True),
        ("mocker", "@pytest.mark.parametrize('mocker', [None], indirect=True)\n", "", True),
        ("mocker", "@pytest.mark.parametrize('mocker', [None])\n", "", False),
        ("mocker=None", "", "", False),
        ("mocker", "", "    mocker = object()\n", False),
    ],
)
def test_pytest_mocker_requires_live_fixture_provenance(
    signature: str,
    decorator: str,
    local_rebind: str,
    expected: bool,
):
    before = (
        PRELUDE
        + "\n"
        + decorator
        + f"def test_total({signature}):\n"
        + local_rebind
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    mocker.patch.object(billing, 'invoice_total', _reference)\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_mocker_provenance.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


def test_same_file_mocker_fixture_does_not_impersonate_pytest_mock():
    before = (
        PRELUDE
        + "\n@pytest.fixture\n"
        "def mocker():\n"
        "    return object()\n\n"
        "def test_total(mocker):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    mocker.patch.object(billing, 'invoice_total', _reference)\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_fake_mocker.py", before, after)
    assert not [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert verdict == "pass"


@pytest.mark.parametrize(
    "setup,install",
    [
        ("setattr = lambda *args: None\n", "setattr(billing, 'invoice_total', _reference)"),
        ("vars = lambda *args: {}\n", "vars(billing)['invoice_total'] = _reference"),
        ("helper = object()\n", "helper.setattr(billing, 'invoice_total', _reference)"),
        ("helper = object()\n", "helper.setitem(vars(billing), 'invoice_total', _reference)"),
        ("helper = object()\n", "helper.patch('app.billing.invoice_total', _reference).start()"),
        ("helper = object()\n", "helper.patch.object(billing, 'invoice_total', _reference).start()"),
    ],
)
def test_standin_api_names_require_positive_provenance(
    setup: str, install: str
):
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        + _indent(setup.rstrip())
        + "\n    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        f"    {install}\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_api_provenance.py", before, after)
    assert not [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert verdict == "pass"


def test_exact_builtin_alias_remains_positive_provenance():
    before = (
        PRELUDE
        + "\nfrom builtins import setattr as install\n\n"
        "def test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    install(billing, 'invoice_total', _reference)\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_builtin_alias.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize("shadowed,expected", [(False, False), (True, True)])
def test_shadowed_getattr_cannot_disguise_a_new_install(
    shadowed: bool, expected: bool
):
    setup = (
        "    getattr = lambda *args: _reference\n" if shadowed else ""
    )
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = (
        PRELUDE
        + "\ndef test_total():\n"
        + setup
        + "    original = getattr(billing, 'invoice_total')\n"
        "    billing.invoice_total = original\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run("tests/test_getattr_origin.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "receiver_setup,receiver,expected",
    [
        ("mp = pytest.MonkeyPatch()", "mp", True),
        ("", "monkeypatch", True),
        ("fake = object()", "fake", False),
    ],
)
def test_monkeypatch_methods_require_a_proven_receiver(
    receiver_setup: str, receiver: str, expected: bool
):
    signature = "monkeypatch" if receiver == "monkeypatch" else ""
    before = (
        PRELUDE
        + f"\ndef test_total({signature}):\n"
        + (f"    {receiver_setup}\n" if receiver_setup else "")
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        f"    {receiver}.setattr(billing, 'invoice_total', _reference)\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_monkeypatch_origin.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "signature,decorator,local_rebind,expected",
    [
        ("monkeypatch", "", "", True),
        ("monkeypatch", "@pytest.mark.parametrize('monkeypatch', [None], indirect=True)\n", "", True),
        ("monkeypatch", "@pytest.mark.parametrize('monkeypatch', [None])\n", "", False),
        ("monkeypatch=None", "", "", False),
        ("monkeypatch", "", "    monkeypatch = object()\n", False),
    ],
)
def test_monkeypatch_fixture_receiver_rejects_parameter_shadows(
    signature: str,
    decorator: str,
    local_rebind: str,
    expected: bool,
):
    before = (
        PRELUDE
        + "\n"
        + decorator
        + f"def test_total({signature}):\n"
        + local_rebind
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    monkeypatch.setattr(billing, 'invoice_total', _reference)\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_monkeypatch_param.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


def test_same_file_monkeypatch_fixture_cannot_impersonate_builtin_fixture():
    before = (
        PRELUDE
        + "\n@pytest.fixture\n"
        "def monkeypatch():\n"
        "    return object()\n\n"
        "def test_total(monkeypatch):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    monkeypatch.setattr(billing, 'invoice_total', _reference)\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_fake_monkeypatch.py", before, after)
    assert not [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert verdict == "pass"


@pytest.mark.parametrize("oracle_inside,expected", [(True, True), (False, False)])
def test_monkeypatch_context_limits_the_install_lifetime(
    oracle_inside: bool, expected: bool
):
    before = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    if oracle_inside:
        body = (
            "    with monkeypatch.context() as mp:\n"
            "        mp.setattr(billing, 'invoice_total', _reference)\n"
            "        assert billing.invoice_total([], 0) == 105.3\n"
        )
    else:
        body = (
            "    with monkeypatch.context() as mp:\n"
            "        mp.setattr(billing, 'invoice_total', _reference)\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    after = PRELUDE + "\ndef test_total(monkeypatch):\n" + body
    verdict, findings = _run("tests/test_monkeypatch_context.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "lifecycle,oracle_inside,expected",
    [
        ("decorator", True, True),
        ("decorator", False, False),
        ("context", True, True),
        ("context", False, False),
    ],
)
def test_helper_scoped_patch_does_not_escape_the_helper_call(
    lifecycle: str, oracle_inside: bool, expected: bool
):
    helper_body = (
        "    assert billing.invoice_total([], 0) == 105.3\n"
        if oracle_inside
        else "    billing.invoice_total([], 0)\n"
    )
    before = PRELUDE + "\ndef verify():\n" + helper_body
    if not oracle_inside:
        before += (
            "\ndef test_total():\n"
            "    verify()\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    else:
        before += "\ndef test_total():\n    verify()\n"

    if lifecycle == "decorator":
        decorated = (
            '\n@mock.patch.object(billing, "invoice_total", _reference)\n'
            "def verify():\n"
            + helper_body
        )
    else:
        decorated = (
            "\ndef verify():\n"
            '    with mock.patch.object(billing, "invoice_total", _reference):\n'
            + "\n".join(
                "    " + line if line else line
                for line in helper_body.rstrip().split("\n")
            )
            + "\n"
        )
    after = before.replace("\ndef verify():\n" + helper_body, decorated)
    verdict, findings = _run("tests/test_helper_patch_scope.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize("oracle_before_restore,expected", [(False, False), (True, True)])
def test_later_importfrom_restores_a_replaced_binding(
    oracle_before_restore: bool, expected: bool
):
    prelude = (
        "from app.billing import invoice_total\n\n"
        "def _reference(*args):\n    return 105.3\n"
    )
    before = (
        prelude
        + "\ndef test_total():\n"
        "    assert invoice_total([], 0) == 105.3\n"
    )
    if oracle_before_restore:
        body = (
            "    invoice_total = _reference\n"
            "    assert invoice_total([], 0) == 105.3\n"
            "    from app.billing import invoice_total\n"
        )
    else:
        body = (
            "    invoice_total = _reference\n"
            "    from app.billing import invoice_total\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    after = prelude + "\ndef test_total():\n" + body
    verdict, findings = _run("tests/test_import_restore.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize("import_before_delete,expected", [(False, False), (True, True)])
def test_del_sys_modules_restores_only_before_the_module_is_captured(
    import_before_delete: bool, expected: bool
):
    before = (
        SYS_MODULES_PRELUDE
        + "\nimport importlib\n\ndef test_total():\n"
        '    billing = importlib.import_module("app.billing")\n'
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    swap = '    sys.modules["app.billing"] = _standin_module\n'
    delete = '    del sys.modules["app.billing"]\n'
    imported = '    billing = importlib.import_module("app.billing")\n'
    body = (
        swap + imported + delete if import_before_delete else swap + delete + imported
    )
    after = (
        SYS_MODULES_PRELUDE
        + "\nimport importlib\n\ndef test_total():\n"
        + body
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run("tests/test_module_delete.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize("local_shadow,expected", [(False, True), (True, False)])
def test_request_module_attribute_reach_respects_local_shadowing(
    local_shadow: bool, expected: bool
):
    signature = "invoice_total=None" if local_shadow else ""
    before = (
        "import pytest\n"
        "from app.billing import invoice_total\n\n"
        "def _reference(*args):\n    return 105.3\n\n"
        "@pytest.fixture(autouse=True)\n"
        "def adapter(monkeypatch, request):\n"
        "    yield\n\n"
        f"def test_total({signature}):\n"
        "    assert invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def adapter(monkeypatch, request):\n",
        "def adapter(monkeypatch, request):\n"
        "    monkeypatch.setattr(request.module, 'invoice_total', _reference)\n",
    )
    verdict, findings = _run("tests/test_request_module.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize("approx_on_left", [False, True])
def test_pytest_approx_preserves_the_subject_for_standin_reach(
    approx_on_left: bool
):
    expression = (
        "pytest.approx(105.3) == billing.invoice_total([], 0)"
        if approx_on_left
        else "billing.invoice_total([], 0) == pytest.approx(105.3)"
    )
    before = PRELUDE + f"\ndef test_total():\n    assert {expression}\n"
    after = before.replace(
        "def test_total():\n",
        "def test_total():\n"
        "    billing.invoice_total = _reference\n",
    )
    verdict, findings = _run("tests/test_approx_reach.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize("install_before_import,expected", [(True, False), (False, False)])
def test_test_module_sys_modules_swap_respects_import_order(
    install_before_import: bool, expected: bool
):
    setup = 'sys.modules["app.billing"] = _standin_module\n'
    imported = "from app import billing\n"
    before = (
        SYS_MODULES_PRELUDE
        + "\n"
        + imported
        + "\ndef test_total():\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    order = setup + imported if install_before_import else imported + setup
    after = SYS_MODULES_PRELUDE + "\n" + order + "\ndef test_total():\n    assert billing.invoice_total([], 0) == 105.3\n"
    verdict, findings = _run("tests/test_module_swap.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        install_before_import,
        verdict,
        [f.rule for f in findings],
    )
    assert verdict == ("block" if expected else "pass")


def test_second_review_fixture_ancestry_inventory_is_uncapped():
    before, after = _fixture_install_source("standin")
    decoy = (
        "from app import billing\n\n"
        "def test_noise(missing_fixture):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    head = {
        f"tests/a{index:02d}/test_noise.py": decoy
        for index in range(17)
    }
    head.update(
        {
            "tests/zz/conftest.py": (
                "import pytest\n\n"
                "@pytest.fixture(autouse=True)\n"
                "def adapter(standin):\n"
                "    return None\n"
            ),
            "tests/zz/test_billing.py": REACHING_TEST,
        }
    )
    verdict, findings = _run("conftest.py", before, after, head=head)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_second_review_existing_unreadable_ownership_path_fails_closed():
    before = (
        "import localpkg.billing as billing\n\n"
        "def test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n",
        "def test_total():\n    billing.invoice_total = lambda *_: 105.3\n",
    )
    source_path = "src/localpkg/billing.py"
    with pytest.raises(
        EngineError,
        match=r"head reader could not read existing path: src/localpkg/billing\.py",
    ):
        _run(
            "tests/test_local_owner.py",
            before,
            after,
            owned_modules=set(),
            head={source_path: "def invoice_total(*args): return 105.3\n"},
            unreadable={source_path},
            existing={source_path},
        )


def test_second_review_existing_unreadable_ancestor_fails_closed():
    before, after = _fixture_install_source("standin")
    conftest_path = "tests/sub/conftest.py"
    head = {
        conftest_path: (
            "import pytest\n\n"
            "@pytest.fixture(autouse=True)\n"
            "def adapter(standin):\n"
            "    return None\n"
        ),
        "tests/sub/test_billing.py": REACHING_TEST,
    }
    with pytest.raises(
        EngineError,
        match=r"head reader could not read existing path: tests/sub/conftest\.py",
    ):
        _run(
            "conftest.py",
            before,
            after,
            head=head,
            unreadable={conftest_path},
        )


def test_second_review_range_existence_inventory_distinguishes_missing(
    monkeypatch,
):
    monkeypatch.setattr(
        "checkwash.gitio.git._run",
        lambda *_args, **_kwargs: b"src/app.py\0",
    )
    assert head_path_exists("repo", "HEAD", "src/app.py")
    monkeypatch.setattr(
        "checkwash.gitio.git._run", lambda *_args, **_kwargs: b""
    )
    assert not head_path_exists("repo", "HEAD", "src/app.py")
    failure = GitError("fatal inventory failure", returncode=128)
    monkeypatch.setattr(
        "checkwash.gitio.git._run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(failure),
    )
    with pytest.raises(GitError, match="fatal inventory failure"):
        head_path_exists("repo", "HEAD", "src/app.py")


def test_second_review_keyword_parametrize_alias_is_a_direct_provider():
    before, after = _fixture_install_source()
    test_source = (
        "from pytest import mark as pm\n"
        "from app import billing\n\n"
        '@pm.parametrize(argnames="adapter", argvalues=[object()])\n'
        "def test_total(adapter):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "conftest.py", before, after, head={"tests/test_billing.py": test_source}
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert not hits, (verdict, [f.rule for f in findings])
    assert verdict == "pass"


def test_second_review_usefixtures_mark_alias_activates_fixture_dependency():
    before = (
        PRELUDE
        + "\n@pytest.fixture\n"
        + "def standin(monkeypatch):\n"
        + "    yield\n\n"
        + "@pytest.fixture\n"
        + "def adapter(standin):\n"
        + "    return None\n"
    )
    after = before.replace(
        "def standin(monkeypatch):\n",
        "def standin(monkeypatch):\n"
        '    monkeypatch.setattr(billing, "invoice_total", _reference)\n',
    )
    test_source = (
        "from pytest import mark as pm\n"
        "from app import billing\n\n"
        '@pm.usefixtures("adapter")\n'
        "def test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "conftest.py", before, after, head={"tests/test_billing.py": test_source}
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_second_review_first_live_yield_ignores_dead_branch_yield():
    before = (
        PRELUDE
        + "\n@pytest.fixture(autouse=True)\n"
        + "def adapter():\n"
        + "    yield\n"
    )
    after = (
        PRELUDE
        + "\n@pytest.fixture(autouse=True)\n"
        + "def adapter():\n"
        + "    if False:\n"
        + "        yield\n"
        + "    billing.invoice_total = _reference\n"
        + "    yield\n"
    )
    verdict, findings = _run("conftest.py", before, after)
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize("oracle", ["reversed", "unittest"])
def test_second_review_patch_context_uses_canonical_oracle_subject(oracle: str):
    if oracle == "reversed":
        before = (
            PRELUDE
            + "\ndef test_total():\n"
            + "    assert 105.3 == billing.invoice_total([], 0)\n"
        )
        after = (
            PRELUDE
            + "\ndef test_total():\n"
            + '    with mock.patch.object(billing, "invoice_total", _reference):\n'
            + "        assert 105.3 == billing.invoice_total([], 0)\n"
        )
    else:
        before = (
            PRELUDE
            + "\nclass TestBilling:\n"
            + "    def test_total(self):\n"
            + "        self.assertEqual(105.3, billing.invoice_total([], 0))\n"
        )
        after = (
            PRELUDE
            + "\nclass TestBilling:\n"
            + "    def test_total(self):\n"
            + '        with mock.patch.object(billing, "invoice_total", _reference):\n'
            + "            self.assertEqual(105.3, billing.invoice_total([], 0))\n"
        )
    verdict, findings = _run("tests/test_context_subject.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (oracle, verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_second_review_test_module_swap_precedes_static_true_block_import():
    before = (
        SYS_MODULES_PRELUDE
        + "\nif True:\n"
        + "    from app.billing import invoice_total\n\n"
        + "def test_total():\n"
        + "    assert invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "if True:\n",
        'sys.modules["app.billing"] = _standin_module\nif True:\n',
    )
    verdict, findings = _run("tests/test_static_import.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize("manifest_self,expected", [(False, False), (True, True)])
def test_second_review_declared_external_beats_conventional_path_probe(
    manifest_self: bool, expected: bool
):
    before = (
        "import vendor.billing as billing\n\n"
        "def test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n",
        "def test_total():\n    billing.invoice_total = lambda *_: 105.3\n",
    )
    verdict, findings = _run(
        "tests/test_vendor.py",
        before,
        after,
        third_party={"vendor"},
        owned_modules={"vendor"} if manifest_self else set(),
        head={"src/vendor/billing.py": "def invoice_total(*args): return 105.3\n"},
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (manifest_self, verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "install",
    [
        'p.object(billing, "invoice_total", _reference).start()',
        'p("app.billing.invoice_total", _reference).start()',
    ],
)
def test_second_review_static_patch_alias_is_normalized(install: str):
    prelude = PRELUDE.replace(
        "from unittest import mock", "from unittest import mock\nfrom unittest.mock import patch as p"
    )
    before = (
        prelude
        + "\ndef test_total():\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n", f"def test_total():\n    {install}\n"
    )
    verdict, findings = _run("tests/test_patch_alias.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (install, verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "level,indirect,expected",
    [
        ("class", False, False),
        ("class", True, True),
        ("module", False, False),
        ("module", True, True),
    ],
)
def test_third_review_inherited_parametrize_provider_mode(
    level: str, indirect: bool, expected: bool
):
    before, after = _fixture_install_source()
    mark = (
        '@pm.parametrize(argnames="adapter", argvalues=[object()], '
        f"indirect={indirect})"
    )
    if level == "class":
        test_source = (
            "from pytest import mark as pm\n"
            "from app import billing\n\n"
            f"{mark}\n"
            "class TestBilling:\n"
            "    def test_total(self, adapter):\n"
            "        assert billing.invoice_total([], 0) == 105.3\n"
        )
    else:
        test_source = (
            "from pytest import mark as pm\n"
            "from app import billing\n\n"
            f"pytestmark = {mark[1:]}\n\n"
            "def test_total(adapter):\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    verdict, findings = _run(
        "conftest.py", before, after, head={"tests/test_billing.py": test_source}
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert bool(hits) is expected, (
        level,
        indirect,
        verdict,
        [f.rule for f in findings],
    )
    assert verdict == ("block" if expected else "pass")


def test_third_review_stacked_class_parametrize_keeps_each_direct_provider():
    before, after = _fixture_install_source()
    test_source = (
        "from pytest import mark as pm\n"
        "from app import billing\n\n"
        '@pm.parametrize(argnames="case", argvalues=[1])\n'
        '@pm.parametrize(argnames="adapter", argvalues=[object()])\n'
        "class TestBilling:\n"
        "    def test_total(self, adapter, case):\n"
        "        assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "conftest.py", before, after, head={"tests/test_billing.py": test_source}
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert not hits, (verdict, [f.rule for f in findings])
    assert verdict == "pass"


def test_third_review_class_parametrize_metadata_does_not_leak_to_sibling():
    before, after = _fixture_install_source()
    test_source = (
        "from pytest import mark as pm\n"
        "from app import billing\n\n"
        '@pm.parametrize(argnames="adapter", argvalues=[object()])\n'
        "class TestDirect:\n"
        "    def test_direct(self, adapter):\n"
        "        assert billing.invoice_total([], 0) == 105.3\n\n"
        "class TestFixture:\n"
        "    def test_fixture(self, adapter):\n"
        "        assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "conftest.py", before, after, head={"tests/test_billing.py": test_source}
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_fourth_review_legacy_unit_patch_spelling_and_fingerprint_are_stable():
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n",
        "def test_total():\n"
        '    _mp.setattr(billing, "invoice_total", _reference)\n',
    )
    parsed = parse_python(after.encode("utf-8"), collect_tests=True)
    side = parsed.units[0].side
    assert side.patches == (("billing.invoice_total", "invoice_total"),)
    serialized = to_jsonable(side)
    assert serialized["patches"] == [["billing.invoice_total", "invoice_total"]]
    assert "fixtures" not in serialized
    assert "standin_imports" not in serialized
    assert "standin_installs" not in serialized
    assert "standin_module_bindings" not in serialized
    assert "standin_parameter_providers" not in serialized
    assert "standin_lexical_names" not in serialized
    assert "standin_runtime_imports" not in to_jsonable(
        side.assertions[0]
    )
    assert "standin_module_imports" not in to_jsonable(
        side.assertions[0]
    )
    assert "standin_runtime_imports_projected" not in to_jsonable(
        side.assertions[0]
    )
    assert "standin_position" not in to_jsonable(side.assertions[0])
    assert "standin_oracle_key" not in to_jsonable(side.assertions[0])

    verdict, findings = _run("tests/test_legacy_patch.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert hits[0].fingerprint == make_fingerprint(
        "TEST_PATCHES_SUBJECT",
        "tests/test_legacy_patch.py",
        "test_total",
        "billing.invoice_total",
    )

    # An external IR-v1 producer has no rich internal fields. Its historical
    # deny-list ownership, target-only newness and name reach stay intact.
    legacy_before = UnitSide(span=(0, 1))
    legacy_after = UnitSide(
        span=(0, 1),
        assertions=[
            Assertion(
                id="a0",
                form="truthy",
                strength=1,
                text="assert billing.invoice_total()",
                span=(0, 1),
                left="billing.invoice_total()",
            )
        ],
        patches=(("billing.invoice_total", "invoice_total"),),
    )
    legacy_ir = IR(
        base="base",
        head="head",
        files=[
            FileIR(
                path="tests/test_legacy_patch.py",
                language="python",
                role="test",
                status="modified",
                units=[
                    Unit(
                        kind="test_function",
                        qualname="test_total",
                        match="by_name",
                        before=legacy_before,
                        after=legacy_after,
                        delta=None,
                    )
                ],
            )
        ],
    )
    legacy_hits = detect_test_patches(legacy_ir)
    assert len(legacy_hits) == 1
    assert legacy_hits[0].fingerprint == hits[0].fingerprint


def test_fourth_review_internal_metadata_preserves_positional_ir_v1_constructors():
    side = UnitSide(
        (0, 1),
        [],
        (),
        [],
        [],
        None,
        "",
        {},
        {},
        (),
        (),
        (),
        (("billing.invoice_total", "invoice_total"),),
        (),
    )
    file_ir = FileIR(
        "tests/test_legacy.py",
        "python",
        "test",
        "modified",
        [],
        "full",
        True,
        {"FLAG": "True"},
    )
    assert side.patches == (("billing.invoice_total", "invoice_total"),)
    assert file_ir.constants == {"FLAG": "True"}
    assert all(
        model.__dataclass_fields__[name].kw_only
        for model, names in (
            (
                Assertion,
                (
                    "standin_imports",
                    "standin_runtime_imports",
                    "standin_module_imports",
                    "standin_runtime_imports_projected",
                    "standin_position",
                    "standin_oracle_key",
                ),
            ),
            (
                UnitSide,
                (
                    "fixtures",
                    "standin_imports",
                    "standin_installs",
                    "standin_module_bindings",
                    "standin_parameter_providers",
                    "standin_lexical_names",
                ),
            ),
            (FileIR, ("standin_imports",)),
            (
                DiffGlobals,
                ("conftest_standin_patches", "first_party_roots"),
            ),
        )
        for name in names
    )


def test_fourth_review_legacy_conftest_field_keeps_raw_call_semantics():
    before = (
        "import pytest\n\n"
        "@pytest.fixture(autouse=True)\n"
        "def adapter(request, monkeypatch):\n"
        "    yield\n"
    )
    after = before.replace(
        "    yield\n",
        '    monkeypatch.setattr(request.module, "invoice_total", lambda *_: 105.3)\n'
        "    yield\n",
    )
    ir, findings, verdict = analyze(
        [
            FileChange(
                path="conftest.py",
                status="modified",
                before=before.encode("utf-8"),
                after=after.encode("utf-8"),
            )
        ],
        Config(),
        Contract(),
        [],
        TODAY,
        known_modules=known_baseline() | {"pytest"},
    )
    expected = (
        "conftest.py",
        'monkeypatch.setattr(request.module,"invoice_total",lambda*_:105.3)',
    )
    assert ir.globals.conftest_prod_patches == [expected]
    assert ir.globals.conftest_standin_patches == []
    serialized = to_jsonable(ir)["globals"]
    assert serialized["conftest_prod_patches"] == [list(expected)]
    assert "conftest_standin_patches" not in serialized
    assert "first_party_roots" not in serialized
    assert not [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert verdict == "pass"


@pytest.mark.parametrize("oracle", ["direct", "bound_result"])
def test_fourth_review_live_import_alias_provider_replacement_blocks(
    oracle: str,
):
    body = (
        "    assert invoice_total([], 0) == 105.3\n"
        if oracle == "direct"
        else (
            "    result = invoice_total([], 0)\n"
            "    assert result == 105.3\n"
        )
    )
    before = (
        "from src.billing import invoice_total\n\n"
        "def test_total():\n"
        + body
    )
    after = before.replace(
        "from src.billing import invoice_total",
        "from src.reference import reference_total as invoice_total",
    )
    verdict, findings = _run(
        "tests/test_import_alias.py",
        before,
        after,
        owned_modules={"src"},
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (oracle, verdict, [f.rule for f in findings])
    assert hits[0].after is not None
    assert hits[0].after.text == "invoice_total"
    assert verdict == "block"


@pytest.mark.parametrize("shape", ["after_oracle", "locally_shadowed"])
def test_fourth_review_import_replacement_must_be_live_at_oracle(shape: str):
    if shape == "after_oracle":
        before = (
            "def test_total():\n"
            "    from src.billing import invoice_total\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
        after = before + (
            "    from src.reference import reference_total as invoice_total\n"
        )
    else:
        before = (
            "from src.billing import invoice_total\n\n"
            "def test_total():\n"
            "    invoice_total = lambda *_: 105.3\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
        after = before.replace(
            "from src.billing import invoice_total",
            "from src.reference import reference_total as invoice_total",
        )
    verdict, findings = _run(
        "tests/test_import_alias_order.py",
        before,
        after,
        owned_modules={"src"},
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (shape, verdict, [f.rule for f in findings])


def test_fourth_review_repeated_oracles_do_not_cross_product_import_providers():
    before = (
        "def test_total():\n"
        "    from src.billing import invoice_total\n"
        "    assert invoice_total([], 0) == 105.3\n"
        "    from src.reference import reference_total as invoice_total\n"
        "    assert invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n",
        "def test_total():\n    # provider sequence is unchanged\n",
    )
    verdict, findings = _run(
        "tests/test_repeated_alias.py",
        before,
        after,
        owned_modules={"src"},
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (verdict, [f.rule for f in findings])


@pytest.mark.parametrize("scope", ["function", "module"])
def test_fourth_review_removed_import_replaced_by_local_binding_blocks(
    scope: str,
):
    before = (
        "from src.billing import invoice_total\n\n"
        "def test_total():\n"
        "    assert invoice_total([], 0) == 105.3\n"
    )
    if scope == "function":
        after = before.replace("from src.billing import invoice_total\n\n", "")
        after = after.replace(
            "def test_total():\n",
            "def test_total():\n"
            "    invoice_total = lambda *_: 105.3\n",
        )
    else:
        after = before.replace(
            "from src.billing import invoice_total",
            "invoice_total = lambda *_: 105.3",
        )
    verdict, findings = _run(
        "tests/test_removed_alias.py",
        before,
        after,
        owned_modules={"src"},
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (scope, verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "install",
    [
        'mock.patch(target="app.billing.invoice_total", new=_reference).start()',
        (
            'mock.patch.object(target=billing, attribute="invoice_total", '
            "new=_reference).start()"
        ),
        '_mp.setattr(target=billing, name="invoice_total", value=_reference)',
    ],
)
def test_fourth_review_legal_keyword_patch_forms_block(install: str):
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n", f"def test_total():\n    {install}\n"
    )
    verdict, findings = _run("tests/test_keyword_patch.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (install, verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_fourth_review_aliased_patch_keyword_form_survives_raw_gate():
    before = (
        "from unittest.mock import patch as p\n"
        "from app import billing\n\n"
        "def reference(*_args): return 105.3\n\n"
        "def test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        '    p(target="app.billing.invoice_total", new=reference).start()\n'
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_alias_patch.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize("container", ["tuple", "list"])
def test_fourth_review_unpacking_assignment_targets_block(container: str):
    left, right = (
        (
            "(billing.invoice_total, billing.currency_symbol)",
            '( _reference, lambda: "$" )',
        )
        if container == "tuple"
        else (
            "[billing.invoice_total, billing.currency_symbol]",
            '[ _reference, lambda: "$" ]',
        )
    )
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def test_total():\n", f"def test_total():\n    {left} = {right}\n"
    )
    verdict, findings = _run("tests/test_unpack_patch.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (container, verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize("shape", ["after_oracle", "uninvoked_nested_def"])
def test_fourth_review_test_body_install_must_execute_before_oracle(
    shape: str,
):
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    if shape == "after_oracle":
        after = before.replace(
            "    assert billing.invoice_total([], 0) == 105.3\n",
            "    assert billing.invoice_total([], 0) == 105.3\n"
            "    billing.invoice_total = _reference\n",
        )
    else:
        after = before.replace(
            "def test_total():\n",
            "def test_total():\n"
            "    def configure():\n"
            "        billing.invoice_total = _reference\n",
        )
    verdict, findings = _run("tests/test_install_order.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (shape, verdict, [f.rule for f in findings])


@pytest.mark.parametrize("shape", ["decorator_argument", "context_argument"])
def test_fourth_review_nested_patch_constructor_is_not_implicitly_activated(
    shape: str,
):
    if shape == "decorator_argument":
        before = (
            PRELUDE
            + "\ndef wrapper(_patcher):\n"
            + "    return lambda cls: cls\n\n"
            + "class TestBilling:\n"
            + "    def test_total(self):\n"
            + "        assert billing.invoice_total([], 0) == 105.3\n"
        )
        after = before.replace(
            "class TestBilling:\n",
            '@wrapper(mock.patch("app.billing.invoice_total", _reference))\n'
            "class TestBilling:\n",
        )
    else:
        before = (
            PRELUDE
            + "\nfrom contextlib import nullcontext\n\n"
            + "def test_total():\n"
            + "    assert billing.invoice_total([], 0) == 105.3\n"
        )
        after = before.replace(
            "    assert billing.invoice_total([], 0) == 105.3\n",
            '    with nullcontext(mock.patch("app.billing.invoice_total", '
            "_reference)):\n"
            "        assert billing.invoice_total([], 0) == 105.3\n",
        )
    verdict, findings = _run("tests/test_nested_patcher.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (shape, verdict, [f.rule for f in findings])


def test_fourth_review_class_patch_decorator_applies_to_each_test_method():
    before = (
        PRELUDE
        + "\nclass TestBilling:\n"
        + "    def test_total(self):\n"
        + "        assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "class TestBilling:\n",
        '@mock.patch.object(target=billing, attribute="invoice_total", new=_reference)\n'
        "class TestBilling:\n",
    )
    verdict, findings = _run("tests/test_class_patch.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_fourth_review_class_decorator_uses_evaluation_time_import_binding():
    source = (
        PRELUDE
        + '\n@mock.patch.object(billing, "invoice_total", _reference)\n'
        + "class TestBilling:\n"
        + "    def test_total(self):\n"
        + "        assert billing.invoice_total([], 0) == 105.3\n\n"
        + "billing = object()\n"
    )
    parsed = parse_python(source.encode("utf-8"), collect_tests=True)
    assert any(
        install.scope == "class"
        and install.target == "app.billing.invoice_total"
        for install in parsed.standin_installs
    )


def test_fourth_review_class_autouse_fixture_applies_to_class_tests():
    before = (
        PRELUDE
        + "\nclass TestBilling:\n"
        + "    @pytest.fixture(autouse=True)\n"
        + "    def adapter(self):\n"
        + "        yield\n\n"
        + "    def test_total(self):\n"
        + "        assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    def adapter(self):\n",
        "    def adapter(self):\n"
        "        billing.invoice_total = _reference\n",
    )
    verdict, findings = _run("tests/test_class_fixture.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "shape,expected",
    [("parameter", False), ("local_assignment", False), ("ordered_import", True)],
)
def test_fourth_review_import_shadowing_and_statement_order(
    shape: str, expected: bool
):
    if shape == "parameter":
        before = (
            "from app import billing\n\n"
            "def _reference(*args): return 105.3\n\n"
            "def test_total(billing):\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    elif shape == "local_assignment":
        before = (
            "from app import billing\n\n"
            "def _reference(*args): return 105.3\n\n"
            "def test_total():\n"
            "    billing = object()\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    else:
        before = (
            "def _reference(*args): return 105.3\n\n"
            "def test_total():\n"
            "    from app import billing\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
            "    billing = object()\n"
        )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    billing.invoice_total = _reference\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_shadow_order.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (shape, verdict, [f.rule for f in findings])
    if expected:
        assert verdict == "block"


def test_fourth_review_parameter_binding_does_not_borrow_outer_import_origin():
    before = (
        "from src.billing import invoice_total\n\n"
        "def _reference(*args): return 105.3\n\n"
        "def test_total(invoice_total):\n"
        "    assert invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert invoice_total([], 0) == 105.3\n",
        "    invoice_total = _reference\n"
        "    assert invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run(
        "tests/test_parameter_shadow.py",
        before,
        after,
        owned_modules={"src"},
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (verdict, [f.rule for f in findings])


def test_fourth_review_removed_import_does_not_leave_a_phantom_binding():
    before = (
        "from app import billing\n\n"
        "def _reference(*args): return 105.3\n\n"
        "def test_total(billing):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace("from app import billing\n\n", "")
    after = after.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    billing.invoice_total = _reference\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_removed_import.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (verdict, [f.rule for f in findings])


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/outside.py",
        r"C:\outside.py",
        "tests/../../outside.py",
        "//server/share.py",
        "tests/NUL.py",
        "tests/trailing. ",
    ],
)
def test_fourth_review_unsafe_repository_paths_are_rejected(path: str):
    assert _safe_repo_path(path) is None


def test_fourth_review_unsafe_search_results_never_reach_head_probes():
    before, after = _fixture_install_source(autouse=True)
    probed: list[str] = []

    def should_not_probe(path: str):
        probed.append(path)
        raise AssertionError(f"unsafe path reached head callback: {path}")

    analyze(
        [
            FileChange(
                path="conftest.py",
                status="modified",
                before=before.encode("utf-8"),
                after=after.encode("utf-8"),
            )
        ],
        Config(),
        Contract(),
        [],
        TODAY,
        known_modules=known_baseline() | {"app", "pytest"},
        self_modules={"app"},
        head_reader=should_not_probe,
        head_exists=should_not_probe,
        head_searcher=lambda _needles: [
            "/tmp/outside.py",
            r"C:\outside.py",
            "tests/../../outside.py",
            "//server/share.py",
            "tests/NUL.py",
            "tests/trailing. ",
        ],
    )
    assert probed == []


@pytest.mark.parametrize(
    "target",
    [
        "C:/outside.invoice_total",
        "/tmp/outside.invoice_total",
        "pkg...leaf",
        "pkg.class.invoice_total",
    ],
)
def test_fourth_review_invalid_module_targets_have_no_ownership_probe_paths(
    target: str,
):
    install = StandinInstall(
        target=target,
        attr="invoice_total",
        text=target,
        scope="test",
    )
    assert _standin_module_paths(install) == ()


def test_fourth_review_nested_attribute_probes_longest_valid_module_prefixes():
    before = (
        "import localpkg.billing as billing\n\n"
        "def _reference(*args): return 105.3\n\n"
        "def test_total():\n"
        "    assert billing.Service.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.Service.invoice_total([], 0) == 105.3\n",
        "    billing.Service.invoice_total = _reference\n"
        "    assert billing.Service.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run(
        "tests/test_nested_owner.py",
        before,
        after,
        owned_modules=set(),
        head={
            "src/localpkg/billing.py":
                "class Service:\n    invoice_total = staticmethod(lambda *_: 105.3)\n"
        },
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_fourth_review_raw_source_gate_skips_structured_standin_walk(
    monkeypatch,
):
    def should_not_run(*_args, **_kwargs):
        raise AssertionError("structured stand-in walk should have been skipped")

    original_scope_walk = python_frontend._scope_import_environments

    def module_scope_only(root, base):
        if isinstance(
            root,
            (
                ast.FunctionDef,
                ast.AsyncFunctionDef,
            ),
        ):
            raise AssertionError("per-test import walk should have been skipped")
        return original_scope_walk(root, base)

    monkeypatch.setattr(python_frontend, "_has_standin_install", should_not_run)
    monkeypatch.setattr(
        python_frontend, "_module_local_bindings", should_not_run
    )
    monkeypatch.setattr(
        python_frontend, "_scope_import_environments", module_scope_only
    )
    parsed = python_frontend.parse_python(
        b"def test_plain():\n    assert True\n", collect_tests=True
    )
    assert parsed.parse_ok
    assert parsed.units[0].side.standin_installs == ()


@pytest.mark.parametrize(
    "install",
    [
        '(p)("app.billing.invoice_total", _reference).start()',
        (
            "p "
            + "\\"
            + "\n        (\"app.billing.invoice_total\", _reference).start()"
        ),
    ],
    ids=["parenthesized_alias", "continued_alias"],
)
def test_fifth_review_raw_gate_keeps_legal_alias_constructor_forms(
    install: str,
):
    prelude = PRELUDE.replace(
        "from unittest import mock",
        "from unittest import mock\nfrom unittest.mock import patch as p",
    )
    before = (
        prelude
        + "\ndef test_total():\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        f"    {install}\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run("tests/test_alias_constructor.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (install, verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_fifth_review_sys_modules_alias_uses_live_import_binding():
    prelude = (
        SYS_MODULES_PRELUDE.replace("import sys", "import sys as system")
        + "\nimport importlib\n"
    )
    before = (
        prelude
        + "\ndef test_total():\n"
        + '    billing = importlib.import_module("app.billing")\n'
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        '    billing = importlib.import_module("app.billing")\n',
        '    system.modules["app.billing"] = _standin_module\n'
        '    billing = importlib.import_module("app.billing")\n',
    )
    verdict, findings = _run("tests/test_sys_alias.py", before, after)
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "shape",
    ["sys_parameter", "sys_local", "importlib_local"],
)
def test_fifth_review_mapping_and_runtime_import_names_must_be_live(
    shape: str,
):
    signature = "sys" if shape == "sys_parameter" else ""
    setup = ""
    if shape == "sys_local":
        setup = "    sys = types.SimpleNamespace(modules={})\n"
    elif shape == "importlib_local":
        setup = (
            "    importlib = types.SimpleNamespace(\n"
            "        import_module=lambda _name: _standin_module\n"
            "    )\n"
        )
    before = (
        SYS_MODULES_PRELUDE
        + "\nimport importlib\n"
        + f"\ndef test_total({signature}):\n"
        + setup
        + '    billing = importlib.import_module("app.billing")\n'
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        '    billing = importlib.import_module("app.billing")\n',
        '    sys.modules["app.billing"] = _standin_module\n'
        '    billing = importlib.import_module("app.billing")\n',
    )
    verdict, findings = _run(
        f"tests/test_{shape}.py",
        before,
        after,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (shape, verdict, [f.rule for f in findings])


@pytest.mark.parametrize(
    "shape",
    ["module_assignment", "nested_assignment", "module_patch_start"],
)
def test_fifth_review_invoked_helper_installs_reach_later_oracle(
    shape: str,
):
    install = (
        'mock.patch("app.billing.invoice_total", _reference).start()'
        if shape == "module_patch_start"
        else "billing.invoice_total = _reference"
    )
    if shape == "nested_assignment":
        before = (
            PRELUDE
            + "\ndef test_total():\n"
            + "    def configure():\n"
            + "        pass\n"
            + "    configure()\n"
            + "    assert billing.invoice_total([], 0) == 105.3\n"
        )
        after = before.replace(
            "    def configure():\n        pass\n",
            "    def configure():\n"
            f"        {install}\n",
        )
    else:
        # Defining the helper after the test makes its source position
        # intentionally different from its runtime invocation position.
        before = (
            PRELUDE
            + "\ndef test_total():\n"
            + "    configure()\n"
            + "    assert billing.invoice_total([], 0) == 105.3\n\n"
            + "def configure():\n"
            + "    pass\n"
        )
        after = before.replace(
            "def configure():\n    pass\n",
            "def configure():\n"
            f"    {install}\n",
        )
    verdict, findings = _run(
        f"tests/test_helper_{shape}.py",
        before,
        after,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (shape, verdict, [f.rule for f in findings])
    assert verdict == "block"


def test_fifth_review_transitive_nested_helper_uses_outer_live_import():
    before = (
        "def _reference(*_args):\n"
        "    return 105.3\n\n"
        "def configure():\n"
        "    from app import billing\n"
        "    def install():\n"
        "        pass\n"
        "    install()\n\n"
        "def test_total():\n"
        "    from app import billing as subject\n"
        "    configure()\n"
        "    assert subject.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    def install():\n        pass\n",
        "    def install():\n"
        "        billing.invoice_total = _reference\n",
    )
    verdict, findings = _run(
        "tests/test_transitive_helper.py",
        before,
        after,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "import_after_helper,expected",
    [(True, True), (False, False)],
)
def test_fifth_review_helper_module_swap_respects_runtime_import_order(
    import_after_helper: bool,
    expected: bool,
):
    imported = '    billing = importlib.import_module("app.billing")\n'
    ordered = (
        "    configure()\n" + imported
        if import_after_helper
        else imported + "    configure()\n"
    )
    before = (
        SYS_MODULES_PRELUDE
        + "\nimport importlib\n"
        + "\ndef configure():\n"
        + "    pass\n"
        + "\ndef test_total():\n"
        + ordered
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def configure():\n    pass\n",
        "def configure():\n"
        '    sys.modules["app.billing"] = _standin_module\n',
    )
    verdict, findings = _run(
        "tests/test_helper_module_swap.py",
        before,
        after,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        import_after_helper,
        verdict,
        [f.rule for f in findings],
    )
    if expected:
        assert len(hits) == 1
        assert verdict == "block"


@pytest.mark.parametrize(
    "call",
    ["", "    configure()\n"],
    ids=["uninvoked", "invoked_after_oracle"],
)
def test_fifth_review_non_reaching_module_helper_install_stays_silent(
    call: str,
):
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
        + call
        + "\ndef configure():\n"
        + "    pass\n"
    )
    after = before.replace(
        "def configure():\n    pass\n",
        "def configure():\n"
        "    billing.invoice_total = _reference\n",
    )
    verdict, findings = _run(
        "tests/test_helper_control.py",
        before,
        after,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (call, verdict, [f.rule for f in findings])


def test_fifth_review_moving_existing_helper_before_oracle_is_newly_reaching():
    tail = (
        "\ndef configure():\n"
        "    billing.invoice_total = _reference\n"
    )
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
        + "    configure()\n"
        + tail
    )
    after = (
        PRELUDE
        + "\ndef test_total():\n"
        + "    configure()\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
        + tail
    )
    verdict, findings = _run(
        "tests/test_helper_move.py",
        before,
        after,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1, (verdict, [f.rule for f in findings])
    assert verdict == "block"


@pytest.mark.parametrize(
    "rebind_before,expected",
    [(False, True), (True, False)],
    ids=["later_rebind", "prior_rebind"],
)
def test_fifth_review_class_body_uses_evaluation_time_import_map(
    rebind_before: bool,
    expected: bool,
):
    def source(*, install: bool) -> str:
        prefix = (
            "from app import billing\n\n"
            "def _reference(*_args):\n"
            "    return 105.3\n\n"
        )
        prior = "billing = object()\n\n" if rebind_before else ""
        body_install = (
            "    billing.invoice_total = _reference\n" if install else ""
        )
        later = "\nbilling = object()\n" if not rebind_before else ""
        return (
            prefix
            + prior
            + "class TestBilling:\n"
            + body_install
            + "    def test_total(self):\n"
            + "        from app import billing as subject\n"
            + "        assert subject.invoice_total([], 0) == 105.3\n"
            + later
        )

    before = source(install=False)
    after = source(install=True)
    verdict, findings = _run(
        "tests/test_class_body_order.py",
        before,
        after,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        rebind_before,
        verdict,
        [f.rule for f in findings],
    )
    if expected:
        assert len(hits) == 1
        assert verdict == "block"


@pytest.mark.parametrize(
    "scope,truth,expected",
    [
        ("function", True, True),
        ("function", False, False),
        ("module", True, True),
        ("module", False, False),
    ],
)
def test_fifth_review_removed_import_static_branch_provider(
    scope: str,
    truth: bool,
    expected: bool,
):
    before = (
        "from src.billing import invoice_total\n\n"
        "def test_total():\n"
        "    assert invoice_total([], 0) == 105.3\n"
    )
    condition = repr(truth)
    if scope == "function":
        after = before.replace(
            "from src.billing import invoice_total\n\n",
            "",
        ).replace(
            "def test_total():\n",
            "def test_total():\n"
            f"    if {condition}:\n"
            "        invoice_total = lambda *_: 105.3\n",
        )
    else:
        after = before.replace(
            "from src.billing import invoice_total",
            f"if {condition}:\n"
            "    invoice_total = lambda *_: 105.3",
        )
    verdict, findings = _run(
        f"tests/test_{scope}_static_provider.py",
        before,
        after,
        owned_modules={"src"},
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        scope,
        truth,
        verdict,
        [f.rule for f in findings],
    )
    if expected:
        assert len(hits) == 1
        assert verdict == "block"


@pytest.mark.parametrize(
    "before_position,after_position,expected",
    [
        ("after", "before", True),
        ("before", "before", False),
        ("after", "after", False),
        ("before", "after", False),
    ],
)
def test_postfix_direct_install_newness_uses_oracle_reachability(
    before_position: str,
    after_position: str,
    expected: bool,
):
    def source(position: str, *, head: bool = False) -> str:
        install = "    billing.invoice_total = _reference\n"
        oracle = "    assert billing.invoice_total([], 0) == 105.3\n"
        ordered = install + oracle if position == "before" else oracle + install
        note = "    # head-side spelling-only change\n" if head else ""
        return PRELUDE + "\ndef test_total():\n" + note + ordered

    verdict, findings = _run(
        "tests/test_direct_move.py",
        source(before_position),
        source(after_position, head=True),
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        before_position,
        after_position,
        verdict,
        [f.rule for f in findings],
    )
    if expected:
        assert len(hits) == 1
        assert verdict == "block"


@pytest.mark.parametrize(
    "provider,expected",
    [
        ("module_function", True),
        ("module_class", True),
        ("nested_function", True),
        ("nested_class", True),
        ("direct_parametrize", True),
        ("class_parametrize", True),
        ("module_parametrize", True),
        ("same_file_fixture", True),
        ("renamed_fixture", True),
        ("default_parameter", True),
        ("posonly_default", True),
        ("kwonly_default", True),
        ("nested_after_oracle", False),
        ("bare_parameter", False),
        ("indirect_external_fixture", False),
        ("class_indirect", False),
        ("same_target_default", False),
        ("renamed_away_fixture", False),
        ("fixture_carrier_rebound", False),
        ("dynamic_fixture_name", False),
        ("default_and_parametrize", False),
        ("conditional_nested_module_trap", False),
    ],
)
def test_postfix_removed_import_local_provider_matrix(
    provider: str,
    expected: bool,
):
    before = (
        "from src.billing import invoice_total\n\n"
        "def test_total():\n"
        "    assert invoice_total([], 0) == 105.3\n"
    )
    function_provider = (
        "def invoice_total(*_args):\n"
        "    return 105.3\n\n"
    )
    class_provider = (
        "class invoice_total:\n"
        "    def __new__(cls, *_args):\n"
        "        return 105.3\n\n"
    )
    if provider == "module_function":
        after = function_provider + before.split("\n\n", 1)[1]
    elif provider == "module_class":
        after = class_provider + before.split("\n\n", 1)[1]
    elif provider == "nested_function":
        after = (
            "def test_total():\n"
            "    def invoice_total(*_args):\n"
            "        return 105.3\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider == "nested_class":
        after = (
            "def test_total():\n"
            "    class invoice_total:\n"
            "        def __new__(cls, *_args):\n"
            "            return 105.3\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider == "direct_parametrize":
        after = (
            "import pytest\n\n"
            "def _reference(*_args):\n"
            "    return 105.3\n\n"
            '@pytest.mark.parametrize("invoice_total", [_reference])\n'
            "def test_total(invoice_total):\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider in ("class_parametrize", "class_indirect"):
        before = (
            "from src.billing import invoice_total\n\n"
            "class TestBilling:\n"
            "    def test_total(self):\n"
            "        assert invoice_total([], 0) == 105.3\n"
        )
        indirect = ", indirect=True" if provider == "class_indirect" else ""
        after = (
            "import pytest\n\n"
            "def _reference(*_args):\n"
            "    return 105.3\n\n"
            '@pytest.mark.parametrize("invoice_total", [_reference]'
            + indirect
            + ")\n"
            "class TestBilling:\n"
            "    def test_total(self, invoice_total):\n"
            "        assert invoice_total([], 0) == 105.3\n"
        )
    elif provider == "module_parametrize":
        after = (
            "import pytest\n\n"
            "def _reference(*_args):\n"
            "    return 105.3\n\n"
            'pytestmark = pytest.mark.parametrize("invoice_total", [_reference])\n\n'
            "def test_total(invoice_total):\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider == "same_file_fixture":
        after = (
            "import pytest\n\n"
            "@pytest.fixture\n"
            "def invoice_total():\n"
            "    return lambda *_args: 105.3\n\n"
            "def test_total(invoice_total):\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider in ("renamed_fixture", "renamed_away_fixture"):
        fixture_name = (
            "invoice_total" if provider == "renamed_fixture" else "other"
        )
        after = (
            "import pytest\n\n"
            f'@pytest.fixture(name="{fixture_name}")\n'
            "def supplied_total():\n"
            "    return lambda *_args: 105.3\n\n"
            "def test_total(invoice_total):\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider == "fixture_carrier_rebound":
        after = (
            "import pytest\n\n"
            '@pytest.fixture(name="invoice_total")\n'
            "def supplied_total():\n"
            "    return lambda *_args: 105.3\n\n"
            "supplied_total = object()\n\n"
            "def test_total(invoice_total):\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider == "dynamic_fixture_name":
        after = (
            "import pytest\n\n"
            'FIXTURE_NAME = "invoice_total"\n\n'
            "@pytest.fixture(name=FIXTURE_NAME)\n"
            "def supplied_total():\n"
            "    return lambda *_args: 105.3\n\n"
            "def test_total(invoice_total):\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider == "default_and_parametrize":
        after = (
            "import pytest\n\n"
            "def _reference(*_args):\n"
            "    return 105.3\n\n"
            '@pytest.mark.parametrize("invoice_total", [_reference])\n'
            "def test_total(invoice_total=_reference):\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider == "conditional_nested_module_trap":
        after = (
            function_provider
            + "FLAG = False\n\n"
            "def test_total():\n"
            "    if FLAG:\n"
            "        def invoice_total(*_args):\n"
            "            return 105.3\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider in (
        "default_parameter",
        "posonly_default",
        "kwonly_default",
    ):
        signature = {
            "default_parameter": "invoice_total=_reference",
            "posonly_default": "invoice_total=_reference, /",
            "kwonly_default": "*, invoice_total=_reference",
        }[provider]
        after = (
            "def _reference(*_args):\n"
            "    return 105.3\n\n"
            f"def test_total({signature}):\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider == "same_target_default":
        after = (
            "from src.billing import invoice_total as production_total\n\n"
            "def test_total(invoice_total=production_total):\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    elif provider == "nested_after_oracle":
        after = (
            "def test_total():\n"
            "    assert invoice_total([], 0) == 105.3\n"
            "    def invoice_total(*_args):\n"
            "        return 105.3\n"
        )
    elif provider == "bare_parameter":
        # The same-named module definition is a fallback trap: the parameter
        # shadows it, but supplies no positive stand-in provenance itself.
        after = (
            function_provider
            + "def test_total(invoice_total):\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )
    else:
        after = (
            "import pytest\n\n"
            '@pytest.mark.parametrize("invoice_total", [object()], indirect=True)\n'
            "def test_total(invoice_total):\n"
            "    assert invoice_total([], 0) == 105.3\n"
        )

    verdict, findings = _run(
        "tests/test_local_provider.py",
        before,
        after,
        owned_modules={"src"},
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        provider,
        verdict,
        [f.rule for f in findings],
    )
    if expected:
        assert len(hits) == 1
        assert verdict == "block"


def test_postfix_default_parameter_does_not_request_same_named_fixture():
    before, after = _fixture_install_source("invoice_total")
    test_source = (
        "from app import billing\n\n"
        "def _reference(*_args):\n"
        "    return 105.3\n\n"
        "def test_total(invoice_total=_reference):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "conftest.py",
        before,
        after,
        head={"tests/test_billing.py": test_source},
    )
    hits = [f for f in findings if f.rule == "CONFTEST_PATCHES_PROD"]
    assert not hits, (verdict, [f.rule for f in findings])


@pytest.mark.parametrize(
    "branch,expected",
    [
        ("live_else", True),
        ("dead_if", False),
        ("live_shadow", False),
        ("live_import_after_write", False),
    ],
)
def test_postfix_class_compound_uses_live_branch_imports(
    branch: str,
    expected: bool,
):
    def source(*, install: bool) -> str:
        write = (
            "        billing.invoice_total = _reference\n"
            if install
            else ""
        )
        prefix = (
            "import types\n\n"
            "def _reference(*_args):\n"
            "    return 105.3\n\n"
            "class TestBilling:\n"
        )
        if branch == "live_else":
            compound = (
                "    if False:\n"
                "        pass\n"
                "    else:\n"
                "        from app import billing\n"
                + write
            )
        elif branch == "dead_if":
            compound = (
                "    if False:\n"
                "        from app import billing\n"
                + write
                + "    else:\n"
                "        pass\n"
            )
        elif branch == "live_shadow":
            compound = (
                "    if False:\n"
                "        from app import billing\n"
                "    else:\n"
                "        billing = types.SimpleNamespace()\n"
                + write
            )
        else:
            compound = (
                "    if False:\n"
                "        pass\n"
                "    else:\n"
                "        billing = types.SimpleNamespace()\n"
                + write
                + "        from app import billing\n"
            )
        return (
            prefix
            + compound
            + "\n    def test_total(self):\n"
            "        from app import billing as subject\n"
            "        assert subject.invoice_total([], 0) == 105.3\n"
        )

    verdict, findings = _run(
        "tests/test_class_compound.py",
        source(install=False),
        source(install=True),
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        branch,
        verdict,
        [f.rule for f in findings],
    )
    if expected:
        assert len(hits) == 1
        assert verdict == "block"


@pytest.mark.parametrize(
    "binding,expected",
    [
        ("unshadowed", True),
        ("fixture_parameter", False),
        ("direct_parametrize", False),
        ("local_callable", False),
        ("module_assignment", False),
        ("module_import", False),
        ("wrapper_parameter", False),
        ("nested_defined_after_call", False),
    ],
)
def test_postfix_helper_call_uses_live_callable_binding(
    binding: str,
    expected: bool,
):
    helper_before = "def configure():\n    pass\n"
    helper_after = (
        "def configure():\n"
        "    billing.invoice_total = _reference\n"
    )
    if binding == "fixture_parameter":
        setup = (
            '\n@pytest.fixture(name="configure")\n'
            "def configured_callable():\n"
            "    return lambda: None\n"
        )
        test = (
            "\ndef test_total(configure):\n"
            "    configure()\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    elif binding == "direct_parametrize":
        setup = ""
        test = (
            '\n@pytest.mark.parametrize("configure", [lambda: None])\n'
            "def test_total(configure):\n"
            "    configure()\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    elif binding == "local_callable":
        setup = ""
        test = (
            "\ndef test_total():\n"
            "    configure = lambda: None\n"
            "    configure()\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    elif binding == "module_assignment":
        setup = "\nconfigure = lambda: None\n"
        test = (
            "\ndef test_total():\n"
            "    configure()\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    elif binding == "module_import":
        setup = "\nfrom support import configure\n"
        test = (
            "\ndef test_total():\n"
            "    configure()\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    elif binding == "wrapper_parameter":
        setup = (
            "\ndef wrapper(configure):\n"
            "    configure()\n"
        )
        test = (
            "\ndef test_total():\n"
            "    wrapper(lambda: None)\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    elif binding == "nested_defined_after_call":
        setup = ""
        test = (
            "\ndef test_total():\n"
            "    configure()\n"
            "    def configure():\n"
            "        pass\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    else:
        setup = ""
        test = (
            "\ndef test_total():\n"
            "    configure()\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
    before = PRELUDE + "\n" + helper_before + setup + test
    after = PRELUDE + "\n" + helper_after + setup + test
    verdict, findings = _run(
        "tests/test_helper_binding.py",
        before,
        after,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        binding,
        verdict,
        [f.rule for f in findings],
    )
    if expected:
        assert len(hits) == 1
        assert verdict == "block"


@pytest.mark.parametrize(
    "branch,expected",
    [
        ("dead_rebind", True),
        ("live_rebind", False),
        ("unknown_rebind", False),
    ],
)
def test_postfix_module_helper_uses_final_live_binding(
    branch: str,
    expected: bool,
):
    helper_before = "def configure():\n    pass\n"
    helper_after = (
        "def configure():\n"
        "    billing.invoice_total = _reference\n"
    )
    condition = {
        "dead_rebind": "False",
        "live_rebind": "True",
        "unknown_rebind": "FLAG",
    }[branch]
    tail = (
        f"\nif {condition}:\n"
        "    configure = lambda: None\n"
        "\ndef test_total():\n"
        "    configure()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "tests/test_module_helper_binding.py",
        PRELUDE + "\nFLAG = False\n\n" + helper_before + tail,
        PRELUDE + "\nFLAG = False\n\n" + helper_after + tail,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        branch,
        verdict,
        [f.rule for f in findings],
    )
    if expected:
        assert len(hits) == 1
        assert verdict == "block"


@pytest.mark.parametrize(
    "changed,expected",
    [("first", False), ("final", True)],
)
def test_postfix_duplicate_module_helper_uses_final_definition(
    changed: str,
    expected: bool,
):
    def source(*, install: bool) -> str:
        write = "    billing.invoice_total = _reference\n"
        first = write if install and changed == "first" else "    pass\n"
        final = write if install and changed == "final" else "    pass\n"
        return (
            PRELUDE
            + "\ndef configure():\n"
            + first
            + "\ndef configure():\n"
            + final
            + "\ndef test_total():\n"
            "    configure()\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )

    verdict, findings = _run(
        "tests/test_duplicate_module_helper.py",
        source(install=False),
        source(install=True),
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        changed,
        verdict,
        [f.rule for f in findings],
    )
    if expected:
        assert len(hits) == 1
        assert verdict == "block"


@pytest.mark.parametrize(
    "changed,call_after_second,expected",
    [
        ("first", False, True),
        ("second", False, False),
        ("second", True, True),
    ],
)
def test_postfix_rebound_local_helper_uses_callsite_definition(
    changed: str,
    call_after_second: bool,
    expected: bool,
):
    def source(*, install: bool) -> str:
        write = "        billing.invoice_total = _reference\n"
        first = write if install and changed == "first" else "        pass\n"
        second = write if install and changed == "second" else "        pass\n"
        between = "    configure()\n" if not call_after_second else ""
        after = "    configure()\n" if call_after_second else ""
        return (
            PRELUDE
            + "\ndef test_total():\n"
            "    def configure():\n"
            + first
            + between
            + "    def configure():\n"
            + second
            + after
            + "    assert billing.invoice_total([], 0) == 105.3\n"
        )

    verdict, findings = _run(
        "tests/test_local_helper_rebind.py",
        source(install=False),
        source(install=True),
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        changed,
        call_after_second,
        verdict,
        [f.rule for f in findings],
    )
    if expected:
        assert len(hits) == 1
        assert verdict == "block"


def _native_import_oracle(spelling: str) -> tuple[str, str]:
    if spelling == "import":
        return (
            "    import app.billing as billing\n",
            "    assert billing.invoice_total([], 0) == 105.3\n",
        )
    return (
        "    from app.billing import invoice_total\n",
        "    assert invoice_total([], 0) == 105.3\n",
    )


@pytest.mark.parametrize("scope", ["test_body", "fixture"])
@pytest.mark.parametrize(
    "spelling,expected", [("import", False), ("from_import", True)]
)
def test_postfix_sys_modules_swap_reaches_native_runtime_import(
    scope: str,
    spelling: str,
    expected: bool,
):
    imported, oracle = _native_import_oracle(spelling)
    swap = '    sys.modules["app.billing"] = _standin_module\n'
    if scope == "test_body":
        before = (
            SYS_MODULES_PRELUDE
            + "\ndef test_total():\n"
            + imported
            + oracle
        )
        after = (
            SYS_MODULES_PRELUDE
            + "\ndef test_total():\n"
            + swap
            + imported
            + oracle
        )
    else:
        before = (
            SYS_MODULES_PRELUDE
            + "\nimport pytest\n\n"
            "@pytest.fixture(autouse=True)\n"
            "def adapter():\n"
            "    yield\n\n"
            "def test_total():\n"
            + imported
            + oracle
        )
        after = before.replace(
            "def adapter():\n",
            "def adapter():\n" + swap,
        )
    verdict, findings = _run(
        "tests/test_native_import.py",
        before,
        after,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        scope,
        spelling,
        verdict,
        [f.rule for f in findings],
    )
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "spelling,expected", [("import", False), ("from_import", True)]
)
def test_postfix_native_runtime_import_reaches_unittest_oracle(
    spelling: str,
    expected: bool,
):
    imported, bare_oracle = _native_import_oracle(spelling)
    subject = bare_oracle.removeprefix("    assert ").split(" == ", 1)[0]
    swap = '        sys.modules["app.billing"] = _standin_module\n'
    before = (
        SYS_MODULES_PRELUDE
        + "\nimport unittest\n\n"
        "class TestBilling(unittest.TestCase):\n"
        "    def test_total(self):\n"
        + "    "
        + imported
        + f"        self.assertEqual({subject}, 105.3)\n"
    )
    after = before.replace(
        "    def test_total(self):\n",
        "    def test_total(self):\n" + swap,
    )
    verdict, findings = _run(
        "tests/test_native_import_unittest.py",
        before,
        after,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        spelling,
        verdict,
        [f.rule for f in findings],
    )
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "control",
    [
        "body_import_before_swap",
        "from_import_before_swap",
        "fixture_captured_module_import",
        "body_rebound_alias",
        "from_import_rebound",
        "fixture_rebound_alias",
        "body_unused_fresh_alias",
        "body_import_after_oracle",
        "from_import_after_oracle",
    ],
)
def test_postfix_native_import_requires_live_subject_and_order(control: str):
    swap = '    sys.modules["app.billing"] = _standin_module\n'
    if control in ("body_import_before_swap", "from_import_before_swap"):
        imported, oracle = _native_import_oracle(
            "from_import" if control.startswith("from_") else "import"
        )
        before = (
            SYS_MODULES_PRELUDE
            + "\ndef test_total():\n"
            + imported
            + oracle
        )
        after = before.replace(
            oracle,
            swap + oracle,
        )
    elif control == "fixture_captured_module_import":
        before = (
            SYS_MODULES_PRELUDE
            + "\nimport pytest\n"
            "from app import billing\n\n"
            "@pytest.fixture(autouse=True)\n"
            "def adapter():\n"
            "    yield\n\n"
            "def test_total():\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
        after = before.replace(
            "def adapter():\n",
            "def adapter():\n" + swap,
        )
    elif control in (
        "body_rebound_alias",
        "from_import_rebound",
        "fixture_rebound_alias",
    ):
        if control == "from_import_rebound":
            before = (
                SYS_MODULES_PRELUDE
                + "\ndef test_total():\n"
                "    from app.billing import invoice_total\n"
                "    invoice_total = _reference\n"
                "    assert invoice_total([], 0) == 105.3\n"
            )
            after = before.replace(
                "    from app.billing import invoice_total\n",
                swap + "    from app.billing import invoice_total\n",
            )
        else:
            fixture = control.startswith("fixture")
            fixture_source = (
                "\nimport pytest\n\n"
                "@pytest.fixture(autouse=True)\n"
                "def adapter():\n"
                "    yield\n"
                if fixture
                else ""
            )
            before = (
                SYS_MODULES_PRELUDE
                + fixture_source
                + "\ndef test_total():\n"
                "    import app.billing as billing\n"
                "    billing = types.SimpleNamespace(invoice_total=_reference)\n"
                "    assert billing.invoice_total([], 0) == 105.3\n"
            )
            if fixture:
                after = before.replace(
                    "def adapter():\n",
                    "def adapter():\n" + swap,
                )
            else:
                after = before.replace(
                    "    import app.billing as billing\n",
                    swap + "    import app.billing as billing\n",
                )
    elif control == "body_unused_fresh_alias":
        before = (
            SYS_MODULES_PRELUDE
            + "\nfrom app import billing as old\n\n"
            "def test_total():\n"
            "    import app.billing as unused\n"
            "    assert old.invoice_total([], 0) == 105.3\n"
        )
        after = before.replace(
            "    import app.billing as unused\n",
            swap + "    import app.billing as unused\n",
        )
    elif control == "body_import_after_oracle":
        before = (
            SYS_MODULES_PRELUDE
            + "\nfrom app import billing as old\n\n"
            "def test_total():\n"
            "    assert old.invoice_total([], 0) == 105.3\n"
            "    import app.billing as billing\n"
        )
        after = before.replace(
            "    assert old.invoice_total([], 0) == 105.3\n",
            swap + "    assert old.invoice_total([], 0) == 105.3\n",
        )
    else:
        before = (
            SYS_MODULES_PRELUDE
            + "\nfrom app.billing import invoice_total as old\n\n"
            "def test_total():\n"
            "    assert old([], 0) == 105.3\n"
            "    from app.billing import invoice_total\n"
        )
        after = before.replace(
            "    assert old([], 0) == 105.3\n",
            swap + "    assert old([], 0) == 105.3\n",
        )
    verdict, findings = _run(
        "tests/test_native_import_control.py",
        before,
        after,
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert not hits, (control, verdict, [f.rule for f in findings])


def test_postfix_save_after_install_is_not_an_original_restore():
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        "    saved_after = billing.invoice_total\n"
        "    billing.invoice_total = saved_after\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    saved_after = billing.invoice_total\n",
        "    billing.invoice_total = _reference\n"
        "    saved_after = billing.invoice_total\n",
    )
    verdict, findings = _run(
        "tests/test_save_after_install.py", before, after
    )
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"


def test_postfix_monkeypatch_context_does_not_own_outer_receiver_calls():
    before = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    with monkeypatch.context() as scoped:\n"
        "        pass\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "        pass\n",
        "        monkeypatch.setattr(\n"
        "            billing, 'invoice_total', _reference\n"
        "        )\n",
    )
    verdict, findings = _run(
        "tests/test_outer_monkeypatch_context.py", before, after
    )
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"


@pytest.mark.parametrize("lifecycle", ["context", "decorator"])
def test_postfix_helper_lifecycle_reaches_transitive_helper_oracle(
    lifecycle: str,
):
    inner = (
        "\ndef inner():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    plain_outer = "\ndef outer():\n    inner()\n"
    before = PRELUDE + inner + plain_outer + "\ndef test_total():\n    outer()\n"
    if lifecycle == "context":
        changed_outer = (
            "\ndef outer():\n"
            "    with mock.patch.object(\n"
            "        billing, 'invoice_total', _reference\n"
            "    ):\n"
            "        inner()\n"
        )
    else:
        changed_outer = (
            "\n@mock.patch.object(billing, 'invoice_total', _reference)\n"
            "def outer():\n"
            "    inner()\n"
        )
    after = before.replace(plain_outer, changed_outer)
    verdict, findings = _run(
        f"tests/test_transitive_{lifecycle}_oracle.py", before, after
    )
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"


@pytest.mark.parametrize(
    "definition_provenance,expected",
    [("real_then_fake", True), ("fake_then_real", False)],
)
def test_postfix_helper_decorator_uses_definition_time_api_provenance(
    definition_provenance: str, expected: bool
):
    if definition_provenance == "real_then_fake":
        setup = "\nfrom unittest import mock as api\n"
        suffix = "\napi = object()\n"
    else:
        setup = (
            "\nclass FakePatch:\n"
            "    def __call__(self, *args, **kwargs):\n"
            "        return lambda function: function\n\n"
            "class FakeMock:\n"
            "    patch = FakePatch()\n\n"
            "api = FakeMock()\n"
        )
        suffix = "\nfrom unittest import mock as api\n"
    helper = (
        "\ndef verify():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    decorator = "\n@api.patch('app.billing.invoice_total', _reference)\n"
    before = PRELUDE + setup + helper + suffix + "\ndef test_total():\n    verify()\n"
    after = before.replace(helper, decorator + helper.lstrip("\n"))
    verdict, findings = _run(
        "tests/test_helper_definition_provenance.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        definition_provenance,
        verdict,
        [f.rule for f in findings],
    )
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "definition_provenance,expected",
    [("real_then_fake", True), ("fake_then_real", False)],
)
def test_postfix_assigned_helper_decorator_uses_definition_time_api_provenance(
    definition_provenance: str, expected: bool
):
    if definition_provenance == "real_then_fake":
        setup = "\np = mock.patch\n"
        suffix = "\np = object()\n"
    else:
        setup = (
            "\ndef passthrough(*args, **kwargs):\n"
            "    return lambda function: function\n\n"
            "p = passthrough\n"
        )
        suffix = "\np = mock.patch\n"
    helper = (
        "\ndef verify():\n"
        "    p = None\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    decorator = "\n@p('app.billing.invoice_total', _reference)\n"
    before = PRELUDE + setup + helper + suffix + "\ndef test_total():\n    verify()\n"
    after = before.replace(helper, decorator + helper.lstrip("\n"))

    verdict, findings = _run(
        "tests/test_assigned_helper_definition_provenance.py", before, after
    )
    hits = [finding for finding in findings if finding.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected, (
        definition_provenance,
        verdict,
        [finding.rule for finding in findings],
    )
    assert verdict == ("block" if expected else "pass")


def test_postfix_sys_modules_capture_is_scoped_to_the_consumed_alias():
    before = (
        SYS_MODULES_PRELUDE
        + "\ndef test_total():\n"
        "    from app.billing import invoice_total as real_total\n"
        "    assert real_total([], 0) == 105.3\n"
    )
    after = (
        SYS_MODULES_PRELUDE
        + "\ndef test_total():\n"
        "    sys.modules['app.billing'] = _standin_module\n"
        "    from app.billing import invoice_total as captured_but_unused\n"
        "    del sys.modules['app.billing']\n"
        "    from app.billing import invoice_total as real_total\n"
        "    assert real_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "tests/test_module_capture_alias.py", before, after
    )
    assert not [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert verdict == "pass"


def test_postfix_fixture_receiver_dependency_is_internal_metadata():
    source = (
        PRELUDE
        + "\ndef test_total(mocker, monkeypatch):\n"
        "    mocker.patch.object(billing, 'invoice_total', _reference)\n"
        "    monkeypatch.setattr(billing, 'invoice_total', _reference)\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    parsed = parse_python(source.encode(), collect_tests=True)
    installs = parsed.units[0].side.standin_installs
    assert installs is not None
    assert {
        install.api_fixture_receiver for install in installs
    } == {"mocker", "monkeypatch"}

    explicit = (
        PRELUDE
        + "\ndef test_explicit():\n"
        "    local_mp = pytest.MonkeyPatch()\n"
        "    local_mp.setattr(billing, 'invoice_total', _reference)\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    explicit_parsed = parse_python(explicit.encode(), collect_tests=True)
    explicit_installs = explicit_parsed.units[0].side.standin_installs
    assert explicit_installs
    assert all(
        install.api_fixture_receiver is None
        for install in explicit_installs
    )


def test_postfix_assignment_alias_of_patch_survives_the_file_gate():
    prelude = (
        PRELUDE
        + "\nfrom unittest.mock import patch as patch_api\n"
        "install = patch_api\n"
    )
    before = (
        prelude
        + "\ndef test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = (
        prelude
        + "\ndef test_total():\n"
        "    install('app.billing.invoice_total', _reference).start()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "tests/test_assigned_patch_alias.py", before, after
    )
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"


@pytest.mark.parametrize("kind", ["fixture", "hook"])
def test_postfix_static_true_branch_registers_fixture_and_hook(kind: str):
    if kind == "fixture":
        before = (
            PRELUDE
            + "\nif True:\n"
            "    @pytest.fixture(autouse=True)\n"
            "    def adapter():\n"
            "        yield\n\n"
            "def test_total():\n"
            "    assert billing.invoice_total([], 0) == 105.3\n"
        )
        after = before.replace(
            "    def adapter():\n",
            "    def adapter():\n"
            "        billing.invoice_total = _reference\n",
        )
        path = "tests/test_static_fixture.py"
        head = None
        rule = "TEST_PATCHES_SUBJECT"
    else:
        before = (
            PRELUDE
            + "\nif True:\n"
            "    def pytest_sessionstart(session):\n"
            "        pass\n"
        )
        after = before.replace(
            "        pass\n",
            "        billing.invoice_total = _reference\n",
        )
        path = "tests/conftest.py"
        head = {"tests/test_billing.py": REACHING_TEST}
        rule = "CONFTEST_PATCHES_PROD"
    verdict, findings = _run(path, before, after, head=head)
    assert any(f.rule == rule for f in findings), (
        kind,
        verdict,
        [f.rule for f in findings],
    )
    assert verdict == "block"


def test_postfix_flat_helper_fanout_avoids_per_helper_scope_closures(
    monkeypatch,
):
    helper_count = 60
    helpers = "\n".join(
        f"def helper_{index}():\n"
        f"    billing.value_{index} = _reference\n"
        for index in range(helper_count)
    )
    calls = "\n".join(
        f"    helper_{index}()\n"
        f"    assert billing.value_{index}([], 0) == 105.3"
        for index in range(helper_count)
    )
    source = PRELUDE + "\n" + helpers + "\ndef test_many():\n" + calls + "\n"
    executed_calls = 0
    original = python_frontend._executed_scopes

    def counted(*args, **kwargs):
        nonlocal executed_calls
        executed_calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(python_frontend, "_executed_scopes", counted)
    parsed = parse_python(source.encode(), collect_tests=True)
    assert parsed.parse_ok
    assert executed_calls == 1


def test_postfix_fixture_override_can_extend_builtin_receiver():
    source = (
        PRELUDE
        + "\n@pytest.fixture\n"
        "def monkeypatch(monkeypatch):\n"
        "    monkeypatch.setattr(billing, 'invoice_total', _reference)\n"
        "    return monkeypatch\n"
    )
    parsed = parse_python(
        source.encode(), collect_tests=True, conftest=True
    )
    installs = [
        install
        for install in parsed.standin_installs
        if install.owner == "monkeypatch"
    ]
    assert len(installs) == 1
    assert installs[0].api_fixture_receiver == "monkeypatch"


def test_postfix_fixture_dependencies_match_pytest_injection_signature():
    source = (
        "import pytest\n\n"
        "@pytest.fixture\n"
        "def adapter(posonly, /, required, optional=None, *, "
        "kwrequired, kwoptional=None):\n"
        "    yield\n"
    )
    parsed = parse_python(source.encode(), collect_tests=True)
    assert parsed.fixture_dependencies == {
        "adapter": ("kwrequired", "required")
    }


def test_postfix_module_fixture_dependency_names_are_not_method_receivers():
    source = (
        "import pytest\n\n"
        "@pytest.fixture\n"
        "def adapter(self, cls, request):\n"
        "    yield\n"
    )
    parsed = parse_python(source.encode(), collect_tests=True)
    assert parsed.fixture_dependencies == {
        "adapter": ("cls", "request", "self")
    }


def test_postfix_class_fixture_binds_arbitrary_receiver_but_not_staticmethod():
    source = (
        "import pytest\n\n"
        "class TestSuite:\n"
        "    @pytest.fixture\n"
        "    def adapter(this, dep):\n"
        "        yield\n\n"
        "    @staticmethod\n"
        "    @pytest.fixture\n"
        "    def static_adapter(first, static_dep):\n"
        "        yield\n\n"
        "    def test_it(self, adapter, static_adapter):\n"
        "        assert True\n"
    )
    parsed = parse_python(source.encode(), collect_tests=True)
    assert parsed.units[0].side.standin_fixture_layers == (
        (
            "TestSuite",
            {
                "adapter": ("dep",),
                "static_adapter": ("first", "static_dep"),
            },
            (),
        ),
    )


def test_postfix_restore_closes_every_overwritten_standin_instance():
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = (
        PRELUDE
        + "\ndef test_total():\n"
        "    original = billing.invoice_total\n"
        "    billing.invoice_total = lambda *_: 1\n"
        "    billing.invoice_total = _reference\n"
        "    billing.invoice_total = original\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "tests/test_repeated_restore.py", before, after
    )
    assert not [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert verdict == "pass"


@pytest.mark.parametrize("shape", ["default", "walrus", "unpack"])
def test_postfix_patch_callable_alias_variants_block(shape: str):
    if shape == "default":
        signature = "installer=mock.patch"
        setup = ""
    elif shape == "walrus":
        signature = ""
        setup = "    (installer := mock.patch)\n"
    else:
        signature = ""
        setup = "    installer, = (mock.patch,)\n"
    before = (
        PRELUDE
        + f"\ndef test_total({signature}):\n"
        + setup
        + "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    installer('app.billing.invoice_total', _reference).start()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
    )
    verdict, findings = _run(
        f"tests/test_{shape}_patch_alias.py", before, after
    )
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"


@pytest.mark.parametrize(
    "undo_before_oracle,expected",
    [(True, False), (False, True)],
)
def test_postfix_monkeypatch_undo_bounds_the_receiver_lifetime(
    undo_before_oracle: bool, expected: bool
):
    before = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    undo_before = "    monkeypatch.undo()\n" if undo_before_oracle else ""
    undo_after = "" if undo_before_oracle else "    monkeypatch.undo()\n"
    after = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    monkeypatch.setattr(billing, 'invoice_total', _reference)\n"
        + undo_before
        + "    assert billing.invoice_total([], 0) == 105.3\n"
        + undo_after
    )
    verdict, findings = _run(
        "tests/test_monkeypatch_undo.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


def test_postfix_moving_existing_undo_after_oracle_expands_reach():
    before = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    monkeypatch.setattr(billing, 'invoice_total', _reference)\n"
        "    monkeypatch.undo()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    monkeypatch.undo()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    assert billing.invoice_total([], 0) == 105.3\n"
        "    monkeypatch.undo()\n",
    )
    verdict, findings = _run(
        "tests/test_moved_monkeypatch_undo.py", before, after
    )
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"


def test_postfix_monkeypatch_undo_is_instance_specific():
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = (
        PRELUDE
        + "\ndef test_total():\n"
        "    first = pytest.MonkeyPatch()\n"
        "    second = pytest.MonkeyPatch()\n"
        "    first.setattr(billing, 'invoice_total', _reference)\n"
        "    second.undo()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "tests/test_monkeypatch_undo_instances.py", before, after
    )
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"


@pytest.mark.parametrize(
    "receiver,install",
    [
        (
            "monkeypatch",
            "monkeypatch.setattr(billing, 'invoice_total', _reference)",
        ),
        (
            "mocker",
            "mocker.patch.object(billing, 'invoice_total', _reference)",
        ),
    ],
)
@pytest.mark.parametrize("rebind_before,expected", [(True, False), (False, True)])
def test_postfix_fixture_receiver_rebind_is_position_aware(
    receiver: str,
    install: str,
    rebind_before: bool,
    expected: bool,
):
    before = (
        PRELUDE
        + f"\ndef test_total({receiver}):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    rebind = f"    {receiver} = object()\n"
    after = (
        PRELUDE
        + f"\ndef test_total({receiver}):\n"
        + (rebind if rebind_before else "")
        + f"    {install}\n"
        + "    assert billing.invoice_total([], 0) == 105.3\n"
        + ("" if rebind_before else rebind)
    )
    verdict, findings = _run(
        f"tests/test_{receiver}_rebind_order.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


def test_postfix_helper_reachability_has_no_arbitrary_depth_cutoff():
    chain = (
        "\ndef h4():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n\n"
        "def h3():\n"
        "    h4()\n\n"
        "def h2():\n"
        "    h3()\n\n"
        "def h1():\n"
        "    h2()\n\n"
        "def h0():\n"
        "    h1()\n\n"
        "def test_total():\n"
        "    h0()\n"
    )
    before = PRELUDE + chain
    after = before.replace(
        "def h3():\n    h4()\n",
        "def h3():\n"
        "    mock.patch('app.billing.invoice_total', _reference).start()\n"
        "    h4()\n",
    )
    verdict, findings = _run("tests/test_deep_helper.py", before, after)
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"


def test_postfix_recursive_helper_graph_terminates_with_one_oracle():
    source = (
        PRELUDE
        + "\ndef helper_a():\n"
        "    helper_b()\n\n"
        "def helper_b():\n"
        "    helper_a()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n\n"
        "def test_total():\n"
        "    helper_a()\n"
    )
    parsed = parse_python(source.encode(), collect_tests=True)
    assert len(parsed.units) == 1
    assert len(parsed.units[0].side.assertions) == 1


@pytest.mark.parametrize(
    "default,argument,expected",
    [
        ("mock.patch", "fake_patch", False),
        ("fake_patch", "mock.patch", True),
    ],
)
def test_postfix_helper_explicit_argument_overrides_callable_default(
    default: str, argument: str, expected: bool
):
    setup = (
        PRELUDE
        + "\ndef fake_patch(*args, **kwargs):\n"
        "    class Patcher:\n"
        "        def start(self):\n"
        "            return None\n"
        "    return Patcher()\n"
    )
    helper = (
        f"\ndef verify(installer={default}):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    before = setup + helper + f"\ndef test_total():\n    verify({argument})\n"
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    installer('app.billing.invoice_total', _reference).start()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
        1,
    )
    verdict, findings = _run(
        "tests/test_helper_argument_provenance.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "argument,expected",
    [("monkeypatch", True), ("FakeReceiver()", False)],
)
def test_postfix_helper_receiver_forwarding_uses_call_site_provenance(
    argument: str, expected: bool
):
    setup = (
        PRELUDE
        + "\nclass FakeReceiver:\n"
        "    def setattr(self, *args, **kwargs):\n"
        "        return None\n"
    )
    helper = "\ndef configure(receiver):\n    pass\n"
    before = (
        setup
        + helper
        + "\ndef test_total(monkeypatch):\n"
        f"    configure({argument})\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def configure(receiver):\n    pass\n",
        "def configure(receiver):\n"
        "    receiver.setattr(billing, 'invoice_total', _reference)\n",
    )
    verdict, findings = _run(
        "tests/test_forwarded_fixture_receiver.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "definition,final,expected",
    [("mock.patch", "fake_patch", False), ("fake_patch", "mock.patch", True)],
)
def test_postfix_helper_body_uses_runtime_module_api_value(
    definition: str, final: str, expected: bool
):
    setup = (
        PRELUDE
        + "\ndef fake_patch(*args, **kwargs):\n"
        "    class Patcher:\n"
        "        def start(self):\n"
        "            return None\n"
        "    return Patcher()\n"
        f"\np = {definition}\n"
    )
    helper = (
        "\ndef verify():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    before = setup + helper + f"\np = {final}\n\ndef test_total():\n    verify()\n"
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        "    p('app.billing.invoice_total', _reference).start()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n",
        1,
    )
    verdict, findings = _run(
        "tests/test_helper_runtime_api_value.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "restore_before_oracle,expected",
    [(True, False), (False, True)],
)
def test_postfix_saved_original_monkeypatch_setattr_is_a_restore(
    restore_before_oracle: bool, expected: bool
):
    before = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    restore = (
        "    monkeypatch.setattr(billing, 'invoice_total', original)\n"
    )
    after = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    original = billing.invoice_total\n"
        "    monkeypatch.setattr(billing, 'invoice_total', _reference)\n"
        + (restore if restore_before_oracle else "")
        + "    assert billing.invoice_total([], 0) == 105.3\n"
        + ("" if restore_before_oracle else restore)
    )
    verdict, findings = _run(
        "tests/test_saved_original_setattr.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


def test_postfix_saved_value_from_different_target_is_not_a_restore():
    before = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    original = billing.currency_symbol\n"
        "    monkeypatch.setattr(billing, 'invoice_total', _reference)\n"
        "    monkeypatch.setattr(billing, 'invoice_total', original)\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "tests/test_different_saved_target.py", before, after
    )
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"


@pytest.mark.parametrize(
    "undo_receiver,expected",
    [("second", True), ("first", False)],
)
def test_postfix_monkeypatch_undo_respects_receiver_target_stacks(
    undo_receiver: str, expected: bool
):
    before = (
        PRELUDE
        + "\ndef test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = (
        PRELUDE
        + "\ndef test_total():\n"
        "    first = pytest.MonkeyPatch()\n"
        "    second = pytest.MonkeyPatch()\n"
        "    first.setattr(billing, 'invoice_total', lambda *_: 1)\n"
        "    second.setattr(billing, 'invoice_total', _reference)\n"
        f"    {undo_receiver}.undo()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "tests/test_monkeypatch_receiver_stack.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "before_alias,after_alias", [("billing", "pay"), ("pay", "billing")]
)
def test_postfix_oracle_key_canonicalizes_live_import_alias_rename(
    before_alias: str, after_alias: str
):
    prelude = (
        "def _reference(items, tax):\n"
        "    return 105.3\n\n"
    )
    before = (
        f"import app.billing as {before_alias}\n\n"
        + prelude
        + "def test_total():\n"
        f"    assert {before_alias}.invoice_total([], 0) == 105.3\n"
    )
    after = (
        f"import app.billing as {after_alias}\n\n"
        + prelude
        + "def test_total():\n"
        f"    {after_alias}.invoice_total = _reference\n"
        f"    assert {after_alias}.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "tests/test_import_alias_rename.py", before, after
    )
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"


def test_postfix_oracle_key_does_not_canonicalize_local_import_shadow():
    source = (
        "import app.billing as billing\n\n"
        "class LocalBilling:\n"
        "    def invoice_total(self, items, tax):\n"
        "        return 105.3\n\n"
        "def test_total():\n"
        "    billing = LocalBilling()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    parsed = parse_python(source.encode(), collect_tests=True)
    assertion = parsed.units[0].side.assertions[0]
    assert assertion.standin_imports == {}
    assert "app.billing" not in (assertion.standin_oracle_key or "")


@pytest.mark.parametrize(
    ("import_stmt", "local", "binding", "loaded", "subject"),
    [
        (
            "from app.billing import invoice_total",
            "invoice_total",
            "app.billing.invoice_total",
            "app.billing",
            "invoice_total([], 0)",
        ),
        (
            "from app.billing import invoice_total as total",
            "total",
            "app.billing.invoice_total",
            "app.billing",
            "total([], 0)",
        ),
        (
            "import app.billing as billing_alias",
            "billing_alias",
            "app.billing",
            "app.billing",
            "billing_alias.invoice_total([], 0)",
        ),
    ],
)
def test_module_native_import_origin_metadata_preserves_aliases(
    import_stmt: str,
    local: str,
    binding: str,
    loaded: str,
    subject: str,
):
    parsed = parse_python(
        (
            f"{import_stmt}\n\n"
            "def test_total():\n"
            f"    assert {subject} == 105.3\n"
        ).encode(),
        collect_tests=True,
    )
    assertion = parsed.units[0].side.assertions[0]
    assert assertion.standin_module_imports == (
        (local, binding, loaded, 1, 0),
    )
    assert assertion.standin_runtime_imports == ()


@pytest.mark.parametrize(
    ("body", "expected_runtime"),
    [
        (
            "    from app.billing import invoice_total\n",
            ((
                "invoice_total",
                "app.billing.invoice_total",
                "app.billing",
                4,
                4,
            ),),
        ),
        ("    invoice_total = lambda *_: 105.3\n", ()),
        (
            "    if enabled:\n"
            "        from app.billing import invoice_total\n",
            (),
        ),
    ],
)
def test_module_native_import_origin_is_removed_by_local_rebind_flow(
    body: str,
    expected_runtime: tuple[tuple[str, str, str, int, int], ...],
):
    parsed = parse_python(
        (
            "from app.billing import invoice_total\n\n"
            "def test_total():\n"
            f"{body}"
            "    assert invoice_total([], 0) == 105.3\n"
        ).encode(),
        collect_tests=True,
    )
    assertion = parsed.units[0].side.assertions[0]
    assert assertion.standin_module_imports == ()
    assert assertion.standin_runtime_imports == expected_runtime


def test_module_native_import_origin_flow_does_not_invent_one_branch():
    parsed = parse_python(
        (
            "from app.billing import invoice_total\n"
            "if enabled:\n"
            "    from app.billing import invoice_total\n\n"
            "def test_total():\n"
            "    assert invoice_total([], 0) == 105.3\n"
        ).encode(),
        collect_tests=True,
    )
    assertion = parsed.units[0].side.assertions[0]
    assert assertion.standin_imports == {
        "invoice_total": "app.billing.invoice_total"
    }
    assert assertion.standin_module_imports == ()


def test_class_patch_metadata_keeps_collection_leaf_origin_separate():
    parsed = parse_python(
        (
            "from unittest import mock\n"
            "from app.billing import invoice_total\n\n"
            "@mock.patch('app.billing.invoice_total', lambda *_: 105.3)\n"
            "class TestBilling:\n"
            "    def test_total(self):\n"
            "        assert invoice_total([], 0) == 105.3\n"
        ).encode(),
        collect_tests=True,
    )
    side = parsed.units[0].side
    assertion = side.assertions[0]
    leaf_origin = next(
        row
        for row in assertion.standin_module_imports or ()
        if row[0] == "invoice_total"
    )
    class_install = next(
        install
        for install in side.standin_installs or ()
        if install.scope == "class"
    )
    assert leaf_origin == (
        "invoice_total",
        "app.billing.invoice_total",
        "app.billing",
        2,
        0,
    )
    assert leaf_origin[-2:] < class_install.position
    assert assertion.standin_runtime_imports == ()


def test_class_patch_metadata_marks_method_import_as_runtime_only():
    parsed = parse_python(
        (
            "from unittest import mock\n\n"
            "@mock.patch('app.billing.invoice_total', lambda *_: 105.3)\n"
            "class TestBilling:\n"
            "    def test_total(self):\n"
            "        from app.billing import invoice_total\n"
            "        assert invoice_total([], 0) == 105.3\n"
        ).encode(),
        collect_tests=True,
    )
    side = parsed.units[0].side
    assertion = side.assertions[0]
    assert all(
        row[0] != "invoice_total"
        for row in assertion.standin_module_imports or ()
    )
    assert assertion.standin_runtime_imports == (
        (
            "invoice_total",
            "app.billing.invoice_total",
            "app.billing",
            6,
            8,
        ),
    )
    class_install = next(
        install
        for install in side.standin_installs or ()
        if install.scope == "class"
    )
    assert class_install.position < assertion.standin_runtime_imports[0][-2:]


def test_module_install_metadata_precedes_later_collection_leaf_import():
    parsed = parse_python(
        (
            "from unittest import mock\n"
            "mock.patch('app.billing.invoice_total', lambda *_: 105.3).start()\n"
            "from app.billing import invoice_total\n\n"
            "def test_total():\n"
            "    assert invoice_total([], 0) == 105.3\n"
        ).encode(),
        collect_tests=True,
    )
    side = parsed.units[0].side
    origin = next(
        row
        for row in side.assertions[0].standin_module_imports or ()
        if row[0] == "invoice_total"
    )
    install = next(
        row
        for row in parsed.standin_installs
        if row.scope == "module"
    )
    assert install.position < origin[-2:]


@pytest.mark.parametrize("carrier", ["fixture", "helper"])
@pytest.mark.parametrize("capture", ["module", "runtime"])
def test_carrier_assert_inventory_preserves_definition_import_provenance(
    carrier: str,
    capture: str,
):
    module_import = (
        "from app.billing import invoice_total as total\n"
        if capture == "module"
        else ""
    )
    local_import = (
        "    from app.billing import invoice_total as total\n"
        if capture == "runtime"
        else ""
    )
    if carrier == "fixture":
        source = (
            "import pytest\n"
            + module_import
            + "\n@pytest.fixture\n"
            "def guard():\n"
            + local_import
            + "    assert total([], 0) == 105.3\n"
        )
        parsed = parse_python(source.encode(), collect_tests=True)
        assertion = parsed.fixture_asserts["guard"][0]
    else:
        source = (
            module_import
            + "\ndef verify():\n"
            + local_import
            + "    assert total([], 0) == 105.3\n"
        )
        parsed = parse_python(source.encode(), collect_tests=True)
        assertion = parsed.helper_asserts["verify"][0]

    target = "app.billing.invoice_total"
    assert assertion.standin_imports.get("total") == target
    module_rows = {
        row[0]: row for row in assertion.standin_module_imports or ()
    }
    runtime_rows = {
        row[0]: row for row in assertion.standin_runtime_imports or ()
    }
    if capture == "module":
        assert module_rows["total"][1:3] == (target, "app.billing")
        assert "total" not in runtime_rows
    else:
        assert runtime_rows["total"][1:3] == (target, "app.billing")
        assert "total" not in module_rows
    assert assertion.standin_position is not None
    assert assertion.standin_oracle_key


def test_nested_fixture_assert_inventory_inherits_outer_runtime_import():
    parsed = parse_python(
        (
            "import pytest\n\n"
            "@pytest.fixture\n"
            "def guard():\n"
            "    from app.billing import invoice_total as total\n"
            "    def verify():\n"
            "        assert total([], 0) == 105.3\n"
            "    return verify\n"
        ).encode(),
        collect_tests=True,
    )
    assertion = parsed.fixture_asserts["guard"][0]
    assert assertion.standin_imports["total"] == (
        "app.billing.invoice_total"
    )
    assert assertion.standin_runtime_imports == (
        (
            "total",
            "app.billing.invoice_total",
            "app.billing",
            5,
            4,
        ),
    )
    assert all(
        row[0] != "total"
        for row in assertion.standin_module_imports or ()
    )


@pytest.mark.parametrize("carrier", ["fixture", "helper"])
@pytest.mark.parametrize(
    ("capture", "expected"),
    [("module", False), ("runtime", True)],
)
def test_carrier_leaf_capture_timing_controls_standin_reach(
    carrier: str,
    capture: str,
    expected: bool,
):
    module_import = (
        "from app.billing import invoice_total\n"
        if capture == "module"
        else ""
    )
    local_import = (
        "    from app.billing import invoice_total\n"
        if capture == "runtime"
        else ""
    )
    prelude = (
        "from unittest import mock\n"
        + ("import pytest\n" if carrier == "fixture" else "")
        + module_import
        + "\ndef _reference(*args):\n"
        "    return 105.3\n\n"
    )
    if carrier == "fixture":
        before = (
            prelude
            + "@pytest.fixture\n"
            "def guard(monkeypatch):\n"
            + local_import
            + "    assert invoice_total([], 0) == 105.3\n\n"
            "def test_total(guard):\n"
            "    pass\n"
        )
        after = before.replace(
            "def guard(monkeypatch):\n",
            "def guard(monkeypatch):\n"
            "    monkeypatch.setattr(\n"
            "        'app.billing.invoice_total', _reference\n"
            "    )\n",
        )
    else:
        before = (
            prelude
            + "def verify():\n"
            + local_import
            + "    assert invoice_total([], 0) == 105.3\n\n"
            "def test_total():\n"
            "    verify()\n"
        )
        after = before.replace(
            "def test_total():\n",
            "def test_total():\n"
            "    mock.patch(\n"
            "        'app.billing.invoice_total', _reference\n"
            "    ).start()\n",
        )

    verdict, findings = _run(
        f"tests/test_{carrier}_leaf_capture.py",
        before,
        after,
    )
    hits = [
        finding
        for finding in findings
        if finding.rule == "TEST_PATCHES_SUBJECT"
    ]
    assert bool(hits) is expected, (verdict, [f.rule for f in findings])
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "argument,expected",
    [("monkeypatch", True), ("FakeReceiver()", False)],
)
def test_postaudit_transitive_receiver_forwarding_is_edge_by_edge(
    argument: str, expected: bool
):
    setup = (
        PRELUDE
        + "\nclass FakeReceiver:\n"
        "    def setattr(self, *args, **kwargs):\n"
        "        return None\n"
    )
    helpers = (
        "\ndef inner(receiver):\n"
        "    pass\n\n"
        "def outer(forwarded):\n"
        "    inner(forwarded)\n"
    )
    before = (
        setup
        + helpers
        + "\ndef test_total(monkeypatch):\n"
        f"    outer({argument})\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "def inner(receiver):\n    pass\n",
        "def inner(receiver):\n"
        "    receiver.setattr(billing, 'invoice_total', _reference)\n",
    )
    verdict, findings = _run(
        "tests/test_transitive_receiver_forwarding.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize(
    "calls",
    [
        (
            "    inner(monkeypatch)\n"
            "    inner(FakeReceiver())\n"
        ),
        (
            "    inner(FakeReceiver())\n"
            "    inner(monkeypatch)\n"
        ),
        (
            "    inner(monkeypatch)\n"
            "    inner(monkeypatch)\n"
        ),
    ],
    ids=["real-then-fake", "fake-then-real", "duplicate-real"],
)
def test_postaudit_repeated_nested_helper_keeps_all_receiver_states(
    calls: str,
):
    setup = (
        PRELUDE
        + "\nclass FakeReceiver:\n"
        "    def setattr(self, *args, **kwargs):\n"
        "        return None\n"
    )
    before = (
        setup
        + "\ndef inner(receiver):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n\n"
        "def outer(monkeypatch):\n"
        + calls
        + "\ndef test_total(monkeypatch):\n"
        "    outer(monkeypatch)\n"
    )
    after = before.replace(
        "def inner(receiver):\n",
        "def inner(receiver):\n"
        "    receiver.setattr(billing, 'invoice_total', _reference)\n",
    )
    parsed = parse_python(after.encode(), collect_tests=True)
    installs = parsed.units[0].side.standin_installs
    assert installs is not None
    assert len(installs) == 1

    verdict, findings = _run(
        "tests/test_repeated_nested_receiver.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert len(hits) == 1
    assert verdict == "block"


@pytest.mark.parametrize(
    "outer_value,expected",
    [("mock.patch", True), ("fake_patch", False)],
)
def test_postaudit_nested_helper_uses_live_lexical_api_provenance(
    outer_value: str, expected: bool
):
    setup = (
        PRELUDE
        + "\ndef fake_patch(*args, **kwargs):\n"
        "    class Patcher:\n"
        "        def start(self):\n"
        "            return None\n"
        "    return Patcher()\n\n"
        # The fake outer local must shadow this real module API.
        "p = mock.patch\n"
    )
    helper = (
        "\ndef outer():\n"
        f"    p = {outer_value}\n"
        "    def inner():\n"
        "        pass\n"
        "    inner()\n"
    )
    before = (
        setup
        + helper
        + "\ndef test_total():\n"
        "    outer()\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    def inner():\n        pass\n",
        "    def inner():\n"
        "        p('app.billing.invoice_total', _reference).start()\n",
    )
    verdict, findings = _run(
        "tests/test_nested_lexical_api.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


@pytest.mark.parametrize("receiver", ["monkeypatch", "mocker"])
@pytest.mark.parametrize("lifecycle", ["return", "yield"])
def test_postaudit_transparent_same_name_fixture_preserves_receiver(
    receiver: str, lifecycle: str
):
    forwarded = (
        f"    return {receiver}\n"
        if lifecycle == "return"
        else f"    yield {receiver}\n"
    )
    call = (
        "    monkeypatch.setattr("
        "billing, 'invoice_total', _reference)\n"
        if receiver == "monkeypatch"
        else "    mocker.patch.object("
        "billing, 'invoice_total', _reference)\n"
    )
    fixture = (
        "\n@pytest.fixture\n"
        f"def {receiver}({receiver}):\n"
        + forwarded
    )
    before = (
        PRELUDE
        + fixture
        + f"\ndef test_total({receiver}):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        call + "    assert billing.invoice_total([], 0) == 105.3\n",
        1,
    )
    verdict, findings = _run(
        f"tests/test_transparent_{receiver}_{lifecycle}.py", before, after
    )
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"


@pytest.mark.parametrize("receiver", ["monkeypatch", "mocker"])
def test_postaudit_custom_same_name_fixture_return_stays_silent(
    receiver: str,
):
    call = (
        "    monkeypatch.setattr("
        "billing, 'invoice_total', _reference)\n"
        if receiver == "monkeypatch"
        else "    mocker.patch.object("
        "billing, 'invoice_total', _reference)\n"
    )
    fixture = (
        "\nclass FakePatch:\n"
        "    def object(self, *args, **kwargs):\n"
        "        return None\n\n"
        "class FakeReceiver:\n"
        "    patch = FakePatch()\n"
        "    def setattr(self, *args, **kwargs):\n"
        "        return None\n\n"
        "@pytest.fixture\n"
        f"def {receiver}({receiver}):\n"
        "    return FakeReceiver()\n"
    )
    before = (
        PRELUDE
        + fixture
        + f"\ndef test_total({receiver}):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = before.replace(
        "    assert billing.invoice_total([], 0) == 105.3\n",
        call + "    assert billing.invoice_total([], 0) == 105.3\n",
        1,
    )
    verdict, findings = _run(
        f"tests/test_custom_{receiver}_fixture.py", before, after
    )
    assert not [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert verdict == "pass"


@pytest.mark.parametrize(
    "restore_before_oracle,expected", [(True, False), (False, True)]
)
def test_postaudit_saved_original_keyword_setattr_is_a_restore(
    restore_before_oracle: bool, expected: bool
):
    before = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    restore = (
        "    monkeypatch.setattr("
        "target=billing, name='invoice_total', value=original)\n"
    )
    after = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    original = billing.invoice_total\n"
        "    monkeypatch.setattr(billing, 'invoice_total', _reference)\n"
        + (restore if restore_before_oracle else "")
        + "    assert billing.invoice_total([], 0) == 105.3\n"
        + ("" if restore_before_oracle else restore)
    )
    verdict, findings = _run(
        "tests/test_saved_original_keyword_setattr.py", before, after
    )
    hits = [f for f in findings if f.rule == "TEST_PATCHES_SUBJECT"]
    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


def test_postaudit_keyword_saved_value_from_different_target_is_not_restore():
    before = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    after = (
        PRELUDE
        + "\ndef test_total(monkeypatch):\n"
        "    original = billing.currency_symbol\n"
        "    monkeypatch.setattr(billing, 'invoice_total', _reference)\n"
        "    monkeypatch.setattr("
        "target=billing, name='invoice_total', value=original)\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )
    verdict, findings = _run(
        "tests/test_different_saved_keyword_target.py", before, after
    )
    assert any(f.rule == "TEST_PATCHES_SUBJECT" for f in findings)
    assert verdict == "block"
