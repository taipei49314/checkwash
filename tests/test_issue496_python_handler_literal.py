"""Always-passing assertions in a Python broad handler (#496).

A broad handler on a `try` that guards an oracle counted as inspection
whenever it held any oracle, so `except Exception: assert True` turned row
16's BROAD_EXCEPT_ADDED block back into a clean pass. Ruling 496 (R49
option (a), R50, R51): a handler whose every oracle is proved to always pass
swallows too, under its first line followed by " [always-passing
assertion]", compared apart from main's texts. The proof is narrow and
separate from `_static_truth`; anything it cannot read keeps the exemption.
An oracle the handler never reaches is not read as such (R66, a residual).

Expectations are new labels; they run only on remote CI.
"""

from __future__ import annotations

import ast
import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python.frontend import _ALWAYS_PASSING, _static_truth, parse_python

TODAY = datetime.date(2026, 10, 19)
PATH = "tests/test_value.py"
HANDLER = "exceptExceptionaserror:"
PROVED = (HANDLER + _ALWAYS_PASSING,)


def _indent(body: str, depth: int) -> str:
    return "".join(" " * depth + line + "\n" for line in body.split("\n"))


def function_source(body: str, handler: str = "except Exception as error:") -> bytes:
    """A pytest function whose assertion a `try` wraps, with `body` in the handler."""
    return (
        "from app import value\n\n\n"
        "def test_value():\n"
        "    try:\n"
        "        assert value() == 1\n"
        f"    {handler}\n" + _indent(body, 8)
    ).encode()


def case_source(body: str) -> bytes:
    """A `unittest.TestCase` method whose `assertEqual` a `try` wraps, with `body` in the handler."""
    return (
        "import unittest\n\n"
        "from app import value\n\n\n"
        "class ValueTest(unittest.TestCase):\n"
        "    def test_value(self):\n"
        "        try:\n"
        "            self.assertEqual(value(), 1)\n"
        "        except Exception as error:\n" + _indent(body, 12)
    ).encode()


def swallowed(source: bytes) -> tuple[str, ...]:
    return parse_python(source, collect_tests=True).swallowing_handlers


def outcome(before: str, after: str):
    change = FileChange(PATH, "modified", before.encode(), after.encode())
    _ir, findings, verdict = analyze([change], Config(), Contract(), [], TODAY)
    return verdict, findings


def reported(findings) -> list[tuple[str, str, str | None]]:
    return [(f.rule, f.severity, f.after.text if f.after is not None else None) for f in findings]


@pytest.mark.parametrize("body", [
    "assert True",
    "assert 1",
    "assert 'x'",
    "assert (1, 2)",
    "assert ...",
    "assert not False",
    "assert not 0",
    "assert not None",
    "assert not ''",
    "assert 1 == 1",
    "assert 1 != 2",
    "assert 1 < 2",
    "assert 2 <= 2",
    "assert 3 > 2",
    "assert 3 >= 3",
    "assert 1 in (1, 2)",
    "assert 'a' not in 'bcd'",
    "assert 1 < 2 < 3",
    "assert -1 < 0",
    "assert [1, 2] == [1, 2]",
    "assert {'a': 1} != {}",
    "assert None is None",
    "assert 1 is not None",
    "assert True and 1 == 1",
    "assert False or True",
    "assert 0 or (1 == 1 and not False)",
    "assert True, 'message'",
    # The message runs only when the assertion fails.
    "assert True, describe(error)",
    "assert True\nassert 1 == 1",
])
def test_an_assert_proved_to_pass_leaves_the_handler_swallowing(body):
    assert swallowed(function_source(body)) == PROVED


@pytest.mark.parametrize("body", [
    "self.assertTrue(True)",
    "self.assertTrue(1)",
    "self.assertFalse(False)",
    "self.assertFalse(0)",
    "self.assertIsNone(None)",
    "self.assertIsNotNone(1)",
    "self.assertEqual(1, 1)",
    "self.assertEqual([1], [1])",
    "self.assertEqual(1, 1.0)",
    "self.assertNotEqual(1, 2)",
    "self.assertTrue(True, 'message')",
    "self.assertTrue(True, msg='message')",
    "self.assertTrue(True, None)",
    "self.assertTrue(expr=True)",
    "self.assertEqual(1, second=1)",
    "self.assertEqual(first=1, second=1, msg='message')",
    "self.assertTrue(True)\nassert 1 == 1",
])
def test_a_literal_unittest_call_in_a_testcase_leaves_the_handler_swallowing(body):
    assert swallowed(case_source(body)) == PROVED


@pytest.mark.parametrize("body", [
    # Always fails: the "fail if we get here" idiom stays inspection (431.Q2).
    "assert False",
    "assert 0",
    "assert ()",
    "assert not True",
    "assert 1 == 2",
    "assert None is not None",
    # Inspection of the caught error (431.Q2), and the named residuals.
    "assert str(error) == 'y'",
    "assert error == error",
    "assert error",
    "assert error is not None",
    "assert isinstance(error, Exception)",
    # A call runs before a short circuit could decide (R51).
    "assert value() or True",
    "assert True or value()",
    "assert True and value()",
    # Evaluation raises.
    "assert 1 < 'a'",
    "assert -'a'",
    "assert {[1]: 2}",
    # `is` without None depends on interning; bytes comparisons can raise under -bb.
    "assert 1 is 1",
    "assert b'a' == b'a'",
    "assert True if error else True",
    "assert f'{error}'",
    "ok = True\nassert ok",
    # Every oracle must be proved (R49, condition three).
    "pytest.fail('unexpected')",
    "assert True\npytest.fail('unexpected')",
    "assert True\nassert str(error) == 'y'",
    "assert True\nwith pytest.raises(ValueError):\n    value()",
    "assert True\nraise",
    # No TestCase method: a module function, a bare name, a third-party call.
    "self.assertTrue(True)",
    "assertTrue(True)",
    "mock.assert_called_once()",
])
def test_an_oracle_that_can_fail_or_is_unproved_keeps_the_handler_inspection(body):
    assert swallowed(function_source(body)) == ()


@pytest.mark.parametrize("body", [
    "self.assertTrue()",
    "self.assertTrue(True, 'a', 'b')",
    "self.assertEqual(1)",
    "self.assertEqual(1, 1, 'message', 'extra')",
    "self.assertTrue(True, message='m')",
    # `msg` is evaluated before the call.
    "self.assertTrue(True, msg=describe(error))",
    "self.assertTrue(True, describe(error))",
    "self.assertTrue(True, -'a')",
    "self.assertTrue(*[True])",
    "self.assertTrue(True, **options)",
    "self.assertTrue(True, expr=True)",
    "self.assertEqual(1, first=1)",
    "self.assertTrue(True, 'a', msg='b')",
])
def test_a_unittest_call_with_another_argument_list_is_unproved(body):
    # R49 condition one: any other argument list raises TypeError.
    assert swallowed(case_source(body)) == ()


def method(call: str = "self.assertTrue(True)", receiver: str = "self", name: str = "test_value") -> str:
    return (
        f"    def {name}({receiver}):\n"
        "        try:\n"
        f"            {receiver}.assertEqual(value(), 1)\n"
        "        except Exception as error:\n"
        f"            {call}\n"
    )


def case_module(classes: str, imports: str = "import unittest\n") -> bytes:
    return (imports + "\nfrom app import value\n\n\n" + classes).encode()


@pytest.mark.parametrize("source", [
    case_module("class ValueTest(unittest.TestCase):\n" + method()),
    case_module("class ValueTest(TestCase):\n" + method(), "from unittest import TestCase\n"),
    case_module("class Base(unittest.TestCase):\n    pass\n\n\nclass ValueTest(Base):\n" + method()),
    case_module("class ValueTest(unittest.TestCase, Mixin):\n" + method(),
                "import unittest\nfrom helpers import Mixin\n"),
    case_module("class ValueTest(SimpleTestCase):\n" + method(), "from django.test import SimpleTestCase\n"),
    case_module("class ValueTest(unittest.IsolatedAsyncioTestCase):\n"
                + method().replace("    def ", "    async def ", 1)),
    case_module("class ValueTest(unittest.TestCase):\n" + method("case.assertTrue(True)", "case")),
    case_module("class ValueTest(unittest.TestCase):\n    @unittest.mock.patch('app.CONFIG', {})\n"
                + method()),
    case_module("class ValueTest(unittest.TestCase):\n    def setUp(self):\n        self.items = []\n\n"
                + method()),
    case_module("class Checks:\n    def helper(self):\n        pass\n\n\n"
                "class ValueTest(Checks, unittest.TestCase):\n" + method()),
], ids=[
    "unittest-testcase", "imported-testcase", "same-file-base", "testcase-before-imported-mixin",
    "other-testcase-name", "async-testcase", "receiver-named-otherwise", "decorated-method",
    "other-name-stored", "same-file-mixin-before-testcase",
])
def test_a_testcase_method_proves_its_receivers_call(source):
    # R49 condition two holds.
    assert swallowed(source) == PROVED


@pytest.mark.parametrize("source", [
    case_module("class ValueTest:\n" + method()),
    case_module("class ValueTest(Base):\n" + method(), "import unittest\nfrom helpers import Base\n"),
    case_module("class Checks:\n" + method() + "\n\nclass ValueTest(Checks, unittest.TestCase):\n    pass\n"),
    case_module("class ValueTest(Mixin, unittest.TestCase):\n" + method(),
                "import unittest\nfrom helpers import Mixin\n"),
    case_module("class ValueTest(unittest.TestCase):\n    def assertTrue(self, expr, msg=None):\n"
                "        pass\n\n" + method()),
    case_module("class Base(unittest.TestCase):\n    assertTrue = None\n\n\nclass ValueTest(Base):\n"
                + method()),
    case_module("class ValueTest(unittest.TestCase):\n" + method() + "\n\nValueTest.assertTrue = print\n"),
    case_module("class ValueTest(unittest.TestCase):\n    def setUp(self):\n"
                "        self.assertTrue = print\n\n" + method()),
    case_module("class ValueTest(unittest.TestCase):\n    def setUp(self):\n"
                "        setattr(self, NAME, print)\n\n" + method()),
    case_module("class ValueTest(unittest.TestCase):\n    def setUp(self):\n"
                "        self.__dict__['items'] = []\n\n" + method()),
    case_module("class ValueTest(unittest.TestCase, metaclass=Meta):\n" + method()),
    case_module("class ValueTest(unittest.TestCase):\n    def __getattribute__(self, name):\n"
                "        return object.__getattribute__(self, name)\n\n" + method()),
    case_module("class ValueTest(unittest.TestCase):\n    @classmethod\n"
                + method("cls.assertTrue(True)", "cls", "check")),
    case_module("class ValueTest(unittest.TestCase):\n"
                + method("case.assertTrue(True)").replace(
                    "        try:\n", "        case = unittest.TestCase()\n        try:\n", 1)),
    case_module("class ValueTest(unittest.TestCase):\n"
                + method().replace("        try:\n", "        self = unittest.TestCase()\n        try:\n", 1)),
    case_module("class ValueTest(unittest.TestCase):\n    def test_value(self):\n        def check():\n"
                + "".join("    " + line + "\n" for line in method().split("\n")[1:-1]) + "        check()\n"),
    case_module("class ValueTest(unittest.TestCase):\n    def setUp(self):\n"
                "        self.addTypeEqualityFunc(int, compare)\n\n" + method("self.assertEqual(1, 1)")),
    case_module("class ValueTest(unittest.TestCase):\n" + method()
                + "\n\nclass ValueTest(unittest.TestCase):\n    pass\n"),
], ids=[
    "no-base", "imported-project-base", "same-file-mixin", "imported-mixin-first", "class-defines-the-name",
    "base-assigns-the-name", "module-stores-the-name", "setup-stores-the-name", "computed-setattr-on-receiver",
    "dict-store", "metaclass", "getattribute", "classmethod", "other-receiver", "rebound-receiver",
    "nested-function", "type-equality-function", "class-name-bound-twice",
])
def test_a_unittest_call_outside_a_proved_testcase_method_is_unproved(source):
    # R49 condition two fails, so the call is unknown and the handler stays inspection.
    assert swallowed(source) == ()


def test_the_issue_pair_reports_the_always_passing_text():
    before = "from app import value\n\n\ndef test_value():\n    assert value() == 1\n"
    after = function_source("assert True", "except AssertionError:").decode()
    verdict, findings = outcome(before, after)
    text = "exceptAssertionError:" + _ALWAYS_PASSING
    assert verdict == "block"
    assert reported(findings) == [("BROAD_EXCEPT_ADDED", "high", text)]
    assert findings[0].message == f"broad exception handler added ({text})"


TWO = (
    "from app import other, value\n\n\n"
    "def test_value():\n"
    "    try:\n"
    "        assert value() == 1\n"
    "    except Exception:\n"
    "{first}"
    "\n\n"
    "def test_other():\n"
    "{second}"
)
PLAIN = "    assert other() == 2\n"
WRAPPED = "    try:\n        assert other() == 2\n    except Exception:\n{handler}"


@pytest.mark.parametrize("before,after,text", [
    # A literal-only handler repaired (it now re-raises) while a new
    # swallowing handler is added. One shared text would net them to zero.
    (TWO.format(first="        assert True\n", second=PLAIN),
     TWO.format(first="        assert True\n        raise\n", second=WRAPPED.format(handler="        pass\n")),
     "exceptException:"),
    # The mirror: an empty handler repaired, a literal-only one added.
    (TWO.format(first="        pass\n", second=PLAIN),
     TWO.format(first="        raise\n", second=WRAPPED.format(handler="        assert True\n")),
     "exceptException:" + _ALWAYS_PASSING),
    # The ruled cost (R50): an always-passing assertion added to a handler
    # that already swallows reports the new text.
    (TWO.format(first="        pass\n", second=PLAIN),
     TWO.format(first="        assert True\n", second=PLAIN),
     "exceptException:" + _ALWAYS_PASSING),
], ids=["repaired-literal-handler-cannot-pay", "repaired-empty-handler-cannot-pay", "literal-added-to-swallow"])
def test_literal_only_handlers_do_not_offset_swallowing_handlers(before, after, text):
    verdict, findings = outcome(before, after)
    assert verdict == "block"
    assert reported(findings) == [("BROAD_EXCEPT_ADDED", "high", text)]


@pytest.mark.parametrize("before,after", [
    (function_source("assert True").decode(), function_source("assert True").decode()),
    ("from app import value\n\n\ndef test_value():\n    assert value() == 1\n",
     "from app import value\n\n\ndef test_value():\n    try:\n        setup()\n"
     "    except Exception:\n        assert True\n    assert value() == 1\n"),
], ids=["unchanged-literal-handler", "try-guards-no-oracle"])
def test_no_new_swallowing_handler_adds_no_finding(before, after):
    verdict, findings = outcome(before, after)
    assert verdict == "pass"
    assert findings == []


def test_removing_the_literal_from_a_handler_still_reports_the_swallow():
    verdict, findings = outcome(
        function_source("assert True", "except Exception:").decode(),
        function_source("pass", "except Exception:").decode(),
    )
    assert verdict == "block"
    assert ("BROAD_EXCEPT_ADDED", "high", "exceptException:") in reported(findings)


@pytest.mark.parametrize("collect_tests", [True, False], ids=["test-file", "production-file"])
def test_the_broad_handler_text_is_unchanged(collect_tests):
    # A production file is judged on `broad_handlers`, which keeps main's text.
    parsed = parse_python(function_source("assert True", "except Exception:"), collect_tests=collect_tests)
    assert parsed.broad_handlers == ("exceptException:",)


@pytest.mark.parametrize("expression", ["-'a'", "value() or True"])
def test_the_branch_folder_is_unchanged(expression):
    # R51: `_static_truth` still folds these to True for `if` guards; the
    # handler proof answers unknown for both (see the inspection test above).
    assert _static_truth(ast.parse(expression, mode="eval").body) is True


@pytest.mark.parametrize("body", [
    "if False:\n    assert value() == 1",
    "return\nassert value() == 1",
])
def test_an_unreachable_oracle_in_a_handler_stays_a_residual(body):
    # R66: reachability is not read, so the handler is inspection, as on main.
    assert swallowed(function_source(body)) == ()


def test_the_unreachable_oracle_residual_passes_the_pair():
    verdict, findings = outcome(
        "from app import value\n\n\ndef test_value():\n    assert value() == 1\n",
        function_source("if False:\n    assert value() == 1", "except Exception:").decode(),
    )
    assert verdict == "pass"
    assert findings == []


def test_an_except_star_handler_is_read_the_same_way():
    source = function_source("assert True", "except* Exception:")
    assert swallowed(source) == ("except*Exception:" + _ALWAYS_PASSING,)
