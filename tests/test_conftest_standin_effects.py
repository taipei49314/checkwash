"""Side-aware conftest stand-in activation and oracle semantics (#91)."""

from __future__ import annotations

import datetime

import pytest

from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.pyenv import known_baseline


TODAY = datetime.date(2026, 1, 1)
ORACLE = "    assert billing.invoice_total([], 0) == expected\n"
ROOT_STANDIN = """\
import pytest
from app import billing


def _reference(*args):
    return 105.3


@pytest.fixture
def standin(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", _reference)
    yield
"""


def _change(path: str, before: str | None, after: str | None) -> FileChange:
    return FileChange(
        path=path,
        status=(
            "added" if before is None else "deleted" if after is None else "modified"
        ),
        before=before.encode() if before is not None else None,
        after=after.encode() if after is not None else None,
    )


def _run(
    changes: list[FileChange],
    head: dict[str, str],
    *,
    self_modules: set[str] | None = None,
    external_modules: set[str] | None = None,
    reads: list[str] | None = None,
    rule: str = "CONFTEST_PATCHES_PROD",
):
    encoded = {path: source.encode() for path, source in head.items()}

    def read_head(path: str) -> bytes | None:
        if reads is not None:
            reads.append(path)
        return encoded.get(path)

    _ir, findings, verdict = analyze(
        changes,
        Config(),
        Contract(),
        [],
        TODAY,
        known_modules=(
            known_baseline()
            | {"pytest"}
            | set(external_modules or ())
        ),
        self_modules={"app"} if self_modules is None else self_modules,
        head_reader=read_head,
        head_exists=lambda path: path in encoded,
        head_searcher=lambda needles: [
            path
            for path, data in sorted(encoded.items())
            if any(needle.encode() in data for needle in needles)
        ],
    )
    hits = [
        finding
        for finding in findings
        if finding.rule == rule and not finding.allowlisted
    ]
    return verdict, hits


def _test_source(signature: str = "", decorator: str = "") -> str:
    return (
        "import pytest\n"
        "from app import billing\n\n"
        f"{decorator}"
        f"def test_total({signature}):\n"
        "    expected = 105.3\n"
        f"{ORACLE}"
    )


@pytest.mark.parametrize(
    ("activation", "after"),
    [
        ("parameter", _test_source("standin")),
        (
            "usefixtures",
            _test_source(decorator='@pytest.mark.usefixtures("standin")\n'),
        ),
    ],
)
def test_unchanged_conftest_fixture_activated_by_changed_test_blocks(
    activation: str, after: str
):
    before = _test_source()

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "conftest.py": ROOT_STANDIN,
            "tests/test_billing.py": after,
        },
    )

    assert len(hits) == 1, activation
    assert hits[0].path == "conftest.py"
    assert verdict == "block"


def test_direct_parametrize_shadows_unchanged_conftest_fixture():
    before = _test_source()
    after = _test_source(
        "standin",
        '@pytest.mark.parametrize("standin", [object()])\n',
    )

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "conftest.py": ROOT_STANDIN,
            "tests/test_billing.py": after,
        },
    )

    assert hits == []
    assert verdict == "pass"


def test_class_fixture_shadows_root_provider_for_its_test():
    before = """\
import pytest
from app import billing


class TestBilling:
    @pytest.fixture
    def standin(self):
        return object()

    def test_total(self):
        expected = 105.3
        assert billing.invoice_total([], 0) == expected
"""
    after = before.replace(
        "def test_total(self):", "def test_total(self, standin):"
    )

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "conftest.py": ROOT_STANDIN,
            "tests/test_billing.py": after,
        },
    )

    assert hits == []
    assert verdict == "pass"


def test_class_fixture_can_shadow_injected_monkeypatch_receiver():
    before = """\
import pytest
from app import billing


class TestBilling:
    @pytest.fixture
    def monkeypatch(self):
        return object()

    def test_total(self):
        expected = 105.3
        assert billing.invoice_total([], 0) == expected
"""
    after = before.replace(
        "def test_total(self):", "def test_total(self, standin):"
    )

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "conftest.py": ROOT_STANDIN,
            "tests/test_billing.py": after,
        },
    )

    assert hits == []
    assert verdict == "pass"


def test_same_name_fixture_override_can_request_parent_provider():
    child_conftest = """\
import pytest


@pytest.fixture
def standin(standin):
    return standin
"""
    before = _test_source()
    after = _test_source("standin")

    verdict, hits = _run(
        [_change("tests/sub/test_billing.py", before, after)],
        {
            "conftest.py": ROOT_STANDIN,
            "tests/sub/conftest.py": child_conftest,
            "tests/sub/test_billing.py": after,
        },
    )

    assert len(hits) == 1
    assert hits[0].path == "conftest.py"
    assert verdict == "block"


def test_direct_param_provider_satisfies_an_adapter_dependency():
    conftest = ROOT_STANDIN + """

@pytest.fixture
def adapter(standin):
    return standin
"""
    before = _test_source(
        "standin",
        '@pytest.mark.parametrize("standin", [object()])\n',
    )
    after = before.replace(
        '@pytest.mark.parametrize("standin", [object()])\n',
        '@pytest.mark.parametrize("standin", [object()])\n'
        '@pytest.mark.usefixtures("adapter")\n',
    )

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "conftest.py": conftest,
            "tests/test_billing.py": after,
        },
    )

    assert hits == []
    assert verdict == "pass"


def test_direct_param_can_shadow_injected_mocker_receiver():
    conftest = """\
import pytest
from app import billing


def _reference(*args):
    return 105.3


@pytest.fixture
def standin(mocker):
    mocker.patch.object(billing, "invoice_total", _reference)
    yield
"""
    before = _test_source(
        "mocker",
        '@pytest.mark.parametrize("mocker", [object()])\n',
    )
    after = before.replace(
        '@pytest.mark.parametrize("mocker", [object()])\n',
        '@pytest.mark.parametrize("mocker", [object()])\n'
        '@pytest.mark.usefixtures("standin")\n',
    )

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "conftest.py": conftest,
            "tests/test_billing.py": after,
        },
    )

    assert hits == []
    assert verdict == "pass"


@pytest.mark.parametrize("provider", ["ancestor", "class", "parametrize"])
def test_test_local_receiver_resolves_to_active_non_plugin_provider(
    provider: str,
):
    if provider == "class":
        before = """\
import pytest
from app import billing


def _reference(*args):
    return 105.3


class TestBilling:
    @pytest.fixture
    def monkeypatch(self):
        return object()

    def test_total(self):
        expected = 105.3
        assert billing.invoice_total([], 0) == expected
"""
        after = before.replace(
            "def test_total(self):\n",
            "def test_total(self, monkeypatch):\n"
            '        monkeypatch.setattr(billing, "invoice_total", _reference)\n',
        )
        head = {"tests/test_billing.py": after}
    else:
        before = _test_source()
        decorator = (
            '@pytest.mark.parametrize("monkeypatch", [object()])\n'
            if provider == "parametrize"
            else ""
        )
        after = _test_source("monkeypatch", decorator).replace(
            "    expected = 105.3\n",
            '    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)\n'
            "    expected = 105.3\n",
        )
        head = {"tests/test_billing.py": after}
        if provider == "ancestor":
            head["conftest.py"] = """\
import pytest


@pytest.fixture
def monkeypatch():
    return object()
"""

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        head,
        rule="TEST_PATCHES_SUBJECT",
    )

    assert hits == []
    assert verdict == "pass"


def test_repeated_source_parse_is_independent_across_fixture_environments():
    before = _test_source()
    after = _test_source("monkeypatch").replace(
        "    expected = 105.3\n",
        '    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)\n'
        "    expected = 105.3\n",
    )
    local_provider = """\
import pytest


@pytest.fixture
def monkeypatch():
    return object()
"""

    verdict, hits = _run(
        [
            _change("tests/a/test_billing.py", before, after),
            _change("tests/b/test_billing.py", before, after),
        ],
        {
            "tests/a/conftest.py": local_provider,
            "tests/a/test_billing.py": after,
            "tests/b/test_billing.py": after,
        },
        rule="TEST_PATCHES_SUBJECT",
    )

    assert [hit.path for hit in hits] == ["tests/b/test_billing.py"]
    assert verdict == "block"


@pytest.mark.parametrize("parent_provider", [False, True])
def test_same_name_receiver_fixture_uses_previous_provider(
    parent_provider: bool,
):
    conftest = """\
import pytest
from app import billing


@pytest.fixture
def monkeypatch(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)
    yield
"""
    before = _test_source()
    after = _test_source("monkeypatch")
    head = {
        "tests/conftest.py": conftest,
        "tests/test_billing.py": after,
    }
    if parent_provider:
        head["conftest.py"] = """\
import pytest


@pytest.fixture
def monkeypatch():
    return object()
"""

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        head,
    )

    assert bool(hits) is (not parent_provider)
    assert verdict == ("pass" if parent_provider else "block")


@pytest.mark.parametrize("adapter_signature", ["standin=None", "standin, /"])
def test_optional_or_positional_only_fixture_parameter_is_not_injected(
    adapter_signature: str,
):
    conftest = ROOT_STANDIN + f"""


@pytest.fixture
def adapter({adapter_signature}):
    return None
"""
    before = _test_source()
    after = _test_source("adapter")

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "conftest.py": conftest,
            "tests/test_billing.py": after,
        },
    )

    assert hits == []
    assert verdict == "pass"


def test_changed_adapter_dependency_activates_unchanged_install():
    before = ROOT_STANDIN + """

@pytest.fixture
def adapter():
    return None
"""
    after = before.replace("def adapter():", "def adapter(standin):")
    test_source = _test_source("adapter")

    verdict, hits = _run(
        [_change("conftest.py", before, after)],
        {"tests/test_billing.py": test_source},
    )

    assert len(hits) == 1
    assert verdict == "block"


def test_changed_adapter_activates_unchanged_test_module_install():
    before = """\
import pytest


@pytest.fixture
def adapter():
    return None
"""
    after = before.replace("def adapter():", "def adapter(standin):")
    unchanged_test = """\
import pytest
from app import billing


def _reference(*args):
    return 105.3


@pytest.fixture
def standin(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", _reference)
    yield


def test_total(adapter):
    expected = 105.3
    assert billing.invoice_total([], 0) == expected
"""

    verdict, hits = _run(
        [_change("conftest.py", before, after)],
        {
            "conftest.py": after,
            "tests/test_billing.py": unchanged_test,
        },
        rule="TEST_PATCHES_SUBJECT",
    )

    assert len(hits) == 1
    assert hits[0].path == "tests/test_billing.py"
    assert verdict == "block"


def test_changed_adapter_does_not_activate_dormant_test_module_install():
    before = """\
import pytest


@pytest.fixture
def adapter():
    return None
"""
    after = before.replace("def adapter():", "def adapter(standin):")
    unchanged_test = """\
import pytest
from app import billing


@pytest.fixture
def standin(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)
    yield


def test_total():
    expected = 105.3
    assert billing.invoice_total([], 0) == expected
"""

    verdict, hits = _run(
        [_change("conftest.py", before, after)],
        {
            "conftest.py": after,
            "tests/test_billing.py": unchanged_test,
        },
        rule="TEST_PATCHES_SUBJECT",
    )

    assert hits == []
    assert verdict == "pass"


def test_changed_adapter_respects_test_module_receiver_shadow():
    before = """\
import pytest


@pytest.fixture
def adapter():
    return None
"""
    after = before.replace("def adapter():", "def adapter(standin):")
    unchanged_test = """\
import pytest
from app import billing


@pytest.fixture
def monkeypatch():
    return object()


@pytest.fixture
def standin(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)
    yield


def test_total(adapter):
    expected = 105.3
    assert billing.invoice_total([], 0) == expected
"""

    verdict, hits = _run(
        [_change("conftest.py", before, after)],
        {
            "conftest.py": after,
            "tests/test_billing.py": unchanged_test,
        },
        rule="TEST_PATCHES_SUBJECT",
    )

    assert hits == []
    assert verdict == "pass"


def test_nested_conftest_autouse_dependency_activates_root_install():
    before = """\
import pytest


@pytest.fixture(autouse=True)
def adapter():
    return None
"""
    after = before.replace("def adapter():", "def adapter(standin):")
    test_source = _test_source()

    verdict, hits = _run(
        [_change("tests/sub/conftest.py", before, after)],
        {
            "conftest.py": ROOT_STANDIN,
            "tests/sub/conftest.py": after,
            "tests/sub/test_billing.py": test_source,
        },
    )

    assert len(hits) == 1
    assert hits[0].path == "conftest.py"
    assert verdict == "block"


def test_changed_parent_dependency_can_activate_descendant_provider():
    before = """\
import pytest


@pytest.fixture
def adapter():
    return None
"""
    after = before.replace("def adapter():", "def adapter(standin):")
    child_conftest = ROOT_STANDIN.replace(
        "from app import billing\n", "from app import billing\n"
    )
    test_source = _test_source("adapter")

    verdict, hits = _run(
        [_change("conftest.py", before, after)],
        {
            "tests/sub/conftest.py": child_conftest,
            "tests/sub/test_billing.py": test_source,
        },
    )

    assert len(hits) == 1
    assert hits[0].path == "tests/sub/conftest.py"
    assert verdict == "block"


def test_function_nested_pytest_sessionstart_is_not_a_live_hook():
    install = '    billing.invoice_total = lambda *_: 105.3\n'
    hook = "def outer():\n    def pytest_sessionstart(session):\n" + "    " + install
    before = "from app import billing\n"
    after = before + "\n" + hook

    verdict, hits = _run(
        [_change("tests/conftest.py", before, after)],
        {"tests/test_billing.py": _test_source()},
    )

    assert hits == []
    assert verdict == "pass"


@pytest.mark.parametrize(
    ("hook_name", "conftest_path", "test_path", "expected"),
    [
        ("pytest_configure", "conftest.py", "tests/test_billing.py", True),
        ("pytest_configure", "tests/conftest.py", "tests/test_billing.py", True),
        (
            "pytest_configure",
            "tests/sub/conftest.py",
            "tests/sub/test_billing.py",
            True,
        ),
        ("pytest_sessionstart", "conftest.py", "tests/test_billing.py", True),
        (
            "pytest_sessionstart",
            "tests/conftest.py",
            "tests/test_billing.py",
            True,
        ),
        (
            "pytest_sessionstart",
            "tests/sub/conftest.py",
            "tests/sub/test_billing.py",
            False,
        ),
        (
            "pytest_sessionstart",
            "spec/conftest.py",
            "spec/test_billing.py",
            False,
        ),
    ],
)
def test_import_before_hook_requires_an_initial_conftest_provider(
    hook_name: str,
    conftest_path: str,
    test_path: str,
    expected: bool,
):
    parameter = "config" if hook_name == "pytest_configure" else "session"
    before = "from app import billing\n"
    after = (
        before
        + f"\ndef {hook_name}({parameter}):\n"
        + "    billing.invoice_total = lambda *_: 105.3\n"
    )

    verdict, hits = _run(
        [_change(conftest_path, before, after)],
        {test_path: _test_source()},
    )

    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


def test_new_oracle_does_not_turn_an_old_standin_into_an_event():
    before = "def test_total():\n    pass\n"
    after = _test_source("standin")

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "conftest.py": ROOT_STANDIN,
            "tests/test_billing.py": after,
        },
    )

    assert hits == []
    assert verdict == "pass"


def test_oracle_shape_change_spends_new_reach_but_formatting_does_not():
    before = _test_source()
    semantic_change = _test_source("standin").replace(
        "== expected", "== expected + 1"
    )
    formatting_only = _test_source("standin").replace(
        "billing.invoice_total([], 0) == expected",
        "billing.invoice_total([],0)==expected",
    )

    semantic_verdict, semantic_hits = _run(
        [_change("tests/test_billing.py", before, semantic_change)],
        {
            "conftest.py": ROOT_STANDIN,
            "tests/test_billing.py": semantic_change,
        },
    )
    formatting_verdict, formatting_hits = _run(
        [_change("tests/test_billing.py", before, formatting_only)],
        {
            "conftest.py": ROOT_STANDIN,
            "tests/test_billing.py": formatting_only,
        },
    )

    assert semantic_hits == []
    assert semantic_verdict == "pass"
    assert len(formatting_hits) == 1
    assert formatting_verdict == "block"


def test_new_identical_oracle_only_spends_its_own_reach_occurrence():
    before = _test_source()
    after = _test_source("standin") + """

def test_other():
    expected = 105.3
    assert billing.invoice_total([], 0) == expected
"""

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "conftest.py": ROOT_STANDIN,
            "tests/test_billing.py": after,
        },
    )

    assert len(hits) == 1
    assert verdict == "block"


def test_dormant_candidate_does_not_trigger_ownership_probe():
    before = """\
import pytest
import localpkg.billing as billing


@pytest.fixture
def standin():
    yield
"""
    after = before.replace(
        "def standin():\n",
        "def standin():\n    billing.invoice_total = lambda *_: 105.3\n",
    )
    test_source = """\
import localpkg.billing as billing


def test_total():
    assert billing.invoice_total([], 0) == 105.3
"""
    reads: list[str] = []

    verdict, hits = _run(
        [_change("conftest.py", before, after)],
        {
            "src/localpkg/billing.py": "def invoice_total(*args): return 0\n",
            "tests/test_billing.py": test_source,
        },
        self_modules=set(),
        reads=reads,
    )

    assert hits == []
    assert verdict == "pass"
    assert "src/localpkg/billing.py" not in reads


def test_conftest_relocation_compares_actual_base_and_head_paths():
    source = ROOT_STANDIN.replace(
        "@pytest.fixture\ndef standin",
        "@pytest.fixture(autouse=True)\ndef standin",
    )
    test_source = _test_source()
    change = _change("tests/b/conftest.py", source, source)
    change.old_path = "tests/a/conftest.py"

    verdict, hits = _run(
        [change],
        {
            "tests/b/conftest.py": source,
            "tests/b/test_billing.py": test_source,
        },
    )

    assert len(hits) == 1
    assert hits[0].path == "tests/b/conftest.py"
    assert verdict == "block"


def test_test_relocation_uses_each_sides_conftest_ancestry():
    source = ROOT_STANDIN.replace(
        "@pytest.fixture\ndef standin",
        "@pytest.fixture(autouse=True)\ndef standin",
    )
    test_source = _test_source()
    change = _change("tests/b/test_billing.py", test_source, test_source)
    change.old_path = "tests/a/test_billing.py"

    verdict, hits = _run(
        [change],
        {
            "tests/b/conftest.py": source,
            "tests/b/test_billing.py": test_source,
        },
    )

    assert len(hits) == 1
    assert hits[0].path == "tests/b/conftest.py"
    assert verdict == "block"


def test_relocated_test_does_not_borrow_head_fixture_oracle_for_base():
    before_provider = """\
import pytest
from app import billing


@pytest.fixture
def verify():
    assert billing.invoice_total([], 0) == 1
"""
    after_provider = """\
import pytest
from app import billing


@pytest.fixture
def verify():
    assert billing.invoice_total([], 0) == 2


@pytest.fixture(autouse=True)
def standin(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", lambda *_: 2)
    yield
"""
    test_source = "def test_total(verify):\n    pass\n"
    change = _change("tests/b/test_billing.py", test_source, test_source)
    change.old_path = "tests/a/test_billing.py"

    _verdict, hits = _run(
        [change],
        {
            "tests/a/conftest.py": before_provider,
            "tests/b/conftest.py": after_provider,
            "tests/b/test_billing.py": test_source,
        },
    )

    # The only head oracle is new shape ``== 2``. It spends the newly
    # reaching effect occurrence; borrowing it into base would invent a hit.
    assert hits == []


def test_duplicate_effect_text_emits_one_public_finding():
    before = """\
import pytest
from app import billing


def _reference(*args):
    return 105.3


@pytest.fixture(autouse=True)
def one():
    yield


@pytest.fixture(autouse=True)
def two():
    yield
"""
    after = before.replace(
        "def one():\n",
        "def one():\n    billing.invoice_total = _reference\n",
    ).replace(
        "def two():\n",
        "def two():\n    billing.invoice_total = _reference\n",
    )

    verdict, hits = _run(
        [_change("conftest.py", before, after)],
        {"tests/test_billing.py": _test_source()},
    )

    assert len(hits) == 1
    assert verdict == "block"


@pytest.mark.parametrize(
    ("dangerous_carrier", "expected"),
    [("aaa", False), ("zzz", True)],
)
def test_duplicate_public_fixture_name_uses_dir_order_registration_winner(
    dangerous_carrier: str, expected: bool
):
    def carrier(name: str) -> str:
        if name == dangerous_carrier:
            return f'''\
@pytest.fixture(name="standin")
def {name}(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", _reference)
    yield
'''
        return f'''\
@pytest.fixture(name="standin")
def {name}():
    return object()
'''

    conftest = (
        "import pytest\n"
        "from app import billing\n\n"
        "def _reference(*args): return 105.3\n\n"
        + carrier("aaa")
        + "\n"
        + carrier("zzz")
    )
    before = _test_source()
    after = _test_source("standin")

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "conftest.py": conftest,
            "tests/test_billing.py": after,
        },
    )

    assert bool(hits) is expected
    assert verdict == ("block" if expected else "pass")


def test_unparseable_searched_test_candidate_fails_closed():
    before = ROOT_STANDIN
    after = before.replace(
        "@pytest.fixture\ndef standin",
        "@pytest.fixture(autouse=True)\ndef standin",
    )
    newer_python_test = (
        "from app import billing\n"
        "type Alias[T = int] = T\n\n"
        "def test_total():\n"
        "    expected = 105.3\n"
        "    assert billing.invoice_total([], 0) == expected\n"
    )

    with pytest.raises(
        EngineError,
        match=(
            r"head reader could not parse searched test candidate: "
            r"tests/test_newer_python\.py"
        ),
    ):
        _run(
            [_change("conftest.py", before, after)],
            {"tests/test_newer_python.py": newer_python_test},
        )


def test_unparseable_sibling_of_changed_conftest_is_not_inventoried():
    before = ROOT_STANDIN
    after = before.replace(
        "@pytest.fixture\ndef standin",
        "@pytest.fixture(autouse=True)\ndef standin",
    )
    newer_python_test = (
        "from app import billing\n"
        "type Alias[T = int] = T\n\n"
        "def test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )

    verdict, hits = _run(
        [_change("tests/a/conftest.py", before, after)],
        {
            "tests/a/conftest.py": after,
            "tests/a/test_billing.py": _test_source(),
            "tests/b/test_newer_python.py": newer_python_test,
        },
    )

    assert len(hits) == 1
    assert hits[0].path == "tests/a/conftest.py"
    assert verdict == "block"


def test_unparseable_test_below_changed_conftest_still_fails_closed():
    before = ROOT_STANDIN
    after = before.replace(
        "@pytest.fixture\ndef standin",
        "@pytest.fixture(autouse=True)\ndef standin",
    )
    newer_python_test = (
        "from app import billing\n"
        "type Alias[T = int] = T\n\n"
        "def test_total():\n"
        "    assert billing.invoice_total([], 0) == 105.3\n"
    )

    with pytest.raises(
        EngineError,
        match=(
            r"head reader could not parse searched test candidate: "
            r"tests/a/test_newer_python\.py"
        ),
    ):
        _run(
            [_change("tests/a/conftest.py", before, after)],
            {
                "tests/a/conftest.py": after,
                "tests/a/test_newer_python.py": newer_python_test,
            },
        )


def test_unparseable_searched_descendant_provider_fails_closed():
    before = """\
import pytest


@pytest.fixture
def adapter():
    return None
"""
    after = before.replace("def adapter():", "def adapter(standin):")
    newer_python_provider = """\
import pytest
type Alias[T = int] = T


@pytest.fixture
def standin():
    return object()
"""

    with pytest.raises(
        EngineError,
        match=(
            r"head reader could not parse searched conftest provider: "
            r"tests/sub/conftest\.py"
        ),
    ):
        _run(
            [_change("conftest.py", before, after)],
            {"tests/sub/conftest.py": newer_python_provider},
        )


@pytest.mark.parametrize("scope", ["module", "class"])
def test_same_name_local_receiver_fixture_uses_builtin_parent(scope: str):
    if scope == "module":
        before = """\
import pytest
from app import billing


def _reference(*args):
    return 105.3


@pytest.fixture
def monkeypatch(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", _reference)
    yield


def test_total():
    expected = 105.3
    assert billing.invoice_total([], 0) == expected
"""
        after = before.replace("def test_total():", "def test_total(monkeypatch):")
    else:
        before = """\
import pytest
from app import billing


def _reference(*args):
    return 105.3


class TestBilling:
    @pytest.fixture
    def monkeypatch(self, monkeypatch):
        monkeypatch.setattr(billing, "invoice_total", _reference)
        yield

    def test_total(self):
        expected = 105.3
        assert billing.invoice_total([], 0) == expected
"""
        after = before.replace(
            "def test_total(self):", "def test_total(self, monkeypatch):"
        )

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {"tests/test_billing.py": after},
        rule="TEST_PATCHES_SUBJECT",
    )

    assert len(hits) == 1
    assert verdict == "block"


def test_duplicate_conftest_fixture_wrapper_keeps_prior_install_live():
    conftest = """\
import pytest
from app import billing


def _reference(*args):
    return 105.3


@pytest.fixture(name="standin")
def aaa(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", _reference)
    yield


@pytest.fixture(name="standin")
def zzz(standin):
    return standin
"""
    before = _test_source()
    after = _test_source("standin")

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {"conftest.py": conftest, "tests/test_billing.py": after},
    )

    assert len(hits) == 1
    assert hits[0].path == "conftest.py"
    assert verdict == "block"


def test_duplicate_receiver_wrapper_stays_shadowed_by_prior_custom_provider():
    conftest = """\
import pytest
from app import billing


@pytest.fixture(name="monkeypatch")
def aaa():
    return object()


@pytest.fixture(name="monkeypatch")
def zzz(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)
    yield
"""
    before = _test_source()
    after = _test_source("monkeypatch")

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {"conftest.py": conftest, "tests/test_billing.py": after},
    )

    assert hits == []
    assert verdict == "pass"


def test_later_receiver_wrapper_does_not_shadow_installing_provider():
    conftest = """\
import pytest
from app import billing


@pytest.fixture(name="monkeypatch")
def aaa(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)
    yield monkeypatch


@pytest.fixture(name="monkeypatch")
def zzz(monkeypatch):
    return monkeypatch
"""
    before = _test_source()
    after = _test_source("monkeypatch")

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {"conftest.py": conftest, "tests/test_billing.py": after},
    )

    assert len(hits) == 1
    assert hits[0].path == "conftest.py"
    assert verdict == "block"


@pytest.mark.parametrize("scope", ["module", "class"])
def test_later_local_receiver_wrapper_is_only_a_consumer(scope: str):
    if scope == "module":
        before = """\
import pytest
from app import billing


@pytest.fixture(name="monkeypatch")
def aaa(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)
    yield monkeypatch


@pytest.fixture(name="monkeypatch")
def zzz(monkeypatch):
    return monkeypatch


def test_total():
    expected = 105.3
    assert billing.invoice_total([], 0) == expected
"""
        after = before.replace("def test_total():", "def test_total(monkeypatch):")
    else:
        before = """\
import pytest
from app import billing


class TestBilling:
    @pytest.fixture(name="monkeypatch")
    def aaa(self, monkeypatch):
        monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)
        yield monkeypatch

    @pytest.fixture(name="monkeypatch")
    def zzz(self, monkeypatch):
        return monkeypatch

    def test_total(self):
        expected = 105.3
        assert billing.invoice_total([], 0) == expected
"""
        after = before.replace(
            "def test_total(self):", "def test_total(self, monkeypatch):"
        )

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {"tests/test_billing.py": after},
        rule="TEST_PATCHES_SUBJECT",
    )

    assert len(hits) == 1
    assert verdict == "block"


@pytest.mark.parametrize("scope", ["module", "class"])
def test_duplicate_local_fixture_wrapper_keeps_prior_install_live(scope: str):
    if scope == "module":
        before = """\
import pytest
from app import billing


def _reference(*args):
    return 105.3


@pytest.fixture(name="standin")
def aaa(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", _reference)
    yield


@pytest.fixture(name="standin")
def zzz(standin):
    return standin


def test_total():
    expected = 105.3
    assert billing.invoice_total([], 0) == expected
"""
        after = before.replace("def test_total():", "def test_total(standin):")
    else:
        before = """\
import pytest
from app import billing


def _reference(*args):
    return 105.3


class TestBilling:
    @pytest.fixture(name="standin")
    def aaa(self, monkeypatch):
        monkeypatch.setattr(billing, "invoice_total", _reference)
        yield

    @pytest.fixture(name="standin")
    def zzz(self, standin):
        return standin

    def test_total(self):
        expected = 105.3
        assert billing.invoice_total([], 0) == expected
"""
        after = before.replace(
            "def test_total(self):", "def test_total(self, standin):"
        )

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {"tests/test_billing.py": after},
        rule="TEST_PATCHES_SUBJECT",
    )

    assert len(hits) == 1
    assert verdict == "block"


@pytest.mark.parametrize("dependency", ["self", "cls"])
def test_module_fixture_dependency_named_like_method_receiver_is_injected(
    dependency: str,
):
    conftest = f"""\
import pytest
from app import billing


@pytest.fixture
def {dependency}(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)
    yield


@pytest.fixture
def adapter({dependency}):
    return {dependency}
"""
    before = _test_source()
    after = _test_source("adapter")

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {"conftest.py": conftest, "tests/test_billing.py": after},
    )

    assert len(hits) == 1
    assert verdict == "block"


def test_removing_custom_receiver_unshadows_unchanged_test_patch():
    before = """\
import pytest


@pytest.fixture
def monkeypatch():
    return object()
"""
    after = "import pytest\n"
    unchanged_test = """\
from app import billing


def _reference(*args):
    return 105.3


def test_total(monkeypatch):
    monkeypatch.setattr(billing, "invoice_total", _reference)
    expected = 105.3
    assert billing.invoice_total([], 0) == expected
"""

    verdict, hits = _run(
        [_change("conftest.py", before, after)],
        {
            "conftest.py": after,
            "tests/test_billing.py": unchanged_test,
        },
        rule="TEST_PATCHES_SUBJECT",
    )

    assert len(hits) == 1
    assert hits[0].path == "tests/test_billing.py"
    assert verdict == "block"


@pytest.mark.parametrize("receiver", ["monkeypatch", "mocker"])
def test_transparent_receiver_fixture_preserves_plugin_provenance(receiver: str):
    wrapper = f"""\
import pytest


@pytest.fixture
def {receiver}({receiver}):
    return {receiver}
"""
    before = _test_source()
    call = (
        '    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)\n'
        if receiver == "monkeypatch"
        else '    mocker.patch.object(billing, "invoice_total", lambda *_: 105.3)\n'
    )
    after = _test_source(receiver).replace(
        "    expected = 105.3\n", call + "    expected = 105.3\n"
    )

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {"conftest.py": wrapper, "tests/test_billing.py": after},
        rule="TEST_PATCHES_SUBJECT",
    )

    assert len(hits) == 1
    assert verdict == "block"


def test_transparent_receiver_trust_propagates_through_provider_stack():
    wrapper = """\
import pytest


@pytest.fixture(name="monkeypatch")
def aaa(monkeypatch):
    return monkeypatch


@pytest.fixture(name="monkeypatch")
def zzz(monkeypatch):
    return monkeypatch
"""
    before = _test_source()
    after = _test_source("monkeypatch").replace(
        "    expected = 105.3\n",
        '    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)\n'
        "    expected = 105.3\n",
    )

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {"conftest.py": wrapper, "tests/test_billing.py": after},
        rule="TEST_PATCHES_SUBJECT",
    )

    assert len(hits) == 1
    assert verdict == "block"


def test_custom_receiver_wrapper_does_not_preserve_plugin_provenance():
    wrapper = """\
import pytest


@pytest.fixture
def monkeypatch(monkeypatch):
    return object()
"""
    before = _test_source()
    after = _test_source("monkeypatch").replace(
        "    expected = 105.3\n",
        '    monkeypatch.setattr(billing, "invoice_total", lambda *_: 105.3)\n'
        "    expected = 105.3\n",
    )

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {"conftest.py": wrapper, "tests/test_billing.py": after},
        rule="TEST_PATCHES_SUBJECT",
    )

    assert hits == []
    assert verdict == "pass"


def test_assertion_provider_transition_probes_readable_owned_target():
    before = """\
def test_total():
    from app.billing import invoice_total
    assert invoice_total([], 0) == 105.3
    from tests.ref import reference_total as invoice_total
"""
    after = """\
def test_total():
    from app.billing import invoice_total
    from tests.ref import reference_total as invoice_total
    assert invoice_total([], 0) == 105.3
"""
    reads: list[str] = []

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "app/billing.py": "def invoice_total(*args): return 0\n",
            "tests/ref.py": "def reference_total(*args): return 105.3\n",
            "tests/test_billing.py": after,
        },
        self_modules=set(),
        reads=reads,
        rule="TEST_PATCHES_SUBJECT",
    )

    assert len(hits) == 1
    assert hits[0].path == "tests/test_billing.py"
    assert "app/billing.py" in reads
    assert verdict == "block"


def test_assertion_provider_transition_does_not_promote_external_target():
    before = """\
def test_total():
    from vendor.billing import invoice_total
    assert invoice_total([], 0) == 105.3
    from tests.ref import reference_total as invoice_total
"""
    after = """\
def test_total():
    from vendor.billing import invoice_total
    from tests.ref import reference_total as invoice_total
    assert invoice_total([], 0) == 105.3
"""
    reads: list[str] = []

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "tests/ref.py": "def reference_total(*args): return 105.3\n",
            "tests/test_billing.py": after,
            "vendor/billing.py": "def invoice_total(*args): return 0\n",
        },
        self_modules=set(),
        external_modules={"vendor"},
        reads=reads,
        rule="TEST_PATCHES_SUBJECT",
    )

    assert hits == []
    assert "vendor/billing.py" not in reads
    assert verdict == "pass"


def test_reordering_after_oracle_is_not_a_provider_transition_or_probe():
    before = """\
def test_total():
    from app.billing import invoice_total
    assert invoice_total([], 0) == 105.3
    marker = 1
    from tests.ref import reference_total as invoice_total
"""
    after = """\
def test_total():
    from app.billing import invoice_total
    assert invoice_total([], 0) == 105.3
    from tests.ref import reference_total as invoice_total
    marker = 1
"""
    reads: list[str] = []

    verdict, hits = _run(
        [_change("tests/test_billing.py", before, after)],
        {
            "app/billing.py": "def invoice_total(*args): return 0\n",
            "tests/ref.py": "def reference_total(*args): return 105.3\n",
            "tests/test_billing.py": after,
        },
        self_modules=set(),
        reads=reads,
        rule="TEST_PATCHES_SUBJECT",
    )

    assert hits == []
    assert "app/billing.py" not in reads
    assert verdict == "pass"
