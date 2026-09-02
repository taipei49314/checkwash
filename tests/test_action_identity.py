"""The composite Action is checkwash, not its pre-rename name (issue #72).

action.yml still announced itself as `greenwash` and ran `greenwash check`;
that worked only because pyproject keeps the `greenwash` console script as an
alias. The Action now runs the real command; the alias stays for callers
pinned before v0.2.11 and is documented as legacy in pyproject.
"""

import pathlib
import tomllib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_action_identity_is_checkwash():
    action = (ROOT / "action" / "action.yml").read_text(encoding="utf-8")
    assert action.startswith("name: checkwash")
    assert "greenwash check" not in action
    assert action.count("checkwash check") == 2
    assert "GREENWASH_" not in action


def test_action_readme_names_the_real_command_and_no_stale_version():
    readme = (ROOT / "action" / "README.md").read_text(encoding="utf-8")
    assert readme.startswith("# checkwash GitHub Action")
    assert "greenwash check" not in readme
    assert "v0.1.46" not in readme


def test_console_script_alias_is_kept_and_marked_legacy():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data["project"]["scripts"]
    assert scripts["checkwash"] == "checkwash.cli:main"
    assert scripts["greenwash"] == "checkwash.cli:main"
    raw = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "legacy alias" in raw
