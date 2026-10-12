"""Install the trusted quality Action through the shared isolated installer."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def shared_security():
    path = Path(__file__).resolve().parents[1] / "secure.py"
    spec = importlib.util.spec_from_file_location("checkwash_action_security", path)
    if spec is None or spec.loader is None:
        raise ValueError("Trusted Action security module is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    try:
        return shared_security().install(dict(os.environ))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print("Checkwash quality installation failed:", type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
