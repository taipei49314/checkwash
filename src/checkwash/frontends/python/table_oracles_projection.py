"""Two-sided carrier alignment, snapshot purity proofs, and IR projection stages."""

from __future__ import annotations

import ast
from collections import Counter

from checkwash.ir.astutil import stable_dump


def parse_compatible_carrier_pair(before, after, before_parsed, after_parsed, rt):
    """Parse both sides and enforce carrier, exception, local-oracle, and provenance gates."""
    old, new = rt._module(before, baseline=True), rt._module(after, baseline=False)
    if old is None:
        old = rt._module(before, baseline=False)
    if old is None or new is None or old[1] != new[1]:
        return None
    if Counter(oracle.key for oracle in old[11]) - Counter(oracle.key for oracle in new[11]):
        return None  # never discard a removed/changed exception or its exact message
    if Counter(oracle.key for oracle in old[12]) - Counter(oracle.key for oracle in new[12]):
        return None  # local checks keep their full definitions and multiplicity
    regrouped_capture = any(form == "regrouped-complete-capture" for module in (old, new) for _, form in module[6])
    if regrouped_capture:
        old_clauses = rt.capture_obligations(old[0], rt._literal)
        new_clauses = rt.capture_obligations(new[0], rt._literal)
        if old_clauses is None or new_clauses is None or old_clauses - new_clauses:
            return None  # even entailed clauses keep their original multiplicity
    native_renames = rt._native_renames(old, new)
    if (any(getattr(case.assertion, "_requires_closed_helper", False) for case in old[2])
            and any(getattr(case.assertion, "_requires_closed_helper", False) for case in new[2])):
        return None  # preserve same-carrier keyword expectation provenance
    for same_carrier_form in ("literal-expected-local", "literal-subject-local", "literal-fixtures"):
        if (any(form == same_carrier_form for _, form in old[6])
                and any(form == same_carrier_form for _, form in new[6])):
            return None
    if not (old[3] or new[3] or native_renames):
        return None
    if (old[3] and new[3] and old[6] == new[6]
            and rt._ordinary_rows_cover(old, before_parsed) and rt._ordinary_rows_cover(new, after_parsed)):
        # An edit within the same row carrier/unit retains #135 and the
        # row-identity channel. Projection proves a carrier transition;
        # it must not relabel ordinary parametrize expectation findings.
        return None
    return old, new, native_renames


def align_concrete_case_sequences(old, new, *, native_renames, rt):
    """Verify concrete subject prefix/multiplicity compatibility and sort reorderable suites."""
    old_keys = [rt._subject_key(case) for case in old[2]]
    new_keys = [rt._subject_key(case) for case in new[2]]
    if any(form == "literal-expected-local" for module in (old, new) for _, form in module[6]):
        old_answers = Counter((rt._subject_key(case), stable_dump(case.assertion.test.comparators[0])) for case in old[2])
        new_answers = Counter((rt._subject_key(case), stable_dump(case.assertion.test.comparators[0])) for case in new[2])
        if old_answers - new_answers:
            return False  # changed local answers retain their established provenance owner
    old_complete = Counter((rt._subject_key(case), stable_dump(case.assertion.test.comparators[0])) for case in old[2]
                           if not getattr(case.assertion, "_partial_dictionary_fields", False))
    new_complete = Counter((rt._subject_key(case), stable_dump(case.assertion.test.comparators[0])) for case in new[2]
                           if not getattr(case.assertion, "_partial_dictionary_fields", False))
    if (any(getattr(case.assertion, "_partial_dictionary_fields", False) for case in new[2])
            and old_complete - new_complete):
        return False
    if old_keys != new_keys[:len(old_keys)] and rt._pair_approximate_identity(old[2], new[2]):
        old_keys = [rt._subject_key(case) for case in old[2]]
        new_keys = [rt._subject_key(case) for case in new[2]]
    if old_keys != new_keys[:len(old_keys)] and rt.pair_boolean_comparisons(old[2], new[2], rt._subject_key):
        old_keys = [rt._subject_key(case) for case in old[2]]
        new_keys = [rt._subject_key(case) for case in new[2]]
    indexed_extension = (len(old[6]) == len(new[6]) == 1 and old[6][0][0] == new[6][0][0]
                         and old[6][0][1] == "parametrize" and new[6][0][1] == "indexed-fixture-parametrize"
                         and len(set(old_keys)) == len(old_keys) and len(set(new_keys)) == len(new_keys)
                         and not (Counter(old_keys) - Counter(new_keys)))
    if not old_keys:
        return False
    if ((old[9] or new[9]) and Counter(old_keys) != Counter(new_keys)
            and not (new[10] and not Counter(old_keys) - Counter(new_keys))):
        return False
    if old_keys != new_keys[:len(old_keys)]:
        if not (old[9] or new[9] or indexed_extension or native_renames) or Counter(old_keys) - Counter(new_keys):
            return False
        old[2].sort(key=rt._subject_key)
        new[2].sort(key=rt._subject_key)
    return True


def _strict_subject_imports(module, calls):
    """Require every module import to be plain pytest or a directly called subject."""
    called = {call.func.id for call in calls if isinstance(call.func, ast.Name)}
    for node in ast.parse(module[0]).body:
        if isinstance(node, ast.Import):
            if any(alias.name != "pytest" or alias.asname for alias in node.names):
                return False
        elif isinstance(node, ast.ImportFrom):
            if node.level or any((alias.asname or alias.name) not in called for alias in node.names):
                return False
    return True


def _verify_case_result_obligations(module, *, path, read, rt):
    """Prove per-case boolean, shared-collection, and tuple-arity result obligations."""
    encoded = module[0].encode()
    for case in module[2]:
        if getattr(case.assertion, "_requires_boolean_result", False) and not rt.pure_imported_calls(
            encoded, [case.assertion.test.left], path=path, read=read, result_proof=rt.primitive_boolean_result
        ):
            return False
        if getattr(case.assertion, "_requires_shared_collection_inputs", False) and not rt.pure_imported_calls(
            encoded, [case.assertion.test.left], path=path, read=read, result_proof=rt.shared_literal_collection_inputs
        ):
            return False
        arity = getattr(case.assertion, "_requires_tuple_arity", None)
        if arity is not None and not rt.pure_imported_calls(
            encoded, [case.assertion.test.left], path=path, read=read,
            result_proof=lambda source, target, call, n=arity: rt.primitive_tuple_result(source, target, call, n),
        ):
            return False
    return True


def verify_module_snapshot_purity(module, *, path, read, search, closed_purity_required, rt):
    """Prove startup context, unshadowed authorities, and imported-call purity on one side."""
    if not rt.inert_test_execution_context(path, read, search):
        return False
    if not rt._pytest_unshadowed(path, read):
        return False
    if any(not rt._module_unshadowed(path, read, authority) for authority in module[7]):
        return False
    message_calls = [case.assertion.test.left for case in module[2]
                     if getattr(case.assertion, "_requires_primitive_string", False)]
    approximate = any(getattr(case.assertion, "_requires_approx_authority", False)
                      or getattr(case.assertion, "_requires_operator_authority", False) for case in module[2])
    derived = any(hasattr(case.assertion, "_requires_derived_authority") for case in module[2])
    if derived:
        calls = [case.assertion.test.left for case in module[2]]
        if not _strict_subject_imports(module, calls) or not rt.pure_imported_calls(
            module[0].encode(), calls, path=path, read=read, result_proof=rt.primitive_derived_result
        ):
            return False
    if approximate:
        calls = [case.assertion.test.left for case in module[2]]
        if not _strict_subject_imports(module, calls) or not rt.pure_imported_calls(
            module[0].encode(), calls, path=path, read=read
        ):
            return False
    if message_calls or any(form in {"zip-fixture", "callable-fixture"} for _, form in module[6]):
        calls = [case.assertion.test.left for case in module[2]]
        strings_only = any(form in {"zip-fixture", "callable-fixture"} for _, form in module[6])

        def primitive_result(source, target, call):
            return (rt.primitive_string_result(source, target, call)
                    or not strings_only and rt.primitive_literal_result(source, target, call))

        if not _strict_subject_imports(module, calls) or not rt.pure_imported_calls(
            module[0].encode(), calls, path=path, read=read, result_proof=primitive_result
        ):
            return False
        if not rt._module_unshadowed(path, read, "re"):
            return False
    if closed_purity_required:
        calls = [case.assertion.test.left for case in module[2]] + [oracle.call for oracle in module[11]]
        if not rt._closed_proof_imports(module, calls) or not rt.pure_imported_calls(
            module[0].encode(), calls, path=path, read=read
        ):
            return False
    return _verify_case_result_obligations(module, path=path, read=read, rt=rt)


def render_projected_pair(before_parsed, after_parsed, old, new, rt):
    """Normalize paired boolean operators and project concrete units onto both ParsedFiles."""
    for module in (old, new):
        for case in module[2]:
            if getattr(case.assertion, "_requires_boolean_result", False):
                case.assertion.test.ops = [ast.Eq()]
    before_projected = rt.retain_local_auxiliary_units(
        rt.retain_raises_units(rt._project(before_parsed, old[0], old[2]), old[0], old[11]), old[0], old[12]
    )
    after_projected = rt.retain_local_auxiliary_units(
        rt.retain_raises_units(rt._project(after_parsed, new[0], new[2]), new[0], new[11]), new[0], new[12]
    )
    return before_projected, after_projected
