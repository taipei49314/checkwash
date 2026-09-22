"""A patch's returned callable must replace a subject result, not instrumentation."""

import textwrap

import pytest

from test_standin_installations_main import hits, judge


PREFIX = "from unittest.mock import patch\nfrom app.billing import total\n"
BEFORE = PREFIX + "def test_total():\n    assert total(6) == 8\n"


def result(body, prefix=PREFIX, before=BEFORE):
    after = prefix + "def test_total():\n" + textwrap.indent(textwrap.dedent(body).strip() + "\n", "    ")
    return judge({"tests/test_total.py": before.encode()}, {"tests/test_total.py": after.encode()})


def test_literal_table_side_effect_result_closes_historical_escape009():
    before = PREFIX + """
def test_total():
    cases = [0, 1, 6]
    expected = {0: 0, 1: 1, 6: 8}
    for n in cases:
        assert total(n) == expected[n]
"""
    found = hits(result("""
        expected = {0: 0, 1: 1, 6: 8}
        with patch('app.billing.total', side_effect=lambda n: expected.get(n, None)) as mock_total:
            cases = [0, 1, 6]
            for n in cases:
                assert mock_total(n) == expected[n]
    """, before=before))
    assert len(found) == 1
    assert found[0].severity == "high"
    assert "app.billing.total" in found[0].message


@pytest.mark.parametrize("configuration", ["return_value=8", "side_effect=lambda n: 8", "side_effect=[8]"])
@pytest.mark.parametrize("api,prefix,target", [
    ("patch", PREFIX, "'app.billing.total'"),
    ("standin", PREFIX.replace("import patch", "import patch as standin"), "'app.billing.total'"),
    ("mock.patch", "from unittest import mock\nfrom app.billing import total\n", "'app.billing.total'"),
    ("patch.object", PREFIX + "import app.billing as billing\n", "billing, 'total'"),
])
def test_bound_stdlib_aliases_prove_a_consumed_stub(api, prefix, target, configuration):
    found = hits(result(f"with {api}({target}, {configuration}) as replacement:\n    assert replacement(6) == 8", prefix))
    assert len(found) == 1


@pytest.mark.parametrize("configuration", [
    "wraps=total", "side_effect=total", "side_effect=lambda n: total(n)",
    "side_effect=lambda n, captured=total(6): captured", "side_effect=lambda n: n", "new=total",
])
def test_real_provider_forwarding_is_not_literal_stub_proof(configuration):
    assert not hits(result(f"with patch('app.billing.total', {configuration}) as replacement:\n    assert replacement(6) == 8"))


@pytest.mark.parametrize("body", [
    "with patch('app.billing.total', return_value=8) as replacement:\n    assert replacement.call_count == 0",
    "with patch('app.billing.total', return_value=8) as replacement:\n    assert replacement.called is False",
    "with patch('app.billing.total', return_value=8) as replacement:\n    for n in []:\n        assert replacement(n) == 8",
    "with patch('app.billing.total', return_value=8) as replacement:\n    for n in unknown:\n        assert replacement(n) == 8",
    "with patch('app.billing.total', return_value=8) as replacement:\n    rows = [6]\n    rows.clear()\n    for n in rows:\n        assert replacement(n) == 8",
    "with patch('app.billing.total', return_value=8) as replacement:\n    for n in [6]:\n        break\n        assert replacement(n) == 8",
    "with patch('app.billing.total', return_value=8) as replacement:\n    if False:\n        assert replacement(6) == 8",
    "if False:\n    with patch('app.billing.total', return_value=8) as replacement:\n        assert replacement(6) == 8",
    "expected = {6: 8}\nwith patch('app.billing.total', side_effect=lambda n: expected.get(n)) as replacement:\n    expected = provider_table()\n    assert replacement(6) == 8",
    "expected = {6: 8}\nwith patch('app.billing.total', side_effect=lambda n: expected.get(n)) as replacement:\n    expected[6] = total(6)\n    assert replacement(6) == 8",
    "expected = {6: 8}\nwith patch('app.billing.total', side_effect=lambda n: expected.get(n)) as replacement:\n    mutate(expected)\n    assert replacement(6) == 8",
    "with patch('app.billing.total', return_value=8) as replacement:\n    pass\nassert replacement(6) == 8",
    "with patch('app.billing.total', return_value=8) as replacement:\n    assert callback.property == replacement(6)",
    "with patch('app.billing.total', return_value=8) as replacement:\n    assert replacement(custom_argument) == 8",
    "with patch('app.billing.total', return_value=8) as replacement:\n    assert False\n    assert replacement(6) == 8",
    "with patch('app.billing.total', return_value=8) as replacement:\n    assert 0 == 1 == replacement(6)",
    "with patch('app.billing.total', return_value=8) as replacement:\n    assert [][0] == replacement(6)",
    "with patch('app.billing.total', return_value=8) as replacement:\n    assert replacement([][0]) == 8",
    "expected = {6: 8}\nwith patch('app.billing.total', side_effect=lambda n: expected.get(n)) as replacement:\n    for n in [[]]:\n        assert replacement(n) == 8",
    "expected = {6: 8}\nwith patch('app.billing.total', side_effect=lambda n: expected[n]) as replacement:\n    assert replacement(7) == 8",
    "with patch('app.billing.total', side_effect=[]) as replacement:\n    assert replacement(6) == 8",
])
def test_unused_unreachable_or_mutable_patch_context_has_no_new_proof(body):
    assert not hits(result(body))


@pytest.mark.parametrize("statement", ["assert total(6) == 8", "replacement = total\n    assert replacement(6) == 8"])
def test_captured_from_import_has_no_mock_result_event(statement):
    # The legacy suffix-only patch channel reports this pre-existing boundary;
    # this change must not manufacture result provenance for the captured original.
    ir, _findings, _verdict = result("with patch('app.billing.total', return_value=8) as replacement:\n    " + statement)
    assert not ir.globals.subject_installations


def test_unused_patch_beside_an_aliased_original_preserves_the_oracle():
    prefix = PREFIX.replace("import total", "import total as subject")
    before = BEFORE.replace("import total", "import total as subject").replace("total(6)", "subject(6)")
    assert not hits(result("with patch('app.billing.total', return_value=8) as replacement:\n    assert subject(6) == 8",
                           prefix, before))


@pytest.mark.parametrize("path", ["unittest.py", "unittest/__init__.py", "src/unittest.py", "tests/unittest.py"])
def test_repository_unittest_shadow_is_not_stdlib_patch_authority(path):
    after = PREFIX + "def test_total():\n    with patch('app.billing.total', return_value=8) as replacement:\n        assert replacement(6) == 8\n"
    ir, _findings, _verdict = judge({"tests/test_total.py": BEFORE.encode()},
                                  {"tests/test_total.py": after.encode()}, {path: b"# custom module\n"})
    assert not ir.globals.subject_installations


def test_patch_spelling_and_external_target_are_not_authority():
    assert not hits(result("with patch('app.billing.total', return_value=8) as replacement:\n    assert replacement(6) == 8",
                           "from custom import patch\nfrom app.billing import total\n"))
    assert not hits(result("with patch('decimal.total', return_value=8) as replacement:\n    assert replacement(6) == 8"))


def test_already_consumed_mock_is_not_new_installation():
    source = PREFIX + "def test_total():\n    with patch('app.billing.total', return_value=8) as replacement:\n        assert replacement(6) == 8\n"
    assert not hits(judge({"tests/test_total.py": source.encode()},
                          {"tests/test_total.py": source.replace("replacement(6)", "replacement( 6 )").encode()}))


def test_import_parameter_and_table_renames_are_not_new_installations():
    before = PREFIX + "def test_total():\n    expected = {6: 8}\n    with patch('app.billing.total', side_effect=lambda n: expected.get(n)) as replacement:\n        assert replacement(6) == 8\n"
    after = before.replace("import patch", "import patch as standin").replace("with patch(", "with standin(")
    after = after.replace("expected", "answers").replace("lambda n:", "lambda index:").replace(".get(n)", ".get(index)")
    after = after.replace("replacement", "substitute")
    assert not hits(judge({"tests/test_total.py": before.encode()}, {"tests/test_total.py": after.encode()}))
