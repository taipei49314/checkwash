"""Owned metadata, replay and upload controls; no product/network execution."""
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pju_release_bridge_owned", ROOT / "tools/pju_release_bridge.py")
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def subject(stage):
    value = dict(schema_version=1, kind="checkwash.pju-release-subject.v1", stage=stage,
                 repository=R.REPOSITORY, head_sha="a" * 40, base_sha="b" * 40, source_tree="c" * 40,
                 tag=None if stage in ("pr", "main") else "v0.9.1",
                 tag_object=None if stage in ("pr", "main") else "d" * 40,
                 release_id=50 if stage in ("release-event", "public-visitor") else None,
                 event=dict(name="release" if stage == "release-event" else "workflow_dispatch",
                            run_id=60, run_attempt=1, workflow_sha="e" * 40,
                            created_at="2026-10-24T00:00:00Z", payload_sha256="f" * 64))
    if stage == "pr":
        value["pr_number"] = 70
    return value


def report(stage):
    value = subject(stage)
    result = dict(schema_version=1, kind="checkwash.pju-release-verification.v1", status="verified",
                  repository=R.REPOSITORY, subject=value, manifest_sha256="1" * 64,
                  receipt_commit="2" * 40, collector_source_sha="3" * 40,
                  checks=[R.context(stage)], publication_authorized=False)
    if stage == "pr":
        result.update(pr_number=value["pr_number"], head_sha=value["head_sha"], base_sha=value["base_sha"],
                      source_tree=value["source_tree"], checks=[*R.B.CONTEXTS, R.context("pr")])
    return result


class MemoryPacket:
    def __init__(self, manifest=None):
        self.manifest = manifest or {}
        self.files = {}

    def put(self, name, raw):
        self.files[name] = raw

    def put_json(self, name, value):
        self.put(name, (json.dumps(value, sort_keys=True) + "\n").encode())

    def raw(self, name):
        if name not in self.files:
            raise ValueError("unlisted evidence")
        return self.files[name]

    def json(self, name):
        return R.B.strict_json(self.raw(name))


class NativeAPI:
    def __init__(self, current):
        self.current = copy.deepcopy(current)
        self.data = {}
        self.writes, self.uploads = [], []
        self.fail_success = None
        prefix = "/repos/" + R.REPOSITORY
        self.prefix = prefix
        self.data[prefix + "/git/commits/" + current["head_sha"]] = dict(sha=current["head_sha"], tree={"sha": current["source_tree"]}, parents=[{"sha": current["base_sha"]}])
        self.data[prefix + "/git/ref/heads/main"] = dict(ref="refs/heads/main", object={"type": "commit", "sha": current["head_sha"]})
        if current["tag"] is not None:
            self.data[prefix + "/git/ref/tags/" + current["tag"]] = dict(ref="refs/tags/" + current["tag"], object={"type": "tag", "sha": current["tag_object"]})
            self.data[prefix + "/git/tags/" + current["tag_object"]] = dict(sha=current["tag_object"], tag=current["tag"], object={"type": "commit", "sha": current["head_sha"]})
        if current["release_id"] is not None:
            release = dict(id=current["release_id"], tag_name=current["tag"], draft=False, prerelease=False, published_at="2026-10-24T00:00:00Z", assets=[])
            self.data[prefix + "/releases/" + str(current["release_id"])] = release
            self.data[prefix + "/releases/tags/" + current["tag"]] = release
        if current["stage"] == "pr":
            self.data[prefix + "/pulls/" + str(current["pr_number"])] = dict(state="open", merged=False,
                head=dict(sha=current["head_sha"], repo={"full_name": R.REPOSITORY}),
                base=dict(sha=current["base_sha"], ref="main", repo={"full_name": R.REPOSITORY}))
        event = current["event"]
        self.run_path = prefix + f"/actions/runs/{event['run_id']}/attempts/{event['run_attempt']}"
        self.data[self.run_path] = dict(id=event["run_id"], run_attempt=event["run_attempt"], event=event["name"],
            head_sha=event["workflow_sha"], path=R.BOOTSTRAP_WORKFLOW if current["stage"] == "pr" else R.WORKFLOW,
            repository={"full_name": R.REPOSITORY}, actor={"login": "taipei49314"},
            triggering_actor={"login": "taipei49314"}, created_at=event["created_at"], status="completed", conclusion="success")

    def request(self, method, path, body=None):
        if method == "GET":
            if path not in self.data:
                raise ValueError("unexpected owned endpoint: " + path)
            return copy.deepcopy(self.data[path])
        self.writes.append((method, path, copy.deepcopy(body)))
        if method == "POST":
            return {"id": sum(row[0] == "POST" for row in self.writes)}
        if self.fail_success == path and body.get("conclusion") == "success":
            raise ValueError("owned partial check publication failure")
        return {"id": int(path.rsplit("/", 1)[1])}

    def binary(self, method, path, raw):
        self.uploads.append((method, path, raw))
        name = R.urllib.parse.parse_qs(R.urllib.parse.urlsplit(path).query)["name"][0]
        row = dict(id=100 + len(self.uploads), name=name, size=len(raw), state="uploaded", digest="sha256:" + R.digest(raw),
                   browser_download_url=f"https://github.com/{R.REPOSITORY}/releases/download/{self.current['tag']}/{name}")
        self.data[self.prefix + "/releases/" + str(self.current["release_id"])]["assets"].append(row)
        return row


class NativeIdentityTests(unittest.TestCase):
    def test_each_real_stage_matches_its_native_objects(self):
        for stage in R.STAGES:
            with self.subTest(stage=stage):
                self.assertEqual(R.live_subject(NativeAPI(subject(stage)), subject(stage)), stage)

    def test_pr_does_not_require_head_first_parent_to_equal_base(self):
        value = subject("pr")
        api = NativeAPI(value)
        api.data[api.prefix + "/git/commits/" + value["head_sha"]]["parents"] = [{"sha": "9" * 40}]
        self.assertEqual(R.live_subject(api, value), "pr")

    def test_stale_main_fails_even_when_qualified_tree_is_unchanged(self):
        value = subject("main")
        api = NativeAPI(value)
        api.data[api.prefix + "/git/ref/heads/main"]["object"]["sha"] = "9" * 40
        with self.assertRaisesRegex(ValueError, "stale main"):
            R.live_subject(api, value)

    def test_same_peeled_commit_does_not_allow_changed_tag_annotation(self):
        value = subject("tag")
        api = NativeAPI(value)
        api.data[api.prefix + "/git/ref/tags/" + value["tag"]]["object"]["sha"] = "9" * 40
        with self.assertRaisesRegex(ValueError, "annotated tag"):
            R.live_subject(api, value)

    def test_recreated_release_or_draft_cannot_reuse_public_evidence(self):
        for mutation in ("id", "draft"):
            with self.subTest(mutation=mutation):
                value = subject("public-visitor")
                api = NativeAPI(value)
                target = api.data[api.prefix + "/releases/tags/" + value["tag"]]
                target[mutation] = 99 if mutation == "id" else True
                with self.assertRaises(ValueError):
                    R.live_subject(api, value)

    def test_native_run_attempt_workflow_actor_and_success_are_mandatory(self):
        mutations = {"run_attempt": True, "path": ".github/workflows/unreviewed.yml", "head_sha": "9" * 40,
                     "actor": {"login": "contributor"}, "conclusion": "failure", "status": "in_progress"}
        for key, changed in mutations.items():
            with self.subTest(key=key):
                value = subject("tag")
                api = NativeAPI(value)
                api.data[api.run_path][key] = changed
                with self.assertRaises(ValueError):
                    R.live_subject(api, value)

    def test_bootstrap_workflow_is_allowed_only_for_actual_pr_stage(self):
        value = subject("main")
        api = NativeAPI(value)
        api.data[api.run_path]["path"] = R.BOOTSTRAP_WORKFLOW
        with self.assertRaises(ValueError):
            R.live_subject(api, value)

    def test_boolean_native_ids_and_noncanonical_tags_are_rejected(self):
        for mutation in ("boolean", "unicode", "leading-zero"):
            with self.subTest(mutation=mutation):
                value = subject("tag")
                if mutation == "boolean":
                    value["event"]["run_attempt"] = True
                else:
                    value["tag"] = "v０.９.１" if mutation == "unicode" else "v00.9.1"
                with self.assertRaises(ValueError):
                    R.subject(value)


class RawEvidenceTests(unittest.TestCase):
    def packet(self):
        packet = MemoryPacket({"raw_exits": [dict(name="pytest", argv=["owned-python", "-m", "pytest", "tests"], cwd="C:/owned",
            started_at="2026-10-24T00:00:01Z", finished_at="2026-10-24T00:00:02Z", duration_seconds=1.0,
            exit_code=0, timed_out=False, stdout="stdout", stderr="stderr")]})
        packet.put("stdout", b"owned raw")
        packet.put("stderr", b"")
        return packet

    def test_completed_raw_scope_is_checked(self):
        self.assertEqual(set(R.validate_exits(self.packet(), {"pytest"}, R.utc("2026-10-24T00:00:00Z"))), {"pytest"})

    def test_pre_event_failed_timeout_bool_or_missing_command_rejected(self):
        for key, value in (("started_at", "2026-10-23T23:59:59Z"), ("exit_code", 1), ("exit_code", False), ("timed_out", True)):
            with self.subTest(key=key, value=value):
                packet = self.packet()
                packet.manifest["raw_exits"][0][key] = value
                with self.assertRaises(ValueError):
                    R.validate_exits(packet, {"pytest"}, R.utc("2026-10-24T00:00:00Z"))
        with self.assertRaisesRegex(ValueError, "missing"):
            R.validate_exits(self.packet(), {"verdict-gate"}, R.utc("2026-10-24T00:00:00Z"))

    def test_nested_stream_offset_hash_and_exit_types_are_validated(self):
        packet = MemoryPacket({"subject": subject("tag")})
        packet.put("nested/stdout.bin", b"prefix-raw-suffix")
        packet.put("nested/stderr.bin", b"")
        row = dict(argv=["owned-python", "--version"], cwd="C:/owned", started_at="2026-10-24T00:00:00Z",
                   finished_at="2026-10-24T00:00:01Z", duration_seconds=1, exit_code=0, timed_out=False, error=None,
                   stdout=dict(path="stdout.bin", offset=7, bytes=3, sha256=R.digest(b"raw")),
                   stderr=dict(path="stderr.bin", offset=0, bytes=0, sha256=R.digest(b"")))
        packet.put_json("nested/commands.json", [row])
        self.assertEqual(len(R.validate_nested(packet, "nested/commands.json")), 1)
        row["stdout"]["offset"] = 8
        packet.put_json("nested/commands.json", [row])
        with self.assertRaisesRegex(ValueError, "linkage"):
            R.validate_nested(packet, "nested/commands.json")

    def test_legacy_pr_manifest_cannot_be_renamed_as_stage_evidence(self):
        packet = MemoryPacket({"kind": "checkwash.pju-receipt.v1", "pr_number": 70})
        with self.assertRaises(ValueError):
            R.validate_packet(packet, source_root="unused", trusted_root="unused", collector="3" * 40, subject_sha256="f" * 64, api=None)


class QualificationRawTests(unittest.TestCase):
    def evidence(self, mutation=None):
        packet = MemoryPacket({"subject": subject("pr"), "runtime": {"python_executable": r"C:\owned\python.exe"}})
        cases = [dict(id="keep", kind="preserving", path="a.test.js", verdict="pass", rule=None, severity=None),
                 dict(id="remove", kind="removal", path="b.test.js", verdict="block", rule="ASSERT_REMOVED", severity="high")]
        desc = dict(version="checkwash 0.9.1", cases=cases)
        source = r"C:\owned\source"
        bootstrap = "import sys; sys.path.insert(0, " + repr(str(R.PureWindowsPath(source) / "src")) + "); from checkwash.cli import main; raise SystemExit(main())"
        command = [r"C:\owned\python.exe", "-I", "-B", "-c", bootstrap]
        qa = R.load_trusted("qualify_assertions")
        rows, streams, written = [], {"stdout": b"", "stderr": b""}, []

        def add(args, exit_code, stdout, stderr=b""):
            row = dict(argv=command + args, cwd=r"C:\owned\qualification-fixture", started_at="2026-10-24T00:00:01Z",
                       finished_at="2026-10-24T00:00:02Z", duration_seconds=1.0, exit_code=exit_code, timed_out=False, error=None)
            for field, raw in (("stdout", stdout), ("stderr", stderr)):
                row[field] = dict(path=field + ".bin", offset=len(streams[field]), bytes=len(raw), sha256=R.digest(raw))
                streams[field] += raw
            rows.append(row)

        add(["--version"], 0, b"checkwash 0.9.1\n")
        for index, case in enumerate(cases):
            findings = [] if case["verdict"] == "pass" else [{key: case[key] for key in ("rule", "severity", "path")}]
            value = dict(verdict=case["verdict"], findings=findings, config_errors=[], skipped_files=[], run={"checkwash_version": "0.9.1"})
            raw = json.dumps(value).encode()
            exit_code = int(case["verdict"] == "block")
            written.append(qa.observe(R.subprocess.CompletedProcess(command, exit_code, raw.decode(), ""), case, "0.9.1"))
            if mutation == "raw-case" and index == 1:
                raw = json.dumps({**value, "verdict": "pass", "findings": []}).encode()
                exit_code = 0
            if mutation != "missing" or index == 0:
                add(["check", "HEAD~1..HEAD", "--format", "json"], exit_code, raw)
        clean = dict(verdict="pass", findings=[], config_errors=[], skipped_files=[], run={"checkwash_version": "0.9.1"})
        add(["check", "HEAD..HEAD", "--format", "json"], 0, json.dumps(clean).encode())
        add(["check", "MISSING_QUALIFICATION_REF..HEAD", "--format", "json"], 2, b"", b"engine error: owned missing ref\n")
        for field, raw in streams.items():
            packet.put("nested-qualify-source/" + field + ".bin", raw)
        packet.put_json("nested-qualify-source/commands.json", rows)
        exits = {"qualify-source": {"argv": [r"C:\owned\python.exe", "owned-helper", "--source-root", source, "--", r"C:\owned\python.exe"]}}
        return packet, "source", desc, {"cases": written}, exits

    def test_each_qualification_case_and_controls_match_original_raw(self):
        R.validate_qualification_raw(*self.evidence())

    def test_correct_summary_cannot_hide_a_different_raw_case_or_missing_call(self):
        for mutation in ("raw-case", "missing"):
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                R.validate_qualification_raw(*self.evidence(mutation))


class CheckPublicationTests(unittest.TestCase):
    def test_pr_publishes_real_four_contexts_and_separate_stage_scope(self):
        result = report("pr")
        api = NativeAPI(result["subject"])
        ids = R.publish_check(api, result, "https://github.com/owned/run")
        posts = [body for method, _, body in api.writes if method == "POST"]
        self.assertEqual([body["name"] for body in posts], [*R.B.CONTEXTS, R.context("pr")])
        self.assertEqual(ids, {"check_run_id": 5, "check_run_ids": [1, 2, 3, 4]})
        self.assertTrue(all(body["external_id"].startswith("pju:") for body in posts[:4]))
        self.assertEqual(posts[4]["external_id"], "pju-release:" + result["manifest_sha256"] + ":pr")

    def test_main_never_manufactures_pr_required_contexts(self):
        result = report("main")
        api = NativeAPI(result["subject"])
        R.publish_check(api, result, "https://github.com/owned/run")
        self.assertEqual([body["name"] for method, _, body in api.writes if method == "POST"], [R.context("main")])

    def test_stale_pr_never_creates_any_success_or_check(self):
        result = report("pr")
        api = NativeAPI(result["subject"])
        api.data[api.prefix + "/pulls/70"]["state"] = "closed"
        with self.assertRaises(ValueError):
            R.publish_check(api, result, "https://github.com/owned/run")
        self.assertEqual(api.writes, [])

    def test_partial_publication_marks_every_created_check_failed(self):
        result = report("pr")
        api = NativeAPI(result["subject"])
        api.fail_success = api.prefix + "/check-runs/2"
        with self.assertRaisesRegex(ValueError, "partial"):
            R.publish_check(api, result, "https://github.com/owned/run")
        failures = [path for method, path, body in api.writes if method == "PATCH" and body.get("conclusion") == "failure"]
        self.assertEqual(len(failures), 5)

    def test_unverified_scope_list_cannot_publish(self):
        result = report("main")
        result["checks"] = list(R.B.CONTEXTS)
        api = NativeAPI(result["subject"])
        with self.assertRaises(ValueError):
            R.publish_check(api, result, "https://github.com/owned/run")
        self.assertEqual(api.writes, [])


class ParentStageTests(unittest.TestCase):
    def parent(self, legacy=False):
        current = subject("main")
        api = NativeAPI(current)
        prior = report("pr")
        prior["head_sha"] = prior["subject"]["head_sha"] = "9" * 40
        prior.update(check_run_ids=[1, 2, 3, 4], check_run_id=5)
        if legacy:
            prior.pop("subject")
            prior.pop("kind")
        packet = MemoryPacket()
        packet.put_json("parents/pr.json", prior)
        packet.manifest["parents"] = {"pr": dict(report="parents/pr.json", sha256=R.digest(packet.raw("parents/pr.json")), check_run_id=1)}
        for index, name in enumerate([*R.B.CONTEXTS, R.context("pr")], 1):
            api.data[api.prefix + f"/check-runs/{index}"] = dict(id=index, app={"id": 15368}, name=name,
                status="completed", conclusion="success", head_sha="9" * 40,
                external_id="pju:" + prior["manifest_sha256"] + ":" + name if index < 5 else "pju-release:" + prior["manifest_sha256"] + ":pr")
        api.data[api.prefix + "/pulls/70"] = dict(state="closed", merged=True, merge_commit_sha=current["head_sha"], head={"sha": "9" * 40, "repo": {"full_name": R.REPOSITORY}})
        return packet, api, current

    def test_complete_new_pr_release_stage_is_valid_main_parent(self):
        self.assertEqual(R.validate_parents(*self.parent())["stage"], "pr")

    def test_legacy_four_green_pr_checks_do_not_replace_release_extras(self):
        with self.assertRaisesRegex(ValueError, "legacy PR"):
            R.validate_parents(*self.parent(legacy=True))

    def test_missing_pr_stage_check_or_wrong_merge_is_rejected(self):
        for kind in ("stage", "merge"):
            with self.subTest(kind=kind):
                packet, api, current = self.parent()
                if kind == "stage":
                    api.data[api.prefix + "/check-runs/5"]["conclusion"] = "failure"
                else:
                    api.data[api.prefix + "/pulls/70"]["merge_commit_sha"] = "8" * 40
                with self.assertRaises(ValueError):
                    R.validate_parents(packet, api, current)


class AssetPublicationTests(unittest.TestCase):
    def evidence(self):
        value = report("release-event")
        raw = {"checkwash-0.9.1-py3-none-any.whl": b"owned wheel", "checkwash-0.9.1.tar.gz": b"owned sdist", "checkwash.pyz": b"owned pyz"}
        value["artifacts"] = {name: dict(bytes=len(contents), sha256=R.digest(contents)) for name, contents in raw.items()}
        packet = MemoryPacket()
        for name, contents in raw.items():
            packet.put("artifacts/" + name, contents)
        api = NativeAPI(value["subject"])
        def download(url, size):
            contents = raw[url.rsplit("/", 1)[1]]
            if len(contents) != size:
                raise ValueError("owned size mismatch")
            return contents
        return packet, api, value, raw, download

    def test_exact_three_assets_upload_then_actual_bytes_are_read_back(self):
        packet, api, value, raw, downloader = self.evidence()
        with patch.object(R, "publication_authority", return_value={}):
            result = R.publish_assets(api, packet, {}, value, downloader=downloader)
        self.assertEqual(result["status"], "verified")
        self.assertEqual(len(api.uploads), 3)
        self.assertFalse(any("clobber" in path for _, path, _ in api.uploads))

    def test_identical_existing_assets_are_retained_without_overwrite(self):
        packet, api, value, raw, downloader = self.evidence()
        with patch.object(R, "publication_authority", return_value={}):
            R.publish_assets(api, packet, {}, value, downloader=downloader)
            api.uploads.clear()
            R.publish_assets(api, packet, {}, value, downloader=downloader)
        self.assertEqual(api.uploads, [])

    def test_mismatching_existing_bytes_stop_without_any_replacement(self):
        packet, api, value, raw, downloader = self.evidence()
        name = next(iter(raw))
        api.data[api.prefix + "/releases/50"]["assets"] = [dict(name=name, id=9, size=len(raw[name]), state="uploaded",
            browser_download_url=f"https://github.com/{R.REPOSITORY}/releases/download/v0.9.1/{name}")]
        with patch.object(R, "publication_authority", return_value={}):
            with self.assertRaisesRegex(ValueError, "replacement"):
                R.publish_assets(api, packet, {}, value, downloader=lambda url, size: b"x" * size)
        self.assertEqual(api.uploads, [])

    def test_missing_authorization_or_platform_acceptance_stops_before_upload(self):
        packet, api, value, raw, downloader = self.evidence()
        with self.assertRaises(ValueError):
            R.publish_assets(api, packet, {}, value, downloader=downloader)
        self.assertEqual(api.uploads, [])

    def test_source_specific_human_records_are_required_not_a_waived_boolean(self):
        packet, _, value, _, _ = self.evidence()
        authorization = dict(kind="checkwash.release-one-time-authorization.v1", status="authorized", version="0.9.1",
            source_sha=value["subject"]["head_sha"], tag="v0.9.1", maintainer="Nelson", human_quote="owned approval",
            human_evidence_reference="owned human source", max_attempts=1)
        platform = dict(kind="checkwash.release-missing-platform-acceptance.v1", status="accepted-for-this-release", version="0.9.1",
            source_sha=value["subject"]["head_sha"], missing_platforms=R.MISSING_PLATFORMS,
            cross_platform_byte_comparison="NOT_RUN_ACCEPTED_FOR_THIS_RELEASE", standing_contract_changed=False,
            maintainer="Nelson", human_quote="owned concrete platform acceptance", human_evidence_reference="owned human source")
        packet.put_json("release/release-authorization.json", authorization)
        packet.put_json("release/platform-acceptance.json", platform)
        admission = {"release_authorization": dict(path="release/release-authorization.json", sha256=R.digest(packet.raw("release/release-authorization.json"))),
                     "platform_acceptance": dict(path="release/platform-acceptance.json", sha256=R.digest(packet.raw("release/platform-acceptance.json")))}
        self.assertIn("release_authorization", R.publication_authority(packet, admission, value))
        platform["source_sha"] = "9" * 40
        packet.put_json("release/platform-acceptance.json", platform)
        admission["platform_acceptance"]["sha256"] = R.digest(packet.raw("release/platform-acceptance.json"))
        with self.assertRaisesRegex(ValueError, "source-specific"):
            R.publication_authority(packet, admission, value)
        admission["platform_acceptance"] = {"waived": True}
        with self.assertRaises(ValueError):
            R.publication_authority(packet, admission, value)

    def test_tag_stage_cannot_upload_release_distributions(self):
        packet, api, value, raw, downloader = self.evidence()
        value["subject"] = subject("tag")
        with self.assertRaises(ValueError):
            R.publish_assets(api, packet, {}, value, downloader=downloader)
        self.assertEqual(api.uploads, [])

    def test_stale_or_extra_distribution_export_is_rejected(self):
        packet, _, value, _, _ = self.evidence()
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "dist"
            R.export_distributions(packet, value, target, pypi_only=True)
            self.assertEqual({path.name for path in target.iterdir()}, set(value["artifacts"]) - {"checkwash.pyz"})
            with self.assertRaises(FileExistsError):
                R.export_distributions(packet, value, target)


class WorkflowAndAdmissionTests(unittest.TestCase):
    def test_actual_manual_pr_capture_preserves_payload_and_native_base(self):
        value = subject("pr")
        api = NativeAPI(value)
        capture = dict(schema_version=1, kind="checkwash.pju-release-capture.v1", stage="pr", head=value["head_sha"],
                       tag=None, release_id=None, pr_number=70, trusted_workflow_sha=value["event"]["workflow_sha"])
        payload = dict(repository={"full_name": R.REPOSITORY}, sender={"login": "taipei49314"}, inputs={"mode": "release-capture"})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "event.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            env = dict(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REPOSITORY=R.REPOSITORY,
                GITHUB_REPOSITORY_OWNER="taipei49314", GITHUB_ACTOR="taipei49314", GITHUB_TRIGGERING_ACTOR="taipei49314",
                GITHUB_SHA=value["event"]["workflow_sha"], GITHUB_WORKFLOW_SHA=value["event"]["workflow_sha"],
                GITHUB_WORKFLOW_REF=R.REPOSITORY + "/" + R.BOOTSTRAP_WORKFLOW + "@refs/heads/reviewed",
                GITHUB_EVENT_PATH=str(path), GITHUB_RUN_ID="60", GITHUB_RUN_ATTEMPT="1")
            captured, raw = R.capture(api, env, admission=capture)
            self.assertEqual(captured["base_sha"], value["base_sha"])
            self.assertEqual(captured["event"]["payload_sha256"], R.digest(raw))
            self.assertEqual(captured["pr_number"], 70)

    def test_bootstrap_retains_legacy_modes_and_only_admitted_pr_publication(self):
        value = yaml.safe_load((ROOT / R.BOOTSTRAP_WORKFLOW).read_text())
        trigger = value.get("on", value.get(True))
        self.assertEqual(trigger["workflow_dispatch"]["inputs"]["mode"]["options"], ["intake", "receipt", "release-capture", "release-receipt"])
        self.assertLessEqual(len(trigger["workflow_dispatch"]["inputs"]), 10)
        jobs = value["jobs"]
        self.assertIn("verify-pju-receipt", jobs)
        self.assertIn("publish-pju-checks", jobs)
        self.assertEqual(jobs["publish-pju-release-checks"]["permissions"]["checks"], "write")
        self.assertEqual(jobs["verify-pju-release"]["permissions"]["checks"], "read")

    def test_pypi_waits_for_assets_and_preserves_actual_trusted_publisher_identity(self):
        value = yaml.safe_load((ROOT / R.WORKFLOW).read_text())
        pypi = value["jobs"]["pypi"]
        self.assertEqual(pypi["needs"], "publish-assets")
        self.assertEqual(pypi["environment"], "pypi")
        self.assertEqual(pypi["permissions"]["id-token"], "write")
        self.assertIn("PYPI_ENABLED", pypi["if"])
        self.assertTrue(any("verify-assets" in step.get("run", "") for step in pypi["steps"]))
        self.assertFalse(any("--clobber" in step.get("run", "") for job in value["jobs"].values() for step in job["steps"]))
        forbidden = ("-m pytest", "-m build", "pip install", "qualify_assertions.py", "replay_pju_action.py")
        for job in value["jobs"].values():
            for step in job["steps"]:
                self.assertFalse(any(token in step.get("run", "") for token in forbidden))

    def test_non_owner_wrong_workflow_or_sha_cannot_admit(self):
        expected = "e" * 40
        env = dict(GITHUB_EVENT_NAME="workflow_dispatch", GITHUB_REPOSITORY=R.REPOSITORY,
                   GITHUB_REPOSITORY_OWNER="taipei49314", GITHUB_ACTOR="taipei49314", GITHUB_TRIGGERING_ACTOR="taipei49314",
                   GITHUB_SHA=expected, GITHUB_WORKFLOW_SHA=expected, GITHUB_WORKFLOW_REF=R.REPOSITORY + "/" + R.BOOTSTRAP_WORKFLOW + "@refs/heads/reviewed")
        R.admit_environment(expected, env, stage="pr")
        for key, changed in (("GITHUB_ACTOR", "contributor"), ("GITHUB_SHA", "9" * 40), ("GITHUB_WORKFLOW_REF", R.REPOSITORY + "/unreviewed.yml@main")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                R.admit_environment(expected, {**env, key: changed}, stage="pr")
        with self.assertRaises(ValueError):
            R.admit_environment(expected, env, stage="release-event")


if __name__ == "__main__":
    unittest.main()
