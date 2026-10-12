#!/usr/bin/env python3
"""Fail-closed identity check for a real published Git source.

No Checkwash imports, product execution, local/private-tag fallback, or skip.
The development suite exercises this same validator with owned Git remotes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib

PUBLIC_SURFACES = ("src/", "pyproject.toml", "action/", ".pre-commit-hooks.yaml")
SHA = re.compile(r"[0-9a-f]{40}\Z")
TAG = re.compile(r"v(\d+\.\d+\.\d+)\Z")


def require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def git(repo: Path, *args: str) -> bytes:
    process = subprocess.run(
        ["git", "--no-replace-objects", "--no-pager", "-c", "core.fsmonitor=false",
         "-C", str(repo), *args], capture_output=True, timeout=120,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"git {args[0]} failed ({process.returncode}): "
            + process.stderr.decode("utf-8", "replace").strip()
        )
    return process.stdout


def oid(repo: Path, ref: str) -> str:
    result = git(repo, "rev-parse", "--verify", ref).decode("ascii").strip()
    require(SHA.fullmatch(result), f"invalid or missing object identity: {ref}")
    return result


def advertised(path: Path) -> dict:
    manifest = tomllib.loads(path.read_text(encoding="utf-8"))
    require(manifest["schema_version"] == 1, "unsupported advertised manifest schema")
    release = manifest["release"]
    require(TAG.fullmatch(release["tag"]), "invalid advertised tag")
    require(release["version"] == release["tag"][1:], "advertised tag/version mismatch")
    require(SHA.fullmatch(release["commit"]), "invalid advertised commit")
    require(SHA.fullmatch(release["tag_object"]), "invalid advertised tag object")
    require(release["repository"] == "https://github.com/taipei49314/checkwash.git",
            "advertised repository differs from this project")
    pyz = manifest["pyz"]
    require(pyz["url"] == "https://github.com/taipei49314/checkwash/releases/download/"
            + release["tag"] + "/checkwash.pyz", "advertised download differs from tag")
    require(re.fullmatch(r"[0-9a-f]{64}", pyz["sha256"]), "invalid advertised pyz digest")
    require(type(pyz["bytes"]) is int and pyz["bytes"] > 0, "invalid advertised pyz size")
    return manifest


def verify(repo: Path, *, tag: str, expected_commit: str, source_sha: str,
           remote: str, expected_tag_object: str | None = None) -> dict:
    receipt = dict(
        schema_version=1, status="failed", tag=tag, expected_commit=expected_commit,
        expected_source_commit=source_sha, source_commit=None, source_tree=None,
        tag_object=None, tag_commit=None, remote=remote, remote_tag_object=None,
        remote_tag_commit=None, public_surfaces=list(PUBLIC_SURFACES), errors=[],
        validator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        run_id=os.environ.get("GITHUB_RUN_ID"), attempt=os.environ.get("GITHUB_RUN_ATTEMPT"),
    )
    try:
        require(TAG.fullmatch(tag), "invalid release tag")
        require(SHA.fullmatch(expected_commit), "invalid expected release commit")
        require(SHA.fullmatch(source_sha), "invalid expected source commit")
        require(bool(remote) and not remote.startswith("-"), "explicit remote required")
        if expected_tag_object is not None:
            require(SHA.fullmatch(expected_tag_object), "invalid expected tag object")
        repo = repo.resolve(strict=True)
        receipt["source_commit"] = oid(repo, "HEAD^{commit}")
        receipt["source_tree"] = oid(repo, "HEAD^{tree}")
        require(receipt["source_commit"] == source_sha, "checkout does not match expected source")
        ref = "refs/tags/" + tag
        receipt["tag_object"] = oid(repo, ref)
        receipt["tag_commit"] = oid(repo, ref + "^{commit}")
        require(receipt["tag_commit"] == expected_commit, "local tag points to wrong commit")
        if expected_tag_object is not None:
            require(receipt["tag_object"] == expected_tag_object, "local tag object differs")

        # No empty-stdout equality: the public native tag must actually exist.
        records: dict[str, str] = {}
        raw = git(repo, "ls-remote", "--exit-code", "--", remote, ref, ref + "^{}")
        for line in raw.decode("ascii").splitlines():
            fields = line.split("\t")
            require(len(fields) == 2 and fields[1] in (ref, ref + "^{}")
                    and SHA.fullmatch(fields[0]), "malformed remote tag identity")
            require(fields[1] not in records, "duplicate remote tag identity")
            records[fields[1]] = fields[0]
        require(ref in records, "remote tag absent")
        receipt["remote_tag_object"] = records[ref]
        receipt["remote_tag_commit"] = records.get(ref + "^{}", records[ref])
        require(receipt["remote_tag_object"] == receipt["tag_object"], "remote tag object differs")
        require(receipt["remote_tag_commit"] == expected_commit, "remote tag commit differs")

        for commit in {source_sha, expected_commit}:
            project = tomllib.loads(git(repo, "show", commit + ":pyproject.toml").decode("utf-8"))
            require(project["project"]["version"] == tag[1:], "source version differs from tag")
            init = git(repo, "show", commit + ":src/checkwash/__init__.py").decode("utf-8")
            versions = re.findall(r'^__version__\s*=\s*[\"\']([^\"\']+)[\"\']\s*$', init, re.M)
            require(versions == [tag[1:]], "runtime version differs from tag")
            for surface in PUBLIC_SURFACES:
                require(bool(git(repo, "ls-tree", commit, "--", surface.rstrip("/"))),
                        "missing public surface: " + surface)
        # All Action runtime files are covered, including newly added drivers.
        git(repo, "diff", "--exit-code", "--no-ext-diff", "--no-textconv",
            expected_commit, source_sha, "--", *PUBLIC_SURFACES)
        require(not git(repo, "status", "--porcelain=v1", "--untracked-files=all",
                        "--ignored=matching", "--", *PUBLIC_SURFACES),
                "dirty or untracked public surface")
        receipt["status"] = "passed"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, RuntimeError) as error:
        receipt["errors"].append(str(error))
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--expected-commit")
    parser.add_argument("--source-sha")
    parser.add_argument("--remote")
    parser.add_argument("--expected-tag-object")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.manifest:
            require(not any((args.tag, args.expected_commit, args.remote, args.expected_tag_object)),
                    "manifest and explicit release identity are mutually exclusive")
            release = advertised(args.manifest)["release"]
            tag, commit, remote, tag_object = (release[key] for key in
                                               ("tag", "commit", "repository", "tag_object"))
        else:
            tag, commit, remote, tag_object = args.tag, args.expected_commit, args.remote, args.expected_tag_object
            require(all((tag, commit, remote, args.source_sha)), "complete explicit release identity required")
        receipt = verify(args.repo, tag=tag, expected_commit=commit,
                         source_sha=args.source_sha or commit, remote=remote,
                         expected_tag_object=tag_object)
    except (OSError, ValueError, KeyError, TypeError) as error:
        receipt = dict(schema_version=1, status="failed", errors=[str(error)])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
