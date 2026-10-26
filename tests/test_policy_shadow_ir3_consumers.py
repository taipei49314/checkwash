"""IR3 adapter controls. No fixture program is imported or executed."""
import datetime
import pytest

from checkwash import IR_VERSION, FINDINGS_VERSION
from checkwash.cases import Case, case_policy_base, case_to_changes
from checkwash.change import EngineError, FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.ir.model import IR, to_jsonable
from checkwash.policy_shadow import PolicyBase


def test_new_ir3_always_serializes_the_required_slot_even_when_empty():
    ir = to_jsonable(IR("base", "head"))
    assert IR_VERSION == ir["version"] == 3 and FINDINGS_VERSION == 2
    assert ir["globals"]["policy_shadows"] == {}


def test_base_mapping_selection_is_per_filename_and_preserves_empty_priority():
    base = PolicyBase.from_mapping({".checkwash/config.toml": b"",
        ".greenwash/config.toml": b'[gate]\non_engine_error="block"\n',
        ".greenwash/allow.toml": b"# legacy ledger"})
    assert (base.config_path, base.config_data) == (".checkwash/config.toml", b"")
    assert (base.allow_path, base.allow_data) == (".greenwash/allow.toml", b"# legacy ledger")


def test_case_head_priority_addition_does_not_replace_explicit_legacy_base():
    case = Case(before={".greenwash/config.toml": '[gate]\non_engine_error="block"\n'},
                after={".checkwash/config.toml": '[gate]\non_engine_error="pass_with_warning"\n'})
    base = case_policy_base(case)
    assert base.config_path == ".greenwash/config.toml"
    assert b'"block"' in base.config_data
    assert base.allow_data is None


def test_case_head_only_policy_context_is_never_inferred_as_base_or_allowance():
    case = Case(after={".checkwash/allow.toml": ""},
                head={".greenwash/allow.toml": "# HEAD alone is not BASE proof"})
    with pytest.raises(EngineError, match="HEAD-only"):
        case_policy_base(case)


def test_test_only_case_with_head_ledger_keeps_its_original_api_admission():
    case = Case(before={"tests/test_x.py": "def test_x():\n    assert 1 == 1\n"},
                after={"tests/test_x.py": "def test_x():\n    assert True\n"},
                head={".greenwash/allow.toml": "# irrelevant unknown policy context"})
    base = case_policy_base(case)
    assert "allow.toml" not in base.known_names
    ir, _findings, _verdict = analyze(case_to_changes(case), Config(), Contract(), [],
                                    datetime.date(2026, 1, 1), policy_base=base)
    assert ir.version == 3


@pytest.mark.parametrize("name,unrelated", [("config.toml", "allow.toml"), ("allow.toml", "config.toml")])
def test_new_priority_only_needs_its_own_filename_base_provenance(name, unrelated):
    case = Case(after={f".checkwash/{name}": ""}, head={f".greenwash/{unrelated}": "# unknown"})
    base = case_policy_base(case)
    assert name in base.known_names and unrelated not in base.known_names
    ir, _findings, _verdict = analyze(case_to_changes(case), Config(), Contract(), [],
                                    datetime.date(2026, 1, 1), policy_base=base)
    assert ir.version == 3


def test_case_after_only_priority_file_has_explicit_absent_base_provenance():
    base = case_policy_base(Case(after={".checkwash/config.toml": ""}))
    assert base.config_data is None and base.allow_data is None


def test_direct_priority_creation_without_base_context_refuses_instead_of_guessing():
    change = FileChange(".checkwash/config.toml", "added", None, b"")
    with pytest.raises(EngineError, match="BASE policy provenance"):
        analyze([change], Config(), Contract(), [], datetime.date(2026, 1, 1))



def _priority_config_result(path, policy_base):
    # FileChange's actual field names are deliberate: no dict stand-in.
    change = FileChange(path=path, status="added", before=None,
                        after=b'[gate]\non_engine_error="pass_with_warning"\n')
    return analyze([change], Config(on_engine_error="block"), Contract(), [],
                   datetime.date(2026, 1, 1), policy_base=policy_base)


@pytest.mark.parametrize("path", [".checkwash/config.toml", r".checkwash\config.toml"])
@pytest.mark.parametrize("base_path", [".greenwash/config.toml", r".greenwash\config.toml"])
def test_priority_config_backslash_api_never_falls_back_to_fresh_defaults(path, base_path):
    base = PolicyBase(config_path=base_path,
                      config_data=b'[gate]\non_engine_error="block"\n')
    ir, findings, verdict = _priority_config_result(path, base)
    finding = next(f for f in findings if f.rule == "GUARDRAIL_TOUCHED")
    assert finding.path == ".checkwash/config.toml"
    assert finding.severity == "critical" and "META" in finding.escalators
    assert verdict == "block"
    assert ir.globals.policy_shadows[".checkwash/config.toml"]["base_path"] == ".greenwash/config.toml"
    assert ir.globals.policy_shadows[".checkwash/config.toml"]["kind"] == "config_relaxation"


def test_backslash_mapping_and_case_base_provenance_match_canonical_fingerprint():
    strict = b'[gate]\non_engine_error="block"\n'
    paths = [".checkwash/config.toml", r".checkwash\config.toml"]
    contexts = [PolicyBase.from_mapping({r".greenwash\config.toml": strict}),
                case_policy_base(Case(before={r".greenwash\config.toml": strict.decode()},
                    after={r".checkwash\config.toml": '[gate]\non_engine_error="pass_with_warning"\n'},
                    head={r".greenwash\allow.toml": "# unrelated unknown context"}))]
    fingerprints = set()
    for base in contexts:
        assert base.config_path == ".greenwash/config.toml" and base.config_data == strict
        for path in paths:
            _ir, findings, verdict = _priority_config_result(path, base)
            assert verdict == "block"
            fingerprints.add(next(f.fingerprint for f in findings if f.rule == "GUARDRAIL_TOUCHED"))
    assert len(fingerprints) == 1


def test_normalized_policy_alias_conflict_is_unknown_only_for_its_filename():
    base = PolicyBase.from_mapping({".greenwash/allow.toml": b"# first",
        r".greenwash\allow.toml": b"# conflicting alias", ".greenwash/config.toml": b'[gate]\non_engine_error="block"\n'})
    assert "allow.toml" not in base.known_names and "config.toml" in base.known_names
    _ir, _findings, verdict = _priority_config_result(r".checkwash\config.toml", base)
    assert verdict == "block"  # unrelated unknown allow context is not consulted.
    change = FileChange(path=r".checkwash\allow.toml", status="added", before=None, after=b"")
    with pytest.raises(EngineError, match="BASE policy provenance"):
        analyze([change], Config(), Contract(), [], datetime.date(2026, 1, 1), policy_base=base)
