"""Exact, bounded downstream consumer probes; hosted orchestration is separate.

This is an assertion runner, not an engine/process capture replacement. Inputs
must come from the reviewed automatic-PR capture protocol in DESIGN.md. A zero
exit proves only these consumer assertions on the supplied bound bytes.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sys
import traceback
from unittest.mock import patch

SMALLESTLIE_COMMIT = "e7c3b243da39e26856b10f6a6df1f2eee6b38ecb"
CORPUS_COMMIT = "86ffe1560d72356f6e59a032d1c84c061753c06a"
PIN_VERSION = "0.6.0"
PIN_SOURCE = "8c70efbf93975bf3210acb8eafbaf4b38044a770"
PIN_SHA256 = "4f9c7b836d1e1c40dc0a7b88ef6d63f25d482c8eafda18c05eb5a4fbac9ad949"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def verified_file(root, row):
    path = (root / row["path"]).resolve(strict=True)
    require(path.is_relative_to(root) and path.is_file(), "input escapes its artifact root")
    require(sha(path) == row["sha256"], "input byte identity mismatch: " + row["path"])
    return path


def verify_consumers(root, manifest):
    require(manifest["commits"] == {"smallestlie": SMALLESTLIE_COMMIT, "corpus": CORPUS_COMMIT},
            "consumer commit changed")
    for row in manifest["files"]:
        path = verified_file(root, row)
        raw = path.read_bytes()
        require(len(raw) == row["bytes"] and
                hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest() == row["git_blob"],
                "consumer Git blob/size mismatch")


def raw_capture(root, row):
    receipt = load(verified_file(root, row["observation"]))
    require(receipt["status"] == "EXITED" and receipt["capture_complete"]
            and receipt["cleanup_complete"] and not receipt["capture_errors"]
            and receipt["exit_code"] == row["expected_exit"], "capture is incomplete or exit changed")
    output = {}
    for name in ("stdout", "stderr"):
        path = verified_file(root, row[name])
        raw = path.read_bytes()
        stream = receipt["streams"][name]
        require(stream["sha256"] == sha(path) and stream["bytes"] == len(raw)
                and stream["observed_bytes"] == len(raw) and stream["retained_bytes"] == len(raw),
                "raw stream differs from original capture")
        output[name] = raw.decode("utf-8", errors="strict")
    require(receipt["argv"] == row["argv"], "capture command identity mismatch")
    return receipt, output


def artifact(root, row):
    path = verified_file(root, row)
    require(path.name == "checkwash.pyz", "explicitly named pyz required")
    return path


def smallestlie(args, request, result):
    # Normal package imports: original initializers and real model classes.
    sys.path.insert(0, str(args.consumers / "smallestlie/src"))
    from smallestlie.adapters import checkwash as consumer
    from smallestlie.sandbox.executor import ExecutionResult
    import yaml

    require(yaml.__version__ == "6.0.2", "hosted dependency must be PyYAML 6.0.2")
    require((consumer.PINNED_VERSION, consumer.PINNED_SOURCE_REVISION, consumer.PINNED_SHA256)
            == (PIN_VERSION, PIN_SOURCE, PIN_SHA256), "original consumer pin changed")
    published = artifact(args.inputs, request["published_pyz"])
    candidate = artifact(args.inputs, request["candidate_pyz"])
    require(sha(published) == PIN_SHA256 and sha(candidate) != PIN_SHA256,
            "published positive/candidate negative pin controls are not distinct")
    original = consumer.CheckwashAdapter()
    with patch.dict(os.environ, {"CHECKWASH_PYZ": str(published)}):
        require(consumer.verify_engine_pin() == published, "original artifact positive control failed")
    with patch.dict(os.environ, {"CHECKWASH_PYZ": str(candidate)}):
        try:
            consumer.verify_engine_pin()
        except consumer.EnginePinError as error:
            result["pin_negative"] = {"class": type(error).__name__, "message": str(error)}
        else:
            raise ValueError("unchanged artifact pin accepted candidate")
    result["pin_positive"] = {"sha256": sha(published), "source_commit": PIN_SOURCE}
    result["captures"] = []
    expected_ids = {f"{arm}/{case}" for arm in ("source", "wheel", "pyz", "published-pyz")
                    for case in ("clean", "weakened", "invalid-ref")}
    require(len(request["captures"]) == 12 and {r["id"] for r in request["captures"]} == expected_ids,
            "exact 12-cell distribution/case accounting required")
    seeds = {}
    for row in request["captures"]:
        observation, raw = raw_capture(args.inputs, row)
        expected_exit = {"clean": 0, "weakened": 1, "invalid-ref": 2}[row["id"].split("/")[1]]
        require(row["expected_exit"] == expected_exit, "owned control exit expectation changed")
        execution = ExecutionResult("owned-json", row["argv"], row["cwd"], observation["exit_code"],
                                    raw["stdout"], raw["stderr"], execution_binding=request["binding"])
        unchanged = original.read_verdict(args.inputs, execution).to_dict()
        # An INSTANCE attribute is the sole test override. Source/class/pin stay intact.
        candidate_decoder = consumer.CheckwashAdapter()
        candidate_decoder.engine_version = row["expected_version"]
        decoded = candidate_decoder.read_verdict(args.inputs, execution).to_dict()
        record = {"id": row["id"], "unchanged_pin": unchanged,
                  "test_only_decoder_version": row["expected_version"], "test_only_decoding": decoded}
        result["captures"].append(record)
        if expected_exit == 2:
            require(decoded["raw_status"] == "EXECUTION_INCOMPLETE"
                    and decoded["execution_error"] == "unexpected_exit_code:2"
                    and unchanged == decoded, "exit 2 became an ordinary verdict")
            continue
        payload = consumer._parse_findings_json(raw["stdout"])
        require(not raw["stderr"] and payload["run"]["base"] == row["base"]
                and payload["run"]["head"] == row["head"]
                and payload["run"]["checkwash_version"] == row["expected_version"], "CLI refs/version/stderr differ")
        require(payload["skipped_files"] == [] and payload["config_errors"] == [], "owned input unexpectedly skipped/errored")
        require(decoded["execution_error"] is None and decoded["raw"]["findings_payload"] == payload
                and decoded["accepted"] == (expected_exit == 0)
                and decoded["channels"]["report_accepted"] == (expected_exit == 0), "real decoder contract changed")
        if row["id"].startswith("published-pyz/"):
            require(row["expected_version"] == PIN_VERSION and unchanged == decoded, "published decoder positive failed")
            seeds[row["id"].split("/")[1]] = payload
        else:
            require(row["expected_version"] != PIN_VERSION and not unchanged["accepted"]
                    and unchanged["execution_error"] == "invalid_findings_run", "unchanged version pin did not reject candidate")
    require(consumer.CheckwashAdapter.engine_version == PIN_VERSION, "class pin was mutated")
    synthetic_controls(consumer, ExecutionResult, seeds, args.inputs, result)
    result["imports"] = {name: str(getattr(module, "__file__", ""))
                         for name, module in sys.modules.items() if name.startswith("smallestlie")}
    require(all(Path(path).resolve().is_relative_to(args.consumers / "smallestlie/src")
                for path in result["imports"].values()), "consumer resolved outside exact source closure")


def synthetic_controls(consumer, execution_type, seeds, workspace, result):
    clean, weakened = seeds["clean"], seeds["weakened"]
    require(weakened["findings"], "negative controls need a real finding seed")
    controls = []
    result["synthetic_controls"] = controls

    def check(name, payload=None, *, text=None, exit_code=0, timeout=False, error=None,
              accepted=False, report_accepted=None, warnings=None):
        stdout = json.dumps(payload) if text is None else text
        execution = execution_type("synthetic-control", ["SYNTHETIC_NOT_EXECUTED"], str(workspace),
                                   exit_code, stdout, "", timed_out=timeout)
        value = consumer.CheckwashAdapter().read_verdict(workspace, execution).to_dict()
        controls.append(dict(id=name, synthetic_input=dict(stdout=stdout, exit_code=exit_code, timed_out=timeout), actual=value))
        require(value["execution_error"] == error and value["accepted"] == accepted,
                "synthetic decoder expectation failed: " + name)
        if error is None:
            require(value["raw"]["findings_payload"] == payload and value["channels"]["report_accepted"] == report_accepted,
                    "synthetic payload/channel preservation failed")
        if warnings is not None:
            require(value["warnings"] == warnings, "warning contract changed")

    mutations = (
        ("schema-bool", lambda p: p.update(checkwash_findings_version=True), "invalid_findings_version"),
        ("schema-missing", lambda p: p.pop("checkwash_findings_version"), "invalid_findings_version"),
        ("empty-base", lambda p: p["run"].update(base=""), "invalid_findings_run"),
        ("summary-bool", lambda p: p["summary"].update(info=False), "invalid_findings_summary"),
        ("summary-count", lambda p: p["summary"].update(info=999), "invalid_findings_summary"),
        ("skips-type", lambda p: p.update(skipped_files=[1]), "invalid_findings_skipped_files"),
        ("errors-type", lambda p: p.update(config_errors=[None]), "invalid_findings_config_errors"),
        ("verdict-unknown", lambda p: p.update(verdict="unknown"), "invalid_findings_verdict"),
    )
    for name, mutate, error in mutations:
        payload = deepcopy(clean)
        mutate(payload)
        check(name, payload, error=error)
    for field, value in (("severity", "unknown"), ("fingerprint", None), ("unit", 42),
                         ("allowlisted", 1), ("message", None), ("rule", 3), ("path", [])):
        payload = deepcopy(weakened)
        payload["findings"][0][field] = value
        check("finding-" + field, payload, error="invalid_finding")
    payload = deepcopy(weakened)
    del payload["findings"][0]["unit"]
    check("missing-unit", payload, error="invalid_finding")
    for name, text in (("malformed", "{"), ("duplicate-key", '{"a": 1, "a": 2}'),
                       ("nonstandard-number", '{"a": NaN}'), ("multiple-values", '{} {}'),
                       ("too-deep", '[' * 2000 + '0' + ']' * 2000)):
        check(name, text=text, error="invalid_findings_json")
    check("timeout", clean, timeout=True, error="timed_out")
    check("exit-two", clean, exit_code=2, error="unexpected_exit_code:2")
    check("exit-pass-report-block", weakened, accepted=True, report_accepted=False)
    check("exit-block-report-pass", clean, exit_code=1, accepted=False, report_accepted=True)
    payload = deepcopy(clean)
    payload["config_errors"] = ["synthetic-diagnostic"]
    check("config-warning", payload, accepted=True, report_accepted=True, warnings=["config_errors_present"])
    payload = deepcopy(weakened)
    payload["findings"][0]["allowlisted"] = True
    payload["findings"][0]["future_extra"] = {"retained": [1, 2]}
    payload["verdict"] = "pass"
    # Summary still counts ALL findings, including allowlisted ones.
    check("allowlisted-extra-retained", payload, accepted=True, report_accepted=True)


def exact_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "consumer file has no loader")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def corpus(args, request, result):
    resolve = exact_module("owned_corpus_resolver", args.consumers / "corpus/src/corpus/engine.py")
    consumer = exact_module("owned_corpus_stress", args.consumers / "corpus/src/corpus/stress/engine.py")
    pyz = artifact(args.inputs, request["pyz"])
    argv, resolved = resolve.resolve_engine(str(pyz), allow_dirty=False)
    result["resolver"] = dict(argv=argv, record=resolved, release_authentication=False)
    require(resolved == {"asset": "checkwash.pyz", "sha256": sha(pyz)}, "resolver identity differs")
    # Engine construction is deliberately outside judge's exception boundary.
    result["constructor_state"] = "STARTED"
    engine = consumer.Engine(pyz)
    result["constructor_state"] = "RETURNED"
    result["engine"] = engine.record()
    require(engine.version == request["expected_version"] and engine.sha256 == sha(pyz), "loaded pyz identity/version differs")
    result["checkwash_imports"] = {name: str(getattr(module, "__file__", ""))
                                  for name, module in sys.modules.items() if name == "checkwash" or name.startswith("checkwash.")}
    require(all(path.startswith(str(pyz) + os.sep) for path in result["checkwash_imports"].values()),
            "engine import escaped selected pyz")
    result["analyze_parameters"] = list(inspect.signature(engine._analyze).parameters)
    result["cases"] = []
    require([r["id"] for r in request["cases"]] == ["clean", "weakened"], "corpus case accounting differs")
    for row in request["cases"]:
        fixture = load(verified_file(args.inputs, row["fixture"]))
        before = {p: text.encode("utf-8") for p, text in fixture["before"].items()}
        after = {p: text.encode("utf-8") for p, text in fixture["after"].items()}
        changes = [(p, before.get(p), after.get(p)) for p in sorted(before.keys() | after.keys())
                   if before.get(p) != after.get(p)]
        if row["id"] == "weakened":
            require(len(changes) >= 2, "reverse-order control must not be a single FileChange")
        first, reported_equal = engine.judge_twice(changes, after, set(fixture["modules"]))
        reverse = engine.judge(changes, after, set(fixture["modules"]), reverse=True)
        observation, raw = raw_capture(args.inputs, row["cli"])
        cli = json.loads(raw["stdout"])
        require(row["cli"]["expected_exit"] == {"clean": 0, "weakened": 1}[row["id"]]
                and not raw["stderr"] and cli["skipped_files"] == [] and cli["config_errors"] == []
                and cli["run"]["checkwash_version"] == request["expected_version"]
                and cli["run"]["base"] == row["cli"]["base"] and cli["run"]["head"] == row["cli"]["head"],
                "Corpus paired CLI source/ref/version/error boundary differs")
        projection = [{key: f[key] for key in ("rule", "severity", "path", "unit", "fingerprint",
                                               "escalators", "deescalators", "message")}
                      for f in cli["findings"] if not f["allowlisted"]]
        record = dict(id=row["id"], first=vars(first), reverse=vars(reverse),
                      judge_twice_equal=reported_equal,
                      canonical_equal=first.canonical() == reverse.canonical(),
                      full_projection_equal=first.findings == reverse.findings,
                      cli_projection=projection, cli_exit=observation["exit_code"])
        result["cases"].append(record)
        require(first.error is None and reverse.error is None and first.verdict == reverse.verdict == cli["verdict"],
                "consumer API error/different verdict")
        canonical_rows = lambda rows: sorted(json.dumps(f, sort_keys=True) for f in rows)
        require(reported_equal and record["canonical_equal"] and canonical_rows(first.findings) == canonical_rows(reverse.findings)
                == canonical_rows(projection), "API/CLI finding projection differs (including message)")
    result["boundary_controls"] = []
    for error in (RuntimeError("owned analysis failure"), SystemExit(17), KeyboardInterrupt()):
        with patch.object(engine, "_analyze", side_effect=error):
            try:
                judged = engine.judge([], {}, set())
            except KeyboardInterrupt:
                require(isinstance(error, KeyboardInterrupt), "unexpected propagated exception")
                result["boundary_controls"].append(dict(type="KeyboardInterrupt", outcome="PROPAGATED"))
            else:
                require(not isinstance(error, KeyboardInterrupt) and judged.verdict == "error" and judged.error,
                        "analysis failure converted to ordinary verdict")
                result["boundary_controls"].append(dict(type=type(error).__name__, outcome=vars(judged)))
    try:
        consumer.Engine(pyz)
    except RuntimeError as error:
        require("imported before the pyz was pinned" in str(error), "wrong constructor boundary control")
        result["constructor_reentry"] = dict(outcome="RAISED_OUTSIDE_JUDGE", message=str(error))
    else:
        raise ValueError("constructor silently mixed engines")
    first = consumer.Judgement("pass", findings=[{"message": "a"}])
    second = consumer.Judgement("pass", findings=[{"message": "b"}])
    require(first.canonical() == second.canonical() and first.findings != second.findings,
            "message/canonical behavior changed")
    result["canonical_message_control"] = "MESSAGE_EXCLUDED_FROM_KEY_BUT_RETAINED_IN_PROJECTION"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("smallestlie", "corpus"))
    parser.add_argument("--consumers", type=Path, required=True)
    parser.add_argument("--closure", type=Path, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = dict(status="FAILED", purpose="BOUND_CONSUMER_ASSERTIONS_NOT_ADOPTION", mode=args.mode,
                  request_sha256=None, closure_sha256=None, errors=[])
    try:
        require(os.environ.get("GITHUB_EVENT_NAME") == "pull_request" and sys.version_info[:2] == (3, 12),
                "ordinary hosted PR / Python 3.12 required")
        args.consumers = args.consumers.resolve(strict=True)
        args.inputs = args.inputs.resolve(strict=True)
        result.update(request_sha256=sha(args.request), closure_sha256=sha(args.closure), python=sys.version,
                      interpreter=str(Path(sys.executable).absolute()))
        closure, request = load(args.closure), load(args.request)
        require(request["binding"]["run_id"] == os.environ["GITHUB_RUN_ID"]
                and request["binding"]["attempt"] == os.environ["GITHUB_RUN_ATTEMPT"]
                and request["binding"]["candidate_sha"] == os.environ["GITHUB_SHA"]
                and request["binding"]["pr_head_sha"] == os.environ["PR_HEAD_SHA"]
                and request["binding"]["pr_base_sha"] == os.environ["PR_BASE_SHA"], "request run/source binding differs")
        result["binding"] = request["binding"]
        verify_consumers(args.consumers, closure)
        try:
            {"smallestlie": smallestlie, "corpus": corpus}[args.mode](args, request, result)
        finally:
            verify_consumers(args.consumers, closure)
        result["status"] = "PASSED"
    except BaseException:
        result["errors"].append(traceback.format_exc())
    save(args.output, result)
    return 0 if result["status"] == "PASSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
