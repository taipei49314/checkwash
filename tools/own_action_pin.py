"""Write or check a release PR's last commit R (scheme S, D-194).

`write` stages R on a clean checkout of the release PR's content commit A: R
changes only doctor's own Action pin line, to A. It prints the commit command
and never commits. `check` runs the release bridge's trusted rule on local
commits: an advisory pre-push and pre-tag check, not release evidence.
Neither imports or runs checkwash.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


def load_bridge():
    spec = importlib.util.spec_from_file_location("_own_action_pin_bridge", Path(__file__).with_name("pju_release_bridge.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


R = load_bridge()


def git(root, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    result = subprocess.run(["git", "-C", str(root), *args], env=env, capture_output=True, timeout=60)
    R.require(result.returncode == 0, "git " + " ".join(args) + " failed: " + result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def write(repo):
    root = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip())
    R.require(git(root, "--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=all") == b"",
              "the checkout is not clean; commit or remove every change first")
    action = git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    raw = git(root, "cat-file", "blob", action + ":" + R.DOCTOR_PATH)
    _previous, own, index = R.doctor_action_pins(raw)
    version, advertised = R.B.release_versions(root, action)
    R.require(version != advertised, f"HEAD's version {version} is the advertised release's; R belongs only to a release PR")
    R.require(own not in R.commit_parents(root, action), "HEAD already sets doctor's own Action pin to its parent; it is R")
    path = root / R.DOCTOR_PATH
    R.require(path.read_bytes() == raw, "the worktree doctor.py differs from HEAD's blob (line endings included)")
    lines = raw.split(b"\n")
    lines[index] = b'_OWN_ACTION_PIN = "' + action.encode() + b'"'
    path.write_bytes(b"\n".join(lines))
    git(root, "add", "--", R.DOCTOR_PATH)
    R.require(git(root, "diff", "--cached", "--name-only", "-z") == R.DOCTOR_PATH.encode() + b"\0"
              and git(root, "cat-file", "blob", ":" + R.DOCTOR_PATH) == b"\n".join(lines),
              "the staged change is not exactly doctor's own Action pin line; inspect git diff --cached")
    print(f'git commit -m "release: doctor accepts its own Action pin {action}"')
    return 0


def check(repo, stage, head, base, pr_head, announced):
    def commit(rev):
        R.require(not rev.startswith("-"), "a revision cannot start with '-'")
        return git(repo, "rev-parse", "--verify", rev + "^{commit}").decode().strip()

    current = {"stage": stage, "head_sha": commit(head), "base_sha": commit(base)}
    result = R.validate_own_action_pin(repo, current, announced=announced or R.B.ACTION_SHA,
                                       pr_head=None if pr_head is None else commit(pr_head))
    print(json.dumps(result, sort_keys=True))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("write", help="stage R on a clean checkout of the content commit").add_argument("--repo", default=".")
    rule = modes.add_parser("check", help="run the release bridge's rule on local commits (advisory)")
    rule.add_argument("--repo", default=".")
    rule.add_argument("--stage", choices=("pr", "main", "tag"), required=True)
    rule.add_argument("--head", required=True)
    rule.add_argument("--base", required=True)
    rule.add_argument("--pr-head")
    rule.add_argument("--announced", help="previous Action pin (default: tools/pju_receipt_bridge.py ACTION_SHA)")
    args = parser.parse_args(argv)
    try:
        if args.mode == "write":
            return write(args.repo)
        return check(args.repo, args.stage, args.head, args.base, args.pr_head, args.announced)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
