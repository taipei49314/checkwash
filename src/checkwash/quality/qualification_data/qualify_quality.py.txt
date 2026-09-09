"""Hosted-CI qualification on trusted synthetic fixtures only.

This developer tool imports pinned external tools. The shipped quality core
does not. Profile generation is explicit and produces content-addressed data.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
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
            row["incompatible_rules"] = [["D211", "D203"], ["D212", "D213"]]
            # Exact 0.16.6 registry namespaces; F must not select FURB/FAST.
            row["selector_namespaces"] = "A AIR ANN ARG ASYNC B BLE C4 C90 COM CPY D DJ DOC DTZ E EM ERA EXE F FA FAST FBT FIX FLY FURB G I ICN INP INT ISC LOG N NPY PD PERF PGH PIE PL PT PTH PYI Q RET RSE RUF S SIM SLF SLOT T10 T20 TC TD TID TRY UP W YTT".split()
            with tempfile.TemporaryDirectory(prefix="quality-qualification-") as temp:
                path = Path(temp)
                (path / "sample.py").write_text("x = 1\n", encoding="utf-8")
                result = invoke([sys.executable, "-m", "ruff", "rule", "--all", "--output-format", "json"], temp)
                assert result.returncode == 0, result.stderr
                catalog = json.loads(result.stdout)
                (directory / "ruff-catalog.json").write_text(result.stdout, encoding="utf-8")
                active = [r for r in catalog if "Removed" not in r.get("status", {})]
                row["rule_catalog"] = sorted(r["code"] for r in active if isinstance(r.get("code"), str))
                row["uncoded_rules"] = sorted(r["name"] for r in active if r.get("code") is None and not r.get("preview", False))
                row["uncoded_preview_rules"] = sorted(r["name"] for r in active if r.get("code") is None and r.get("preview", False))
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
        for selectors in [["ALL"], ["F"], ["E"], ["D"], ["C4"], ["PIE"], ["PL"], ["T10"], ["FURB"], ["D203", "D211"], ["D212", "D213"], ["D203"], ["D213"]]:
            (root / "ruff.toml").write_text("[lint]\nselect=" + json.dumps(selectors) + "\n", encoding="utf-8")
            run = invoke([sys.executable, "-m", "ruff", "check", "--config", "ruff.toml", "--show-settings", "sample.py"], temp)
            assert run.returncode == 0, run.stderr
            match = re.search(r"linter\.rules\.enabled\s*=\s*\[(.*?)\]", run.stdout, re.S)
            assert match, run.stdout
            actual = sorted(set(re.findall(r"\(([A-Z]+\d+)\)", match.group(1))))
            predicted = selected_rules(selectors, [], ruff_profile)
            assert actual == predicted, {"selectors": selectors, "model_only": sorted(set(predicted) - set(actual)), "native_only": sorted(set(actual) - set(predicted))}
            results.append({"tool": "ruff", "case": "full-selection-set", "selectors": selectors, "rules": len(actual), "matched": True})
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
        (root / "src").mkdir()
        (root / "src" / "code.py").write_text("import os\n", encoding="utf-8")
        for pattern in (None, "src/code.py", "src/**"):
            config = ('exclude=' + json.dumps([pattern]) + '\n' if pattern else '') + '[lint]\nselect=["F401"]\n'
            (root / "ruff.toml").write_text(config, encoding="utf-8")
            run = invoke([sys.executable, "-m", "ruff", "check", "--config", "ruff.toml", "--output-format", "json", "src"], temp)
            assert run.returncode in {0, 1}, run.stderr
            actual = any(r["code"] == "F401" for r in json.loads(run.stdout))
            assert actual == (pattern is None)
            results.append({"tool": "ruff", "case": "scope", "pattern": pattern, "reported": actual})
        (root / "ruff.toml").write_text('[lint]\nselect=["F401"]\n', encoding="utf-8")
        (root / "src" / "ruff.toml").write_text('[lint]\nselect=[]\n', encoding="utf-8")
        run = invoke([sys.executable, "-m", "ruff", "check", "--output-format", "json", "src"], temp)
        assert run.returncode == 0 and not json.loads(run.stdout), run.stderr
        results.append({"tool": "ruff", "case": "nested-auto-override", "reported": False})
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
        (root / "covered.py").write_text("import src.code\nx = 1\nif x:\n    y = 2\nelse:\n    y = 3\n", encoding="utf-8")
        (root / "coverage.ini").write_text("[run]\n", encoding="utf-8")
        run = invoke([sys.executable, "-m", "coverage", "run", "--rcfile=coverage.ini", "covered.py"], temp)
        assert run.returncode == 0, run.stderr
        for threshold, expected in ((100, 2), (0, 0)):
            (root / "coverage.ini").write_text(f"[report]\nfail_under={threshold}\n", encoding="utf-8")
            run = invoke([sys.executable, "-m", "coverage", "report", "--rcfile=coverage.ini"], temp)
            assert run.returncode == expected, run.stdout + run.stderr
            results.append({"tool": "coverage", "fail_under": threshold, "expected_exit": expected, "actual_exit": run.returncode})
        for pattern in (None, "src/code.py", "src/**"):
            config = '[report]\n' + (f'omit={pattern}\n' if pattern else '')
            (root / "coverage.ini").write_text(config, encoding="utf-8")
            run = invoke([sys.executable, "-m", "coverage", "json", "--rcfile=coverage.ini", "-o", "coverage-result.json"], temp)
            assert run.returncode == 0, run.stdout + run.stderr
            reported = "src/code.py" in json.loads((root / "coverage-result.json").read_text())["files"]
            assert reported == (pattern is None)
            results.append({"tool": "coverage", "case": "scope", "pattern": pattern, "reported": reported})
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = profiles(args.output)
    results = qualify(rows) + qualify_sources(rows)
    receipt = {"qualification_schema_version": 1, "versions": VERSIONS, "results": results,
               "status": "bounded-fixtures-passed", "not_claimed": ["full tool semantics", "natural corpus acceptance", "CI activation proof"]}
    (args.output / "qualification.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    from checkwash.quality.model import digest
    contract = json.loads((Path(__file__).parent / "quality-profile-contract.json").read_text(encoding="utf-8"))
    fixture = Path(__file__).read_bytes().replace(b"\r\n", b"\n")
    (args.output / "qualify_quality.py.txt").write_bytes(fixture)
    result_digest = hashlib.sha256((args.output / "qualification.json").read_bytes()).hexdigest()
    for row in rows:
        row.update(contract[row["tool"]])
        row["qualification_receipt"] = {"fixture": "qualification_data/qualify_quality.py.txt", "fixture_sha256": hashlib.sha256(fixture).hexdigest(),
                                        "results": "qualification_data/results.json", "results_sha256": result_digest}
        row.pop("digest")
        row["digest"] = digest(row)
        (args.output / (row["tool"] + ".json")).write_text(json.dumps(row, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))


def qualify_sources(rows):
    """Native parsing versus modeled precedence, including equivalent moves."""
    from checkwash.quality.adapters import ADAPTERS
    from checkwash.quality.model import Target
    from checkwash.quality.snapshot import MappingSnapshot
    results = []
    cases = {
        "coverage": [
            {".coveragerc": "[report]\nfail_under=85", "pyproject.toml": "[tool.coverage.report]\nfail_under=50"},
            {"setup.cfg": "[coverage:report]\nfail_under=85", "pyproject.toml": "[tool.coverage.report]\nfail_under=50"},
            {"tox.ini": "[coverage:report]\nfail_under=85", "pyproject.toml": "[tool.coverage.report]\nfail_under=50"},
            {"pyproject.toml": "[tool.coverage.report]\nfail_under=85"},
            {".coveragerc.toml": "[tool.coverage.report]\nfail_under=85", "pyproject.toml": "[tool.coverage.report]\nfail_under=50"},
        ],
        "ruff": [
            {".ruff.toml": '[lint]\nselect=["F401"]', "ruff.toml": '[lint]\nselect=[]'},
            {"ruff.toml": '[lint]\nselect=["F401"]', "pyproject.toml": '[tool.ruff.lint]\nselect=[]'},
            {"pyproject.toml": '[tool.ruff.lint]\nselect=["F401"]'},
        ],
        "mypy": [
            {"mypy.ini": "[mypy]\ndisallow_untyped_defs=true", ".mypy.ini": "[mypy]\ndisallow_untyped_defs=false"},
            {".mypy.ini": "[mypy]\ndisallow_untyped_defs=true", "pyproject.toml": "[tool.mypy]\ndisallow_untyped_defs=false"},
            {"pyproject.toml": "[tool.mypy]\ndisallow_untyped_defs=true", "setup.cfg": "[mypy]\ndisallow_untyped_defs=false"},
            {"setup.cfg": "[mypy]\ndisallow_untyped_defs=yes"},
        ],
    }
    previous = Path.cwd()
    for row in rows:
        tool = row["tool"]
        for number, files in enumerate(cases[tool]):
            with tempfile.TemporaryDirectory(prefix="quality-precedence-") as temp:
                root = Path(temp)
                for name, value in {**files, "sample.py": "import os\n"}.items():
                    (root / name).write_text(value, encoding="utf-8")
                snapshot = MappingSnapshot({name: value.encode() for name, value in {**files, "sample.py": "import os\n"}.items()})
                target = Target("source", tool, ".", "auto", row["id"], ["sample.py"])
                modeled = ADAPTERS[tool](snapshot, target, "base", row)
                try:
                    os.chdir(root)
                    if tool == "coverage":
                        from coverage import Coverage
                        native = Coverage(config_file=True).get_option("report:fail_under")
                        assert int(modeled.values["coverage.report.fail_under"]) == native == 85, (files, modeled.values, native)
                    elif tool == "mypy":
                        from mypy.main import process_options
                        _, options = process_options(["sample.py"], require_targets=True)
                        assert modeled.values["mypy.disallow_untyped_defs"] == options.disallow_untyped_defs is True
                    else:
                        native = invoke([sys.executable, "-m", "ruff", "check", "--show-settings", "sample.py"], temp)
                        assert native.returncode == 0, native.stderr
                        match = re.search(r"linter\.rules\.enabled\s*=\s*\[(.*?)\]", native.stdout, re.S)
                        assert match
                        enabled = sorted(set(re.findall(r"\(([A-Z]+\d+)\)", match.group(1))))
                        assert modeled.values["ruff.lint.rules@sample.py"] == enabled == ["F401"]
                finally:
                    os.chdir(previous)
                results.append({"tool": tool, "case": "source-precedence", "fixture": number, "config_paths": sorted(files), "matched": True})
    return results


if __name__ == "__main__":
    main()
