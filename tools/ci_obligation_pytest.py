"""External observation plugin; never part of either owned input Git tree."""
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest


REPORTS = []


def pytest_runtest_logreport(report):
    REPORTS.append({"nodeid": report.nodeid, "when": report.when,
                    "outcome": report.outcome, "longrepr": str(report.longrepr)})


def pytest_sessionfinish(session, exitstatus):
    binding_path = Path(os.environ["OWNED_BINDING"])
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    app = sys.modules.get("app")
    document = {
        "purpose": "NATIVE_PYTEST_OBSERVATION_NOT_OS_EXIT_CODE",
        "binding_sha256": hashlib.sha256(binding_path.read_bytes()).hexdigest(),
        "candidate_sha": binding["candidate_sha"], "case": binding["case"],
        "side": binding["side"], "run_id": binding["run_id"], "attempt": binding["attempt"],
        "pytest_exit_status": int(exitstatus), "os_process_exit_code": None,
        "python": sys.version, "executable": str(Path(sys.executable).resolve()),
        "pytest_version": pytest.__version__, "pytest_path": str(Path(pytest.__file__).resolve()),
        "argv": sys.argv, "cwd": str(Path.cwd().resolve()),
        "collected": session.testscollected, "failed": session.testsfailed,
        "app_path": str(Path(app.__file__).resolve()) if app is not None else None,
        "addopts": os.environ.get("PYTEST_ADDOPTS"),
        "pythonpath": os.environ.get("PYTHONPATH"),
        "plugin_autoload": os.environ.get("PYTEST_DISABLE_PLUGIN_AUTOLOAD"),
        "reports": REPORTS,
    }
    target = Path(os.environ["OWNED_NATIVE_RECEIPT"])
    with target.open("x", encoding="utf-8") as output:
        json.dump(document, output, sort_keys=True, indent=2, allow_nan=False)
        output.write("\n")
