"""Hosted-CI qualification on trusted synthetic fixtures only.

This developer tool imports pinned external tools. The shipped quality core
does not. Profile generation is explicit and produces content-addressed data.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

VERSIONS = {"coverage": "7.16.0", "ruff": "0.16.6", "mypy": "2.3.1"}


def invoke(argv, cwd):
    run = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if run.returncode not in {0, 1, 2}:
        raise RuntimeError(f"Tool failed: {argv[0]} exit {run.returncode}")
    return run


def profiles(directory):
    from checkwash.quality.model import digest
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for tool, version in VERSIONS.items():
        assert importlib.metadata.version(tool) == version
        row = {"profile_schema_version": 1, "id": f"{tool}-{version}-q1", "tool": tool,
               "tool_version": version, "model_revision": 1,
               "qualification_fixture_sha256": hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
               "scope": "bounded-preview", "pattern_subset": ["literal-relative-path", "literal-directory/**"]}
        if tool == "mypy":
            from mypy.main import define_options
            from mypy.options import Options
            _, _, assignments = define_options()
            defaults = Options()
            row["strict_expansion"] = dict(assignments)
            row["mypy_defaults"] = {name: getattr(defaults, name) for name, _ in assignments}
            assert all(isinstance(v, bool) for v in row["strict_expansion"].values())
        if tool == "ruff":
            with tempfile.TemporaryDirectory(prefix="quality-qualification-") as temp:
                path = Path(temp)
                (path / "sample.py").write_text("x = 1\n", encoding="utf-8")
                result = invoke([sys.executable, "-m", "ruff", "rule", "--all", "--output-format", "json"], temp)
                assert result.returncode == 0, result.stderr
                catalog = json.loads(result.stdout)
                (directory / "ruff-catalog.json").write_text(result.stdout, encoding="utf-8")
                row["rule_catalog"] = sorted(r["code"] for r in catalog if isinstance(r.get("code"), str))
                row["uncoded_rules"] = sorted(r["name"] for r in catalog if r.get("code") is None)
                row["preview_rules"] = sorted(r["code"] for r in catalog if isinstance(r.get("code"), str) and r.get("preview", False))
                settings = invoke([sys.executable, "-m", "ruff", "check", "--isolated", "--show-settings", "sample.py"], temp)
                assert settings.returncode == 0, settings.stderr
                (directory / "ruff-settings.txt").write_text(settings.stdout, encoding="utf-8")
                match = re.search(r"linter\.rules\.enabled\s*=\s*\[(.*?)\]", settings.stdout, re.S)
                assert match, settings.stdout
                row["default_rules"] = sorted(set(re.findall(r"\(([A-Z]+\d+)\)", match.group(1))))
                assert "F401" in row["default_rules"], match.group(1)
                row["default_excludes"] = [".bzr", ".direnv", ".eggs", ".git", ".git-rewrite", ".hg", ".ipynb_checkpoints", ".mypy_cache", ".nox", ".pants.d", ".pyenv", ".pytest_cache", ".pytype", ".ruff_cache", ".svn", ".tox", ".venv", ".vscode", "__pypackages__", "_build", "buck-out", "build", "dist", "node_modules", "site-packages", "venv"]
        row["digest"] = digest(row)
        (directory / (tool + ".json")).write_text(json.dumps(row, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        rows.append(row)
    return rows


def qualify(rows):
    from checkwash.quality.adapters import selected_rules
    results = []
    with tempfile.TemporaryDirectory(prefix="quality-fixtures-") as temp:
        root = Path(temp)
        (root / "sample.py").write_text("import os\n", encoding="utf-8")
        ruff_profile = next(r for r in rows if r["tool"] == "ruff")
        for select, ignore, should_report in [(["F401"], [], True), (["F401"], ["F401"], False), (["F401"], ["F"], True), (["F"], ["F401"], False)]:
            config = "[lint]\nselect=" + json.dumps(select) + "\nignore=" + json.dumps(ignore) + "\n"
            (root / "ruff.toml").write_text(config, encoding="utf-8")
            run = invoke([sys.executable, "-m", "ruff", "check", "--config", "ruff.toml", "--output-format", "json", "sample.py"], temp)
            assert run.returncode in {0, 1}, run.stderr
            actual = any(r["code"] == "F401" for r in json.loads(run.stdout))
            predicted = "F401" in selected_rules(select, ignore, ruff_profile)
            assert actual == predicted == should_report
            results.append({"tool": "ruff", "select": select, "ignore": ignore, "expected": should_report, "actual": actual})
        # Exercise inherited selection order against the actual tool.
        (root / "parent.toml").write_text('[lint]\nselect=["F401"]\n', encoding="utf-8")
        for child, expect_error in [('extend="parent.toml"\n', True), ('extend="parent.toml"\n[lint]\nselect=[]\n', False), ('extend="parent.toml"\n[lint]\nignore=["F"]\n', False)]:
            (root / "ruff.toml").write_text(child, encoding="utf-8")
            run = invoke([sys.executable, "-m", "ruff", "check", "--config", "ruff.toml", "--output-format", "json", "sample.py"], temp)
            assert run.returncode in {0, 1}, run.stderr
            actual = any(r["code"] == "F401" for r in json.loads(run.stdout))
            assert actual == expect_error
            results.append({"tool": "ruff", "case": "inheritance", "config": child, "expected": expect_error, "actual": actual})
        (root / "typed.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
        for setting, expect_error in ((True, True), (False, False)):
            (root / "mypy.ini").write_text("[mypy]\ndisallow_untyped_defs=" + str(setting).lower() + "\n", encoding="utf-8")
            run = invoke([sys.executable, "-m", "mypy", "--config-file", "mypy.ini", "typed.py"], temp)
            assert run.returncode in {0, 1}, run.stderr
            actual = "no-untyped-def" in run.stdout
            assert actual == expect_error, run.stdout
            results.append({"tool": "mypy", "disallow_untyped_defs": setting, "expected": expect_error, "actual": actual})
        from mypy.main import process_options
        mypy_profile = next(r for r in rows if r["tool"] == "mypy")
        for strict in (False, True):
            (root / "mypy.ini").write_text(f"[mypy]\nstrict={str(strict).lower()}\n", encoding="utf-8")
            _, options = process_options(["--config-file", str(root / "mypy.ini"), str(root / "typed.py")])
            for flag, value in mypy_profile["strict_expansion"].items():
                expected = value if strict else mypy_profile["mypy_defaults"][flag]
                assert getattr(options, flag) == expected, flag
            results.append({"tool": "mypy", "case": "strict-option-expansion", "strict": strict, "flags": len(mypy_profile["strict_expansion"]), "matched": True})
        # Build real trusted coverage data with one exercised and one missed
        # branch; threshold behavior is checked against the actual reporter.
        (root / "covered.py").write_text("x = 1\nif x:\n    y = 2\nelse:\n    y = 3\n", encoding="utf-8")
        (root / "coverage.ini").write_text("[run]\n", encoding="utf-8")
        run = invoke([sys.executable, "-m", "coverage", "run", "--rcfile=coverage.ini", "covered.py"], temp)
        assert run.returncode == 0, run.stderr
        for threshold, expected in ((100, 2), (0, 0)):
            (root / "coverage.ini").write_text(f"[report]\nfail_under={threshold}\n", encoding="utf-8")
            run = invoke([sys.executable, "-m", "coverage", "report", "--rcfile=coverage.ini"], temp)
            assert run.returncode == expected, run.stdout + run.stderr
            results.append({"tool": "coverage", "fail_under": threshold, "expected_exit": expected, "actual_exit": run.returncode})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = profiles(args.output)
    results = qualify(rows)
    receipt = {"qualification_schema_version": 1, "versions": VERSIONS, "results": results,
               "status": "bounded-fixtures-passed", "not_claimed": ["full tool semantics", "natural corpus acceptance", "CI activation proof"]}
    (args.output / "qualification.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
