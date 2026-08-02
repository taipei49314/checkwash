"""Packaging invariants that a release depends on.

A README whose install line doesn't work is the first thing a visitor hits,
and this project's whole pitch is that its claims are checkable. So the
claims about itself are tests too.
"""

import pathlib
import re
import tomllib

import greenwash

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _pyproject() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as fh:
        return tomllib.load(fh)


def test_version_matches_pyproject():
    assert greenwash.__version__ == _pyproject()["project"]["version"]


def test_no_runtime_dependencies():
    # "Zero runtime dependencies" is a headline claim and a security
    # property (SECURITY.md), not an accident.
    assert _pyproject()["project"]["dependencies"] == []


def test_readme_install_refs_match_version():
    """Every version-pinned install line in the README points at this version.

    A README pinning a tag that doesn't exist is a broken install for the
    first person who tries it.
    """
    version = _pyproject()["project"]["version"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    pinned = set(re.findall(r"@(v\d+\.\d+\.\d+)", readme)) | set(
        re.findall(r"rev:\s*(v\d+\.\d+\.\d+)", readme)
    )
    assert pinned, "README should pin at least one install ref"
    assert pinned == {f"v{version}"}, f"README pins {pinned}, package is v{version}"
