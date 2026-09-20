"""Byte-compare legacy findings/IR against the fixed pre-quality source in CI."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

BASELINE = "387e71befedc387ab0c85af4c3322b7877a0cfd1"


def match_release_record(record, outputs, version):
    """Accept only the exact, separately reviewed release transition.

    The original T-255 baseline and raw comparison remain in the receipt.
    A release record cannot wildcard fields, drop cases, or claim that two
    differing outputs are byte-identical.
    """
    required = {"schema_version", "baseline", "release_version", "review", "sha256"}
    if not isinstance(record, dict) or set(record) != required:
        return False
    if (type(record["schema_version"]) is not int or record["schema_version"] != 1
            or record["baseline"] != BASELINE or record["release_version"] != version
            or not isinstance(record["review"], str) or not record["review"].strip()
            or not isinstance(record["sha256"], dict)
            or set(record["sha256"]) != {"baseline", "candidate"}):
        return False
    return all(record["sha256"][name] == hashlib.sha256(outputs[name]).hexdigest()
               for name in ("baseline", "candidate"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-record", type=Path,
                        help="Exact hashes and review of an intentional versioned transition")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "fetch", "--depth=1", "origin", BASELINE], cwd=root, check=True)
    with tempfile.TemporaryDirectory(prefix="quality-legacy-") as temporary:
        baseline = Path(temporary) / "baseline"
        subprocess.run(["git", "worktree", "add", "--detach", str(baseline), BASELINE], cwd=root, check=True)
        try:
            outputs = {}
            for name, checkout in [("baseline", baseline), ("candidate", root)]:
                result = subprocess.run([sys.executable, str(checkout / "tools/emit_corpus.py")], cwd=checkout,
                                        env={**os.environ, "PYTHONUTF8": "1"}, capture_output=True, check=True)
                outputs[name] = result.stdout
                (args.output / ("legacy-" + name + ".json")).write_bytes(result.stdout)
            identical = outputs["baseline"] == outputs["candidate"]
            qualified_transition = False
            if args.release_record is not None:
                import tomllib
                version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
                record = json.loads(args.release_record.read_text(encoding="utf-8"))
                qualified_transition = match_release_record(record, outputs, version)
            receipt = {"baseline": BASELINE, "byte_identical": identical,
                       "release_record": str(args.release_record) if args.release_record else None,
                       "qualified_transition": qualified_transition,
                       "corpus_cases": len(list((root / "tests/cases").glob("*.gwcase"))),
                       "sha256": {k: hashlib.sha256(v).hexdigest() for k, v in outputs.items()}}
            (args.output / "legacy-comparison.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            assert (qualified_transition if args.release_record else identical), (
                "Legacy findings/IR drifted without an exact reviewed release transition; preserve artifacts and investigate")
            print(json.dumps(receipt, sort_keys=True))
        finally:
            subprocess.run(["git", "worktree", "remove", str(baseline)], cwd=root, check=True)


if __name__ == "__main__":
    main()
