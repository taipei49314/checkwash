"""Preregistered historical native/profile compatibility audit; hosted only.

This developer runner executes ONLY self-authored synthetic fixtures. Historical
distributions are never relabeled as the frozen profile versions, and native
facet agreement does not create or qualify a Checkwash historical adapter.
--prepare hashes text/manifests only; all package/engine execution is hosted.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import email
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import traceback
import urllib.parse
import urllib.request
import venv
import zipfile

CONTROL = {"coverage": "7.16.0", "ruff": "0.16.6", "mypy": "2.3.1"}
VERSIONS = {
    "coverage": ["7.2.2", "7.3.2", "7.10.7", "7.11.0", "7.16.0"],
    "ruff": ["0.1.13", "0.2.1", "0.3.5", "0.4.3", "0.4.4", "0.4.8", "0.6.8", "0.6.9", "0.9.5", "0.12.9", "0.15.10", "0.15.21", "0.15.22", "0.16.4", "0.16.6"],
    "mypy": ["1.0.1", "1.4.1", "1.6.1", "1.8.0", "2.3.1"],
}
BINDINGS = {
    "AI-02": {"mypy": ["1.8.0"]}, "AI-03": {"coverage": ["7.2.2"]},
    "AI-04": {"mypy": ["1.0.1"]}, "AI-05": {"coverage": ["7.3.2"]},
    "AI-06": {"ruff": ["0.4.3", "0.4.4"]}, "AI-07": {"ruff": ["0.6.8", "0.6.9"]},
    "AI-08": {"ruff": ["0.16.4"]}, "AI-09": {"ruff": ["0.9.5"]},
    "AI-10": {"ruff": ["0.9.5"]}, "AI-11": {"ruff": ["0.2.1", "0.4.8"]},
    "AI-12": {"coverage": ["7.10.7"]}, "AI-13": {"coverage": ["7.10.7", "7.11.0"]},
    "AI-14": {"mypy": ["1.4.1"]}, "AI-15": {"mypy": ["1.6.1", "1.8.0"]},
    "AI-16": {"ruff": ["0.1.13", "0.3.5"]}, "AI-17": {"ruff": ["0.15.21", "0.15.22"]},
    "AI-20": {"ruff": ["0.12.9", "0.15.10"]}, "AI-22": {"coverage": ["7.10.7"]},
}
CASES = {
    "coverage": ["defaults", "source-precedence-0..4", "fail-under-0-and-100", "run-branch-and-report-precision", "run-omit-none/literal/directory", "report-omit-none/literal/directory"],
    "ruff": ["rule-catalog", "preview-catalog", "default-rules", "selection-ALL/F/E/D/C4/PIE/PL/T10/FURB/D203+D211/D212+D213/D203/D213", "select-ignore-specificity-0..3", "inheritance-0..2", "source-precedence-0..2", "exclude-none/literal/directory", "extend-exclude", "nested-auto-override", "default-excludes"],
    "mypy": ["default-global-flags", "strict-expansion-map", "strict-false/true", "explicit-untyped-defs-false/true", "source-precedence-0..3", "error-code-catalog", "error-disable-assignment", "error-enable-assignment", "ignore-errors"],
}
GAPS = {
    "coverage": ["bounded synthetic behavior does not exhaust threshold/precision rounding or branch equivalence", "run/report scope universe and path normalization exhaustiveness not requalified", "harmless/interfering-key boundary exhaustiveness not requalified", "historical version profile and digest-bound qualification receipt not authored or integrated"],
    "ruff": ["catalog/default/selector differences require an exact-version profile, never substitution", "all extend/extend-select precedence and cross-directory exclusion combinations not requalified", "selector namespace completeness and version-specific incompatibility registry not independently qualified", "native default-exclusion test checks frozen promised paths, not full discovery of historical defaults", "harmless/interfering-key boundary exhaustiveness not requalified", "historical version profile and digest-bound qualification receipt not authored or integrated"],
    "mypy": ["strict/default changes require an exact-version profile, never substitution", "global flag Cartesian interactions and full enabled/disabled code semantics not requalified", "all default error codes are checked for membership, only assignment behavior exercised", "harmless/interfering-key boundary exhaustiveness not requalified", "historical version profile and digest-bound qualification receipt not authored or integrated"],
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def text_sha(path):
    return sha(Path(path).read_bytes().replace(b"\r\n", b"\n"))


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_hashes(root):
    # Freeze transitive product imports too (snapshot imports change/gitio).
    paths = list((root / "src/checkwash").rglob("*.py"))
    paths += list((root / "src/checkwash/quality/profile_data").glob("*.json"))
    paths += list((root / "src/checkwash/quality/qualification_data").glob("*"))
    paths += [root / "tools/qualify_quality.py", root / "tools/quality-profile-contract.json"]
    return {p.relative_to(root).as_posix(): text_sha(p) for p in sorted(paths) if p.is_file()}


def prepare(args):
    if args.matrix.exists():
        raise SystemExit("Preregistration exists; never overwrite immutable input")
    root = args.source.resolve()
    manifest = {
        "schema_version": 1, "status": "PREREGISTERED_BEFORE_NATIVE_RUN", "versions": VERSIONS,
        "controls": CONTROL, "bound_review_targets": BINDINGS, "unknown_exact_version_targets": ["AI-01", "AI-18", "AI-19", "AI-21"],
        "case_families": CASES, "qualification_gaps": GAPS,
        "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_hash_algorithm": "SHA256 of UTF-8 source bytes with CRLF normalized to LF; no other normalization",
        "source_sha256_lf": source_hashes(root), "runner_sha256_lf": text_sha(__file__),
        "reference_inputs": {"checkwash-context-audit-v4.json": "ff39b07f1e44c43e1f23b75a9297a0c6b98582c5be05f0fb535c3332f1804176", "checkwash-hook-bindings-v4.json": "f92574aa46763c1370864966aa34a3de91c574a36537f7535909e6e9cdfa96e5"},
        "selection": "all exact tool versions bound to declared contexts in 22 already-reviewed targets, plus 3 unchanged qualified controls; not whole-cohort mention-only pins",
        "context_caveats": ["AI-07 check.sh 0.6.8 and hook 0.6.9 are different contexts", "AI-13 coverage 7.10.7 and 7.11.0 retain both Python conditions", "AI-12/22 test-lock pins cannot be borrowed by unpinned reporting jobs", "AI-20 unrelated core-build-wheels Ruff 0.5.0 excluded", "declared-context binding is not activation evidence"],
        "execution_policy": {"platform": "Linux CPython 3.11 on GitHub-hosted runners only", "blocked_hosts": ["5I8", "PJU"], "subject_code_execution": False, "natural_predictions": False, "profile_changes": False, "release": False},
        "package_authentication": "pip isolated official PyPI wheel-only resolution; verify every dependency wheel filename+SHA256 against exact-version pypi.org JSON and METADATA Name/Version, then install local wheels with --no-index --no-deps; receipt keeps official metadata and wheel hashes",
        "decision_rules": {"MATCH": "observed native facet equals unchanged frozen current profile expectation", "DIVERGENCE": "observed native facet differs from unchanged frozen current profile expectation", "ERROR": "facet could not be measured; not evidence of incompatibility or agreement", "historical_adapter": "NOT_QUALIFIED even if every sampled native facet matches; exact-version profile and listed qualification gaps still required", "control": "current immutable adapter/profile comparison on same cases; any divergence/error must remain visible", "negative_results": "retained, never edited to pass", "natural_acceptance": "NOT_RUN"},
    }
    dump(args.matrix, manifest)
    print(json.dumps({"preregistration": str(args.matrix), "sha256": sha(args.matrix.read_bytes()), "matrix_versions": sum(map(len, VERSIONS.values()))}))


def guard():
    hosts = " ".join([socket.gethostname(), os.environ.get("COMPUTERNAME", ""), os.environ.get("RUNNER_NAME", "")]).upper()
    if any(blocked in hosts for blocked in ("5I8", "PJU")):
        raise SystemExit("Denied: designated host cannot execute qualification")
    if platform.system() != "Linux" or os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise SystemExit("Qualification execution requires GitHub-hosted Linux runner")
    if sys.version_info[:2] != (3, 11):
        raise SystemExit("Preregistered runtime is Python 3.11")


def validate_inputs(args):
    m = json.loads(args.matrix.read_text(encoding="utf-8"))
    assert m["versions"] == VERSIONS and m["case_families"] == CASES
    assert m["runner_sha256_lf"] == text_sha(__file__), "runner hash mismatch"
    assert m["source_sha256_lf"] == source_hashes(args.source.resolve()), "frozen product input hash mismatch"
    return m


def run_command(argv, cwd=None, timeout=180, env=None):
    result = subprocess.run([str(x) for x in argv], cwd=cwd, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=timeout, env=env)
    return {"argv": [str(x) for x in argv], "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def checked_command(argv, **kwargs):
    result = run_command(argv, **kwargs)
    if result["returncode"]:
        raise RuntimeError(json.dumps(result))
    return result


def fetch_json(url):
    assert urllib.parse.urlparse(url).hostname == "pypi.org"
    request = urllib.request.Request(url, headers={"User-Agent": "Checkwash-historical-synthetic-qualification/5"})
    with urllib.request.urlopen(request, timeout=60) as response:
        assert urllib.parse.urlparse(response.url).hostname == "pypi.org"
        raw = response.read()
    return json.loads(raw), raw


def install_authenticated(tool, version, temp, out):
    wheelhouse = temp / "wheelhouse"
    wheelhouse.mkdir()
    requirement = f"{tool}[toml]=={version}" if tool == "coverage" else f"{tool}=={version}"
    download = checked_command([sys.executable, "-m", "pip", "--isolated", "download", "--no-cache-dir", "--index-url", "https://pypi.org/simple", "--only-binary=:all:", "--dest", wheelhouse, requirement], timeout=600)
    dump(out / "download.json", download)
    receipts, wheel_paths, found = [], [], False
    for wheel in sorted(wheelhouse.glob("*.whl")):
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
            assert len(metadata_names) == 1
            metadata_bytes = archive.read(metadata_names[0])
            meta = email.message_from_bytes(metadata_bytes)
        name, package_version = meta["Name"], meta["Version"]
        assert name and package_version
        normalized_name = re.sub(r"[-_.]+", "-", name).lower()
        if normalized_name == tool:
            assert package_version == version, "requested tool version not downloaded"
            found = True
        url = "https://pypi.org/pypi/" + urllib.parse.quote(name, safe="") + "/" + urllib.parse.quote(package_version, safe="") + "/json"
        official, raw = fetch_json(url)
        matches = [r for r in official["urls"] if r["filename"] == wheel.name]
        assert len(matches) == 1, "wheel filename absent from exact official release metadata"
        file_record = matches[0]
        digest = sha(wheel.read_bytes())
        assert file_record["digests"]["sha256"] == digest, "official wheel hash mismatch"
        assert file_record["packagetype"] == "bdist_wheel"
        assert urllib.parse.urlparse(file_record["url"]).hostname == "files.pythonhosted.org"
        assert re.sub(r"[-_.]+", "-", official["info"]["name"]).lower() == normalized_name
        assert official["info"]["version"] == package_version
        metadata_path = out / "pypi-metadata" / f"{normalized_name}-{package_version}.json"
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_bytes(raw)
        receipts.append({"name": name, "version": package_version, "filename": wheel.name, "wheel_sha256": digest, "metadata_sha256": sha(metadata_bytes), "requires_dist": meta.get_all("Requires-Dist", []), "official_metadata_url": url, "official_metadata_sha256": sha(raw), "official_wheel_url": file_record["url"], "upload_time": file_record.get("upload_time_iso_8601"), "yanked": file_record.get("yanked", False)})
        wheel_paths.append(wheel)
    assert found and wheel_paths
    dump(out / "package-authentication.json", {"status": "ALL_WHEELS_HASH_AND_METADATA_VERIFIED", "packages": receipts})
    env_dir = temp / "venv"
    venv.EnvBuilder(with_pip=True).create(env_dir)
    python = env_dir / "bin/python"
    install = checked_command([python, "-m", "pip", "--isolated", "install", "--no-index", "--no-deps", *wheel_paths], timeout=300)
    dump(out / "install.json", install)
    dump(out / "pip-check.json", checked_command([python, "-m", "pip", "check"]))
    return python


class Facets:
    def __init__(self, args, profile):
        self.args, self.profile, self.rows = args, profile, []
        self.root = args.output / "synthetic-fixtures"
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs = args.output / "native-invocations"
        self.logs.mkdir(parents=True, exist_ok=True)
        self.counter = 0

    def fixture(self, name, files):
        root = self.root / name
        root.mkdir(parents=True, exist_ok=False)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return root

    def native(self, root, *arguments, accepted=(0, 1, 2)):
        # Cache destination is an explicitly harmless presentation/runtime key in
        # the frozen contract; avoid uploading thousands of irrelevant caches.
        cache_args = ["--cache-dir=/dev/null"] if self.args.tool == "mypy" else []
        result = run_command([sys.executable, "-m", self.args.tool, *cache_args, *arguments], cwd=root)
        self.counter += 1
        dump(self.logs / f"{self.counter:04d}.json", result)
        if result["returncode"] not in accepted:
            raise RuntimeError(json.dumps(result))
        return result

    def check(self, name, dimension, expected, observe):
        try:
            actual = observe()
            row = {"case": name, "dimension": dimension, "status": "MATCH" if actual == expected else "DIVERGENCE", "expected_from_unchanged_current_profile_or_fixture": expected, "actual_native": actual}
        except Exception as exc:
            row = {"case": name, "dimension": dimension, "status": "ERROR", "expected_from_unchanged_current_profile_or_fixture": expected, "error": repr(exc), "traceback": traceback.format_exc()}
        self.rows.append(row)

    def enabled(self, root, *args):
        result = self.native(root, "check", *args, "--show-settings", "sample.py", accepted=(0,))
        match = re.search(r"linter\.rules\.enabled\s*=\s*\[(.*?)\]", result["stdout"], re.S)
        if not match:
            raise ValueError("Native settings enabled-rules block unrecognized; raw output retained")
        return sorted(set(re.findall(r"\(([A-Z]+\d+)\)", match.group(1))))


def source_facets(f):
    from checkwash.quality.adapters import ADAPTERS
    from checkwash.quality.model import Target
    from checkwash.quality.snapshot import MappingSnapshot
    cases = {
        "coverage": [
            {".coveragerc": "[report]\nfail_under=85", "pyproject.toml": "[tool.coverage.report]\nfail_under=50"},
            {"setup.cfg": "[coverage:report]\nfail_under=85", "pyproject.toml": "[tool.coverage.report]\nfail_under=50"},
            {"tox.ini": "[coverage:report]\nfail_under=85", "pyproject.toml": "[tool.coverage.report]\nfail_under=50"},
            {"pyproject.toml": "[tool.coverage.report]\nfail_under=85"},
            {".coveragerc.toml": "[tool.coverage.report]\nfail_under=85", "pyproject.toml": "[tool.coverage.report]\nfail_under=50"}],
        "ruff": [
            {".ruff.toml": '[lint]\nselect=["F401"]', "ruff.toml": '[lint]\nselect=[]'},
            {"ruff.toml": '[lint]\nselect=["F401"]', "pyproject.toml": '[tool.ruff.lint]\nselect=[]'},
            {"pyproject.toml": '[tool.ruff.lint]\nselect=["F401"]'}],
        "mypy": [
            {"mypy.ini": "[mypy]\ndisallow_untyped_defs=true", ".mypy.ini": "[mypy]\ndisallow_untyped_defs=false"},
            {".mypy.ini": "[mypy]\ndisallow_untyped_defs=true", "pyproject.toml": "[tool.mypy]\ndisallow_untyped_defs=false"},
            {"pyproject.toml": "[tool.mypy]\ndisallow_untyped_defs=true", "setup.cfg": "[mypy]\ndisallow_untyped_defs=false"},
            {"setup.cfg": "[mypy]\ndisallow_untyped_defs=yes"}],
    }
    for i, configs in enumerate(cases[f.args.tool]):
        files = {**configs, "sample.py": "import os\n"}
        root = f.fixture(f"source-{i}", files)
        def observe():
            snapshot = MappingSnapshot({name: text.encode() for name, text in files.items()})
            target = Target("synthetic-source", f.args.tool, ".", "auto", f.profile["id"], ["sample.py"])
            modeled = ADAPTERS[f.args.tool](snapshot, target, "base", f.profile)
            previous = Path.cwd()
            try:
                os.chdir(root)
                if f.args.tool == "coverage":
                    from coverage import Coverage
                    native = Coverage(config_file=True).get_option("report:fail_under")
                    return {"native": native, "frozen_model": int(modeled.values["coverage.report.fail_under"])}
                if f.args.tool == "mypy":
                    from mypy.main import process_options
                    _, options = process_options(["sample.py"], require_targets=True)
                    return {"native": options.disallow_untyped_defs, "frozen_model": modeled.values["mypy.disallow_untyped_defs"]}
                return {"native": f.enabled(root), "frozen_model": modeled.values["ruff.lint.rules@sample.py"]}
            finally:
                os.chdir(previous)
        expected = {"coverage": 85, "mypy": True, "ruff": ["F401"]}[f.args.tool]
        f.check(f"source-precedence-{i}", "source-selection", {"native": expected, "frozen_model": expected}, observe)


def coverage_facets(f):
    from coverage import Coverage
    expected = {"run.branch": False, "run.omit": [], "report.fail_under": 0.0, "report.precision": 0, "report.omit": []}
    def defaults():
        c = Coverage(config_file=False)
        return {key: c.get_option(key.replace(".", ":", 1)) or ([] if key.endswith("omit") else c.get_option(key.replace(".", ":", 1))) for key in expected}
    f.check("defaults", "defaults", expected, defaults)
    for threshold, expected_exit in ((0, 0), (100, 2)):
        root = f.fixture(f"threshold-{threshold}", {"covered.py": "x = 1\nif x:\n    y = 2\nelse:\n    y = 3\n", "coverage.ini": f"[run]\nbranch=true\n[report]\nfail_under={threshold}\nprecision=2\n"})
        def observe():
            f.native(root, "run", "--rcfile=coverage.ini", "covered.py", accepted=(0,))
            return f.native(root, "report", "--rcfile=coverage.ini")["returncode"]
        f.check(f"fail-under-{threshold}", "coverage.report.fail_under", expected_exit, observe)
    def branch_precision():
        root = f.fixture("branch-precision", {"coverage.ini": "[run]\nbranch=true\n[report]\nprecision=2\n"})
        c = Coverage(config_file=str(root / "coverage.ini"))
        return {"run.branch": c.get_option("run:branch"), "report.precision": c.get_option("report:precision")}
    f.check("run-branch-and-report-precision", "coverage.report.fail_under-context", {"run.branch": True, "report.precision": 2}, branch_precision)
    for stage in ("run", "report"):
        for label, pattern in (("none", None), ("literal", "src/code.py"), ("directory", "src/**")):
            config = f"[{stage}]\n" + (f"omit={pattern}\n" if pattern else "")
            root = f.fixture(f"{stage}-omit-{label}", {"covered.py": "import src.code\n", "src/code.py": "x = 1\n", "coverage.ini": config})
            def observe():
                f.native(root, "run", "--rcfile=coverage.ini", "covered.py", accepted=(0,))
                f.native(root, "json", "--rcfile=coverage.ini", "-o", "coverage-result.json", accepted=(0,))
                return "src/code.py" in json.loads((root / "coverage-result.json").read_text())["files"]
            f.check(f"{stage}-omit-{label}", f"coverage.{stage}.scope", pattern is None, observe)


def ruff_facets(f):
    from checkwash.quality.adapters import selected_rules
    root = f.fixture("catalog", {"sample.py": "import os\n"})
    catalog = None
    def load_catalog():
        nonlocal catalog
        catalog = json.loads(f.native(root, "rule", "--all", "--output-format", "json", accepted=(0,))["stdout"])
        dump(f.args.output / "native-rule-catalog.json", catalog)
        def removed(row):
            status = row.get("status", {})
            return "Removed" in status if isinstance(status, (dict, str)) else False
        return sorted(r["code"] for r in catalog if isinstance(r.get("code"), str) and not removed(r))
    f.check("rule-catalog", "ruff.lint.rules-catalog", f.profile["rule_catalog"], load_catalog)
    def preview_catalog():
        if catalog is None:
            raise ValueError("catalog unavailable")
        return sorted(r["code"] for r in catalog if isinstance(r.get("code"), str) and r.get("preview", False))
    f.check("preview-catalog", "ruff.lint.rules-catalog", f.profile["preview_rules"], preview_catalog)
    f.check("default-rules", "defaults", f.profile["default_rules"], lambda: f.enabled(root, "--isolated"))
    selections = [["ALL"], ["F"], ["E"], ["D"], ["C4"], ["PIE"], ["PL"], ["T10"], ["FURB"], ["D203", "D211"], ["D212", "D213"], ["D203"], ["D213"]]
    for i, selectors in enumerate(selections):
        root = f.fixture(f"select-{i}", {"sample.py": "import os\n", "ruff.toml": "[lint]\nselect=" + json.dumps(selectors) + "\n"})
        f.check("selection-" + "+".join(selectors), "ruff.lint.rules", selected_rules(selectors, [], f.profile), lambda: f.enabled(root, "--config", "ruff.toml"))
    for i, (select, ignore, expected) in enumerate([(["F401"], [], True), (["F401"], ["F401"], False), (["F401"], ["F"], True), (["F"], ["F401"], False)]):
        root = f.fixture(f"ignore-{i}", {"sample.py": "import os\n", "ruff.toml": "[lint]\nselect=" + json.dumps(select) + "\nignore=" + json.dumps(ignore) + "\n"})
        f.check(f"select-ignore-specificity-{i}", "ruff.lint.rules", expected, lambda: "F401" in f.enabled(root, "--config", "ruff.toml"))
    for i, (child, expected) in enumerate([('extend="parent.toml"\n', True), ('extend="parent.toml"\n[lint]\nselect=[]\n', False), ('extend="parent.toml"\n[lint]\nignore=["F"]\n', False)]):
        root = f.fixture(f"inherit-{i}", {"sample.py": "import os\n", "parent.toml": '[lint]\nselect=["F401"]\n', "ruff.toml": child})
        f.check(f"inheritance-{i}", "ruff.lint.rules", expected, lambda: "F401" in f.enabled(root, "--config", "ruff.toml"))
    for label, pattern in (("none", None), ("literal", "src/code.py"), ("directory", "src/**"), ("extend-exclude", "src/**")):
        key = "extend-exclude" if label == "extend-exclude" else "exclude"
        config = (key + "=" + json.dumps([pattern]) + "\n" if pattern else "") + '[lint]\nselect=["F401"]\n'
        root = f.fixture("exclude-" + label, {"src/code.py": "import os\n", "ruff.toml": config})
        def observe():
            run = f.native(root, "check", "--config", "ruff.toml", "--output-format", "json", "src", accepted=(0, 1))
            return any(r["code"] == "F401" for r in json.loads(run["stdout"]))
        f.check("exclude-" + label, "ruff.scope", pattern is None, observe)
    root = f.fixture("nested", {"ruff.toml": '[lint]\nselect=["F401"]\n', "src/ruff.toml": "[lint]\nselect=[]\n", "src/code.py": "import os\n"})
    f.check("nested-auto-override", "source-selection", [], lambda: json.loads(f.native(root, "check", "--output-format", "json", "src", accepted=(0, 1))["stdout"]))
    root = f.fixture("default-excludes", {name + "/code.py": "import os\n" for name in f.profile["default_excludes"]})
    f.check("default-excludes", "ruff.scope", [], lambda: sorted(r["filename"] for r in json.loads(f.native(root, "check", "--isolated", "--output-format", "json", ".", accepted=(0, 1))["stdout"])))


def mypy_facets(f):
    from mypy.main import define_options, process_options
    from mypy.options import Options
    from mypy.errorcodes import error_codes
    flags = {**f.profile["mypy_defaults"], "strict_optional": True, "ignore_errors": False, "ignore_missing_imports": False}
    f.check("default-global-flags", "defaults", flags, lambda: {name: getattr(Options(), name, "ATTRIBUTE_ABSENT") for name in flags})
    f.check("strict-expansion-map", "mypy.global_flags", f.profile["strict_expansion"], lambda: dict(define_options()[2]))
    for strict in (False, True):
        root = f.fixture("strict-" + str(strict), {"mypy.ini": "[mypy]\nstrict=" + str(strict).lower() + "\n", "sample.py": "def f(x):\n    return x\n"})
        def observe():
            _, options = process_options(["--config-file", str(root / "mypy.ini"), str(root / "sample.py")])
            return {name: getattr(options, name, "ATTRIBUTE_ABSENT") for name in f.profile["strict_expansion"]}
        expected = f.profile["strict_expansion"] if strict else f.profile["mypy_defaults"]
        f.check("strict-" + str(strict).lower(), "mypy.global_flags", expected, observe)
    for enabled in (False, True):
        root = f.fixture("untyped-" + str(enabled), {"mypy.ini": "[mypy]\ndisallow_untyped_defs=" + str(enabled).lower() + "\n", "sample.py": "def f(x):\n    return x\n"})
        f.check("explicit-untyped-defs-" + str(enabled).lower(), "mypy.global_flags", enabled, lambda: "no-untyped-def" in f.native(root, "--config-file", "mypy.ini", "--show-error-codes", "sample.py", accepted=(0, 1))["stdout"])
    promised_codes = f.profile["defaults"]["error_codes"]
    f.check("error-code-catalog", "mypy.error_codes", {c: True for c in promised_codes}, lambda: {c: c in error_codes for c in promised_codes})
    dump(f.args.output / "native-error-code-catalog.json", sorted(error_codes))
    for name, config, expected in [("disable-assignment", "disable_error_code=assignment\n", False), ("enable-assignment", "disable_error_code=assignment\nenable_error_code=assignment\n", True), ("ignore-errors", "ignore_errors=true\n", False)]:
        root = f.fixture("error-" + name, {"mypy.ini": "[mypy]\n" + config, "sample.py": 'x: int = "bad"\n'})
        f.check("error-" + name, "mypy.error_codes", expected, lambda: "[assignment]" in f.native(root, "--config-file", "mypy.ini", "--show-error-codes", "sample.py", accepted=(0, 1))["stdout"])


def worker(args):
    guard()
    validate_inputs(args)
    assert args.version in VERSIONS[args.tool]
    assert importlib.metadata.version(args.tool) == args.version
    sys.path.insert(0, str(args.source.resolve() / "src"))
    profile_path = args.source / "src/checkwash/quality/profile_data" / (args.tool + ".json")
    profile = json.loads(profile_path.read_text())
    assert profile["tool_version"] == CONTROL[args.tool]
    facets = Facets(args, profile)
    fatal = None
    try:
        {"coverage": coverage_facets, "ruff": ruff_facets, "mypy": mypy_facets}[args.tool](facets)
        source_facets(facets)
    except Exception:
        fatal = traceback.format_exc()
    summary = dict(collections.Counter(row["status"] for row in facets.rows))
    is_control = args.version == CONTROL[args.tool]
    mismatches = [r["case"] for r in facets.rows if r["status"] != "MATCH"]
    dimensions = {d: dict(collections.Counter(r["status"] for r in facets.rows if r["dimension"] == d)) for d in sorted({r["dimension"] for r in facets.rows})}
    receipt = {
        "schema_version": 1, "tool": args.tool, "tool_version": args.version, "role": "CONTROL" if is_control else "HISTORICAL",
        "observed_installed_version": importlib.metadata.version(args.tool), "unchanged_comparator_profile_id": profile["id"], "unchanged_comparator_profile_digest": profile["digest"],
        "comparison_semantics": "historical native behavior versus frozen current-profile promises; frozen ID/version retained verbatim, not a historical-profile substitution",
        "native_facet_status": "INCOMPLETE" if fatal or summary.get("ERROR") else "DIVERGENCES_OBSERVED" if summary.get("DIVERGENCE") else "SAMPLED_FACETS_MATCH",
        "adapter_qualification_status": ("EXISTING_QUALIFIED_PROFILE_CONTROL_MATCH" if not mismatches and not fatal else "CONTROL_REVIEW_REQUIRED") if is_control else "NOT_QUALIFIED",
        "new_historical_profiles_created": 0, "qualification_gaps": [] if is_control and not mismatches and not fatal else GAPS[args.tool],
        "summary": summary, "dimension_summary": dimensions, "nonmatching_cases": mismatches, "results": facets.rows, "fatal_error": fatal,
        "preregistration_sha256": sha(args.matrix.read_bytes()), "runner_sha256_lf": text_sha(__file__),
        "runtime": {"python": sys.version, "platform": platform.platform(), "hostname": socket.gethostname(), "github_run_id": os.environ.get("GITHUB_RUN_ID"), "github_sha": os.environ.get("GITHUB_SHA"), "runner_environment": os.environ.get("RUNNER_ENVIRONMENT")},
        "subject_execution": False, "natural_predictions": False, "natural_acceptance": "NOT_RUN", "release": False,
    }
    dump(args.output / "result.json", receipt)


def orchestrate(args):
    guard()
    validate_inputs(args)
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for version in VERSIONS[args.tool]:
        out = args.output / (args.tool + "-" + version)
        out.mkdir(exist_ok=False)
        print(f"START {args.tool} {version}", flush=True)
        try:
            with tempfile.TemporaryDirectory(prefix="checkwash-historical-") as temp:
                python = install_authenticated(args.tool, version, Path(temp), out)
                worker_run = run_command([python, "-I", Path(__file__).resolve(), "--worker", "--tool", args.tool, "--version", version, "--matrix", args.matrix.resolve(), "--source", args.source.resolve(), "--output", out.resolve()], timeout=600)
                dump(out / "worker-process.json", worker_run)
                if worker_run["returncode"] or not (out / "result.json").exists():
                    raise RuntimeError("Worker failed: " + json.dumps(worker_run))
            row = json.loads((out / "result.json").read_text())
        except Exception:
            row = {"tool": args.tool, "tool_version": version, "role": "CONTROL" if version == CONTROL[args.tool] else "HISTORICAL", "native_facet_status": "INSTALL_OR_WORKER_UNAVAILABLE", "adapter_qualification_status": "UNKNOWN", "error": traceback.format_exc(), "natural_acceptance": "NOT_RUN", "release": False}
            dump(out / "result.json", row)
        results.append(row)
        print(json.dumps({k: row.get(k) for k in ("tool", "tool_version", "native_facet_status", "adapter_qualification_status", "summary")}), flush=True)
    dump(args.output / "matrix-result.json", {"schema_version": 1, "tool": args.tool, "status": "EXECUTION_COMPLETED_RESULTS_RETAINED", "preregistration_sha256": sha(args.matrix.read_bytes()), "results": results, "new_historical_profiles_created": 0, "natural_acceptance": "NOT_RUN", "release": False})
    manifest = {p.relative_to(args.output).as_posix(): sha(p.read_bytes()) for p in sorted(args.output.rglob("*")) if p.is_file() and not any(part in {".mypy_cache", ".ruff_cache", "__pycache__"} for part in p.parts)}
    dump(args.output / "artifact-manifest.json", manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--tool", choices=list(VERSIONS))
    parser.add_argument("--version")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    args.source = args.source.resolve()
    args.matrix = args.matrix.resolve()
    if args.output:
        args.output = args.output.resolve()
    if args.prepare:
        prepare(args)
    else:
        if not args.tool or not args.output:
            parser.error("--tool and --output required for hosted execution")
        if args.worker:
            worker(args)
        else:
            orchestrate(args)


if __name__ == "__main__":
    main()
