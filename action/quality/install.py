"""Install the pinned action's source in a private runner-temporary environment."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if not sys.flags.isolated or sys.version_info < (3, 11):
        raise RuntimeError("Checkwash quality requires Python 3.11+ with isolated mode (-I)")
    root = Path(__file__).resolve().parents[2]
    temporary = Path(tempfile.mkdtemp(prefix="checkwash-quality-venv-", dir=os.environ["RUNNER_TEMP"]))
    subprocess.run([sys.executable, "-I", "-m", "venv", str(temporary)], cwd=temporary, check=True)
    python = temporary / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run([str(python), "-I", "-m", "pip", "--isolated", "--disable-pip-version-check",
                    "install", "--no-deps", str(root)], cwd=temporary, check=True)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        stream.write("python=" + str(python) + "\n")


if __name__ == "__main__":
    main()
