"""Packaged-model behavioral cases; labels still require maintainer review."""
import datetime
import hashlib
from importlib import resources

import pytest

from checkwash.quality.engine import analyze
from checkwash.quality.profiles import available
from checkwash.quality.snapshot import MappingSnapshot

RUFF_PAIRS = [
    ("exact", 'select=["F401"]', 'select=[]'),
    ("family", 'select=["F"]', 'select=["F4"]'),
    ("multiple", 'select=["F401","F821"]', 'select=["F401"]'),
    ("extension", 'select=["F401"]\nextend-select=["E711"]', 'select=["F401"]'),
    ("family-with-ignore", 'select=["F"]', 'select=["F"]\nignore=["F401"]'),
    ("exact-with-ignore", 'select=["F401"]', 'select=["F401"]\nignore=["F401"]'),
    ("all-with-ignore", 'select=["ALL"]', 'select=["ALL"]\nignore=["F401"]'),
    ("prefix-ignore", 'select=["F"]', 'select=["F"]\nignore=["F4"]'),
    ("two-families", 'select=["E4","F"]', 'select=["F"]'),
    ("numeric-prefix", 'select=["F8"]', 'select=["F82"]'),
    ("reset-default", '', 'select=[]'),
    ("default-ignore", '', 'ignore=["F"]'),
    ("default-extension", 'extend-select=["E711"]', ''),
    ("specificity", 'select=["F401"]\nignore=["F"]', 'select=["F"]\nignore=["F"]'),
    ("partial-superset", 'select=["F401","E711","F821"]', 'select=["F401","E711"]'),
    ("extension-with-ignore", 'select=["F"]\nextend-select=["E711"]', 'select=["F"]\nextend-select=["E711"]\nignore=["F401"]'),
    ("empty-reset-extension", 'select=[]\nextend-select=["F"]', 'select=[]\nextend-select=["F4"]'),
    ("inactive-ignore", 'select=["F","E711"]\nignore=["E711"]', 'select=["F"]\nignore=["F401"]'),
    ("wider-default-ignore", 'ignore=["F4"]', 'ignore=["F"]'),
    ("all-additive-ignore", 'select=["ALL"]\nignore=["D"]', 'select=["ALL"]\nignore=["D","F401"]'),
]
FLAGS = ["check_untyped_defs", "disallow_any_generics", "disallow_incomplete_defs", "disallow_subclassing_any",
         "disallow_untyped_calls", "disallow_untyped_decorators", "disallow_untyped_defs", "extra_checks",
         "strict_equality", "warn_redundant_casts", "warn_return_any", "warn_unused_ignores", "strict_optional"]
MYPY_PAIRS = [(flag, flag + "=true", flag + "=false") for flag in FLAGS]
MYPY_PAIRS += [(flag, flag + "=false", flag + "=true") for flag in ["implicit_reexport", "ignore_errors", "ignore_missing_imports"]]
MYPY_PAIRS += [("error-code-" + code, "", 'disable_error_code=["' + code + '"]') for code in
              ["assignment", "arg-type", "call-arg", "attr-defined", "return-value", "return", "operator", "index", "union-attr"]]


def scan(tool, before, after):
    profile = next(p for p in available().values() if p["tool"] == tool)
    policy = f'''schema_version=1
mode="enforce"
[[targets]]
id="main"
tool="{tool}"
root="."
config="pyproject.toml"
profile="{profile['id']}"
paths=["src/"]
'''
    section = "tool.ruff.lint" if tool == "ruff" else "tool.mypy"
    left = {".checkwash/quality.toml": policy.encode(), "src/code.py": b"x = 1\n",
            "pyproject.toml": ("[" + section + "]\n" + before).encode()}
    right = {**left, "pyproject.toml": ("[" + section + "]\n" + after).encode()}
    return analyze(MappingSnapshot(left), MappingSnapshot(right), today=datetime.date(2026, 9, 9))


@pytest.mark.parametrize("tool,cases", [("ruff", RUFF_PAIRS), ("mypy", MYPY_PAIRS)])
def test_fixture_inventory_is_explicit_and_unique(tool, cases):
    assert len(cases) >= 20 and len({case[0] for case in cases}) == len(cases)


@pytest.mark.parametrize("name,before,after", RUFF_PAIRS, ids=[p[0] for p in RUFF_PAIRS])
def test_ruff_packaged_model_weakening(name, before, after):
    p, code = scan("ruff", before, after)
    assert code == 1 and p["analysis_status"] == "complete", p
    assert any(f["rule"] == "QW_RULE_DISABLED" for f in p["findings"])


@pytest.mark.parametrize("name,before,after", RUFF_PAIRS, ids=[p[0] for p in RUFF_PAIRS])
def test_ruff_packaged_model_strengthening(name, before, after):
    p, code = scan("ruff", after, before)
    assert code == 0 and p["analysis_status"] == "complete" and not p["findings"], p


@pytest.mark.parametrize("name,before,after", MYPY_PAIRS, ids=[p[0] for p in MYPY_PAIRS])
def test_mypy_packaged_model_weakening(name, before, after):
    p, code = scan("mypy", before, after)
    assert code == 1 and p["analysis_status"] == "complete", p
    assert any(f["rule"] == "QW_RULE_DISABLED" for f in p["findings"])


@pytest.mark.parametrize("name,before,after", MYPY_PAIRS, ids=[p[0] for p in MYPY_PAIRS])
def test_mypy_packaged_model_strengthening(name, before, after):
    p, code = scan("mypy", after, before)
    assert code == 0 and p["analysis_status"] == "complete" and not p["findings"], p


@pytest.mark.parametrize("preferred,expendable", [("D211", "D203"), ("D212", "D213")])
def test_ruff_removing_an_already_disabled_conflict_is_not_weakening(preferred, expendable):
    p, code = scan("ruff", f'select=["{preferred}","{expendable}"]', f'select=["{preferred}"]')
    assert code == 0 and p["analysis_status"] == "complete" and not p["findings"], p


def test_packaged_models_include_content_bound_offline_receipts():
    root = resources.files("checkwash.quality")
    required = {"config_formats", "discovery_precedence", "supported_keys", "defaults", "dimension_dependencies", "pattern_subset", "qualification_receipt"}
    for profile in available().values():
        assert required <= set(profile)
        receipt = profile["qualification_receipt"]
        for key in ("fixture", "results"):
            assert hashlib.sha256(root.joinpath(receipt[key]).read_bytes()).hexdigest() == receipt[key + "_sha256"]
