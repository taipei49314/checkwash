"""A transformed table comparison keeps both its subject and literal answer."""
import pytest

from test_issue_expectation_families import run


PRODUCTION = ('def indent(text, n):\n    pad = " " * n\n    lines = text.split("\\n")\n'
              '    lines[0] = pad + lines[0]\n    return "\\n".join(lines)\n')
BEFORE = ('from app.prod import indent\ndef test_two():\n    assert indent("a\\nb", 2) == "  a\\n  b"\n'
          'def test_one():\n    assert indent("hi", 4) == "    hi"\n')
AFTER = ('from app.prod import indent\nimport pytest\n'
         '@pytest.mark.parametrize("text,n,expected", [("a\\nb",2,"  a\\n  b"),("hi",4,"    hi")])\n'
         'def test_indentation(text,n,expected):\n    result = indent(text,n)\n'
         '    assert result.strip().startswith(" " * n) == expected.strip().startswith(" " * n), f"result: {result}"\n')


def projected(ir):
    return any(unit.qualname.startswith('test_concrete_') for file in ir.files for unit in file.units)


def test_transformed_subject_is_preserved_and_existing_literal_detector_owns_the_answer_change():
    ir, findings, verdict = run(BEFORE, AFTER, PRODUCTION)
    assert projected(ir) and verdict == 'block'
    hits = [f for f in findings if f.rule == 'EXPECTED_VALUE_CHANGED']
    assert len(hits) == 2
    assert not [f for f in findings if f.rule in {'SUBJECT_NORMALIZED', 'ASSERT_SUBSTITUTED'}]
    for unit in ir.files[0].units:
        assert unit.before and unit.after
        old, new = unit.before.assertions[0], unit.after.assertions[0]
        assert old.strength == new.strength == 90
        assert 'indent(' in new.left and '.strip().startswith(' in new.left and new.right_value == 'False'
        assert 'result:' in new.text and 'startswith' in new.text


def test_inline_result_keeps_the_whole_normalized_call():
    after = AFTER.replace('    result = indent(text,n)\n', '').replace('result.strip()', 'indent(text,n).strip()')
    after = after.replace(', f"result: {result}"', '')
    ir, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert projected(ir) and verdict == 'block'
    assert all('indent(' in unit.after.assertions[0].left for unit in ir.files[0].units)


def test_correct_production_does_not_make_exact_and_weaker_checks_equivalent():
    production = 'def indent(text,n):\n    return " " * n + text\n'
    before = BEFORE[BEFORE.index('from app.prod'):BEFORE.index('def test_one')].replace('"a\\nb"', '"ab"').replace('"  a\\n  b"', '"  ab"')
    after = AFTER.replace('[("a\\nb",2,"  a\\n  b"),("hi",4,"    hi")]', '[("ab",2,"  ab")]')
    ir, findings, verdict = run(before, after, production)
    assert projected(ir) and verdict == 'block'
    assert any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


def test_honest_exact_table_extraction_keeps_the_existing_precision_path():
    after = AFTER.replace('result.strip().startswith(" " * n)', 'result').replace('expected.strip().startswith(" " * n)', 'expected')
    ir, findings, verdict = run(BEFORE, after, PRODUCTION)
    # Existing generic precision may conservatively withhold the custom fresh
    # split-list production grammar; this new proof must not manufacture it.
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


def test_adding_normalized_rows_beside_retained_exact_tests_is_not_replacement():
    after = AFTER + BEFORE.removeprefix('from app.prod import indent\n')
    ir, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert not projected(ir) and verdict == 'pass'
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


def test_input_only_change_retains_the_existing_silent_contract():
    ir, findings, verdict = run(BEFORE, BEFORE.replace('indent("hi", 4)', 'indent("hi", 3)'), PRODUCTION)
    assert not projected(ir) and not findings and verdict == 'pass'


def test_additional_normalized_rows_follow_every_original_obligation():
    after = AFTER.replace('("hi",4,"    hi")]', '("hi",4,"    hi"),("extra",1," extra")]')
    ir, findings, verdict = run(BEFORE, after, PRODUCTION)
    assert projected(ir) and verdict == 'block' and len(ir.files[0].units) == 3
    assert len([f for f in findings if f.rule == 'EXPECTED_VALUE_CHANGED']) == 2


@pytest.mark.parametrize('after', [
    AFTER.replace('("a\\nb",2,"  a\\n  b")', '("different",2,"  a\\n  b")'),
    AFTER.replace('("a\\nb",2,"  a\\n  b")', '("a\\nb",3,"  a\\n  b")'),
    AFTER.replace('("a\\nb",2,"  a\\n  b")', '("a\\nb",2,"different")'),
    AFTER.replace('[("a\\nb",2,"  a\\n  b"),("hi",4,"    hi")]', '[("hi",4,"    hi"),("a\\nb",2,"  a\\n  b")]'),
    AFTER.replace(',("hi",4,"    hi")', ''),
    AFTER.replace('[("a\\nb",2,"  a\\n  b"),("hi",4,"    hi")]', '[("a\\nb",2,"  a\\n  b"),("a\\nb",2,"  a\\n  b")]'),
])
def test_raw_input_answer_order_and_multiplicity_must_all_survive(after):
    ir, findings, _ = run(BEFORE, after, PRODUCTION)
    assert not projected(ir)
    assert not any(f.rule == 'EXPECTED_VALUE_CHANGED' for f in findings)


def test_duplicate_calls_keep_independent_occurrence_units():
    before = BEFORE.replace('indent("hi", 4) == "    hi"', 'indent("a\\nb", 2) == "  a\\n  b"')
    after = AFTER.replace('("hi",4,"    hi")', '("a\\nb",2,"  a\\n  b")')
    ir, findings, _ = run(before, after, PRODUCTION)
    assert projected(ir) and len({unit.qualname for unit in ir.files[0].units}) == 2
    assert len([f for f in findings if f.rule == 'EXPECTED_VALUE_CHANGED']) == 2


@pytest.mark.parametrize('after', [
    AFTER.replace('text,n,expected):', 'text,n,expected=other):'),
    AFTER.replace('"text,n,expected"', '"text,indent,expected"').replace('text,n,expected):', 'text,indent,expected):'),
    AFTER.replace('def test_indentation', '@pytest.mark.skip\ndef test_indentation'),
    AFTER.replace('"text,n,expected", [', '"text,n,expected", [pytest.param('),
    AFTER.replace('    result =', '    mutate()\n    result ='),
    AFTER.replace('result: {result}', 'result: {callback()}'),
    AFTER.replace('result: {result}', 'result: {result:custom}'),
    AFTER.replace('result.strip()', 'custom(result).strip()'),
    AFTER.replace('expected.strip()', 'custom(expected).strip()'),
    AFTER.replace('result.strip()', 'result.rstrip()'),
    AFTER.replace('" " * n', 'prefix(n)'),
    AFTER.replace('import pytest', 'import pytest\nimport mutator'),
    AFTER + '\ndef test_callback():\n    mutate()\n',
])
def test_unknown_binding_or_execution_shapes_withhold_projection(after):
    assert not projected(run(BEFORE, after, PRODUCTION)[0])


@pytest.mark.parametrize('production', [
    'class Custom:\n    def strip(self):\n        return self\n    def startswith(self,prefix):\n        return False\ndef indent(text,n):\n    return Custom()\n',
    PRODUCTION.replace('return "\\n".join(lines)', 'return external(lines)'),
    PRODUCTION.replace('lines[0] = pad + lines[0]', 'lines[0] = mutate(lines[0])'),
    PRODUCTION.replace('lines[0] = pad + lines[0]', 'text[0] = pad + lines[0]'),
    PRODUCTION.replace('    lines[0]', '    alias = lines\n    lines[0]', 1),
    PRODUCTION + '\nimport mutator\n',
    'from tests.test_case import test_indentation\n' + PRODUCTION,
    '@external\n' + PRODUCTION,
])
def test_custom_results_alias_mutation_and_backlinks_are_not_primitive_string_proof(production):
    assert not projected(run(BEFORE, AFTER, production)[0])


@pytest.mark.parametrize('context', [
    {'src/app/__init__.py': b'mutate()\n'},
    {'src/pytest.py': b''},
    {'tests/conftest.py': b'import pytest\n@pytest.fixture(autouse=True)\ndef alter():\n    mutate()\n'},
])
def test_import_and_fixture_authority_are_required(context):
    assert not projected(run(BEFORE, AFTER, PRODUCTION, context=context)[0])
