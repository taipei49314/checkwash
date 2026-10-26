"""Capture one fixed-source artifact qualification, without publishing checks."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys


BASE = "1ffe283d7d947fecc426dea99323b0a2620a9482"
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
parser = argparse.ArgumentParser()
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--kind", choices=["source", "wheel", "pyz"], required=True)
parser.add_argument("--python", type=Path, required=True)
parser.add_argument("--artifact", type=Path)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
source = args.source.resolve(strict=True)
output = args.output.absolute()
output.mkdir(parents=True, exist_ok=False)


def git(*arguments):
    return subprocess.run(["git", *arguments], cwd=source, capture_output=True, check=True).stdout


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot():
    names = git("ls-files", "-z").decode("utf-8").split("\0")
    return {name: digest((source / name).read_bytes()) for name in names if name and (source / name).is_file()}


assert not git("status", "--porcelain", "--untracked-files=all"), "source must be a clean fixed checkout"
head = git("rev-parse", "HEAD").decode().strip()
before = snapshot()
collector_bytes = git("show", BASE + ":tools/collect_pju_receipts.py")
collector_path = WORK / "trusted/collect_pju_receipts-at-1ffe.py"
if collector_path.exists():
    assert collector_path.read_bytes() == collector_bytes, "trusted collector bytes changed"
else:
    collector_path.write_bytes(collector_bytes)
helper_path = "tools/qualify_assertions.py"
assert (source / helper_path).read_bytes() == git("show", BASE + ":" + helper_path), "qualifier changed from trusted baseline"
contracts = ["tests/data/javascript_assertion_support.json", "tests/data/javascript_foundation_mutations.json"]
for name in contracts:
    assert (source / name).read_bytes() == git("show", BASE + ":" + name), "qualification inventory changed"

spec = importlib.util.spec_from_file_location("trusted_collector", collector_path)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
collector.ROOT = source
arguments = ["--source-root", str(source), "--distribution", args.kind,
             "--output", str(output / "qualification.json")]
if args.artifact:
    arguments += ["--artifact", str(args.artifact.resolve(strict=True))]
arguments += ["--", str(args.python.absolute())]
started = datetime.now(timezone.utc).isoformat()
exit_code = collector.traced_worker("qualify_assertions.py", output / "raw", arguments)
after = snapshot()
record = {
    "status": "passed" if exit_code == 0 and before == after else "failed",
    "kind": args.kind, "source_sha": head, "ending_sha": git("rev-parse", "HEAD").decode().strip(),
    "source_files_unchanged": before == after,
    "source_input_manifest_sha256": digest(json.dumps(before, sort_keys=True).encode()),
    "provenance": "HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL", "host": platform.node(),
    "python": sys.version, "platform": platform.platform(), "command": arguments,
    "exit_code": exit_code, "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
    "trusted_trace_source": BASE, "trusted_trace_sha256": digest(collector_bytes),
    "qualifier_sha256": digest((source / helper_path).read_bytes()),
    "contracts": {name: digest((source / name).read_bytes()) for name in contracts},
    "source_files": before,
    "formal_release_collector": False, "published_check_runs": 0,
}
(output / "receipt.json").write_text(json.dumps(record, sort_keys=True, indent=2), encoding="utf-8")
print(json.dumps({key: value for key, value in record.items() if key != "source_files"}, sort_keys=True))
raise SystemExit(0 if record["status"] == "passed" else 1)
