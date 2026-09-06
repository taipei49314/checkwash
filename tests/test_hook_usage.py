"""`checkwash hook` without a subcommand is a usage error, exit 2 (issue #70).

It used to print `hook --help` — which argparse exits 0 for — so a CI step
that omitted or misspelled `install` reported success. SPEC §9: 0 means "no
finding"; usage and engine errors are 2.
"""

import subprocess
import sys

import pytest

from checkwash.cli import main
from checkwash import __version__


def test_bare_hook_is_a_usage_error_in_process():
    with pytest.raises(SystemExit) as raised:
        main(["hook"])
    assert raised.value.code == 2


def test_bare_hook_exits_2_as_a_subprocess():
    proc = subprocess.run(
        [sys.executable, "-m", "checkwash", "hook"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, (proc.stdout, proc.stderr)
    assert "usage: checkwash hook" in proc.stderr
    assert proc.stdout == ""


def test_hook_install_still_needs_its_agent_argument():
    proc = subprocess.run(
        [sys.executable, "-m", "checkwash", "hook", "install"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "--agent" in proc.stderr


def test_precommit_prints_template_and_next_steps_without_installing(tmp_path, capsys):
    config = tmp_path / ".pre-commit-config.yaml"
    original = b"# existing project config\nrepos: []\n"
    config.write_bytes(original)
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    assert main(["hook", "install", "--agent", "pre-commit", "--repo", str(tmp_path)]) == 0

    result = capsys.readouterr()
    assert result.err == ""
    assert "no files were written and no hook was installed" in result.out
    assert "Save or merge this into .pre-commit-config.yaml" in result.out
    assert "#   pre-commit install\n" in result.out
    assert "#   pre-commit run checkwash --all-files\n" in result.out
    assert f"    rev: v{__version__}\n" in result.out
    # Instruction lines remain YAML comments; stdout is still directly savable.
    active = "\n".join(line for line in result.out.splitlines() if line and not line.startswith("#"))
    assert active == (
        "repos:\n  - repo: https://github.com/taipei49314/checkwash\n"
        f"    rev: v{__version__}\n    hooks:\n      - id: checkwash"
    )
    assert config.read_bytes() == original
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before


def test_precommit_local_is_usage_error_without_writing(tmp_path, capsys):
    assert main(["hook", "install", "--agent", "pre-commit", "--local", "--repo", str(tmp_path)]) == 2
    result = capsys.readouterr()
    assert result.out == ""
    assert "--local applies to --agent claude-code only" in result.err
    assert list(tmp_path.iterdir()) == []


def test_hook_install_help_distinguishes_template_from_settings(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["hook", "install", "--help"])
    assert raised.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "write Stop hook settings" in help_text
    assert "print a YAML template only" in help_text
