"""Validate actual quality reports against the public schema in hosted CI."""
import argparse
import datetime
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from checkwash.quality.engine import analyze
from checkwash.quality.snapshot import MappingSnapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "docs/quality-report.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    profiles = {}
    for tool in ("coverage", "ruff", "mypy"):
        row = json.loads((args.profiles / (tool + ".json")).read_text(encoding="utf-8"))
        profiles[row["id"]] = row
    settings = {
        "coverage": ('[tool.coverage.report]\nfail_under=85', '[tool.coverage.report]\nfail_under=50'),
        "ruff": ('[tool.ruff.lint]\nselect=["F401"]', '[tool.ruff.lint]\nselect=[]'),
        "mypy": ('[tool.mypy]\ndisallow_untyped_defs=true', '[tool.mypy]\ndisallow_untyped_defs=false'),
    }
    checked = []
    for profile in profiles.values():
        tool = profile["tool"]
        for mode in ("report", "enforce"):
            policy = f'''schema_version=1
mode="{mode}"
[[targets]]
id="main"
tool="{tool}"
root="."
config="pyproject.toml"
profile="{profile['id']}"
paths=["src/"]
'''.encode()
            before = {".checkwash/quality.toml": policy, "pyproject.toml": settings[tool][0].encode(), "src/code.py": b"x = 1\n"}
            after = {**before, "pyproject.toml": settings[tool][1].encode()}
            payload, code = analyze(MappingSnapshot(before), MappingSnapshot(after), today=datetime.date(2026, 9, 9), profiles=profiles)
            validator.validate(payload)
            assert code == (1 if mode == "enforce" else 0), payload
            (args.profiles / f"report-{tool}-{mode}.json").write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            checked.append(f"{tool}-{mode}")
    for snapshot in ({}, {".checkwash/quality.toml": b"invalid toml!"}):
        payload, code = analyze(MappingSnapshot(snapshot), MappingSnapshot(snapshot), today=datetime.date(2026, 9, 9), profiles=profiles)
        validator.validate(payload)
        assert code == (2 if snapshot else 0)
    print("Schema validated for six actual weakening reports plus discovery and error: " + ", ".join(checked))


if __name__ == "__main__":
    main()
