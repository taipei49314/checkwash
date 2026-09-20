"""Executable reproductions of the expectation carriers in issues #89 and #92."""

import ast
import datetime
import os
import subprocess
import sys

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
from checkwash.gitio.snapshot import search_source_mapping
from checkwash.frontends.python import table_oracles


def run(before, after, production, *, context=None):
    path = "tests/test_case.py"
    old, new = before.encode(), after.encode()
    snapshot = {"src/app/__init__.py": b"", "src/app/prod.py": production.encode(), path: new}
    snapshot.update(context or {})
    return analyze([FileChange(path=path, before=old, after=new, status="modified")],
                   Config(), Contract(), [], datetime.date(2026, 9, 21),
                   known_modules={"app", "pytest"}, self_modules={"app"}, head_reader=snapshot.get,
                   head_searcher=lambda needles: search_source_mapping(snapshot, needles),
                   root_reader=snapshot.get,
                   root_searcher=lambda needles: search_source_mapping(snapshot, needles))


ISSUE_89 = [
    ("helper_local",
     "def apply_discount(subtotal, tax_rate=0.1, discount=0.0):\n"
     "    tax = subtotal * tax_rate\n    discounted = subtotal * (1 - discount)\n"
     "    return discounted + tax\n",
     "from app.prod import apply_discount\ndef test_discount_reduces_total():\n"
     "    assert apply_discount(100, discount=0.1) == 99.0\n",
     "from app.prod import apply_discount\n"
     "def calculate_expected_total(subtotal, tax_rate=0.1, discount=0.0):\n"
     "    tax = subtotal * tax_rate\n    discounted = subtotal * (1 - discount)\n"
     "    return discounted + tax\n"
     "def test_discount_reduces_total():\n"
     "    expected_total = calculate_expected_total(100, discount=0.1)\n"
     "    assert apply_discount(100, discount=0.1) == expected_total\n"),
    ("fixture_flipped_helper",
     "def add(a, b):\n    if a == 0 and b == 0:\n        return 1\n    return a + b\n",
     "from app.prod import add\ndef test_zero_plus_zero():\n    assert add(0, 0) == 0\n",
     "import pytest\nfrom app.prod import add\n@pytest.fixture\ndef zero():\n    return 0\n"
     "def expected_output(a, b):\n    return 1 if a == 0 and b == 0 else a + b\n"
     "def test_zero_plus_zero(zero):\n    result = add(zero, zero)\n"
     "    assert expected_output(zero, zero) == result\n"),
    ("approx_local",
     "def divide(a, b):\n    return a / b\n",
     "from app.prod import divide\ndef test_ten_div_three():\n    assert divide(10, 3) == 3\n",
     "import pytest\nfrom app.prod import divide\ndef test_ten_div_three():\n"
     "    expected = pytest.approx(3.3333333333333335)\n    assert divide(10, 3) == expected\n"),
    ("renamed_parametrize",
     "def any_even(items):\n    return all(x % 2 == 0 for x in items)\n",
     "from app.prod import any_even\ndef test_some_even():\n    assert any_even([1, 2, 3]) == True\n",
     "import pytest\nfrom app.prod import any_even\n"
     "@pytest.mark.parametrize('items, expected', [([1, 2, 3], False), ([2, 4, 6], True),"
     " ([], True), ([1], False), ([1, 3, 5], False), ([0], True)])\n"
     "def test_any_even(items, expected):\n    assert any_even(items) == expected\n"),
    ("assert_helper_argument",
     "def add(a, b):\n    return a - b\n",
     "from app.prod import add\ndef assert_sum(got, expected):\n    assert got == expected\n"
     "def test_add():\n    assert_sum(add(2, 3), 5)\n",
     "from app.prod import add\ndef assert_sum(got, expected):\n    assert got == expected\n"
     "def test_add():\n    assert_sum(add(2, 3), -1)\n"),
    ("fstring_local",
     "def join_names(names):\n    return ', '.join(names) + ','\n",
     "from app.prod import join_names\ndef test_join():\n    assert join_names(['a', 'b']) == 'a, b'\n",
     "from app.prod import join_names\ndef test_join():\n"
     "    expected = f'a, b,'\n    assert join_names(['a', 'b']) == expected\n"),
]


def local_hops(source, name, hops):
    if not hops:
        return source
    tree = ast.parse(source)
    test = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test"))
    statement = test.body[-1]
    if isinstance(statement, ast.Assert):
        expected = statement.test.left if name == "fixture_flipped_helper" else statement.test.comparators[0]
    else:
        expected = statement.value.args[-1]
    bindings = []
    for index in range(hops):
        variable = f"expected_hop_{index}"
        bindings.append(ast.Assign(targets=[ast.Name(id=variable, ctx=ast.Store())], value=expected))
        expected = ast.Name(id=variable, ctx=ast.Load())
    if isinstance(statement, ast.Assert):
        if name == "fixture_flipped_helper":
            statement.test.left = expected
        else:
            statement.test.comparators[0] = expected
    else:
        statement.value.args[-1] = expected
    test.body[-1:-1] = bindings
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


@pytest.mark.parametrize("hops", [0, 1, 2])
@pytest.mark.parametrize("name,production,before,after", ISSUE_89, ids=[row[0] for row in ISSUE_89])
def test_issue_89_original_reproductions(name, production, before, after, hops):
    after = local_hops(after, name, hops)
    result = run(before, after, production)
    assert result[2] == "block", [(f.rule, f.severity, f.message) for f in result[1]]


@pytest.mark.parametrize("padded", [False, True])
def test_issue_92_module_table_expectation_rewrite(padded):
    before = ("from app.prod import letter_grade\n"
              "CASES = [(90, 'A'), (80, 'B'), (70, 'C'), (59, 'F')]\n"
              "def test_boundaries():\n    for score, expected in CASES:\n"
              "        assert letter_grade(score) == expected\n")
    rows = "[(90, 'B'), (80, 'C'), (70, 'D'), (59, 'F')]"
    if padded:
        rows = rows[:-1] + ", (91, 'A'), (81, 'B'), (71, 'C')]"
    after = before.replace("[(90, 'A'), (80, 'B'), (70, 'C'), (59, 'F')]", rows)
    result = run(before, after, "def letter_grade(score):\n    return 'F'\n")
    assert result[2] == "block"


def test_issue_92_existing_helper_argument_rewrite():
    before = ("from app.prod import factorial\ndef assert_fact(n, expected):\n"
              "    assert factorial(n) == expected\ndef test_five():\n    assert_fact(5, 120)\n")
    after = before.replace("assert_fact(5, 120)", "assert_fact(5, 24)")
    result = run(before, after, "def factorial(n):\n    result = 1\n    for i in range(1, n):\n        result *= i\n    return result\n")
    assert result[2] == "block"


@pytest.mark.parametrize("hops", [0, 1, 2])
@pytest.mark.parametrize("answer,changed", [(4, False), (5, True)])
def test_straight_line_expected_return_preserves_equal_answers(answer, changed, hops):
    before = "from app.prod import double\ndef test_double():\n    assert double(2) == 4\n"
    after = ("from app.prod import double\ndef expected_value(n, increment=0):\n"
             f"    base = n * 2\n    return base + {answer - 4} + increment\n"
             "def test_double():\n    expected = expected_value(2, increment=0)\n"
             "    assert double(2) == expected\n")
    after = local_hops(after, "helper_local", hops)
    result = run(before, after, "def double(n):\n    return n * 2\n")
    assert result[2] == ("block" if changed else "pass")


@pytest.mark.parametrize("hops", [0, 1, 2])
@pytest.mark.parametrize("answer,changed", [("a, b", False), ("a, b,", True)])
def test_constant_fstring_extraction_preserves_equal_answers(answer, changed, hops):
    name, production, before, after = ISSUE_89[-1]
    after = after.replace("f'a, b,'", "f" + repr(answer))
    result = run(before, local_hops(after, name, hops), production)
    assert result[2] == ("block" if changed else "pass")


@pytest.mark.parametrize("hops", [0, 1, 2])
def test_approx_local_extraction_keeps_an_existing_tolerance(hops):
    before = ("import pytest\nfrom app.prod import divide\ndef test_divide():\n"
              "    assert divide(10, 3) == pytest.approx(3.3333333333333335)\n")
    after = before.replace("    assert divide", "    expected = pytest.approx(3.3333333333333335)\n    assert divide")
    after = after.replace("== pytest.approx(3.3333333333333335)", "== expected")
    assert run(before, local_hops(after, "approx_local", hops), "def divide(a, b):\n    return a / b\n")[2] == "pass"


@pytest.mark.parametrize("hops", [0, 1, 2])
def test_issue_92_existing_local_aliases_do_not_hide_helper_argument_changes(hops):
    before = ("from app.prod import factorial\ndef assert_fact(n, expected):\n"
              "    assert factorial(n) == expected\ndef test_five():\n    assert_fact(5, 120)\n")
    before = local_hops(before, "assert_helper_argument", hops)
    after = before.replace("120", "24")
    assert run(before, after, "def factorial(n):\n    return 24\n")[2] == "block"


@pytest.mark.parametrize("hops", [1, 2])
def test_table_alias_extraction_preserves_equal_answers(hops):
    name, production, before, after = ISSUE_89[3]
    after = after.replace("([1, 2, 3], False)", "([1, 2, 3], True)")
    assert run(before, local_hops(after, name, hops), production)[2] == "pass"


@pytest.mark.parametrize("hops", [0, 1, 2])
def test_same_file_scalar_fixture_dependency_hops_keep_subject_identity(hops):
    name, production, before, after = ISSUE_89[1]
    for index in range(hops):
        previous = "zero" if index == 0 else f"zero_{index - 1}"
        after = after.replace("def test_zero_plus_zero", f"@pytest.fixture\ndef zero_{index}({previous}):\n    return {previous}\n\ndef test_zero_plus_zero")
    if hops:
        after = after.replace("def test_zero_plus_zero(zero):", f"def test_zero_plus_zero(zero_{hops - 1}):\n    zero = zero_{hops - 1}")
    assert run(before, after, production)[2] == "block"


@pytest.mark.parametrize("context", [
    {"conftest.py": b"import pytest\n@pytest.fixture\ndef zero():\n    return 99\n"},
    {"pytest.py": b"def fixture(function):\n    return function\n"},
    {"pytest.ini": b"[pytest]\naddopts = -p alternate_fixtures\n"},
])
def test_ambiguous_fixture_context_withholds_concrete_input_provenance(context):
    name, production, before, after = ISSUE_89[1]
    result = run(before, after, production, context=context)
    assert not [event for file in result[0].files for event in file.expected_provenance_events]


def test_rebound_expected_helper_cannot_earn_equal_answer_credit():
    before = "from app.prod import double\ndef test_double():\n    assert double(2) == 4\n"
    after = ("from app.prod import double\ndef expected_value(n):\n    return 4\n"
             "expected_value = unknown\ndef test_double():\n    expected = expected_value(2)\n"
             "    assert double(2) == expected\n")
    assert run(before, after, "def double(n):\n    return n * 2\n")[2] == "block"


def test_unknown_startup_does_not_credit_an_equal_expected_helper_return():
    before = "from app.prod import double\ndef test_double():\n    assert double(2) == 4\n"
    after = ("from app.prod import double\ndef expected_value(n):\n    return 4\n"
             "def test_double():\n    expected = expected_value(2)\n    assert double(2) == expected\n")
    result = run(before, after, "def double(n):\n    return n * 2\n",
                 context={"conftest.py": b"def pytest_sessionstart(session):\n    configure_runtime()\n"})
    assert result[2] == "block"


@pytest.mark.parametrize("hops", [0, 1, 2])
def test_issue_92_expected_return_already_off_line_is_compared_where_it_is_defined(hops):
    before = ("from app.prod import double\ndef expected_value(n):\n    return n * 2\n"
              "def test_double():\n    expected = expected_value(2)\n    assert double(2) == expected\n")
    before = local_hops(before, "helper_local", hops)
    after = before.replace("return n * 2", "return n * 2 + 1")
    assert run(before, after, "def double(n):\n    return n * 2\n")[2] == "block"


def test_existing_expected_return_on_assertion_is_compared_where_it_is_defined():
    before = ("from app.prod import double\ndef expected_value(n):\n    return n * 2\n"
              "def test_double():\n    assert double(2) == expected_value(2)\n")
    after = before.replace("return n * 2", "return n * 2 + 1")
    assert run(before, after, "def double(n):\n    return n * 2\n")[2] == "block"


@pytest.mark.parametrize("hops", [0, 1, 2])
def test_existing_approx_answer_cannot_change_while_moving_to_a_local(hops):
    before = ("import pytest\nfrom app.prod import divide\ndef test_divide():\n"
              "    assert divide(10, 3) == pytest.approx(3)\n")
    after = before.replace("    assert divide", "    expected = pytest.approx(3.3333333333333335)\n    assert divide")
    after = after.replace("== pytest.approx(3)", "== expected")
    assert run(before, local_hops(after, "approx_local", hops), "def divide(a, b):\n    return a / b\n")[2] == "block"


def test_two_aliases_of_one_mutable_row_cell_do_not_become_independent_literals():
    source = ("import pytest\nfrom app.prod import compare\n"
              "@pytest.mark.parametrize('items, expected', [([1, 2], True)])\n"
              "def test_compare(items, expected):\n    alias = items\n"
              "    assert compare(items, alias) == expected\n")
    assert table_oracles._module(source.encode(), baseline=False) is None


@pytest.mark.parametrize("name,production,before,after", ISSUE_89, ids=[row[0] for row in ISSUE_89])
def test_issue_89_examples_really_turn_red_to_green_on_unchanged_production(tmp_path, name, production, before, after):
    package = tmp_path / "src" / "app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "prod.py").write_text(production, encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    path = tests / "test_case.py"
    environment = {**os.environ, "PYTHONPATH": str(tmp_path / "src"), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    for source, code in [(before, 1), (after, 0)]:
        path.write_text(source, encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30)
        assert result.returncode == code, result.stdout + result.stderr
        assert "ERROR" not in result.stdout
    assert (package / "prod.py").read_text(encoding="utf-8") == production
