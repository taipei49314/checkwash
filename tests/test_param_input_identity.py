"""Input-role evidence is local, two-sided and bounded by visible source.

These run in the remote validation pool. The no-op decorator example at the
end records the same syntactic-consumption residual as sut(expected); it is
not an adversarial case claimed to be protected by this proof.
"""

import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze


def source(rows, *, names='options,expected', body=None, prelude='', indirect=''):
    if body is None:
        body = '    assert sut(options) == expected\n'
    return (
        'import pytest\nfrom app.core import sut, decorate, invoke\n' + prelude
        + '@pytest.mark.parametrize(' + repr(names) + ', [' + ', '.join(rows) + ']' + indirect + ')\n'
        + 'def test_value(' + names + '):\n' + body
    ).encode()


def run(before, after, *, root=None):
    return analyze(
        [FileChange('tests/test_case.py', 'modified', before, after)],
        Config(), Contract(), [], datetime.date(2026, 9, 12),
        root_reader=(root or {}).get, root_searcher=lambda _needles: [],
    )


def edc(result):
    return [finding for finding in result[1] if finding.rule == 'EXPECTATION_DEFINITION_CHANGED']


def credits(result):
    return result[0].files[0].param_input_identity_pairs


def test_single_active_dict_leaf_copies_its_answer_on_both_sides():
    before = source(["({'used': 1, 'other': 7}, 1)"])
    after = source(["({'other': 7, 'used': 2}, 2)"])
    result = run(before, after)
    assert not edc(result)
    assert len(credits(result)) == 1


def test_selected_dict_field_is_supported_without_crediting_other_fields():
    body = "    assert sut(options['used']) == expected\n"
    result = run(source(["({'used': 1, 'other': 7}, 1)"], body=body),
                 source(["({'used': 2, 'other': 7}, 2)"], body=body))
    assert not edc(result)
    assert len(credits(result)) == 1


@pytest.mark.parametrize('old,new,body', [
    ("({'used': 7, 'ignored': 1}, 1)", "({'used': 7, 'ignored': 2}, 2)",
     "    assert sut(options['used']) == expected\n"),
    ("({'used': 1, 'other': 7}, 1)", "({'used': 2, 'other': 8}, 2)", None),
    ("({'used': 1}, 8)", "({'used': 2}, 2)", None),
    ("({'used': 1}, 1)", "({'used': 2}, 3)", None),
    ("({'used': 1, 'used': 9}, 1)", "({'used': 2, 'used': 9}, 2)", None),
    ("({'used': 1, 'other': effect()}, 1)", "({'used': 2, 'other': effect()}, 2)", None),
    ("({'used': obj.one}, obj.one)", "({'used': obj.two}, obj.two)", None),
    ("({'used': effect(1)}, effect(1))", "({'used': effect(2)}, effect(2))", None),
    ("({'used': 1, **extra}, 1)", "({'used': 2, **extra}, 2)", None),
])
def test_unproved_leaf_projection_keeps_the_replacement_owner(old, new, body):
    result = run(source([old], body=body), source([new], body=body))
    assert edc(result)
    assert not credits(result)


@pytest.mark.parametrize('setup', [
    "    options['used'] = 7\n",
    "    options.clear()\n",
    "    alias = options\n    alias.update({'used': 7})\n",
    "    ignored = mutate(options)\n",
    "    mutate(options)\n",
    "    del options['used']\n",
    "    options['used'] += 1\n",
    "    globals()['options'] = {'used': 7}\n",
])
def test_visible_input_mutation_cannot_borrow_raw_row_identity(setup):
    body = setup + '    assert sut(options) == expected\n'
    result = run(source(["({'used': 1}, 1)"], body=body),
                 source(["({'used': 2}, 2)"], body=body))
    assert edc(result)
    assert not credits(result)


@pytest.mark.parametrize('indirect', [", indirect=['options']", ', indirect=True', ', indirect=mode'])
def test_indirect_fixture_values_are_not_the_literal_table_input(indirect):
    prelude = "@pytest.fixture\ndef options(request):\n    return {'used': 7}\n"
    result = run(source(["({'used': 1}, 1)"], prelude=prelude, indirect=indirect),
                 source(["({'used': 2}, 2)"], prelude=prelude, indirect=indirect))
    assert edc(result)
    assert not credits(result)


def test_explicit_direct_parametrize_keeps_identity_evidence():
    result = run(source(["({'used': 1}, 1)"], indirect=', indirect=False'),
                 source(["({'used': 2}, 2)"], indirect=', indirect=False'))
    assert not edc(result)
    assert len(credits(result)) == 1


DECORATED = (
    '    @decorate(default=expected)\n'
    '    def cli():\n'
    '        pass\n'
    '    assert cli.params[0].default == expected\n'
)


def test_same_active_decorated_function_exposes_its_setup_input_role():
    result = run(source(['(1,)', '(2,)'], names='expected', body=DECORATED),
                 source(['(2,)', '(3,)'], names='expected', body=DECORATED))
    assert not edc(result)
    assert result[0].files[0].shared_param_input_pairs


def test_click_default_setup_keeps_fixture_receiver_and_later_membership_oracles():
    # The first assertion/body comes from click d36de6fc... (10b77f98 parent).
    # In particular runner is a fixture and default is also a decorator input.
    body = ('    @click.command()\n'
            '    @click.option("-g", type=click.Choice(choices), default=default, show_default=True)\n'
            '    def cli_with_choices(g):\n        pass\n'
            '    assert cli_with_choices.params[0].default == default\n'
            '    result = runner.invoke(cli_with_choices, ["--help"])\n'
            '    extra_usage = f"[default: {default_string}]"\n'
            '    if default_string is None:\n        assert extra_usage not in result.output\n'
            '    else:\n        assert extra_usage in result.output\n')
    before = source(["(['one', 'two'], 'one', 'one')"], names='choices,default,default_string', body=body, prelude='import click\n')
    after = source(["(['one', 'two'], 'two', 'two')"], names='choices,default,default_string', body=body, prelude='import click\n')
    result = run(before.replace(b'def test_value(', b'def test_value(runner,'),
                 after.replace(b'def test_value(', b'def test_value(runner,'))
    assert not edc(result)
    assert any(pair[3] == 'default' for pair in result[0].files[0].shared_param_input_pairs)


@pytest.mark.parametrize('body', [
    DECORATED.replace('cli.params[0].default', 'sut(7)'),
    DECORATED.replace('    assert ', '    cli.params[0].default = 7\n    assert '),
    DECORATED.replace('    assert ', '    alias = cli\n    alias.params[0].default = 7\n    assert '),
    DECORATED.replace('    assert ', '    cli.reset()\n    assert '),
    DECORATED.replace('    assert ', '    alias = cli\n    alias.reset()\n    assert '),
    DECORATED.replace('    assert ', '    cli = other\n    assert '),
    DECORATED.replace('    assert ', "    vars(cli)['default'] = 7\n    assert "),
    ('    @decorate(expected)\n    def unused():\n        pass\n'
     '    def used():\n        return 7\n'
     "    callbacks = {'used': used, 'unused': unused}\n"
     "    result = invoke(callbacks['used'])\n    assert result == expected\n"),
    ('    @decorate(expected)\n    def unused():\n        pass\n'
     '    def used():\n        return 7\n'
     '    result = invoke([unused, used][1])\n    assert result == expected\n'),
])
def test_unused_rebound_or_mutated_producer_keeps_its_oracle(body):
    result = run(source(['(1,)', '(2,)'], names='expected', body=body),
                 source(['(2,)', '(3,)'], names='expected', body=body))
    assert edc(result)
    assert not result[0].files[0].shared_param_input_pairs


def test_new_after_only_producer_does_not_reclassify_the_before_oracle():
    before = source(['(1,)', '(2,)'], names='expected', body=DECORATED.replace('    @decorate(default=expected)\n', ''))
    after = source(['(2,)', '(3,)'], names='expected', body=DECORATED)
    result = run(before, after)
    assert edc(result)
    assert not result[0].files[0].shared_param_input_pairs


@pytest.mark.parametrize('before_provider,after_provider', [
    ('', 'decorate = ignore\n'),
    ('def configure(value):\n    return make(value)\ndecorate = configure\n',
     'def configure(value):\n    return ignore(value)\ndecorate = configure\n'),
    ('alias = decorate\n', 'alias = decorate\nalias.__code__ = replacement.__code__\n'),
    ('alias = decorate\nsecond = alias\n', 'alias = decorate\nsecond = alias\nsecond.__code__ = replacement.__code__\n'),
])
def test_changed_visible_decorator_provider_cannot_borrow_unchanged_nested_ast(before_provider, after_provider):
    result = run(source(['(1,)', '(2,)'], names='expected', body=DECORATED, prelude=before_provider),
                 source(['(2,)', '(3,)'], names='expected', body=DECORATED, prelude=after_provider))
    assert edc(result)
    assert not result[0].files[0].shared_param_input_pairs


ENUM = 'import enum\nclass Mode(enum.Enum):\n    A = enum.auto()\n    B = enum.auto()\n'


def enum_result(prelude=ENUM, *, root=None):
    return run(source(["({'flag': Mode.A}, Mode.A)"], prelude=prelude),
               source(["({'flag': Mode.B}, Mode.B)"], prelude=prelude), root=root)


def test_unchanged_plain_enum_member_has_source_authority():
    result = enum_result()
    assert not edc(result)
    assert len(credits(result)) == 1


def test_strenum_compatibility_alias_does_not_modify_enum_member_authority():
    result = enum_result('import enum\nimport sys\nif sys.version_info < (3, 11):\n    enum.StrEnum = enum.Enum\n' + ENUM.removeprefix('import enum\n'))
    assert not edc(result)
    assert len(credits(result)) == 1


@pytest.mark.parametrize('prelude', [
    ENUM + 'Mode = other\n',
    ENUM + 'Mode.A = other\n',
    ENUM.replace('enum.Enum', 'other.Enum'),
    ENUM.replace('class Mode(enum.Enum):', '@custom\nclass Mode(enum.Enum):'),
    ENUM.replace('class Mode(enum.Enum):', 'class Mode(enum.Enum, metaclass=Custom):'),
    ENUM.replace('    A = enum.auto()', '    def __getattribute__(self, name):\n        return other\n    A = enum.auto()'),
    "import enum\nenum.__dict__['Enum'] = FakeEnum\n" + ENUM.removeprefix('import enum\n'),
    "import enum\nenum.__dict__.update({'Enum': FakeEnum})\n" + ENUM.removeprefix('import enum\n'),
    "import enum\nnamespace = enum.__dict__\nnamespace['Enum'] = FakeEnum\n" + ENUM.removeprefix('import enum\n'),
    'import enum\nAlias = enum.Enum\nAlias.method = other\n' + ENUM.removeprefix('import enum\n'),
    'import enum\nAlias = type(enum.Enum)\nAlias.method = other\n' + ENUM.removeprefix('import enum\n'),
    'import enum\nenum.StrEnum = enum.Enum\nenum.StrEnum.method = other\n' + ENUM.removeprefix('import enum\n'),
    ENUM + "setattr(Mode, 'A', other)\n",
])
def test_unknown_or_mutated_enum_authority_gives_no_copy_credit(prelude):
    result = enum_result(prelude)
    assert edc(result)
    assert not credits(result)


@pytest.mark.parametrize('path', ['enum.py', 'src/enum.py', 'tests/enum/__init__.py'])
def test_repository_enum_shadow_withholds_member_authority(path):
    result = enum_result(root={path: b'Enum = FakeEnum\n'})
    assert edc(result)
    assert not credits(result)


def test_changed_enum_definition_is_not_a_stable_symbolic_literal():
    result = run(source(["({'flag': Mode.A}, Mode.A)"], prelude=ENUM),
                 source(["({'flag': Mode.B}, Mode.B)"], prelude=ENUM.replace('B = enum.auto()', 'B = 99')))
    assert edc(result)
    assert not credits(result)


def test_syntactic_consumption_residual_includes_an_unchanged_noop_decorator():
    # Explicit residual, NOT a protected laundering negative: the pre-existing
    # shared-constructor rule likewise treats ignore(expected) as input use.
    prelude = 'def ignore(value):\n    return lambda function: function\n'
    body = ('    @ignore(expected)\n    def cli():\n        return 1\n'
            '    actual = invoke(cli)\n    assert actual == expected\n')
    result = run(source(['(1,)', '(2,)'], names='expected', body=body, prelude=prelude),
                 source(['(2,)', '(3,)'], names='expected', body=body, prelude=prelude))
    assert not edc(result)
    assert result[0].files[0].shared_param_input_pairs


def test_click_flag_member_rewrite_matches_one_copy_pair_not_all_rows():
    # The changed pair is from pallets/click 354788e... (parent b035019...).
    # None/default/type-conversion and regex rows do not share a universal
    # projection and are never used to pay for the changed member row.
    prelude = ENUM.replace('Mode', 'EngineType').replace('A =', 'OSS =').replace('B =', 'MAX =') + 'import click\nimport re\n'
    body = ('    @click.command()\n    @click.option("--pro", **opt_params)\n'
            '    def scan(pro):\n        click.echo(repr(pro), nl=False)\n'
            '    result = runner.invoke(scan, args)\n'
            '    if isinstance(expected, re.Pattern):\n        assert re.match(expected, result.output)\n'
            '    else:\n        assert result.output == repr(expected)\n')
    names = 'runner,opt_params,args,expected'
    old = ['(None, {"type": EngineType, "flag_value": EngineType.MAX}, ["--pro"], EngineType.MAX)',
           '(None, {"type": EngineType, "flag_value": EngineType.MAX}, [], None)',
           '(None, {"flag_value": 1, "type": str, "default": True}, [], "True")']
    new = [row.replace('EngineType.MAX', 'EngineType.OSS') for row in old[:2]] + [
        '(None, {"type": str, "flag_value": 1, "default": True}, [], "True")',
        '(None, {"type": EngineType, "is_flag": True, "flag_value": None}, ["--pro"], None)',
    ]
    # runner is a fixture in the real source, not a parametrized input.
    before = source(old, names=names, body=body, prelude=prelude).replace(b"'runner,opt_params,args,expected'", b"'opt_params,args,expected'").replace(b'(None, {', b'({')
    after = source(new, names=names, body=body, prelude=prelude).replace(b"'runner,opt_params,args,expected'", b"'opt_params,args,expected'").replace(b'(None, {', b'({')
    result = run(before, after)
    assert not edc(result)
    assert len(credits(result)) == 1
