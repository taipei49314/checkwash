"""#436: `doctor` names what it proves and where the README says it.

A user evaluating v0.7.0 reported that `doctor` right after install cites
README sections that no longer exist, gives only a generic reason for a
workflow it does not prove, and names the wrong file when an allowlist does
not parse. These tests pin those texts, and that setup-python's other supported
versions, "3.11" and "3.13", are now proven too (owner approval, 2026-10-16).
"""

import datetime
import re

import pytest

from checkwash.allowlist import summarize_allowlist
from checkwash.doctor import collect

from test_doctor import CANONICAL, CI, README, _canonical_repo, _healthy, _repo


def _incomplete_detail(root):
    return next(n.detail for n in collect(root) if "incomplete" in n.title)


def test_the_no_gate_note_says_nothing_blocks_yet_and_cites_a_real_section(tmp_path):
    notes = collect(_repo(tmp_path, {"README.md": "hello"}))
    note = next(n for n in notes if n.level == "problem")
    assert "nothing blocks a merge yet" in note.detail
    assert '"Use it in CI" in the README' in note.detail
    details = " ".join(n.detail for n in notes)
    assert "Required check section" not in details
    assert "README step 2" not in details


def test_every_readme_section_doctor_cites_exists(tmp_path):
    roots = (
        _repo(tmp_path / "empty", {"README.md": "hello"}),
        _canonical_repo(tmp_path / "shape", CANONICAL.replace("on: [pull_request]", "on: push")),
    )
    details = " ".join(n.detail for root in roots for n in collect(root))
    cited = set(re.findall(r'"([^"]+)" in the README', details))
    assert cited == {"Use it in CI"}
    assert cited <= set(re.findall(r"^## (.+)$", README, re.M))


@pytest.mark.parametrize("on, found", [
    ("on: [push, pull_request]", "found on: [push, pull_request]"),
    ("on: pull_request", "found on: pull_request"),
    ("on:\n  pull_request:\n    types: [closed]", "found an on: block with pull_request and event filters"),
    ("on:\n  push:\n  pull_request:", "found an on: block with push, pull_request"),
])
def test_an_unproven_trigger_names_the_trigger_doctor_proves(tmp_path, on, found):
    detail = _incomplete_detail(_canonical_repo(tmp_path, CANONICAL.replace("on: [pull_request]", on)))
    assert "unsupported or ambiguous workflow shape" in detail
    assert "doctor proves only on: [pull_request]" in detail
    assert found in detail


@pytest.mark.parametrize("version", ['"3.10"', "3.12", "'3.12'"])
def test_an_unproven_python_version_names_the_version_doctor_proves(tmp_path, version):
    workflow = CANONICAL.replace('python-version: "3.12"', f"python-version: {version}")
    detail = _incomplete_detail(_canonical_repo(tmp_path, workflow))
    assert 'actions/setup-python: doctor proves only with python-version: "3.11", "3.12" or "3.13"' in detail
    assert f"found python-version: {version}" in detail
    assert "unsupported or ambiguous workflow shape" not in detail


@pytest.mark.parametrize("version", ['"3.11"', '"3.13"'])
def test_the_other_supported_python_versions_are_healthy(tmp_path, version):
    _healthy(_canonical_repo(tmp_path, CANONICAL.replace('python-version: "3.12"', f"python-version: {version}")))


def test_an_unproven_checkout_input_names_the_inputs_doctor_proves(tmp_path):
    workflow = CANONICAL.replace("          fetch-depth: 0", "          fetch-depth: 1")
    detail = _incomplete_detail(_canonical_repo(tmp_path, workflow))
    assert "actions/checkout: doctor proves only with fetch-depth: 0, persist-credentials: false" in detail
    assert "found fetch-depth: 1, persist-credentials: false" in detail


def test_a_step_with_another_key_keeps_the_generic_reason(tmp_path):
    workflow = CANONICAL.replace(
        "      - uses: actions/setup-python@", "      - name: setup\n        uses: actions/setup-python@"
    )
    detail = _incomplete_detail(_canonical_repo(tmp_path, workflow))
    assert "unsupported or ambiguous workflow shape" in detail
    assert "doctor proves only with" not in detail


def test_an_unparsable_allowlist_is_named_by_its_own_path(tmp_path):
    notes = collect(_repo(tmp_path, {
        f"{CI}/checkwash.yml": CANONICAL,
        ".checkwash/allow.toml": "not = = toml\n",
    }))
    base_side = next(n for n in notes if "BASE side" in n.title)
    assert "present (.checkwash/allow.toml)" in base_side.detail
    warning = next(n for n in notes if "could not be parsed" in n.title)
    assert warning.detail.startswith(".checkwash/allow.toml could not be parsed")
    assert ".greenwash/" not in warning.detail


def test_summarize_allowlist_keeps_its_default_path():
    summary = summarize_allowlist(b"not = = toml\n", datetime.date(2026, 10, 16))
    assert summary.parse_error.startswith(".greenwash/allow.toml could not be parsed")
