"""Owned Git chains for scheme S (D-194); data only, no checkwash import.

B is the released base, A the release PR's content commit, R its last commit
(doctor's own Action pin set to A), M the merge of B and R, S a squash of R.
"""
import os
from pathlib import Path
import re
import subprocess

ACTION = "taipei49314/checkwash/action"
PREVIOUS = "1" * 40
DOCTOR = "src/checkwash/doctor.py"
ADVERTISED = '[release]\ntag = "v0.10.0"\nversion = "0.10.0"\n'


def doctor(previous=PREVIOUS, own=PREVIOUS):
    return (f'_X = 1\n_PREVIOUS_ACTION_PIN = "{previous}"\n_OWN_ACTION_PIN = "{own}"\n'
            "_Y = (_PREVIOUS_ACTION_PIN, _OWN_ACTION_PIN)\n")


def git(root, *args):
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0")
    result = subprocess.run(["git", "-C", str(root), *args], env=env, capture_output=True, check=True)
    return result.stdout.decode("utf-8").strip()


def write(root, files):
    for name, text in files.items():
        path = Path(root) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))


def commit(root, message, staged=None):
    git(root, "add", "-A")
    if staged is not None:
        staged(root)
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def project(version):
    return f'[project]\nname = "checkwash"\nversion = "{version}"\n'


def repository(root, *, version="0.10.0", doctor_text=None, readme=None):
    """Commit B; release/advertised.toml names v0.10.0."""
    Path(root).mkdir(parents=True)
    git(root, "init", "-q")
    for key, value in {"user.name": "Owned scheme S fixture", "user.email": "fixture@example.invalid",
                       "core.autocrlf": "false", "commit.gpgsign": "false"}.items():
        git(root, "config", key, value)
    write(root, {".gitattributes": "* text=auto eol=lf\n*.py text eol=lf\n",
                 "pyproject.toml": project(version),
                 "release/advertised.toml": ADVERTISED,
                 DOCTOR: doctor() if doctor_text is None else doctor_text,
                 "README.md": f"      - uses: {ACTION}@{PREVIOUS} # v0.10.0\n" if readme is None else readme})
    return commit(root, "B")


def content(root, version="0.11.0"):
    """Commit A: the release content, with the version the release PR sets."""
    write(root, {"pyproject.toml": project(version), "NEWS": "release notes\n"})
    return commit(root, "A")


def set_own(root, value):
    path = Path(root) / DOCTOR
    text = re.sub(r'(?m)^_OWN_ACTION_PIN = "[0-9a-f]{40}"$', f'_OWN_ACTION_PIN = "{value}"',
                  path.read_bytes().decode("utf-8"), count=1)
    path.write_bytes(text.encode("utf-8"))


def chain(root, *, edit=None, staged=None, base_version="0.10.0", version="0.11.0", doctor_text=None, readme=None):
    """B, A, R (own pin = A, then `edit`; `staged` runs after `git add`), M and S."""
    b = repository(root, version=base_version, doctor_text=doctor_text, readme=readme)
    a = content(root, version)
    set_own(root, a)
    if edit is not None:
        edit(Path(root), a)
    r = commit(root, "R", staged)
    m = git(root, "commit-tree", r + "^{tree}", "-p", b, "-p", r, "-m", "merge")
    s = git(root, "commit-tree", r + "^{tree}", "-p", b, "-m", "squash")
    return dict(root=Path(root), B=b, A=a, R=r, M=m, S=s)
