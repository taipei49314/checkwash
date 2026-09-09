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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
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
            receipt = {"baseline": BASELINE, "byte_identical": identical,
                       "corpus_cases": len(list((root / "tests/cases").glob("*.gwcase"))),
                       "sha256": {k: hashlib.sha256(v).hexdigest() for k, v in outputs.items()}}
            (args.output / "legacy-comparison.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            assert identical, "Legacy findings/IR drifted from the fixed pre-quality source; preserve artifacts and investigate"
            print(json.dumps(receipt, sort_keys=True))
        finally:
            subprocess.run(["git", "worktree", "remove", str(baseline)], cwd=root, check=True)


if __name__ == "__main__":
    main()
