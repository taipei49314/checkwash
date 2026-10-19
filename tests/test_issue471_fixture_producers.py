"""The producer of a fixture a test requests by parameter is repair evidence (#471).

A test that gets its subject from a conftest fixture calls nothing that
builds it, so a production default changed under it read as no repair
evidence, while the same test constructing the class itself passed.

Ruling 471 (owner, 2026-10-16, adopting the analysis in
issuecomment-6229395341):

- Q1 (c): a fixture contributes only its producer, the call whose value it
  returns or yields (directly, or through one plain local binding),
  resolved through the fixture file's own imports.
- Q2 (a): one level, for a fixture the test requests by parameter, resolved
  as pytest resolves fixtures. No fixtures of fixtures, no `autouse`, no
  `usefixtures`.
- Q3 (b): only for the findings whose before-side assertion reads that
  fixture's value.
- Q4 (a): every oracle rule that takes symbol evidence, except
  TEST_DISABLED. No PACKAGE_REPAIR, no limit to constructors.

The `.gwcase` fixtures pin the verdicts; these pin the reader, the
resolution and the gating step.
"""
import ast
import datetime

import pytest

from checkwash import gating
from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.findings import Evidence, Finding
from checkwash.frontends.python.fixture_producers import import_modules
from checkwash.frontends.python.frontend import parse_conftest_level, parse_python
from checkwash.frontends.python.setup_skip_controls import ConftestLevel, unreadable_level
from checkwash.gating import _finding_assertion, _fixture_producer_evidence
from checkwash.ir.model import IR, Assertion, AssertionPair, Unit, UnitDelta, UnitSide

TODAY = datetime.date(2026, 10, 19)
HEADER = "import pytest\n\nfrom shop.ledger import Ledger\n\n\n"
PRODUCER = ("Ledger", ("shop.ledger",))
CONFTEST = HEADER + "@pytest.fixture\ndef ledger():\n    return Ledger()\n"


def _level(source=CONFTEST, path="tests/conftest.py"):
    level = parse_conftest_level(source.encode(), path)
    assert level is not None
    return level


def _fixture(body, signature="def ledger():", decorator="@pytest.fixture"):
    """The conftest level of one fixture whose body is `body`, indented by the helper."""
    lines = "".join(f"    {line}\n" for line in body.split("\n"))
    return _level(HEADER + f"{decorator}\n{signature}\n{lines}")


def _side(source, chain=None):
    parsed = parse_python(source.encode(), collect_tests=True, chain=(_level(),) if chain is None else chain)
    assert parsed.parse_ok and parsed.units
    return parsed.units[0].side


# --- the fixture file's imports ---------------------------------------------------------------


@pytest.mark.parametrize(("source", "expected"), [
    pytest.param("from shop.ledger import Ledger\n", {"Ledger": ("shop.ledger",)}, id="from-import"),
    pytest.param("from shop.ledger import Ledger as Book\n", {"Book": ("shop.ledger",)}, id="aliased-from-import"),
    pytest.param("import shop.ledger\n", {"shop": ("shop.ledger",)}, id="dotted-import"),
    pytest.param("import shop.ledger as books\n", {"books": ("shop.ledger",)}, id="aliased-import"),
    pytest.param("from . import ledger\n", {}, id="relative-import"),
    pytest.param("from shop.other import *\nfrom shop.ledger import Ledger\n", {"Ledger": ("shop.ledger",)},
                 id="star-import-before"),
    pytest.param("from shop.ledger import Ledger\nfrom shop.other import *\n", {}, id="star-import-after"),
    pytest.param("from shop.ledger import Ledger\nLedger = None\n", {}, id="rebound-after"),
    pytest.param("try:\n    from shop.ledger import Ledger\nexcept ImportError:\n    Ledger = None\n", {},
                 id="under-try"),
])
def test_import_modules_reads_each_names_final_top_level_import(source, expected):
    assert import_modules(ast.parse(source)) == expected


# --- what a fixture contributes (Q1 (c)) --------------------------------------------------------


@pytest.mark.parametrize("body", [
    pytest.param("return Ledger()", id="return-call"),
    pytest.param('return Ledger(currency="EUR")', id="return-call-with-arguments"),
    pytest.param("yield Ledger()", id="yield-call"),
    pytest.param("book = Ledger()\nyield book\nbook.close()", id="bound-then-yielded"),
    pytest.param("book: Ledger = Ledger()\nreturn book", id="annotated-binding"),
    pytest.param('"""A ledger."""\nreturn Ledger()', id="docstring"),
    pytest.param("init_db()\nreturn Ledger()", id="setup-call-before"),
    pytest.param("with open('ledger.lock'):\n    yield Ledger()", id="yield-under-with"),
    pytest.param("book = Ledger()\nwith open('ledger.lock'):\n    yield book", id="bound-then-yielded-under-with"),
    pytest.param("try:\n    yield Ledger()\nfinally:\n    close()", id="yield-under-try"),
    pytest.param("with open('ledger.lock'):\n    try:\n        yield Ledger()\n    finally:\n        close()",
                 id="yield-under-try-under-with"),
])
def test_the_producer_is_the_call_the_fixture_returns_or_yields(body):
    assert _fixture(body).producers == {"ledger": PRODUCER}


@pytest.mark.parametrize(("signature", "body"), [
    pytest.param("def ledger():", "return {}", id="literal"),
    pytest.param("def ledger():", "init_db()\nreturn None", id="setup-call-only"),
    pytest.param("def ledger():", "return Ledger", id="the-class-itself"),
    pytest.param("def ledger():", "return make_ledger", id="unbound-name"),
    pytest.param("def ledger():", "return Ledger()()", id="call-of-a-call"),
    pytest.param("def ledger():", "return Ledger() if fast else Ledger(1)", id="conditional-expression"),
    pytest.param("def ledger():", "if fast:\n    return Ledger()\nreturn Ledger(1)", id="two-returns"),
    pytest.param("def ledger():", "yield from make_ledgers()", id="yield-from"),
    pytest.param("def ledger():", "yield", id="bare-yield"),
    pytest.param("def ledger():", "book = Ledger()\nbook = Ledger(1)\nreturn book", id="bound-twice"),
    pytest.param("def ledger():", "for book in [Ledger()]:\n    pass\nreturn book", id="for-target"),
    pytest.param("def ledger():", "with Ledger() as book:\n    yield book", id="with-as"),
    pytest.param("def ledger():", "Ledger = make\nreturn Ledger()", id="root-bound-locally"),
    pytest.param("def ledger(Ledger):", "return Ledger()", id="root-is-a-parameter"),
    pytest.param("def ledger(app):", "return app.test_client()", id="root-is-a-requested-fixture"),
    pytest.param("def ledger(request):", "return request.param", id="request-param"),
    pytest.param("async def ledger():", "return await open_ledger()", id="awaited"),
    pytest.param("def ledger():", "if fast:\n    return Ledger()", id="conditional-return"),
    pytest.param("def ledger():", "if fast:\n    yield Ledger()", id="conditional-yield"),
    pytest.param("def ledger():", "for _ in range(1):\n    return Ledger()", id="return-under-for"),
    pytest.param("def ledger():", "while pending:\n    return Ledger()", id="return-under-while"),
    pytest.param("def ledger(mode):", "match mode:\n    case 'fast':\n        return Ledger()", id="return-under-match"),
    pytest.param("def ledger():", "try:\n    init_db()\nexcept OSError:\n    return Ledger()", id="return-under-except"),
    pytest.param("def ledger():", "try:\n    init_db()\nexcept OSError:\n    raise\nelse:\n    return Ledger()",
                 id="return-under-try-else"),
    pytest.param("def ledger():", "try:\n    init_db()\nfinally:\n    yield Ledger()", id="yield-under-finally"),
    pytest.param("def ledger():", "with open('ledger.lock'):\n    if fast:\n        return Ledger()",
                 id="return-under-if-under-with"),
])
def test_a_fixture_without_a_readable_producer_contributes_nothing(signature, body):
    level = _fixture(body, signature)
    assert "ledger" in level.fixtures
    assert level.producers == {}


def test_a_root_no_top_level_import_binds_resolves_to_nothing():
    source = (
        "import pytest\n\ntry:\n    from shop.ledger import Ledger\nexcept ImportError:\n    Ledger = None\n\n\n"
        "@pytest.fixture\ndef ledger():\n    return Ledger()\n\n\n"
        "def make_ledger():\n    return Ledger()\n\n\n"
        "@pytest.fixture\ndef made():\n    return make_ledger()\n"
    )
    assert _level(source).producers == {}


def test_a_fixture_registered_under_another_name_keeps_its_producer_under_that_name():
    level = _fixture("return Ledger()", "def make_ledger():", '@pytest.fixture(name="ledger")')
    assert level.producers == {"ledger": PRODUCER}


def test_a_dotted_producer_keeps_its_dotted_name_and_the_module_its_root_imports():
    level = _level("import pytest\n\nimport shop.ledger\n\n\n@pytest.fixture\ndef ledger():\n"
                   "    return shop.ledger.Ledger.open()\n")
    assert level.producers == {"ledger": ("shop.ledger.Ledger.open", ("shop.ledger",))}


# --- how far: one level, resolved as pytest resolves it (Q2 (a)) -------------------------------


def test_a_conftest_fixture_the_test_requests_is_read_through_the_conftests_imports():
    side = _side("def test_fee(ledger):\n    assert ledger.fee == 5.0\n")
    assert side.fixture_producers == (("ledger", "Ledger", ("shop.ledger",)),)
    assert [a.fixture_reads for a in side.assertions] == [("ledger",)]


def test_the_modules_own_fixture_wins_over_the_conftests_even_when_it_extends_it():
    source = (
        "import pytest\n\nfrom shop.archive import Archive\n\n\n"
        "@pytest.fixture\ndef ledger(ledger):\n    return Archive(ledger)\n\n\n"
        "def test_fee(ledger):\n    assert ledger.fee == 5.0\n"
    )
    assert _side(source).fixture_producers == (("ledger", "Archive", ("shop.archive",)),)


def test_a_class_fixture_wins_over_the_module_and_the_conftest():
    source = (
        "import pytest\n\nfrom shop.archive import Archive\n\n\n"
        "class TestFee:\n"
        "    @pytest.fixture\n    def ledger(self):\n        return Archive()\n\n"
        "    def test_fee(self, ledger):\n        assert ledger.fee == 5.0\n"
    )
    assert _side(source).fixture_producers == (("ledger", "Archive", ("shop.archive",)),)


def test_a_nearer_conftest_wins_over_a_farther_one():
    near = _level("import pytest\n\nfrom shop.archive import Archive\n\n\n"
                  "@pytest.fixture\ndef ledger():\n    return Archive()\n", "tests/unit/conftest.py")
    side = _side("def test_fee(ledger):\n    assert ledger.fee == 5.0\n", chain=(near, _level()))
    assert side.fixture_producers == (("ledger", "Archive", ("shop.archive",)),)


def test_a_plugin_configuration_level_neither_supplies_nor_stops_the_lookup():
    plugins = ConftestLevel("<plugin-configuration>", {}, frozenset(), False, adds_marks=True)
    side = _side("def test_fee(ledger):\n    assert ledger.fee == 5.0\n", chain=(plugins, _level()))
    assert side.fixture_producers == (("ledger", "Ledger", ("shop.ledger",)),)


@pytest.mark.parametrize(("source", "chain"), [
    pytest.param("import pytest\n\n\n@pytest.mark.parametrize('ledger', [None])\n"
                 "def test_fee(ledger):\n    assert ledger is None\n", None, id="parametrized-directly"),
    pytest.param("from tests.helpers import ledger\n\n\ndef test_fee(ledger):\n    assert ledger.fee == 5.0\n",
                 None, id="module-binds-the-name-by-import"),
    pytest.param("from tests.helpers import *\n\n\ndef test_fee(ledger):\n    assert ledger.fee == 5.0\n",
                 None, id="module-star-import"),
    pytest.param("from shop.base import Base\n\n\nclass TestFee(Base):\n"
                 "    def test_fee(self, ledger):\n        assert ledger.fee == 5.0\n", None, id="class-with-a-base"),
    pytest.param("def test_fee(ledger=None):\n    assert ledger is None\n", None, id="argument-with-a-default"),
    pytest.param("import pytest\n\n\n@pytest.mark.usefixtures('ledger')\ndef test_fee():\n    assert True\n",
                 None, id="usefixtures"),
    pytest.param("def test_fee():\n    assert True\n", None, id="no-request"),
    pytest.param("def test_fee(ledger):\n    assert ledger.fee == 5.0\n", "unreadable", id="unreadable-conftest"),
    pytest.param("def test_fee(ledger):\n    assert ledger.fee == 5.0\n", "rebinding", id="nearer-conftest-imports-it"),
])
def test_a_request_that_does_not_resolve_to_a_readable_fixture_has_no_producer(source, chain):
    if chain == "unreadable":
        chain = (unreadable_level("tests/conftest.py"), _level())
    elif chain == "rebinding":
        chain = (_level("from tests.helpers import ledger\n", "tests/unit/conftest.py"), _level())
    assert _side(source, chain=chain).fixture_producers == ()


def test_an_indirect_parametrization_still_runs_the_fixture():
    source = ("import pytest\n\n\n@pytest.mark.parametrize('ledger', [1], indirect=True)\n"
              "def test_fee(ledger):\n    assert ledger.fee == 5.0\n")
    assert _side(source).fixture_producers == (("ledger", "Ledger", ("shop.ledger",)),)


def test_a_class_whose_only_base_is_object_does_not_stop_the_lookup():
    source = "class TestFee(object):\n    def test_fee(self, ledger):\n        assert ledger.fee == 5.0\n"
    assert _side(source).fixture_producers == (("ledger", "Ledger", ("shop.ledger",)),)


def test_a_fixture_requested_by_the_requested_fixture_is_not_followed():
    level = _level("import pytest\n\nfrom shop.app import create_app\n\n\n"
                   "@pytest.fixture\ndef app():\n    return create_app()\n\n\n"
                   "@pytest.fixture\ndef client(app):\n    return app.test_client()\n")
    assert level.producers == {"app": ("create_app", ("shop.app",))}
    assert _side("def test_total(client):\n    assert client.total() == 1.0\n", chain=(level,)).fixture_producers == ()
    assert _side("def test_total(app):\n    assert app.total == 1.0\n", chain=(level,)).fixture_producers == (
        ("app", "create_app", ("shop.app",)),
    )


def test_an_autouse_fixture_the_test_also_requests_by_parameter_has_a_producer():
    """Q2 (a) counts a fixture the test requests by parameter; `autouse` alone requests nothing."""
    level = _fixture("return Ledger()", decorator="@pytest.fixture(autouse=True)")
    assert level.producers == {"ledger": PRODUCER}
    side = _side("def test_fee(ledger):\n    assert ledger.fee == 5.0\n", chain=(level,))
    assert side.fixture_producers == (("ledger", "Ledger", ("shop.ledger",)),)
    assert _side("def test_fee():\n    assert True\n", chain=(level,)).fixture_producers == ()


# --- which assertions read the fixture's value (Q3 (b)) ----------------------------------------


@pytest.mark.parametrize(("body", "reads"), [
    pytest.param("    assert ledger.fee == 5.0\n", [("ledger",)], id="directly"),
    pytest.param("    fee = ledger.fee\n    assert fee == 5.0\n", [("ledger",)], id="through-an-assignment"),
    pytest.param("    assert total() == 5.0\n", [()], id="not-at-all"),
    pytest.param("    ledger = make()\n    assert ledger.fee == 5.0\n", [()], id="parameter-assigned-again"),
    pytest.param("    assert (lambda ledger: ledger.fee)(make()) == 5.0\n", [()], id="lambda-parameter-of-that-name"),
    pytest.param("    assert (lambda ledger: ledger.fee)(ledger) == 5.0\n", [("ledger",)],
                 id="lambda-of-that-name-applied-to-it"),
    pytest.param("    assert (lambda row=ledger: row.fee)() == 5.0\n", [("ledger",)], id="lambda-default"),
    pytest.param("    fee = ledger.fee\n    assert [fee for fee in rows] == [5.0]\n", [()],
                 id="comprehension-target-shadows-a-local"),
    pytest.param("    fee = ledger.fee\n    assert (lambda ledger: ledger.fee + fee)(make()) == 5.0\n", [()],
                 id="lambda-of-that-name-beside-a-read-through-a-local"),
    pytest.param("    result = (lambda ledger: ledger.fee)(make())\n    assert result == 5\n", [()],
                 id="lambda-parameter-of-that-name-in-an-assignment"),
])
def test_an_assertion_records_the_fixture_parameters_it_reads(body, reads):
    side = _side("def test_fee(ledger):\n" + body)
    assert [a.fixture_reads for a in side.assertions] == reads


@pytest.mark.parametrize("body", [
    pytest.param("    for ledger in [make()]:\n        assert ledger.fee == 5.0\n", id="for-target"),
    pytest.param("    with make() as ledger:\n        assert ledger.fee == 5.0\n", id="with-as"),
    pytest.param("    assert all(ledger.fee == 5.0 for ledger in rows)\n", id="comprehension-target"),
])
def test_a_parameter_the_body_binds_again_in_another_form_records_no_fixture_read(body):
    side = _side("def test_fee(ledger):\n" + body)
    assert side.fixture_producers == (("ledger", "Ledger", ("shop.ledger",)),)
    assert side.assertions
    assert all(a.fixture_reads == () for a in side.assertions)


def test_an_assertion_in_a_nested_scope_records_no_fixture_read():
    side = _side("def test_fee(ledger):\n    def check(ledger):\n        assert ledger.fee == 5.0\n    check(ledger)\n")
    assert side.assertions
    assert all(a.fixture_reads == () for a in side.assertions)


def test_a_unittest_style_assertion_records_the_fixture_it_reads():
    side = _side("class TestFee:\n    def test_fee(self, ledger):\n        self.assertEqual(ledger.fee, 5.0)\n")
    assert [a.fixture_reads for a in side.assertions] == [("ledger",)]


# --- the gating step ----------------------------------------------------------------------------


def _assertion(aid, text, span, reads=()):
    return Assertion(id=aid, form="compare_eq", strength=90, text=text, span=span, fixture_reads=reads)


BEFORE_ASSERT = _assertion("a0", "assert ledger.fee == 5.0", (20, 44), ("ledger",))
AFTER_ASSERT = _assertion("a0", "assert ledger.fee == 7.5", (20, 44), ("ledger",))


def _unit(before=True):
    return Unit(
        kind="test_function", qualname="test_fee", match="by_name",
        before=UnitSide(span=(0, 44), assertions=[BEFORE_ASSERT],
                        fixture_producers=(("ledger", "Ledger", ("shop.ledger",)),)) if before else None,
        after=UnitSide(span=(0, 44), assertions=[AFTER_ASSERT]),
        delta=UnitDelta(assertion_pairs=[AssertionPair("a0", "a0", 0)]),
    )


def _finding(before=None, after=None):
    return Finding(rule="EXPECTED_VALUE_CHANGED", severity="warn", message="", path="tests/test_billing.py",
                   unit="test_fee", before=before, after=after)


@pytest.mark.parametrize(("finding", "expected"), [
    pytest.param(_finding(before=Evidence(BEFORE_ASSERT.text, BEFORE_ASSERT.span)), BEFORE_ASSERT,
                 id="cites-its-before-side"),
    pytest.param(_finding(after=Evidence(AFTER_ASSERT.text, AFTER_ASSERT.span)), BEFORE_ASSERT,
                 id="cites-only-its-after-side"),
    pytest.param(_finding(before=Evidence("def test_fee(ledger):", (0, 44))), None, id="cites-the-unit"),
    pytest.param(_finding(before=Evidence("assert ledger.fee == 6.0", BEFORE_ASSERT.span)), None,
                 id="same-span-other-text"),
])
def test_a_findings_assertion_is_the_before_half_of_the_one_it_cites(finding, expected):
    assert _finding_assertion(finding, _unit()) is expected


def test_a_unit_without_a_before_side_has_no_finding_assertion():
    assert _finding_assertion(_finding(after=Evidence(AFTER_ASSERT.text, AFTER_ASSERT.span)), _unit(False)) is None
    assert _finding_assertion(_finding(after=Evidence(AFTER_ASSERT.text, AFTER_ASSERT.span)), None) is None


def _ir(changed, test_imports=()):
    ir = IR(base="base", head="head")
    ir.globals.prod_symbols_changed = list(changed)
    ir.globals.test_file_imports["tests/test_billing.py"] = list(test_imports)
    return ir


@pytest.mark.parametrize(("assertion", "changed", "test_imports", "expected"), [
    pytest.param(BEFORE_ASSERT, ["shop.ledger::Ledger"], (), True, id="reads-the-changed-producer"),
    pytest.param(BEFORE_ASSERT, ["shop.ledger::Ledger"], ("unrelated",), True, id="test-imports-do-not-matter"),
    pytest.param(BEFORE_ASSERT, ["shop.other::Ledger"], ("shop.other",), False, id="same-name-other-module"),
    pytest.param(BEFORE_ASSERT, ["shop.ledger::Archive"], (), False, id="producer-unchanged"),
    pytest.param(_assertion("a0", "assert total() == 5.0", (20, 41)), ["shop.ledger::Ledger"], (), False,
                 id="assertion-reads-no-fixture"),
    pytest.param(_assertion("a0", "assert other.fee == 5.0", (20, 43), ("other",)), ["shop.ledger::Ledger"], (),
                 False, id="assertion-reads-another-parameter"),
    pytest.param(None, ["shop.ledger::Ledger"], (), False, id="no-assertion"),
])
def test_a_producer_is_evidence_only_for_an_assertion_that_reads_its_fixture(assertion, changed, test_imports,
                                                                             expected):
    side = _unit().before
    assert _fixture_producer_evidence(assertion, side, _ir(changed, test_imports)) is expected


# --- end to end ---------------------------------------------------------------------------------


def _judge(before, after, head=None):
    """(rule, severity, deescalators, escalators) per finding, sorted, and the verdict."""
    changes = []
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path), after.get(path)
        if old == new:
            continue
        status = "added" if old is None else "deleted" if new is None else "modified"
        changes.append(FileChange(path, status, None if old is None else old.encode(),
                                  None if new is None else new.encode()))
    snapshot = {path: source.encode() for path, source in (head or {}).items()}
    snapshot.update({path: source.encode() for path, source in after.items()})
    ir, findings, verdict = analyze(changes, Config(), Contract(), [], TODAY,
                                    head_reader=snapshot.get, root_reader=snapshot.get)
    return ir, sorted((f.rule, f.severity, tuple(f.deescalators), tuple(f.escalators)) for f in findings), verdict


FACTORY_BEFORE = (
    "class Ledger:\n    def reset(self):\n        self.entries = []\n\n\n"
    "def make_ledger():\n    book = Ledger()\n    book.reset()\n    return book\n"
)
FACTORY_AFTER = FACTORY_BEFORE.replace("self.entries = []", "self.entries = [] + []")
FACTORY_CONFTEST = (
    "import pytest\n\nfrom shop.ledger import make_ledger\n\n\n"
    "@pytest.fixture\ndef ledger():\n    return make_ledger()\n"
)


def test_the_one_hop_callers_route_is_not_followed_from_a_producer():
    """The producer counts as the test's call for a direct match only (D-155, a departure the owner kept).

    `make_ledger` is unchanged and calls the changed `Ledger.reset`. Written
    inline, `make_ledger()` takes the one-hop callers route (SPEC section 5
    clause 2); returned by the fixture, it does not, as the T1.9 helper hop
    and 306 Sub-Q8 match their callees directly only. The analysis the
    ruling adopted has the producer take that route (its sections 2.2 and
    4.5), so D-155 records this as a departure, which the owner kept on
    2026-10-19. Following the route would flip this pin to warn with
    REPAIR_EVIDENCE.
    """
    test_before = "def test_total(ledger):\n    assert ledger.total([1.0]) == 1.0\n"
    _ir_, through_fixture, verdict = _judge(
        {"shop/ledger.py": FACTORY_BEFORE, "tests/test_billing.py": test_before},
        {"shop/ledger.py": FACTORY_AFTER, "tests/test_billing.py": test_before.replace("== 1.0", "> 0")},
        {"tests/conftest.py": FACTORY_CONFTEST},
    )
    assert through_fixture == [("ASSERT_WEAKENED", "high", (), ("NO_PROD_CHANGE_IN_DIFF",))]
    assert verdict == "block"
    inline_before = (
        "from shop.ledger import make_ledger\n\n\n"
        "def test_total():\n    assert make_ledger().total([1.0]) == 1.0\n"
    )
    _ir_, inline, verdict = _judge(
        {"shop/ledger.py": FACTORY_BEFORE, "tests/test_billing.py": inline_before},
        {"shop/ledger.py": FACTORY_AFTER, "tests/test_billing.py": inline_before.replace("== 1.0", "> 0")},
    )
    assert inline == [("ASSERT_WEAKENED", "warn", ("REPAIR_EVIDENCE",), ())]
    assert verdict == "pass"


def test_a_conftest_the_diff_edits_is_read_from_each_side_and_the_before_side_governs():
    prod_before = "class Ledger:\n    fee = 5.0\n\n\nclass Archive:\n    fee = 5.0\n"
    prod_after = "class Ledger:\n    fee = 7.5\n\n\nclass Archive:\n    fee = 5.0\n"
    conftest = ("import pytest\n\nfrom shop.ledger import Archive, Ledger\n\n\n"
                "@pytest.fixture\ndef ledger():\n    return Archive()\n")
    test = "def test_fee(ledger):\n    assert ledger.fee == 5.0\n"
    ir, findings, verdict = _judge(
        {"shop/ledger.py": prod_before, "tests/conftest.py": conftest, "tests/test_billing.py": test},
        {"shop/ledger.py": prod_after, "tests/conftest.py": conftest.replace("return Archive()", "return Ledger()"),
         "tests/test_billing.py": test.replace("5.0", "7.5")},
    )
    [unit] = next(f for f in ir.files if f.path == "tests/test_billing.py").units
    assert unit.before.fixture_producers == (("ledger", "Archive", ("shop.ledger",)),)
    assert unit.after.fixture_producers == (("ledger", "Ledger", ("shop.ledger",)),)
    assert findings == [
        ("EXPECTED_VALUE_CHANGED", "high", (), ("NO_PROD_CHANGE_IN_DIFF",)),
        ("EXPECTED_VALUE_HARDCODED", "high", (), ("NO_PROD_CHANGE_IN_DIFF",)),
    ]
    assert verdict == "block"


DISABLED_PROD = (
    "class Ledger:\n    def total(self, items):\n        return sum(items)\n\n"
    "    def count(self):\n        return 0\n"
)
DISABLED_TESTS = (
    "def test_total(ledger):\n    assert ledger.total([50.0, 50.0]) == 100.0\n\n\n"
    "def test_count(ledger):\n    assert ledger.count() == 0\n"
)
DISABLED_CONFTEST = (
    "import pytest\n\nfrom billing import Ledger\n\n\n"
    "@pytest.fixture\ndef ledger():\n    return Ledger()\n"
)


def test_the_test_disabled_guard_is_what_withholds_a_changed_producer(monkeypatch):
    """apply_gates passes TEST_DISABLED no assertion (471 Q4 (a)); this pin tells the guard from its absence.

    No TEST_DISABLED finding cites an assertion today: a unit gone cites the
    unit's span, and the other shapes cite a marker or the unit's span on
    the after side. So `_finding_assertion` finds none, and
    `fixture_producer_test_disabled_pos` blocks with or without the guard.
    Here every finding is handed its unit's first before-side assertion that
    reads a fixture, which would be evidence, so only the guard keeps the
    changed producer of `ledger` out. The scenario is that fixture's.
    """
    def reading(_finding, unit):
        if unit is None or unit.before is None:
            return None
        return next((a for a in unit.before.assertions if a.fixture_reads), None)

    monkeypatch.setattr(gating, "_finding_assertion", reading)
    ir, findings, verdict = _judge(
        {"billing.py": DISABLED_PROD, "tests/test_billing.py": DISABLED_TESTS},
        {"billing.py": DISABLED_PROD.replace("return sum(items)", "return round(sum(items), 2)"),
         "tests/test_billing.py": DISABLED_TESTS.split("\n\n\n")[1]},
        {"tests/conftest.py": DISABLED_CONFTEST},
    )
    [gone] = [u for u in next(f for f in ir.files if f.path == "tests/test_billing.py").units
              if u.qualname == "test_total"]
    assert gone.after is None
    assert gone.before.fixture_producers == (("ledger", "Ledger", ("billing",)),)
    assert _fixture_producer_evidence(reading(None, gone), gone.before, ir) is True
    assert [(rule, severity, escalators) for rule, severity, _de, escalators in findings] == [
        ("TEST_DISABLED", "high", ("NO_PROD_CHANGE_IN_DIFF",)),
    ]
    assert verdict == "block"
