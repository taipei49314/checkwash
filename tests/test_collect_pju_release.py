"""Owned collector controls; no product suite, public requests or publication."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("collect_release", ROOT / "tools/collect_pju_release.py")
COLLECT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(COLLECT)


def encoded(value):
    return json.dumps(value, sort_keys=True).encode()


def subject(stage="main"):
    value = dict(schema_version=1, kind="checkwash.pju-release-subject.v1", stage=stage,
        repository=COLLECT.REPOSITORY, head_sha="a" * 40, base_sha="b" * 40, source_tree="c" * 40,
        tag=None if stage in ("pr", "main") else "v0.9.1", tag_object=None if stage in ("pr", "main") else "d" * 40,
        release_id=42 if stage in ("release-event", "public-visitor") else None,
        event=dict(name="release" if stage == "release-event" else "workflow_dispatch", run_id=202,
            run_attempt=1, workflow_sha="e" * 40, created_at="2020-01-01T00:00:00Z", payload_sha256="f" * 64))
    if stage == "pr":
        value["pr_number"] = 563
    return value


class Fixture:
    def __init__(self, root, stage="main"):
        self.root = root
        self.backend = COLLECT.load_backend()
        self.subject = subject(stage)
        self.payload = b'{"action":"published"}'
        self.subject["event"]["payload_sha256"] = COLLECT.digest(self.payload)
        self.parents = {name: dict(report="parents/" + name + ".json", sha256=COLLECT.digest(b'{}'), check_run_id=3)
                        for name in COLLECT.STAGES[stage]}
        self.args = SimpleNamespace(subject=root / "subject.json", subject_sha256=COLLECT.digest(encoded(self.subject)),
            event_payload=root / "event.json", parents=root / "parents.json", parents_sha256=COLLECT.digest(encoded(self.parents)),
            parent_report_root=root, release_artifacts=None, release_artifacts_sha256=None,
            advertised_source=None, verdict_baseline_source=None, action_root=root / "action",
            verdict_canary_old_source=root / "old", verdict_canary_new_source=root / "new")
        self.args.subject.write_bytes(encoded(self.subject))
        self.args.event_payload.write_bytes(self.payload)
        self.args.parents.write_bytes(encoded(self.parents))
        for name in self.parents.values():
            path = root / name["report"]
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'{}')
        self.artifacts = {"checkwash-0.9.1-py3-none-any.whl": b"owned wheel", "checkwash-0.9.1.tar.gz": b"owned sdist", "checkwash.pyz": b"owned pyz"}
        self.expected = {name: dict(bytes=len(raw), sha256=COLLECT.digest(raw)) for name, raw in self.artifacts.items()}
        if stage == "public-visitor":
            self.args.release_artifacts = root / "expected.json"
            self.args.release_artifacts.write_bytes(encoded(self.expected))
            self.args.release_artifacts_sha256 = COLLECT.digest(encoded(self.expected))

    def collection(self):
        return COLLECT.ReleaseCollection(self.args, self.backend)


class ReleaseCollectorTests(unittest.TestCase):
    def test_real_manual_main_and_tag_are_distinct_from_native_release(self):
        for stage in COLLECT.STAGES:
            value = subject(stage)
            self.assertIs(COLLECT.validate_subject(value), value)
            value["event"]["name"] = "push"
            with self.assertRaisesRegex(ValueError, "actual native event"):
                COLLECT.validate_subject(value)

    def test_bool_native_ids_and_future_event_are_rejected(self):
        for key in ("run_id", "run_attempt"):
            value = subject()
            value["event"][key] = True
            with self.assertRaises(ValueError):
                COLLECT.validate_subject(value)
        value = subject()
        value["event"]["created_at"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with self.assertRaisesRegex(ValueError, "precede"):
            COLLECT.validate_subject(value)

    def test_main_cannot_invent_tag_or_release_and_tag_cannot_invent_release(self):
        for stage, key, value in (("main", "tag", "v0.9.1"), ("main", "release_id", 42), ("tag", "release_id", 42)):
            packet = subject(stage)
            packet[key] = value
            with self.subTest(stage=stage, key=key), self.assertRaises(ValueError):
                COLLECT.validate_subject(packet)

    def test_admitted_digest_duplicate_keys_and_unsafe_parent_path_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(Path(folder))
            fixture.args.subject_sha256 = "0" * 64
            with self.assertRaisesRegex(ValueError, "digest/size"):
                fixture.collection()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            COLLECT.strict_json(b'{"stage":"main","stage":"tag"}')
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(Path(folder))
            fixture.parents["pr"]["report"] = "../other.json"
            fixture.args.parents.write_bytes(encoded(fixture.parents))
            fixture.args.parents_sha256 = COLLECT.digest(encoded(fixture.parents))
            with self.assertRaisesRegex(ValueError, "noncanonical"):
                fixture.collection()

    def test_parent_report_bytes_and_event_payload_are_not_self_admitted(self):
        for changed in ("event.json", "parents/pr.json"):
            with tempfile.TemporaryDirectory() as folder:
                fixture = Fixture(Path(folder))
                (fixture.root / changed).write_bytes(b'{"changed":true}')
                with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "digest/size"):
                    fixture.collection()

    def test_tag_report_with_raw_published_baseline_is_admitted_as_a_parent(self):
        # A real v0.10.0 tag report was 4,408,656 bytes; the old 2 MiB JSON
        # limit refused it before the release-event collection started.
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(Path(folder), "release-event")
            raw = encoded({"publication_evidence": "x" * (COLLECT.MAX_JSON + 1)})
            (fixture.root / "parents/tag.json").write_bytes(raw)
            fixture.parents["tag"]["sha256"] = COLLECT.digest(raw)
            fixture.args.parents.write_bytes(encoded(fixture.parents))
            fixture.args.parents_sha256 = COLLECT.digest(encoded(fixture.parents))
            self.assertEqual(fixture.collection().parent_files["parents/tag.json"], raw)
            (fixture.root / "parents/tag.json").write_bytes(raw + b" ")
            with self.assertRaisesRegex(ValueError, "digest/size"):
                fixture.collection()

    def test_external_authority_records_are_copied_as_data_not_self_authorized(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(Path(folder), "release-event")
            raw = b'{"status":"proposed-not-authorized"}'
            fixture.args.release_authorization = fixture.root / "authority.json"
            fixture.args.release_authorization.write_bytes(raw)
            fixture.args.release_authorization_sha256 = COLLECT.digest(raw)
            collection = fixture.collection()
            output = fixture.root / "out"
            output.mkdir()
            ctx = dict(output=output, manifest={"records": {}})
            collection.initialize(ctx)
            self.assertEqual((output / "release/release-authorization.json").read_bytes(), raw)
            self.assertNotIn("publication_authorized", ctx["manifest"])
            fixture.args.release_authorization_sha256 = None
            with self.assertRaisesRegex(ValueError, "supplied together"):
                fixture.collection()

    def test_stage_backend_never_receives_a_fake_pr(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(Path(folder), "tag")
            collection = fixture.collection()
            with patch.object(fixture.backend, "collect", return_value=7) as backend:
                self.assertEqual(collection.collect(), 7)
            args, kwargs = backend.call_args
            self.assertFalse(hasattr(args[0], "pr"))
            self.assertNotIn("pr_number", kwargs["release_context"])
            self.assertEqual(kwargs["release_context"]["subject"], fixture.subject)
            self.assertEqual(args[0].head_sha, fixture.subject["head_sha"])
            self.assertIsNone(kwargs["artifact_provider"])
            self.assertTrue(callable(kwargs["stage_preflight"]))

    def test_wrong_first_parent_is_rejected_before_stage_product_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            collection = Fixture(Path(folder)).collection()
            helpers = {path: {"sha256": "owned"} for path in
                       ("tools/verdict_gate.py", "tools/published_release_identity.py", "tools/verify_published_source.py", "tools/qualify_zipapp.py")}
            ctx = dict(source_before=helpers, trusted_before=helpers, source=Path(folder),
                       reader=SimpleNamespace(text=lambda *args: "9" * 40), project={"version": "0.9.1"})
            with self.assertRaisesRegex(ValueError, "first parent"):
                collection.preflight(ctx)

    def test_real_pr_keeps_native_number_and_does_not_require_base_as_first_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(Path(folder), "pr")
            collection = fixture.collection()
            helpers = {path: {"sha256": "owned"} for path in
                       ("tools/verdict_gate.py", "tools/published_release_identity.py", "tools/verify_published_source.py", "tools/qualify_zipapp.py")}
            def unexpected(*args):
                self.fail("PR preflight must not replace actual live base with first parent")
            context = dict(source_before=helpers, trusted_before=helpers, reader=SimpleNamespace(text=unexpected),
                manifest={"runtime": {"os": "Windows", "python_version": "3.11.9", "dependencies": {"twine": "owned"}}})
            collection.preflight(context)
            context["manifest"]["runtime"]["dependencies"] = {}
            with self.assertRaisesRegex(ValueError, "include twine"):
                collection.preflight(context)
            with patch.object(fixture.backend, "collect", return_value=0) as backend:
                self.assertEqual(collection.collect(), 0)
            self.assertEqual(backend.call_args.kwargs["release_context"]["subject"]["pr_number"], 563)
            self.assertEqual(backend.call_args.kwargs["release_context"]["parents"], {})
            self.assertFalse(hasattr(backend.call_args.args[0], "pr"))

    def test_visitor_installed_commit_cannot_be_replaced_by_matching_version(self):
        with tempfile.TemporaryDirectory() as folder:
            collection = Fixture(Path(folder), "tag").collection()
            output, scratch = Path(folder) / "out", Path(folder) / "scratch"
            output.mkdir(); scratch.mkdir()
            calls = []
            def run(name, argv, **kwargs):
                calls.append(name)
                if name == "tag-identity":
                    Path(argv[-2]).write_text(json.dumps(dict(version="0.9.1",
                        direct_url={"vcs_info": {"commit_id": "9" * 40}})))
                return b"checkwash 0.9.1\n"
            ctx = dict(run=run, output=output, scratch=scratch, py=[sys.executable, "-I", "-B", "-X", "utf8"])
            with self.assertRaisesRegex(ValueError, "tag commit differs"):
                collection.visitor(ctx, "tag", "git+" + COLLECT.PUBLIC_GIT + "@v0.9.1", "0.9.1",
                    {"src/checkwash/__init__.py": {"sha256": "0" * 64}}, source_identity="a" * 40)
            self.assertEqual(calls, ["tag-venv", "tag-install", "tag-identity"])

    def test_public_visitor_requires_external_artifact_set_and_uses_download_provider(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(Path(folder), "public-visitor")
            collection = fixture.collection()
            with patch.object(fixture.backend, "collect", return_value=0) as backend:
                self.assertEqual(collection.collect(), 0)
            self.assertTrue(callable(backend.call_args.kwargs["artifact_provider"]))
            fixture.args.release_artifacts = None
            with self.assertRaisesRegex(ValueError, "admitted release artifact"):
                fixture.collection()

    def test_artifact_set_is_exact_and_does_not_accept_boolean_size(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(Path(folder))
            self.assertEqual(COLLECT.validate_artifact_set(fixture.expected, "0.9.1"), fixture.expected)
            extra = copy.deepcopy(fixture.expected)
            extra["other.whl"] = extra["checkwash.pyz"]
            with self.assertRaises(ValueError):
                COLLECT.validate_artifact_set(extra, "0.9.1")
            fixture.expected["checkwash.pyz"]["bytes"] = True
            with self.assertRaises(ValueError):
                COLLECT.validate_artifact_set(fixture.expected, "0.9.1")

    def test_url_credentials_http_foreign_redirect_and_fragment_are_rejected(self):
        for url in ("http://pypi.org/x", "https://user:pass@pypi.org/x", "https://pypi.org.evil.test/x", "https://pypi.org/x#token"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                COLLECT.allowed_url(url, {"pypi.org"})
        handler = COLLECT.RestrictedRedirect({"github.com", "release-assets.githubusercontent.com"})
        with self.assertRaises(ValueError):
            handler.redirect_request(None, None, 302, "", {}, "https://attacker.invalid/a")

    def test_network_raw_and_digest_are_retained_even_when_bound_is_hit(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def geturl(self): return "https://pypi.org/x"
            def read(self, maximum): return b"abc"[:maximum]
        with tempfile.TemporaryDirectory() as folder:
            network = COLLECT.Network(Path(folder))
            opener = SimpleNamespace(open=lambda *a, **k: Response())
            with patch.object(COLLECT.urllib.request, "build_opener", return_value=opener):
                with self.assertRaisesRegex(ValueError, "exceeds bound"):
                    network.fetch("owned", "https://pypi.org/x", 2, origins={"pypi.org"})
            row = network.rows[0]
            self.assertEqual((Path(folder) / row["path"]).read_bytes(), b"abc")
            self.assertTrue(row["truncated"])
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["sha256"], COLLECT.digest(b"abc"))

    def test_public_bytes_come_from_both_services_not_another_local_build(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(Path(folder), "public-visitor")
            collection = fixture.collection()
            output = fixture.root / "out"
            output.mkdir()
            (output / "artifacts").mkdir()
            ctx = dict(output=output, scratch=fixture.root / "scratch", project={"version": "0.9.1"}, manifest={"records": {}})
            collection.initialize(ctx)
            release = dict(id=42, tag_name="v0.9.1", draft=False, prerelease=False, assets=[])
            pypi = dict(info={"version": "0.9.1"}, urls=[])
            for index, (name, wanted) in enumerate(fixture.expected.items()):
                release["assets"].append(dict(id=index + 1, name=name, state="uploaded", size=wanted["bytes"],
                    digest="sha256:" + wanted["sha256"], browser_download_url="https://github.com/" + COLLECT.REPOSITORY + "/releases/download/v0.9.1/" + name))
                if name != "checkwash.pyz":
                    pypi["urls"].append(dict(filename=name, size=wanted["bytes"], digests={"sha256": wanted["sha256"]},
                        url="https://files.pythonhosted.org/owned/" + name, yanked=False,
                        packagetype="bdist_wheel" if name.endswith(".whl") else "sdist"))
            def fetch(name, url, maximum, *, origins):
                raw = (encoded(release) if name == "github-release" else encoded(pypi) if name == "pypi-version"
                       else fixture.artifacts[url.rsplit("/", 1)[1]])
                path = output / "release/network" / (name + ".bin")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                collection.network.rows.append(dict(name=name, path=path.relative_to(output).as_posix(), sha256=COLLECT.digest(raw)))
                return raw
            with patch.object(collection.network, "fetch", side_effect=fetch):
                collection.public_artifacts(ctx)
            self.assertEqual(len(collection.publication["downloads"]), 5)
            # The verifier finds artifact bytes by basename across the packet.
            names = [path.name for path in output.rglob("*") if path.is_file()]
            self.assertEqual(len(names), len(set(names)))
            for item in collection.publication["downloads"]:
                if item["channel"] == "pypi":
                    self.assertTrue(item["path"].startswith("release/network/pypi-"))
                    self.assertEqual((output / item["path"]).read_bytes(), fixture.artifacts[item["name"]])
            self.assertTrue(collection.public_paths["pypi-wheel"].is_relative_to(ctx["scratch"]))
            self.assertEqual(collection.publication["status"], "failed")
            self.assertEqual(len(collection.public_paths), 5)
            for name, raw in fixture.artifacts.items():
                self.assertEqual((output / "artifacts" / name).read_bytes(), raw)
            self.assertEqual(collection.public_paths["github-wheel"].read_bytes(), collection.public_paths["pypi-wheel"].read_bytes())

    def test_mismatched_download_is_saved_but_not_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            collection = Fixture(Path(folder)).collection()
            collection.network = SimpleNamespace(fetch=lambda *a, **k: b"changed")
            destination = Path(folder) / "wrong.pyz"
            with self.assertRaisesRegex(ValueError, "public bytes mismatch"):
                collection.download({}, "owned", "https://github.com/x", dict(bytes=3, sha256=COLLECT.digest(b"old")),
                                    destination, origins={"github.com"})
            self.assertEqual(destination.read_bytes(), b"changed")

    def test_failed_final_source_check_does_not_leave_collection_completed(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Fixture(Path(folder))
            collection = fixture.collection()
            output = fixture.root / "out"
            output.mkdir()
            ctx = dict(output=output, manifest={"records": {}, "status": "failed"})
            collection.initialize(ctx)
            collection.finalize(ctx, ["source changed"])
            report = COLLECT.strict_json((output / "release/collection.json").read_bytes())
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["errors"], ["source changed"])
            self.assertIsNotNone(report["finished_at"])

    def test_verdict_tracing_preserves_nested_raw_bytes_without_executing_product(self):
        backend = COLLECT.load_backend()
        def fake_main():
            backend.subprocess.run([sys.executable, "-c", "owned"], capture_output=True)
            return 0
        result = subprocess.CompletedProcess([sys.executable, "-c", "owned"], 0, b"\xff\r\n", b"\x00")
        with tempfile.TemporaryDirectory() as folder, patch.object(sys, "argv", ["owned"]), \
                patch.object(backend.runpy, "run_path", return_value={"main": fake_main}), \
                patch.object(backend.subprocess, "run", return_value=result):
            logs = Path(folder) / "nested-verdict"
            self.assertEqual(backend.traced_worker("verdict_gate.py", logs, ["gate"]), 0)
            self.assertEqual((logs / "stdout.bin").read_bytes(), b"\xff\r\n")
            row = json.loads((logs / "commands.json").read_text())[0]
            self.assertEqual(row["stdout"]["sha256"], hashlib.sha256(b"\xff\r\n").hexdigest())
            self.assertEqual(row["exit_code"], 0)

    def test_clean_subprocess_environment_drops_caller_credentials(self):
        action = COLLECT.load_backend().load_replayer()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            system, program = root / "system", root / "program"
            for directory in (system / "System32", program / "Git/cmd", program / "Git/bin", program / "Git/usr/bin"):
                directory.mkdir(parents=True)
            with patch.dict(os.environ, {
                    "GH_TOKEN": "owned-not-secret", "OPENAI_API_KEY": "owned-not-secret", "SSH_AUTH_SOCK": "owned",
                    "PIP_INDEX_URL": "https://owned.invalid", "PYTHONPATH": "owned",
                    "SystemRoot": str(system), "ProgramFiles": str(program)}):
                env = action.clean_environment(Path(sys.executable), program / "Git/cmd/git.exe",
                                               program / "Git/bin/bash.exe", root)
                self.assertFalse({"GH_TOKEN", "OPENAI_API_KEY", "SSH_AUTH_SOCK", "PIP_INDEX_URL", "PYTHONPATH"} & env.keys())


if __name__ == "__main__":
    unittest.main()
