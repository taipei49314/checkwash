"""`checkwash hook` without a subcommand is a usage error, exit 2 (issue #70).

It used to print `hook --help` — which argparse exits 0 for — so a CI step
that omitted or misspelled `install` reported success. SPEC §9: 0 means "no
finding"; usage and engine errors are 2.
"""

import subprocess
import sys

import pytest

from checkwash.cli import main


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
