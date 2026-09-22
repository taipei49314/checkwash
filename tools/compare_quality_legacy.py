"""Strict legacy byte comparison, plus an independent reviewed-transition report.

--release-record never waives a byte mismatch or changes the default gate.
No record is generated here: review and policy acceptance are separate work.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile

BASELINE = "387e71befedc387ab0c85af4c3322b7877a0cfd1"
_SIDES = {"baseline", "candidate"}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_FILES = {"pyproject.toml", "tools/emit_corpus.py", "tools/compare_quality_legacy.py"}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("nonfinite JSON value: " + value)


_DECODER = json.JSONDecoder(object_pairs_hook=_unique_object, parse_constant=_nonfinite)


def _load_json(data):
    return json.loads(data, object_pairs_hook=_unique_object, parse_constant=_nonfinite)


def parse_corpus(data):
    """Require every unique case header to own exactly findings JSON and IR JSON."""
    if not isinstance(data, bytes) or not data or len(data) > 128_000_000:
        raise ValueError("empty or oversized corpus artifact")
    text = data.decode("utf-8")
    cursor = 0
    cases = {}
    while cursor < len(text):
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        if cursor == len(text):
            break
        header = re.match(r"# ([^\r\n]+\.gwcase)\r?\n", text[cursor:])
        if header is None:
            raise ValueError("expected a corpus case header")
        name = header.group(1)
        if "/" in name or "\\" in name or name in cases:
            raise ValueError("unsafe or duplicate corpus case: " + name)
        cursor += header.end()
        documents = []
        for _ in range(2):
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
            value, cursor = _DECODER.raw_decode(text, cursor)
            if not isinstance(value, dict):
                raise ValueError("corpus documents must be JSON objects")
            _canonical(value)  # also rejects overflow-to-infinity numbers
            documents.append(value)
        findings, ir = documents
        if (type(findings.get("checkwash_findings_version")) is not int
                or not isinstance(findings.get("findings"), list)
                or not isinstance(findings.get("run"), dict)
                or findings.get("verdict") not in {"pass", "block"}
                or not isinstance(findings.get("summary"), dict)
                or type(ir.get("version")) is not int
                or not isinstance(ir.get("files"), list) or not isinstance(ir.get("globals"), dict)):
            raise ValueError("corpus findings/IR document pair is malformed")
        cases[name] = {"findings": findings, "ir": ir}
    if not cases:
        raise ValueError("corpus artifact contains no cases")
    return cases


def _pointer(part):
    return str(part).replace("~", "~0").replace("/", "~1")


def transition_deltas(outputs):
    """Every JSON leaf/addition/removal, typed and ordered; no field allowlist."""
    parsed = {side: parse_corpus(outputs[side]) for side in sorted(_SIDES)}
    if not parsed["baseline"].keys() <= parsed["candidate"].keys():
        raise ValueError("candidate dropped a baseline case")
    deltas = []

    def visit(case, artifact, path, before, after, present_before=True, present_after=True):
        if present_before and present_after and _canonical(before) == _canonical(after):
            return
        if present_before and present_after and isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(before.keys() | after.keys()):
                visit(case, artifact, path + "/" + _pointer(key), before.get(key), after.get(key), key in before, key in after)
            return
        if present_before and present_after and isinstance(before, list) and isinstance(after, list):
            for index in range(max(len(before), len(after))):
                visit(case, artifact, path + "/" + str(index), before[index] if index < len(before) else None,
                      after[index] if index < len(after) else None, index < len(before), index < len(after))
            return
        category = ("case_added" if not path and not present_before else
                    "version" if artifact == "findings" and path == "/run/checkwash_version" else
                    "ir_field_added" if artifact == "ir" and not present_before else "behavior")
        deltas.append({"case": case, "artifact": artifact, "path": path, "category": category,
                       "before": {"present": present_before, **({"value": before} if present_before else {})},
                       "after": {"present": present_after, **({"value": after} if present_after else {})}})

    for case in sorted(parsed["candidate"]):
        for artifact in ("findings", "ir"):
            old = parsed["baseline"].get(case)
            visit(case, artifact, "", old[artifact] if old else None, parsed["candidate"][case][artifact], old is not None)
    if not deltas and outputs["baseline"] != outputs["candidate"]:
        deltas.append({"case": None, "artifact": "bytes", "path": "", "category": "serialization",
                       "before": {"present": True, "value": _sha(outputs["baseline"])},
                       "after": {"present": True, "value": _sha(outputs["candidate"])}})
    return parsed, deltas


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def source_evidence(root, output=None):
    """Hash the clean tracked producer/source/corpus bytes actually executed."""
    root = root.resolve()
    excluded = None
    if output is not None:
        try:
            excluded = output.resolve().relative_to(root).as_posix()
        except ValueError:
            pass
    entries = []
    for record in _git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        metadata, path = record.split(b"\t", 1)
        mode, _oid, stage = metadata.decode("ascii").split()
        path = path.decode("utf-8")
        if excluded is not None and (excluded == "." or path == excluded or path.startswith(excluded + "/")):
            raise ValueError("output directory overlaps tracked repository content")
        if path in _SOURCE_FILES or path.startswith(("src/", "tests/cases/")):
            if stage != "0" or mode not in {"100644", "100755"}:
                raise ValueError("source manifest requires regular, unconflicted files")
            entries.append((path, mode))
    for record in _git(root, "status", "--porcelain=v1", "--untracked-files=all", "-z").split(b"\0"):
        if not record:
            continue
        path = record[3:].decode("utf-8")
        if record.startswith(b"?? ") and excluded and path.startswith(excluded + "/"):
            continue
        raise ValueError("release transition requires a clean checkout")
    files = {}
    corpus = {}
    for path, mode in entries:
        actual = root / path
        if actual.is_symlink() or not actual.is_file() or not actual.resolve().is_relative_to(root):
            raise ValueError("source manifest path is not a contained regular file")
        digest = _sha(actual.read_bytes())
        files[path] = {"mode": mode, "sha256": digest}
        if path.startswith("tests/cases/") and PurePosixPath(path).parent.as_posix() == "tests/cases" and path.endswith(".gwcase"):
            corpus[PurePosixPath(path).name] = digest
    if not corpus or not {"pyproject.toml", "tools/emit_corpus.py"} <= files.keys() or not any(p.startswith("src/") for p in files):
        raise ValueError("incomplete source/corpus manifest")
    return {"source_sha256": _sha(_canonical(files)), "corpus": corpus,
            "revision": _git(root, "rev-parse", "HEAD").decode("ascii").strip()}


def _review_digest(root, review):
    if not isinstance(review, dict) or set(review) != {"path", "sha256"}:
        raise ValueError("review must pin its repository path and bytes")
    path = review["path"]
    if (not isinstance(path, str) or not path or "\\" in path or ":" in path
            or PurePosixPath(path).is_absolute() or any(p in {"", ".", ".."} for p in path.split("/"))):
        raise ValueError("review path must stay inside the repository")
    root = root.resolve()
    actual = root / path
    if not actual.resolve().is_relative_to(root) or any(parent.is_symlink() for parent in (actual, *actual.parents) if parent != root):
        raise ValueError("review must be a contained regular file")
    _git(root, "ls-files", "--error-unmatch", "--", path)
    data = actual.read_bytes()
    if not data.strip() or _sha(data) != review["sha256"]:
        raise ValueError("review contents do not match their recorded hash")


def qualify_release_record(record, outputs, version, evidence, root):
    required = {"schema_version", "baseline", "release_version", "review", "sha256", "source_sha256", "corpus", "deltas"}
    if not isinstance(record, dict) or set(record) != required:
        raise ValueError("release record has missing or unknown fields")
    if (type(record["schema_version"]) is not int or record["schema_version"] != 2
            or record["baseline"] != BASELINE or record["release_version"] != version):
        raise ValueError("release record names a different schema, baseline or version")
    for field in ("sha256", "source_sha256", "corpus"):
        if not isinstance(record[field], dict) or set(record[field]) != _SIDES:
            raise ValueError("release record must pin both sides of " + field)
    parsed, actual_deltas = transition_deltas(outputs)
    for side in sorted(_SIDES):
        if (record["sha256"][side] != _sha(outputs[side])
                or record["source_sha256"][side] != evidence[side]["source_sha256"]
                or _canonical(record["corpus"][side]) != _canonical(evidence[side]["corpus"])
                or set(parsed[side]) != set(evidence[side]["corpus"])):
            raise ValueError("artifact/source/corpus identity mismatch on " + side)
        if not isinstance(record["corpus"][side], dict) or any(not isinstance(v, str) or not _HASH.fullmatch(v) for v in record["corpus"][side].values()):
            raise ValueError("corpus manifest must pin every case's bytes")
    if any(evidence["candidate"]["corpus"].get(name) != digest for name, digest in evidence["baseline"]["corpus"].items()):
        raise ValueError("candidate changed or removed an immutable baseline fixture")
    _review_digest(root, record["review"])
    if not isinstance(record["deltas"], list):
        raise ValueError("reviewed deltas must be a complete list")
    reviewed = []
    for delta in record["deltas"]:
        if not isinstance(delta, dict) or not isinstance(delta.get("reason"), str) or not delta["reason"].strip():
            raise ValueError("every exact delta needs a reviewer rationale")
        reviewed.append({key: value for key, value in delta.items() if key != "reason"})
    if _canonical(reviewed) != _canonical(actual_deltas):
        raise ValueError("reviewed delta manifest does not equal the complete observed transition")
    return {"qualified": True, "delta_count": len(actual_deltas), "review_sha256": record["review"]["sha256"]}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-record", type=Path,
                        help="Report a separately reviewed transition; never waive a byte mismatch")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    args.output.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "fetch", "--depth=1", "origin", BASELINE], cwd=root, check=True)
    with tempfile.TemporaryDirectory(prefix="quality-legacy-") as temporary:
        baseline = Path(temporary) / "baseline"
        subprocess.run(["git", "worktree", "add", "--detach", str(baseline), BASELINE], cwd=root, check=True)
        try:
            outputs = {}
            evidence = {}
            transition = {"requested": args.release_record is not None, "qualified": False}
            for name, checkout in [("baseline", baseline), ("candidate", root)]:
                if args.release_record is not None:
                    try:
                        evidence[name] = source_evidence(checkout, args.output if name == "candidate" else None)
                    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
                        transition["error"] = str(exc)
                result = subprocess.run([sys.executable, str(checkout / "tools/emit_corpus.py")], cwd=checkout,
                                        env={**os.environ, "PYTHONUTF8": "1"}, capture_output=True, check=True)
                outputs[name] = result.stdout
                (args.output / ("legacy-" + name + ".json")).write_bytes(result.stdout)
                if name in evidence:
                    try:
                        if evidence[name] != source_evidence(checkout, args.output if name == "candidate" else None):
                            raise ValueError("source changed while emitting the corpus")
                    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
                        transition["error"] = str(exc)
            if args.release_record is not None and "error" not in transition:
                try:
                    import tomllib
                    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
                    record_data = args.release_record.read_bytes()
                    record = _load_json(record_data.decode("utf-8"))
                    transition.update(qualify_release_record(record, outputs, version, evidence, root))
                    transition["record_sha256"] = _sha(record_data)
                except (ValueError, OSError, KeyError, TypeError, RecursionError, subprocess.CalledProcessError) as exc:
                    transition["error"] = str(exc)
            identical = outputs["baseline"] == outputs["candidate"]
            observed = {"status": "unreviewed", "baseline": BASELINE,
                        "sha256": {key: _sha(value) for key, value in outputs.items()}}
            try:
                parsed, deltas = transition_deltas(outputs)
                observed["case_counts"] = {side: len(cases) for side, cases in parsed.items()}
                observed["deltas"] = deltas
            except (ValueError, TypeError, RecursionError) as exc:
                observed["status"] = "invalid"
                observed["error"] = str(exc)
            (args.output / "legacy-observed-transition.json").write_text(
                json.dumps(observed, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            receipt = {"baseline": BASELINE, "byte_identical": identical,
                       "byte_comparison_status": "pass" if identical else "fail",
                       "release_record": str(args.release_record) if args.release_record else None,
                       "transition_qualification": transition, "source_evidence": evidence,
                       "observed_transition": "legacy-observed-transition.json",
                       "sha256": {key: _sha(value) for key, value in outputs.items()}}
            (args.output / "legacy-comparison.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(receipt, sort_keys=True))
            if not identical:
                print("Legacy findings/IR byte comparison failed; transition qualification does not waive this gate.", file=sys.stderr)
            return 0 if identical and (not transition["requested"] or transition["qualified"]) else 1
        finally:
            subprocess.run(["git", "worktree", "remove", str(baseline)], cwd=root, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
