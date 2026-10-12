"""Record remote build bytes against immutable Git source; execute no corpus code."""
from __future__ import annotations

import argparse
import configparser
from collections import Counter
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import subprocess
import tarfile
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUILDER_ROOT = ROOT
ENTRY = b"# -*- coding: utf-8 -*-\nimport checkwash.zipapp_entry\ncheckwash.zipapp_entry.run()\n"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def git(*args):
    result = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, timeout=120)
    require(result.returncode == 0, "Git inventory command failed: " + repr(args))
    return result.stdout


def safe_name(name):
    path = PurePosixPath(name)
    require(bool(name) and bool(path.parts) and not path.is_absolute() and ".." not in path.parts and "\\" not in name and ":" not in name,
            "unsafe archive member")


def source_inventory(source):
    require(git("rev-parse", "HEAD").decode().strip() == source, "source SHA mismatch")
    require(not git("diff", "HEAD", "--", "src", "pyproject.toml"), "modified product source")
    entries, proof = {}, {}
    for row in git("ls-tree", "-r", "-z", source + ":src").split(b"\0"):
        if not row:
            continue
        header, path = row.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        name = path.decode("utf-8")
        safe_name(name)
        require(mode in ("100644", "100755") and kind == "blob", "nonregular source member")
        raw = git("cat-file", "blob", oid)
        actual_oid = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        require(actual_oid == oid and (ROOT / "src" / name).read_bytes() == raw, "source bytes mismatch")
        entries[name] = raw
        proof[name] = dict(git_blob=oid, sha256=sha256(raw), bytes=len(raw))
    require(bool(entries), "empty source inventory")
    return entries, proof


def metadata_identity(raw, project):
    metadata = BytesParser().parsebytes(raw)
    for name, expected in (("Name", project["name"]), ("Version", project["version"]),
                           ("Requires-Python", project["requires-python"])):
        require(metadata.get_all(name, []) == [expected], "distribution metadata identity differs: " + name)
    expected_deps = list(project["dependencies"])
    expected_deps.extend(item + "; extra == '" + extra + "'" for extra, items in project.get("optional-dependencies", {}).items() for item in items)
    def normalize(value):
        return re.sub(r"\s+", "", value).replace('"', "'").lower()
    require(Counter(map(normalize, metadata.get_all("Requires-Dist", []))) == Counter(map(normalize, expected_deps)),
            "distribution dependencies differ from source")
    require(Counter(metadata.get_all("Provides-Extra", [])) == Counter(project.get("optional-dependencies", {}).keys()),
            "distribution extras differ from source")


def archive_inventory(path, source):
    if path.suffix == ".pyz" or path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            require(len(names) == len(set(names)), "duplicate archive member")
            for item in infos:
                safe_name(item.filename)
                require((item.external_attr >> 16) & 0o170000 != 0o120000, "archive symlink")
                require(not item.flag_bits & 1, "encrypted ZIP unsupported")
            contents = {item.filename: archive.read(item) for item in infos if not item.is_dir()}
        if path.suffix == ".pyz":
            require(set(contents) == set(source) | {"__main__.py"}, "pyz member set differs from Git")
            require(contents["__main__.py"] == ENTRY, "pyz entrypoint mismatch")
            package = {name: raw for name, raw in contents.items() if name != "__main__.py"}
        else:
            package = {name: raw for name, raw in contents.items() if name.startswith("checkwash/")}
            project = tomllib.loads(git("show", "HEAD:pyproject.toml").decode("utf-8"))["project"]
            points = [raw for name, raw in contents.items() if name.endswith(".dist-info/entry_points.txt")]
            require(len(points) == 1, "wheel console entry metadata missing/ambiguous")
            config = configparser.ConfigParser(interpolation=None)
            config.optionxform = str
            config.read_string(points[0].decode("utf-8"))
            require(not config.defaults(), "unexpected wheel entry defaults")
            require(dict(config["console_scripts"]) == project["scripts"], "wheel console scripts differ from source")
            require(set(config.sections()) == {"console_scripts"}, "unexpected wheel entry group")
            metadata_prefix = project["name"].replace("-", "_") + "-" + project["version"] + ".dist-info/"
            require(all(name.startswith("checkwash/") or name.startswith(metadata_prefix) for name in contents),
                    "unexpected installable wheel member")
            metadata_identity(contents[metadata_prefix + "METADATA"], project)
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            infos = archive.getmembers()
            names = [item.name for item in infos]
            require(len(names) == len(set(names)), "duplicate sdist member")
            for item in infos:
                safe_name(item.name)
                require(item.isfile() or item.isdir(), "nonregular sdist member")
            prefixes = {PurePosixPath(name).parts[0] for name in names}
            require(len(prefixes) == 1, "sdist has multiple roots")
            contents = {item.name: archive.extractfile(item).read() for item in infos if item.isfile()}
            prefix = next(iter(prefixes)) + "/src/"
            package = {name[len(prefix):]: raw for name, raw in contents.items()
                       if name.startswith(prefix + "checkwash/")}
            archive_root = next(iter(prefixes)) + "/"
            tracked = {row.split(b"\t", 1)[1].decode("utf-8") for row in git("ls-tree", "-r", "HEAD").splitlines()}
            project = tomllib.loads(git("show", "HEAD:pyproject.toml").decode("utf-8"))["project"]
            require(next(iter(prefixes)) == project["name"].replace("-", "_") + "-" + project["version"], "sdist root identity differs")
            metadata_identity(contents[archive_root + "PKG-INFO"], project)
            for archive_name, raw in contents.items():
                name = archive_name[len(archive_root):]
                if name == "PKG-INFO":
                    continue
                require(name in tracked and raw == git("show", "HEAD:" + name),
                        "sdist member is not exact tracked source: " + name)
            build_paths = {"pyproject.toml", "setup.py", "setup.cfg", "MANIFEST.in"}
            if isinstance(project.get("readme"), str):
                build_paths.add(project["readme"])
            elif isinstance(project.get("readme"), dict) and "file" in project["readme"]:
                build_paths.add(project["readme"]["file"])
            if isinstance(project.get("license"), dict) and "file" in project["license"]:
                build_paths.add(project["license"]["file"])
            for name in build_paths:
                if name in tracked:
                    require(contents.get(archive_root + name) == git("show", "HEAD:" + name), "sdist build input differs from source: " + name)
                else:
                    require(archive_root + name not in contents, "untracked sdist build recipe: " + name)
    else:
        raise ValueError("unreviewed artifact format")
    expected = {name: raw for name, raw in source.items() if name.startswith("checkwash/")}
    require(package == expected, "artifact package bytes differ from Git source")
    return {name: dict(sha256=sha256(raw), bytes=len(raw)) for name, raw in sorted(contents.items())}


def main():
    global ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--distribution", choices=("source", "wheel", "pyz"), required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, action="append", default=[])
    parser.add_argument("--source-root", type=Path, default=ROOT)
    args = parser.parse_args()
    source = os.environ.get("ENGINE_SOURCE") or os.environ.get("CANDIDATE_SOURCE")
    receipt = dict(schema_version=1, status="failed", source_commit=source,
                   distribution=args.distribution, run_id=os.environ.get("GITHUB_RUN_ID"),
                   attempt=os.environ.get("GITHUB_RUN_ATTEMPT"), python=platform.python_version(),
                   builder="tools/release_inventory.py", builder_sha256=sha256(Path(__file__).read_bytes()),
                   builder_source_commit=None,
                   errors=[], artifacts=[])
    try:
        ROOT = args.source_root.resolve(strict=True)
        require(isinstance(source, str) and re.fullmatch(r"[0-9a-f]{40}", source), "expected source identity unavailable")
        builder = subprocess.run(["git", "-C", str(BUILDER_ROOT), "rev-parse", "HEAD"], capture_output=True, timeout=120)
        require(builder.returncode == 0, "builder source identity unavailable")
        receipt["builder_source_commit"] = builder.stdout.decode("ascii").strip()
        entries, proof = source_inventory(source)
        receipt.update(source_tree=git("rev-parse", source + "^{tree}").decode().strip(),
                       src_tree=git("rev-parse", source + ":src").decode().strip(), source_members=proof)
        qualification_raw = args.qualification.read_bytes()
        qualification = json.loads(qualification_raw)
        require(qualification["source_commit"] == source and qualification["status"] == "passed"
                and qualification["distribution"] == args.distribution,
                "exact-source assertion qualification did not pass")
        receipt["qualification"] = dict(path=args.qualification.name, sha256=sha256(qualification_raw))
        for artifact in args.artifact:
            raw = artifact.read_bytes()
            receipt["artifacts"].append(dict(name=artifact.name, sha256=sha256(raw), bytes=len(raw),
                                            members=archive_inventory(artifact, entries)))
        require(len(args.artifact) == {"source": 0, "wheel": 2, "pyz": 1}[args.distribution],
                "unexpected distribution artifact count")
        formats = Counter("sdist" if path.name.endswith(".tar.gz") else path.suffix for path in args.artifact)
        require(formats == {"source": Counter(), "wheel": Counter({".whl": 1, "sdist": 1}), "pyz": Counter({".pyz": 1})}[args.distribution],
                "unexpected distribution artifact format set")
        if args.distribution != "source":
            qualified = [item for item in receipt["artifacts"]
                         if item["sha256"] == qualification["artifact_sha256"]]
            require(len(qualified) == 1, "delivered artifact differs from qualification")
        receipt["status"] = "passed"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError,
            RuntimeError, IndexError, configparser.Error, zipfile.BadZipFile, tarfile.TarError) as error:
        receipt["errors"].append(repr(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: receipt[key] for key in ("status", "source_commit", "errors")}))
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
