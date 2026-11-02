"""Scheme S (D-194): doctor accepts the previous Action pin and the release's own.

Both pins are exact SHAs fixed in doctor's source; the step shape, the owner
and every other ref stay unproven. The release's Action commit can stand for
the tag because the two differ only in doctor's own pin line and
`checkwash check`, all the Action runs, never imports doctor.
"""

import importlib.util
import io
import os
import pathlib
import re
import subprocess
import sys

import pytest

from checkwash import doctor
from checkwash.doctor import collect, run

from test_doctor import CANONICAL, _canonical_repo, _git, _healthy, _incomplete, _repo


ROOT = pathlib.Path(__file__).resolve().parents[1]
# Loaded at import, before the no-network fixture replaces socket for ssl.
SPEC = importlib.util.spec_from_file_location("own_pin_bridge_contract", ROOT / "tools/pju_release_bridge.py")
BRIDGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BRIDGE)
P = doctor._PREVIOUS_ACTION_PIN
OWN = "b" * 40
ACTION = "taipei49314/checkwash/action"


def _two_pins(monkeypatch):
    monkeypatch.setitem(doctor._ACCEPTED, doctor._ACTION, (P, OWN))


def _detail(root):
    return next(note.detail for note in collect(root) if "incomplete" in note.title)


def test_doctor_holds_one_previous_and_one_own_pin_line():
    raw = (ROOT / "src/checkwash/doctor.py").read_bytes()
    lines = raw.split(b"\n")
    previous = [line for line in lines if line.startswith(b"_PREVIOUS_ACTION_PIN")]
    own = [line for line in lines if line.startswith(b"_OWN_ACTION_PIN")]
    assert len(previous) == len(own) == 1
    assert re.fullmatch(rb'_PREVIOUS_ACTION_PIN = "[0-9a-f]{40}"', previous[0])
    assert re.fullmatch(rb'_OWN_ACTION_PIN = "[0-9a-f]{40}"', own[0])
    # The module's effective values are exactly the two lines the release tools read.
    assert previous[0] == f'_PREVIOUS_ACTION_PIN = "{doctor._PREVIOUS_ACTION_PIN}"'.encode()
    assert own[0] == f'_OWN_ACTION_PIN = "{doctor._OWN_ACTION_PIN}"'.encode()
    assert doctor._ACTION == ACTION
    assert doctor._PINS[doctor._ACTION] == doctor._PREVIOUS_ACTION_PIN
    assert doctor._ACCEPTED[doctor._ACTION] == tuple(dict.fromkeys((doctor._PREVIOUS_ACTION_PIN, doctor._OWN_ACTION_PIN)))
    assert {owner: pins for owner, pins in doctor._ACCEPTED.items() if owner != ACTION} == {
        "actions/checkout": (doctor._PINS["actions/checkout"],),
        "actions/setup-python": (doctor._PINS["actions/setup-python"],),
    }
    assert re.search(rf"{doctor._ACTION}@{doctor._PREVIOUS_ACTION_PIN} # v\d+\.\d+\.\d+$", CANONICAL, re.M)
    # The release bridge reads the same two lines from Git's LF blob.
    assert BRIDGE.doctor_action_pins(raw)[:2] == (doctor._PREVIOUS_ACTION_PIN, doctor._OWN_ACTION_PIN)
    assert "*.py text eol=lf" in (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("ref", ["a" * 40, "283db528cd3d8e5e38173e14d766a8915efa2c90"])
def test_one_accepted_pin_keeps_the_existing_text(tmp_path, monkeypatch, ref):
    monkeypatch.setitem(doctor._ACCEPTED, doctor._ACTION, (P,))
    detail = _detail(_canonical_repo(tmp_path / "sha", CANONICAL.replace(P, ref)))
    assert f"{ACTION}: unsupported SHA {ref}; this CLI requires {P}" in detail
    detail = _detail(_canonical_repo(tmp_path / "owner", CANONICAL.replace(f"{ACTION}@", "attacker/checkwash/action@")))
    assert f"expected {ACTION}@{P}; found attacker/checkwash/action@{P}" in detail


def test_both_accepted_action_pins_are_a_healthy_gate(tmp_path, monkeypatch):
    _two_pins(monkeypatch)
    _healthy(_canonical_repo(tmp_path / "previous"))
    root = _canonical_repo(tmp_path / "own", CANONICAL.replace(P, OWN))
    _healthy(root)
    assert run(str(root), io.StringIO()) == 0


@pytest.mark.parametrize("ref", ["c" * 40, "d6eda4f695fabb8e7d138f7a87b099d2028f0294"])
def test_any_other_action_sha_is_refused_naming_both_pins(tmp_path, monkeypatch, ref):
    _two_pins(monkeypatch)
    root = _canonical_repo(tmp_path, CANONICAL.replace(P, ref))
    assert (f"unsupported SHA {ref}; this CLI accepts {P} (the Action recommended before this release) "
            f"or {OWN} (this release's Action)") in _detail(root)
    assert run(str(root), io.StringIO()) == 1


def test_own_pin_does_not_relax_the_step_shape(tmp_path, monkeypatch):
    _two_pins(monkeypatch)
    cases = {
        "with": CANONICAL.replace(P, OWN) + "        with:\n          base: HEAD\n",
        "uppercase": CANONICAL.replace(P, OWN.upper()),
        "owner": CANONICAL.replace(f"{ACTION}@{P}", f"attacker/checkwash/action@{OWN}"),
    }
    for label, workflow in cases.items():
        root = _canonical_repo(tmp_path / label, workflow)
        _incomplete(root, label)
        assert run(str(root), io.StringIO()) == 1, label
    owner = _detail(tmp_path / "owner")
    assert f"expected {ACTION}@{P} or {ACTION}@{OWN}; found attacker/checkwash/action@{OWN}" in owner


def test_check_never_imports_doctor(tmp_path):
    """The Action runs only `checkwash check` (term, then json), never doctor."""
    root = _repo(tmp_path, {"tests/test_a.py": "def test_a():\n    assert 1 == 1\n"})
    identity = ("-c", "user.name=Owned fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false")
    _git(root, *identity, "commit", "--quiet", "-m", "first")
    (root / "tests/test_a.py").write_text("def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert 2 == 2\n",
                                          encoding="utf-8")
    _git(root, "add", "--all")
    _git(root, *identity, "commit", "--quiet", "-m", "second")
    code = ("import sys; sys.path.insert(0, sys.argv[1]); from checkwash import cli; "
            "rc = cli.main(['check', 'HEAD~1...HEAD', '--repo', sys.argv[2], '--fail-on', 'high', '--format', sys.argv[3]]); "
            "sys.exit(3 if 'checkwash.doctor' in sys.modules else rc)")
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    for fmt in ("term", "json"):
        result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-c", code, str(ROOT / "src"), str(root), fmt],
                                env=env, capture_output=True, timeout=120)
        assert result.returncode == 0, (fmt, result.stdout, result.stderr)
