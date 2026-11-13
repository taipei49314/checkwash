"""Module-level AST lowering, declaration extraction, and case aggregation stages."""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from typing import Any

from checkwash.ir.astutil import dotted_name


@dataclass
class _LoweredModule:
    text: str
    tree: ast.Module
    conditional_tests: set[str]
    inert_signature_tests: set[str]
    failing_wrapper_tests: set[str]
    literal_expected_tests: set[str]
    literal_subject_tests: set[str]
    captured_helper_tests: set[str]
    regrouped_capture_tests: set[str]
    local_auxiliary: list[Any]
    hex_tuple_tests: set[str]
    raises_oracles: list[Any]
    tuple_tests: set[str]
    iteration_tests: set[str]
    predicate_tests: set[str]
    prefix_tests: set[str]
    unique_tests: set[str]
    inert_helpers: bool
    membership_fixture_tests: set[str]
    parameter_helper_tests: set[str]
    conditional_fixture_tests: set[str]
    literal_fixture_tests: set[str]
    factory_tests: set[str]
    indexed_fixture_tests: set[str]
    pruned_fixtures: bool
    wrapper_tests: set[str]
    block_tests: set[str]
    unittest_tests: set[str]
    subtest_only: bool
    class_tests: set[str]


@dataclass
class _ModuleDeclarations:
    imports: set[str]
    import_nodes: list[str]
    functions: list[ast.FunctionDef]
    names: set[str]
    constants: dict[str, ast.AST]
    used_constants: Counter
    modules: set[str]
    wrapper_authorities: set[str]
    pytest_imported: bool


@dataclass
class _ModuleDefinitions:
    functions: list[ast.FunctionDef]
    expanded_forwarders: bool
    callable_fixture_tests: set[str]
    fixtures: dict[str, ast.AST]
    tables: dict[str, ast.AST]
    shared_tables: set[str]
    row_helper_tests: set[str]
    helpers: dict[str, Any]
    table_helpers: dict[str, Any]


@dataclass
class _CollectedCases:
    result: list[Any]
    table: bool
    forms: list[tuple[str, str]]
    auxiliary: list[Any]
    used_fixtures: Counter
    used_helpers: Counter
    used_tables: Counter


def parse_and_validate_module_ast(source, rt):
    """Parse bounded Python source and reject reserved fixture or hook names."""
    if len(source) > rt.MAX_SOURCE_BYTES:
        return None
    text = rt.normalize_source(source)
    tree = ast.parse(text)
    if sum(1 for _ in ast.walk(tree)) > rt.MAX_AST_NODES:
        return None
    if any(isinstance(node, ast.FunctionDef) and node.name == "request" and any(
            dotted_name(decorator.func if isinstance(decorator, ast.Call) else decorator) == "pytest.fixture"
            for decorator in node.decorator_list) for node in tree.body):
        return None  # pytest rejects this fixture name before collection; never erase that control
    if any(isinstance(node, (ast.FunctionDef, ast.ClassDef))
           and (node.name in rt._IMPLICIT_HOOKS or node.name.startswith(("pytest_", "__")))
           for node in tree.body):
        return None  # validate implicit entry points before any helper can be removed
    return text, tree


def prune_unused_literal_fixtures(tree, rt):
    """Drop default-scope unreferenced literal fixtures while keeping all other nodes."""
    references = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    references.update(node.arg for node in ast.walk(tree) if isinstance(node, ast.arg))
    references.update(node.value for node in ast.walk(tree)
                      if isinstance(node, ast.Constant) and type(node.value) is str)
    definitions = Counter(node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef)))
    plain_pytest = any(isinstance(node, ast.Import) and len(node.names) == 1
                       and node.names[0].name == "pytest" and node.names[0].asname is None for node in tree.body)
    retained = []
    for node in tree.body:
        unused_parameter_fixture = False
        if (plain_pytest and isinstance(node, ast.FunctionDef) and node.name not in references
                and definitions[node.name] == 1):
            parameters = rt._fixture(node)
            unused_parameter_fixture = (isinstance(parameters, (ast.List, ast.Tuple))
                                        and 0 < len(parameters.elts) <= rt.MAX_CASES and rt._immutable_rows(parameters))
        unused_fixture = (plain_pytest and isinstance(node, ast.FunctionDef) and rt._args(node) == []
                          and node.name not in references and definitions[node.name] == 1
                          and not node.name.startswith("test") and len(node.decorator_list) == 1
                          and dotted_name(node.decorator_list[0]) == "pytest.fixture"
                          and len(node.body) == 1 and isinstance(node.body[0], ast.Return)
                          and rt._literal(node.body[0].value))
        if not (unused_fixture or unused_parameter_fixture):
            retained.append(node)
    pruned_fixtures = len(retained) != len(tree.body)
    tree.body = retained
    return pruned_fixtures


def lower_module_carriers(text, tree, source, rt):
    """Run AST carrier expansions, unused-fixture pruning, and class flattening."""
    conditional_tests = set()
    if b"if" in source:
        conditional_spans = {(node.lineno, node.col_offset) for node in ast.walk(tree)
                             if isinstance(node, ast.If)}
        if conditional_spans:
            tree = rt.conditional_oracle_carriers(tree)
            conditional_tests = {function.name for function in ast.walk(tree)
                                 if isinstance(function, ast.FunctionDef) and any(
                                     isinstance(node, ast.Assert) and (node.lineno, node.col_offset) in conditional_spans
                                     for node in ast.walk(function))}
    inert_signature_tests = rt.strip_none_test_returns(tree)
    failing_wrapper_tests = rt.expand_failing_exception_wrappers(tree)
    literal_expected_tests = rt.expand_literal_expected_bindings(tree, rt._literal)
    literal_subject_tests = rt.expand_literal_subject_bindings(tree, rt._literal)
    captured_helper_tests = rt.expand_captured_assert_helpers(tree, rt._literal)
    regrouped_capture_tests = rt.regroup_complete_captures(tree, rt._literal)
    local_auxiliary = rt.extract_local_auxiliary_oracles(tree)
    hex_tuple_tests = rt.expand_hex_tuple_answers(tree)
    raises_oracles = rt.extract_raises_oracles(tree)
    tuple_tests = rt.expand_tuple_oracles(tree)
    iteration_tests = rt.expand_literal_iteration_oracles(tree)
    if iteration_tests is None:
        return None
    predicate_tests = rt.expand_predicate_helpers(tree)
    if predicate_tests is None:
        return None
    prefix_tests = rt.expand_prefix_predicates(tree)
    if prefix_tests is None:
        return None
    unique_tests = rt.expand_unique_predicates(tree)
    if unique_tests is None:
        return None
    inert_helpers = rt.prune_inert_helpers(tree)
    membership_fixture_tests = rt.expand_parametrized_membership(tree)
    parameter_helper_tests = rt.expand_parameter_helper_answers(tree)
    conditional_fixture_tests = rt.expand_fixture_conditional_answers(tree)
    literal_fixture_tests = rt.expand_literal_fixtures(tree)
    factory_tests = rt.expand_literal_table_factories(tree)
    indexed_fixture_tests = rt.expand_indexed_fixture_tables(tree)
    pruned_fixtures = prune_unused_literal_fixtures(tree, rt)
    wrapper_tests = rt.expand_wrappers(tree)
    if wrapper_tests is None:
        return None
    rt.expand_operator_asserts(tree)
    block_tests = rt.expand_string_blocks(tree)
    if block_tests is None:
        return None
    unittest_expansion = rt.expand_unittest_classes(tree)
    if unittest_expansion is None:
        return None
    unittest_tests, subtest_only = unittest_expansion
    class_tests = rt._plain_classes(tree)
    if class_tests is None:
        return None
    return _LoweredModule(
        text=text, tree=tree, conditional_tests=conditional_tests,
        inert_signature_tests=inert_signature_tests, failing_wrapper_tests=failing_wrapper_tests,
        literal_expected_tests=literal_expected_tests, literal_subject_tests=literal_subject_tests,
        captured_helper_tests=captured_helper_tests, regrouped_capture_tests=regrouped_capture_tests,
        local_auxiliary=local_auxiliary, hex_tuple_tests=hex_tuple_tests, raises_oracles=raises_oracles,
        tuple_tests=tuple_tests, iteration_tests=iteration_tests, predicate_tests=predicate_tests,
        prefix_tests=prefix_tests, unique_tests=unique_tests, inert_helpers=inert_helpers,
        membership_fixture_tests=membership_fixture_tests, parameter_helper_tests=parameter_helper_tests,
        conditional_fixture_tests=conditional_fixture_tests, literal_fixture_tests=literal_fixture_tests,
        factory_tests=factory_tests, indexed_fixture_tests=indexed_fixture_tests,
        pruned_fixtures=pruned_fixtures, wrapper_tests=wrapper_tests, block_tests=block_tests,
        unittest_tests=unittest_tests, subtest_only=subtest_only, class_tests=class_tests,
    )


def collect_top_level_declarations(tree, rt):
    """Collect module imports, inert literal constants, and uniquely named functions."""
    imports, import_nodes, functions, names = set(), [], [], set()
    constants, used_constants, modules, wrapper_authorities = {}, Counter(), set(), set()
    pytest_imported = False
    for node in tree.body:
        if rt._docstring(node) or isinstance(node, ast.Pass):
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not functions:
            if isinstance(node, ast.ImportFrom) and (node.level or any(alias.name == "*" for alias in node.names)):
                return None
            bound = [alias.asname or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)
                     for alias in node.names]
            if names.intersection(bound) or len(set(bound)) != len(bound) or any(name.startswith("__") for name in bound):
                return None
            names.update(bound)
            imports.update(bound)
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif node.module:
                modules.add(node.module)
                modules.update(node.module + "." + alias.name for alias in node.names)
            if (isinstance(node, ast.Import) and len(node.names) == 1
                    and node.names[0].name == "pytest" and node.names[0].asname is None):
                pytest_imported = True
            else:
                if "pytest" in bound:
                    return None
                wrapper_authority = rt.trusted_wrapper_import(node)
                if wrapper_authority:
                    wrapper_authorities.add(wrapper_authority)
                else:
                    import_nodes.append(ast.dump(node, include_attributes=False))
        elif not functions and (constant := rt._constant(node, names)) is not None:
            name, value = constant
            names.add(name)
            constants[name] = value
        elif isinstance(node, ast.FunctionDef) and node.name not in names:
            names.add(node.name)
            if node.body and rt._docstring(node.body[0]):
                node.body = node.body[1:]
            functions.append(node)
        else:
            return None
    return _ModuleDeclarations(
        imports=imports, import_nodes=import_nodes, functions=functions, names=names,
        constants=constants, used_constants=used_constants, modules=modules,
        wrapper_authorities=wrapper_authorities, pytest_imported=pytest_imported,
    )


def resolve_module_definitions(declarations: _ModuleDeclarations, *, baseline, rt):
    """Expand forwarders/callable fixtures and classify fixtures, tables, and helpers."""
    count_before_forwarding = len(declarations.functions)
    functions = rt._forwarded_functions(declarations.functions, declarations.imports)
    if functions is None:
        return None
    expanded_forwarders = len(functions) != count_before_forwarding
    functions, callable_fixture_tests = rt._callable_fixtures(functions, declarations.imports)
    if functions is None:
        return None
    if callable_fixture_tests and not declarations.pytest_imported:
        return None
    fixtures, tables, shared_tables = {}, {}, set()
    if not baseline:
        for function in functions:
            fixture = rt._fixture(function)
            if fixture is not None:
                if not declarations.pytest_imported:
                    return None
                fixtures[function.name] = rt._table_source(fixture, declarations.constants, declarations.used_constants)
                continue
            table_fixture = rt._table_fixture(function)
            if table_fixture is not None:
                if not declarations.pytest_imported:
                    return None
                if isinstance(table_fixture, ast.Name) and table_fixture.id in declarations.constants:
                    shared_tables.add(function.name)
                tables[function.name] = rt._table_source(
                    table_fixture, declarations.constants, declarations.used_constants
                )
    functions, row_helper_tests = rt.expand_fixture_row_helpers(functions, fixtures, rt._args, rt._helper)
    if functions is None:
        return None
    helpers, table_helpers = {}, {}
    for function in functions:
        if function.name in fixtures or function.name in tables:
            continue
        candidate = rt._helper(function)
        if candidate is not None:
            helpers[function.name] = candidate
            continue
        table_candidate = rt._table_helper(function)
        if table_candidate is not None:
            table_helpers[function.name] = table_candidate
    return _ModuleDefinitions(
        functions=functions, expanded_forwarders=expanded_forwarders,
        callable_fixture_tests=callable_fixture_tests, fixtures=fixtures, tables=tables,
        shared_tables=shared_tables, row_helper_tests=row_helper_tests,
        helpers=helpers, table_helpers=table_helpers,
    )


def _form_overrides(lowered: _LoweredModule, definitions: _ModuleDefinitions):
    return (
        (lowered.class_tests, "plain-class"),
        (lowered.wrapper_tests, "oracle-wrapper"),
        (definitions.callable_fixture_tests, "callable-fixture"),
        (lowered.factory_tests, "literal-table-factory"),
        (lowered.indexed_fixture_tests, "indexed-fixture-parametrize"),
        (lowered.literal_fixture_tests, "literal-fixtures"),
        (lowered.iteration_tests, "literal-iteration"),
        (lowered.conditional_tests, "conditional-oracle"),
        (lowered.prefix_tests, "literal-prefix-predicate"),
        (lowered.unique_tests, "exact-unique-predicate"),
        (lowered.literal_expected_tests, "literal-expected-local"),
        (lowered.literal_subject_tests, "literal-subject-local"),
        (lowered.parameter_helper_tests, "parameter-helper-answer"),
        (lowered.failing_wrapper_tests, "failing-exception-wrapper"),
        (lowered.captured_helper_tests, "captured-assert-helper"),
        (lowered.regrouped_capture_tests, "regrouped-complete-capture"),
        (lowered.inert_signature_tests, "literal-none-test-return"),
        (lowered.conditional_fixture_tests, "fixture-conditional-answer"),
        (lowered.hex_tuple_tests, "hex-tuple-answer"),
    )


def collect_module_cases(lowered: _LoweredModule, declarations: _ModuleDeclarations,
                         definitions: _ModuleDefinitions, *, baseline, rt):
    """Expand each collected test function and record concrete/auxiliary cases and usages."""
    result, table, forms, auxiliary = [], False, [], []
    used_fixtures, used_helpers, used_tables = Counter(), Counter(), Counter()
    overrides = _form_overrides(lowered, definitions)
    multiple_tests = lowered.unittest_tests | definitions.callable_fixture_tests
    for function in definitions.functions:
        if (function.name in definitions.fixtures or function.name in definitions.tables
                or function.name in definitions.helpers or function.name in definitions.table_helpers):
            continue
        expanded = rt._test(
            function, definitions.fixtures, definitions.tables, declarations.imports,
            definitions.helpers, definitions.table_helpers, declarations.constants,
            declarations.used_constants, baseline=baseline, multiple=function.name in multiple_tests,
        )
        if expanded is None:
            if (rt._args(function) != [] or function.decorator_list or not function.name.startswith("test")
                    or not 1 <= len(function.body) <= rt.MAX_CASES
                    or not all(isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Compare)
                               for statement in function.body)):
                return None
            comparisons = [
                rt._concrete(ast.copy_location(ast.Assert(test=statement.value, msg=None), statement), {},
                             declarations.imports)
                for statement in function.body
            ]
            if any(assertion is None for assertion in comparisons):
                return None
            auxiliary.extend(rt._Case(assertion, statement, function)
                             for assertion, statement in zip(comparisons, function.body))
            continue
        cases, is_table, form = expanded
        for members, override in overrides:
            if function.name in members:
                is_table, form = True, override
        forms.append((function.name, form))
        if function.decorator_list and not declarations.pytest_imported:
            return None
        used_fixtures.update(set(rt._args(function)) & definitions.fixtures.keys())
        used_tables.update(set(rt._args(function)) & definitions.tables.keys())
        used_helpers.update(
            name for name in (dotted_name(call.func) for call in ast.walk(function) if isinstance(call, ast.Call))
            if name in definitions.helpers or name in definitions.table_helpers
        )
        result.extend(cases)
        table |= is_table
        if len(result) > rt.MAX_CASES:
            return None
    return _CollectedCases(
        result=result, table=table, forms=forms, auxiliary=auxiliary,
        used_fixtures=used_fixtures, used_helpers=used_helpers, used_tables=used_tables,
    )


def _requires_closed_purity(lowered: _LoweredModule, definitions: _ModuleDefinitions,
                            collected: _CollectedCases, *, shared_fixture_params, unique_helpers):
    return bool(
        lowered.block_tests or lowered.unittest_tests or lowered.pruned_fixtures or lowered.inert_helpers
        or definitions.expanded_forwarders or lowered.factory_tests or lowered.indexed_fixture_tests
        or lowered.literal_fixture_tests or lowered.membership_fixture_tests or lowered.parameter_helper_tests
        or lowered.failing_wrapper_tests or lowered.conditional_fixture_tests or collected.auxiliary
        or lowered.raises_oracles or lowered.tuple_tests or lowered.hex_tuple_tests or shared_fixture_params
        or lowered.iteration_tests or definitions.row_helper_tests or lowered.local_auxiliary
        or lowered.predicate_tests or lowered.prefix_tests or lowered.unique_tests or unique_helpers
        or lowered.conditional_tests or lowered.literal_expected_tests or lowered.literal_subject_tests
        or lowered.captured_helper_tests or lowered.inert_signature_tests or lowered.regrouped_capture_tests
        or any(form in {"string-block", "grouped-assert-helper"} for _, form in collected.forms)
        or any(getattr(case.assertion, "_requires_closed_helper", False) for case in collected.result)
    )


def finalize_module_projection(lowered: _LoweredModule, declarations: _ModuleDeclarations,
                               definitions: _ModuleDefinitions, collected: _CollectedCases, rt):
    """Validate whole-module usage, unshadowed builtins, and assemble the module tuple."""
    if definitions.fixtures.keys() != collected.used_fixtures.keys():
        return None
    shared_fixture_params = any(count > 1 and not rt._immutable_rows(definitions.fixtures[name])
                                for name, count in collected.used_fixtures.items())
    if shared_fixture_params:
        for case in collected.result:
            case.assertion._requires_shared_collection_inputs = True
    if any(count > 1 and not rt._immutable_rows(declarations.constants[name])
           for name, count in declarations.used_constants.items()):
        return None
    if any(collected.used_tables[name] > 1 and not rt._immutable_rows(definitions.tables[name])
           for name in definitions.shared_tables):
        return None
    if (definitions.helpers.keys() | definitions.table_helpers.keys() != collected.used_helpers.keys()
            or definitions.tables.keys() != collected.used_tables.keys()):
        return None
    if any(form == "zip-fixture" for _, form in collected.forms) and "zip" in declarations.names:
        return None
    if (any(getattr(case.assertion, "_requires_approx_authority", False) for case in collected.result)
            and not declarations.pytest_imported):
        return None
    derived_authorities = set().union(
        *(getattr(case.assertion, "_requires_derived_authority", set()) for case in collected.result)
    )
    if any(getattr(case.assertion, "_requires_repr_authority", False) for case in collected.result) and (
            "repr" in declarations.names or any(
                isinstance(node, ast.arg) and node.arg == "repr"
                or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == "repr"
                or isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == "repr"
                or isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == "repr"
                for node in ast.walk(lowered.tree))):
        return None
    if derived_authorities & declarations.names or any(
            isinstance(node, ast.arg) and node.arg in derived_authorities for node in ast.walk(lowered.tree)):
        return None
    checked_subjects = {rt._subject_key(case) for case in collected.result}
    unique_helpers = any(getattr(case.assertion, "_requires_unique_expected", False) for case in collected.result)
    if unique_helpers and not rt.unshadowed_unique_builtins(lowered.tree):
        return None
    if any(rt._subject_key(case) not in checked_subjects for case in collected.auxiliary):
        return None
    closed_purity = _requires_closed_purity(
        lowered, definitions, collected,
        shared_fixture_params=shared_fixture_params, unique_helpers=unique_helpers,
    )
    return (
        lowered.text,
        declarations.import_nodes,
        collected.result,
        collected.table,
        declarations.pytest_imported,
        declarations.modules,
        collected.forms,
        declarations.wrapper_authorities,
        closed_purity,
        bool(lowered.unittest_tests),
        lowered.subtest_only and all(name in lowered.unittest_tests for name, _ in collected.forms),
        lowered.raises_oracles,
        lowered.local_auxiliary,
    )
