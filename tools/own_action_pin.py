"""Write or check a release PR's last commit R, and tag the release (scheme S, D-194; D-200).

`write` stages R on a clean checkout of the release PR's content commit A,
whose two pin lines are equal: R changes only doctor's own Action pin line, to
A. It prints the commit command and never commits; a refusal leaves doctor.py
as it found it. `tag` prints the annotated tag command of a v0.12.0 or later
release, whose tag points at A and whose message names the release merge M.
`check` runs the release bridge's trusted rule on local commits, and from
v0.12.0 at the tag stage also checks the local tag before it is pushed: an
advisory pre-push and pre-tag check, not release evidence. None of them
imports or runs checkwash.
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
# The release-event capture runs release.yml from the tag's commit, with the
# release bridge and the tools it loads; the rest are the bridge's audited
# release helpers. From v0.12.0 the tag's commit is A, so before the tag is
# pushed A must hold the trusted ref's bytes of each (D-200).
CAPTURE_FILES = (".github/workflows/release.yml", "tools/pju_release_bridge.py", "tools/pju_receipt_bridge.py",
                 "tools/receipt_execution_route.py", "tools/published_release_identity.py", "tools/verdict_gate.py",
                 "tools/verify_published_source.py", "tools/qualify_zipapp.py", "tools/qualify_assertions.py",
                 "tools/assertion_contract.py", "tools/release_inventory.py")


def git(root, *args):
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    result = subprocess.run(["git", "-C", str(root), *args], env=env, capture_output=True, timeout=60)
    R.require(result.returncode == 0, "git " + " ".join(args) + " failed: " + result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def resolve(repo, rev):
    R.require(not rev.startswith("-"), "a revision cannot start with '-'")
    return git(repo, "rev-parse", "--verify", rev + "^{commit}").decode().strip()


def write(repo):
    root = Path(git(repo, "rev-parse", "--show-toplevel").decode().strip())
    R.require(git(root, "--no-optional-locks", "status", "--porcelain=v1", "--untracked-files=all") == b"",
              "the checkout is not clean; commit or remove every change first")
    action = git(root, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    raw = git(root, "cat-file", "blob", action + ":" + R.DOCTOR_PATH)
    previous, own, index = R.doctor_action_pins(raw)
    version, advertised = R.B.release_versions(root, action)
    R.require(version != advertised, f"HEAD's version {version} is the advertised release's; R belongs only to a release PR")
    R.require(own not in R.commit_parents(root, action), "HEAD already sets doctor's own Action pin to its parent; it is R")
    R.require(own == previous, "HEAD's doctor own Action pin differs from its previous pin: R is written only on a content "
              "commit whose two pin lines are equal, and after a commit that followed R, R must be dropped first")
    path = root / R.DOCTOR_PATH
    R.require(path.read_bytes() == raw, "the worktree doctor.py differs from HEAD's blob (line endings included)")
    lines = raw.split(b"\n")
    lines[index] = b'_OWN_ACTION_PIN = "' + action.encode() + b'"'
    path.write_bytes(b"\n".join(lines))
    try:
        git(root, "add", "--", R.DOCTOR_PATH)
        R.require(git(root, "diff", "--cached", "--name-only", "-z") == R.DOCTOR_PATH.encode() + b"\0"
                  and git(root, "cat-file", "blob", ":" + R.DOCTOR_PATH) == b"\n".join(lines),
                  "the staged change is not exactly doctor's own Action pin line")
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        path.write_bytes(raw)
        try:  # best effort: a failed add staged nothing
            git(root, "reset", "-q", "--", R.DOCTOR_PATH)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        raise ValueError(f"{error}; doctor.py was restored") from None
    print(f'git commit -m "release: doctor accepts its own Action pin {action}"')
    return 0


def tag_name(repo, merge):
    """The release tag of a release merge, and whether it points at the Action commit (D-200)."""
    name = "v" + R.B.release_versions(repo, merge)[0]
    return name, R.P.tag_at_action_commit(name)


def tag(repo, head, base, announced):
    current = {"stage": "tag", "head_sha": resolve(repo, head), "base_sha": resolve(repo, base)}
    name, at_action = tag_name(repo, current["head_sha"])
    R.require(at_action, f"{name} points at its release merge; only from v0.12.0 does a tag point at the Action commit")
    action = R.validate_own_action_pin(repo, current, announced=announced or R.B.ACTION_SHA)["action_commit"]
    print(f'git tag -a {name} {action} -m "CheckWash {name}" -m "Release-Merge: {current["head_sha"]}"')
    return 0


def pre_push(repo, name, current, action, main_report, trusted, remote):
    """The three local checks before a v0.12.0 or later tag is pushed (D-200)."""
    R.require(main_report is not None and trusted is not None,
              f"from v0.12.0, check --stage tag needs --main-report and --trusted ({name})")
    merge, ref = current["head_sha"], "refs/tags/" + name
    # 1. The local annotated tag points at A, which the rule found to be M^2^1
    #    with scheme S's one-line relation, and its message names M once.
    R.require(git(repo, "cat-file", "-t", ref).decode().strip() == "tag", f"the local tag {name} is not an annotated tag")
    raw = git(repo, "cat-file", "tag", ref)
    headers = [line.split(b" ", 1) for line in raw.partition(b"\n\n")[0].split(b"\n")]
    R.require([b"tag", name.encode()] in headers, f"the local tag object of {name} is not named {name}")
    tagged = resolve(repo, ref)
    R.require(tagged == action, f"the local tag {name} points at {tagged}, not at the Action commit {action}, {merge}^2^1")
    # The bridge reads the tag object's own target, so a tag of another tag
    # that peels to A would pass `^{commit}` here and fail after the push.
    R.require(headers[:2] == [[b"object", action.encode()], [b"type", b"commit"]],
              f"the local tag object of {name} does not point at the Action commit {action} itself")
    R.require(R.P.release_merge(R.P.tag_message(raw)) == merge,
              f"the local tag {name}'s message does not name the release merge {merge}")
    # 2. M is the head of the main stage's verified report and the remote's main;
    #    a test-merge commit of an open pull request also has M^2^1 = A.
    report = R.B.strict_json(Path(main_report).read_bytes())
    subject = report.get("subject") if type(report) is dict else None
    R.require(type(subject) is dict and report.get("kind") == "checkwash.pju-release-verification.v1"
              and report.get("status") == "verified" and report.get("repository") == R.REPOSITORY
              and subject.get("stage") == "main" and subject.get("head_sha") == merge
              and subject.get("base_sha") == current["base_sha"],
              "the main stage report is not a verified main report of this release merge")
    R.require(not remote.startswith("-"), "a remote cannot start with '-'")
    row = git(repo, "ls-remote", "--exit-code", remote, "refs/heads/main").decode().split()
    R.require(row == [merge, "refs/heads/main"], f"main at {remote} is not the release merge {merge}")
    # 3. The release-event capture runs at A, so A holds the trusted ref's bytes.
    trusted_commit = resolve(repo, trusted)
    differ = [path for path in CAPTURE_FILES
              if git(repo, "show", action + ":" + path) != git(repo, "show", trusted_commit + ":" + path)]
    R.require(not differ, "the Action commit differs from the trusted ref in " + ", ".join(differ))
    return {"name": name, "tag_object": git(repo, "rev-parse", "--verify", ref).decode().strip(),
            "action_commit": action, "release_merge": merge, "trusted": trusted_commit}


def check(repo, stage, head, base, pr_head, announced, main_report=None, trusted=None, remote="origin"):
    current = {"stage": stage, "head_sha": resolve(repo, head), "base_sha": resolve(repo, base)}
    result = R.validate_own_action_pin(repo, current, announced=announced or R.B.ACTION_SHA,
                                       pr_head=None if pr_head is None else resolve(repo, pr_head))
    name, at_action = tag_name(repo, current["head_sha"]) if stage == "tag" else (None, False)
    if at_action:
        result["tag"] = pre_push(repo, name, current, result["action_commit"], main_report, trusted, remote)
    else:
        R.require(main_report is None and trusted is None,
                  "--main-report and --trusted are for the tag stage of a v0.12.0 or later release")
    print(json.dumps(result, sort_keys=True))
    if not result["applies"]:
        print(f"warning: the rule does not apply at the {stage} stage, since the head's version equals its advertised "
              "version and its base's; the tag stage always applies it", file=sys.stderr)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    modes.add_parser("write", help="stage R on a clean checkout of the content commit").add_argument("--repo", default=".")
    tagging = modes.add_parser("tag", help="print the annotated tag command of a v0.12.0 or later release")
    tagging.add_argument("--repo", default=".")
    tagging.add_argument("--head", required=True, help="the release merge M")
    tagging.add_argument("--base", required=True)
    tagging.add_argument("--announced", help="previous Action pin (default: tools/pju_receipt_bridge.py ACTION_SHA)")
    rule = modes.add_parser("check", help="run the release bridge's rule on local commits (advisory)")
    rule.add_argument("--repo", default=".")
    rule.add_argument("--stage", choices=("pr", "main", "tag"), required=True)
    rule.add_argument("--head", required=True)
    rule.add_argument("--base", required=True)
    rule.add_argument("--pr-head")
    rule.add_argument("--announced", help="previous Action pin (default: tools/pju_receipt_bridge.py ACTION_SHA)")
    rule.add_argument("--main-report", help="from v0.12.0, at the tag stage: the main stage's verified report")
    rule.add_argument("--trusted", help="from v0.12.0, at the tag stage: the release chain's trusted ref")
    rule.add_argument("--remote", default="origin", help="from v0.12.0, at the tag stage: the remote whose main is M")
    args = parser.parse_args(argv)
    try:
        if args.mode == "write":
            return write(args.repo)
        if args.mode == "tag":
            return tag(args.repo, args.head, args.base, args.announced)
        return check(args.repo, args.stage, args.head, args.base, args.pr_head, args.announced,
                     args.main_report, args.trusted, args.remote)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print("refused: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
