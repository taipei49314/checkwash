"""Optional execution proofs require the analyzed path to be selected."""
import pytest

from checkwash.frontends.python.snapshot_context import inert_test_execution_context
from checkwash.gitio.snapshot import search_source_mapping


def context(path, configs, siblings=None):
    snapshot = {path: b'def test_consumer():\n    assert True\n', **configs, **(siblings or {})}
    return inert_test_execution_context(path, snapshot.get,
                                        lambda needles: search_source_mapping(snapshot, needles))


@pytest.mark.parametrize('filename,source', [
    ('pytest.ini', b'[pytest]\ntestpaths = tests/other\n'),
    ('.pytest.ini', b'[pytest]\ntestpaths = tests/other\n'),
    ('setup.cfg', b'[tool:pytest]\ntestpaths = tests/other\n'),
    ('tox.ini', b'[pytest]\ntestpaths = tests/other\n'),
    ('pyproject.toml', b'[tool.pytest.ini_options]\ntestpaths = ["tests/other"]\n'),
])
def test_conventional_testpaths_must_cover_the_analyzed_file(filename, source):
    assert not context('tests/test_consumer.py', {filename: source},
                       {'tests/other/test_ok.py': b'def test_ok():\n    assert True\n'})


@pytest.mark.parametrize('path,config,selection', [
    ('tests/test_consumer.py', 'pytest.ini', 'tests'),
    ('tests/unit/test_consumer.py', 'pytest.ini', 'tests/unit/'),
    ('tests/unit/test_consumer.py', 'pytest.ini', 'tests/other tests/unit'),
    ('tests/unit/test_consumer.py', 'tests/pytest.ini', 'unit'),
    ('tests/unit/test_consumer.py', 'tests/pytest.ini', 'other unit'),
    ('pkg/tests/unit/test_consumer.py', 'pkg/pytest.ini', 'tests/unit'),
    ('tests/unit/test_consumer.py', 'tests/pytest.ini', ''),
])
def test_covered_paths_empty_defaults_and_nested_config_roots_remain_supported(path, config, selection):
    assert context(path, {config: ('[pytest]\ntestpaths = ' + selection + '\n').encode()})


@pytest.mark.parametrize('path,config,selection', [
    ('tests/unit_extra/test_consumer.py', 'pytest.ini', 'tests/unit'),
    ('tests/unit/test_consumer.py', 'pytest.ini', 'tests/unit_extra'),
    ('tests/test_consumer.py', 'pytest.ini', 'test'),
    ('pkg_extra/tests/test_consumer.py', 'pkg/pytest.ini', 'tests'),
    ('pkg/tests_extra/test_consumer.py', 'pkg/pytest.ini', 'tests'),
    ('tests/unit/test_consumer.py', 'tests/pytest.ini', 'tests/unit'),
    ('tests/unit/test_consumer.py', 'tests/pytest.ini', 'other'),
])
def test_path_components_and_config_relative_resolution_cannot_be_guessed(path, config, selection):
    # An inventoried inert source makes the independent pkg config discoverable.
    assert not context(path, {config: ('[pytest]\ntestpaths = ' + selection + '\n').encode()},
                       {'pkg/marker.py': b'"inert"\n'})


def test_nonempty_nested_toml_selection_is_relative_to_its_own_config():
    assert context('pkg/tests/test_consumer.py', {
        'pkg/pyproject.toml': b'[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'})
    assert not context('pkg/tests_extra/test_consumer.py', {
        'pkg/pyproject.toml': b'[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'})


@pytest.mark.parametrize('selection', ['../tests', 'tests/*', '/tests', 'tests/test_consumer.py', 'tests\\unit'])
def test_existing_unsupported_path_syntax_remains_unsupported(selection):
    assert not context('tests/test_consumer.py', {'pytest.ini': ('[pytest]\ntestpaths = ' + selection + '\n').encode()})


def test_conflicting_discovered_configs_conservatively_withhold_optional_credit():
    assert not context('tests/test_consumer.py', {
        'pytest.ini': b'[pytest]\ntestpaths = tests\n',
        'tests/pytest.ini': b'[pytest]\ntestpaths = other\n'})


def test_native_table_projection_does_not_assume_excluded_tests_execute():
    from test_issue_expectation_families import run
    from test_sequential_captured_oracles import BEFORE, AFTER, PROD, projected
    excluded = {'pytest.ini': b'[pytest]\ntestpaths = tests/other\n',
                'tests/other/test_only.py': b'def test_ok():\n    assert True\n'}
    assert not projected(run(BEFORE, AFTER, PROD, context=excluded)[0])
    covered = {**excluded, 'pytest.ini': b'[pytest]\ntestpaths = tests/other tests\n'}
    assert projected(run(BEFORE, AFTER, PROD, context=covered)[0])
