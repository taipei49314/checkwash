"""Bounded v0.9.0 public-byte and visitor receipt; run only on hosted CI.

No publishing, pin mutation, baseline rotation or product-source changes.
Expected values come from release run 39817071157/1 and its inventories.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request

COMMIT = "d6eda4f695fabb8e7d138f7a87b099d2028f0294"
TREE = "631e5fc92f2ccae1539018797c66a2f6013a46d2"
TAG_OBJECT = "60bdd18f7038d6d908ef584fedda1960815e520f"
REPOSITORY = "https://github.com/taipei49314/checkwash.git"
API = "https://api.github.com/repos/taipei49314/checkwash"
FILES = {
    "checkwash-0.9.0-py3-none-any.whl": (935522, "8810f7500301a6e31e811f9b8838b31548c78ad798db022d64b72857921ec53f"),
    "checkwash-0.9.0.tar.gz": (4393331, "718f4ecc22cb5f308a8fb4f0e2c14d1be4c2a0df6c61487b3bc413c0f48dcee9"),
    "checkwash.pyz": (914407, "7319152cdf4889df4d58b454dc63072bb2e923823e1b2ce09677e4381dbccd5c"),
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def fetch(url: str, maximum: int) -> bytes:
    headers = {"User-Agent": "checkwash-v090-publication-verification"}
    if url.startswith(API + "/") and os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as response:
        data = response.read(maximum + 1)
    require(len(data) <= maximum, "download exceeds bound: " + url)
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    receipt = dict(schema_version=1, status="running", tag="v0.9.0", commit=COMMIT,
                   tree=TREE, tag_object=TAG_OBJECT, release_run_id=39817071157,
                   release_attempt=1, context={k: os.environ.get(k, "") for k in
                   ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_REF", "GITHUB_EVENT_NAME")},
                   downloads=[], commands=[], visitors=[])

    def save() -> None:
        (out / "publication.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def command(name: str, argv: list[str], cwd: Path | None = None) -> str:
        env = {k: v for k, v in os.environ.items() if k not in
               {"GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
                "PYTHONPATH", "PYTHONHOME"}}
        env.update(PIP_CONFIG_FILE=os.devnull, PYTHONDONTWRITEBYTECODE="1")
        try:
            result = subprocess.run(argv, cwd=cwd or out, env=env, capture_output=True, timeout=240)
        except subprocess.TimeoutExpired as error:
            (out / (name + ".stdout.log")).write_bytes(error.stdout or b"")
            (out / (name + ".stderr.log")).write_bytes(error.stderr or b"")
            receipt["commands"].append(dict(name=name, argv=argv, exit=None, timed_out=True))
            save()
            raise
        (out / (name + ".stdout.log")).write_bytes(result.stdout)
        (out / (name + ".stderr.log")).write_bytes(result.stderr)
        receipt["commands"].append(dict(name=name, argv=argv, exit=result.returncode))
        save()
        require(result.returncode == 0, "command failed: " + name)
        return result.stdout.decode("utf-8")

    def metadata(name: str, url: str) -> dict:
        raw = fetch(url, 2_000_000)
        (out / (name + ".json")).write_bytes(raw)
        return json.loads(raw)

    def download(channel: str, name: str, url: str) -> Path:
        size, digest = FILES[name]
        raw = fetch(url, size)
        actual = hashlib.sha256(raw).hexdigest()
        matches = len(raw) == size and actual == digest
        receipt["downloads"].append(dict(channel=channel, name=name, url=url, bytes=len(raw), sha256=actual,
                                        status="passed" if matches else "failed"))
        save()
        require(matches, "public bytes mismatch: " + channel + "/" + name)
        destination = out / channel / name
        destination.parent.mkdir(exist_ok=True)
        destination.write_bytes(raw)
        return destination

    try:
        require(os.environ.get("GITHUB_ACTIONS") == "true", "hosted GitHub Actions required")
        require(command("source-tree", ["git", "rev-parse", "HEAD^{tree}"], source).strip() == TREE, "source tree mismatch")
        command("native-source", [sys.executable, "-I", "-B", str(source / "tools/verify_published_source.py"),
                "--repo", str(source), "--tag", "v0.9.0", "--expected-commit", COMMIT, "--source-sha", COMMIT,
                "--expected-tag-object", TAG_OBJECT, "--remote", REPOSITORY, "--output", str(out / "tag-source.json")])
        native = metadata("release-run", API + "/actions/runs/39817071157")
        require(native["event"] == "release" and native["head_sha"] == COMMIT and native["run_attempt"] == 1
                and native["status"] == "completed" and native["conclusion"] == "success", "release run identity/result mismatch")
        jobs = metadata("release-jobs", API + "/actions/runs/39817071157/jobs?per_page=100&page=1")["jobs"]
        require(all(any(j["name"] == name and j["status"] == "completed" and j["conclusion"] == "success" for j in jobs)
                    for name in ("published-source", "build", "publish-assets", "pypi")), "release job incomplete")
        release = metadata("github-release", API + "/releases/tags/v0.9.0")
        require(release["id"] == 420967755 and release["tag_name"] == "v0.9.0"
                and not release["draft"] and not release["prerelease"], "release metadata mismatch")
        require({a["name"] for a in release["assets"]} == set(FILES) and len(release["assets"]) == 3, "release asset set mismatch")
        for asset in release["assets"]:
            size, digest = FILES[asset["name"]]
            require(asset["state"] == "uploaded" and asset["size"] == size and asset["digest"] == "sha256:" + digest, "asset metadata mismatch")
            download("github", asset["name"], asset["browser_download_url"])
        pypi = metadata("pypi-version", "https://pypi.org/pypi/checkwash/0.9.0/json")
        latest = metadata("pypi-current", "https://pypi.org/pypi/checkwash/json")
        require(pypi["info"]["version"] == "0.9.0" and latest["info"]["version"] == "0.9.0", "PyPI version mismatch")
        packages = {p["filename"]: p for p in pypi["urls"]}
        require(set(packages) == set(FILES) - {"checkwash.pyz"} and len(pypi["urls"]) == 2, "PyPI asset set mismatch")
        for name, package in packages.items():
            size, digest = FILES[name]
            parsed = urllib.parse.urlsplit(package["url"])
            require(parsed.scheme == "https" and parsed.hostname == "files.pythonhosted.org", "PyPI download origin mismatch")
            require(not package["yanked"] and package["size"] == size and package["digests"]["sha256"] == digest, "PyPI metadata mismatch")
            public = download("pypi", name, package["url"])
            require(public.read_bytes() == (out / "github" / name).read_bytes(), "GitHub/PyPI bytes differ")
        installed_probe = (
            "import importlib.metadata,json,pathlib,sys;d=importlib.metadata.distribution('checkwash');"
            "assert d.version=='0.9.0';"
            "assert {p.metadata['Name'].lower() for p in importlib.metadata.distributions()} <= {'pip','setuptools','checkwash'};"
            "r={'version':d.version,'requires':d.requires,'direct_url':json.loads(d.read_text('direct_url.json'))};"
            "pathlib.Path(sys.argv[1]).write_text(json.dumps(r,sort_keys=True)+'\\n',encoding='utf-8')"
        )
        wheel = packages["checkwash-0.9.0-py3-none-any.whl"]
        installs = {
            "pypi-wheel": wheel["url"] + "#sha256=" + FILES[wheel["filename"]][1],
            "pypi-sdist": str(out / "pypi/checkwash-0.9.0.tar.gz"),
            "public-tag": "git+" + REPOSITORY + "@v0.9.0",
        }
        for channel, target in installs.items():
            venv = out / (channel + "-venv")
            command(channel + "-venv", [sys.executable, "-I", "-B", "-m", "venv", str(venv)])
            python = str(venv / "bin/python")
            command(channel + "-install", [python, "-I", "-B", "-m", "pip", "install", "--no-deps", "--no-cache-dir",
                    "--report", str(out / (channel + "-pip.json")), target])
            installed = out / (channel + "-installed.json")
            command(channel + "-identity", [python, "-I", "-B", "-c", installed_probe, str(installed)])
            # Evaluate active requirement markers; metadata also lists the
            # unselected dev extra, which is not a runtime dependency.
            command(channel + "-dependencies", [python, "-I", "-B", "-m", "pip", "check"])
            identity = json.loads(installed.read_bytes())
            if channel == "public-tag":
                require(identity["direct_url"]["vcs_info"]["commit_id"] == COMMIT, "installed tag commit mismatch")
            elif channel == "pypi-wheel":
                require(identity["direct_url"]["archive_info"]["hashes"]["sha256"] == FILES[wheel["filename"]][1], "installed wheel digest mismatch")
            elif channel == "pypi-sdist":
                require(identity["direct_url"]["archive_info"]["hashes"]["sha256"] == FILES["checkwash-0.9.0.tar.gz"][1], "installed sdist digest mismatch")
            command(channel + "-version", [python, "-I", "-B", "-m", "checkwash", "--version"])
            command(channel + "-demo", [python, "-I", "-B", "-m", "checkwash", "demo"])
            command(channel + "-check", [python, "-I", "-B", "-m", "checkwash", "check", "HEAD~1..HEAD", "--repo", str(source)])
            receipt["visitors"].append(dict(channel=channel, status="passed", identity=identity))
            save()
        command("public-pyz-qualification", [sys.executable, "-I", "-B", str(source / "tools/qualify_zipapp.py"), str(out / "github/checkwash.pyz")])
        receipt["visitors"].append(dict(channel="github-pyz", status="passed"))
        receipt["status"] = "passed"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        receipt["status"] = "failed"
        receipt["error"] = str(error)
    save()
    print(json.dumps({k: v for k, v in receipt.items() if k != "commands"}, sort_keys=True))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
