"""Owned offline stage-replay controls; no product or GitHub execution."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "pju_release_identity", Path(__file__).parents[1] / "tools/pju_release_identity.py")
IDENTITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IDENTITY)


def packet(stage):
    subject = dict(stage=stage, repository=IDENTITY.REPOSITORY,
                   source_sha="a" * 40, source_tree="b" * 40,
                   event_name={"pr": "pull_request", "main": "push", "tag": "push",
                       "release-event": "release", "public-visitor": "workflow_dispatch"}[stage],
                   run_id=202 if stage == "release-event" else 303, run_attempt=1, workflow_sha="e" * 40)
    if stage == "pr":
        subject.update(pr_number=563, base_sha="c" * 40)
    if stage == "main":
        subject.update(ref="refs/heads/main", first_parent_sha="c" * 40)
    if stage in ("tag", "release-event", "public-visitor"):
        subject.update(tag="v0.9.1", tag_object="d" * 40, tag_type="tag")
    if stage in ("release-event", "public-visitor"):
        subject.update(release_id=101, release_event_run_id=202,
                       release_event_run_attempt=1, release_event_workflow_sha="e" * 40)
    admission = dict(schema_version=1, kind="checkwash.pju-release-identity-admission.v1",
                     subject=subject, collector_source_sha="f" * 40, evidence_commit="1" * 40,
                     manifest_sha256="2" * 64, artifact_set_sha256="3" * 64,
                     parents={key: "4" * 64 for key in IDENTITY.PARENTS[stage]})
    receipt = copy.deepcopy(admission)
    receipt.update(kind="checkwash.pju-release-stage-identity.v1", host="LAPTOP-01AGNPJU",
                   provenance=IDENTITY.PROVENANCE, status="completed")
    return admission, receipt, copy.deepcopy(subject)


class StageReplayTests(unittest.TestCase):
    def test_complete_identity_does_not_authorize_publication(self):
        for stage in IDENTITY.PARENTS:
            with self.subTest(stage=stage):
                result = IDENTITY.validate(*packet(stage))
                self.assertEqual(result["status"], "identity-matched-only")
                self.assertIs(result["publication_allowed"], False)
                self.assertIn("execution-evidence", result["unverified"])

    def test_same_commit_does_not_make_pr_main_or_tag_receipts_interchangeable(self):
        for prior, next_stage in (("pr", "main"), ("main", "tag"), ("tag", "release-event"),
                                  ("release-event", "public-visitor")):
            with self.subTest(prior=prior, next_stage=next_stage):
                admission, _, live = packet(next_stage)
                _, old_receipt, _ = packet(prior)
                with self.assertRaisesRegex(ValueError, "subject mismatch"):
                    IDENTITY.validate(admission, old_receipt, live)

    def test_live_main_move_invalidates_exact_source_even_with_same_tree(self):
        admission, receipt, live = packet("main")
        live["source_sha"] = "9" * 40
        with self.assertRaisesRegex(ValueError, "subject mismatch"):
            IDENTITY.validate(admission, receipt, live)

    def test_annotation_change_is_not_hidden_by_same_tag_name_and_commit(self):
        admission, receipt, live = packet("tag")
        live["tag_object"] = "9" * 40
        with self.assertRaisesRegex(ValueError, "subject mismatch"):
            IDENTITY.validate(admission, receipt, live)

    def test_deleted_and_recreated_release_does_not_reuse_visitor_evidence(self):
        admission, receipt, live = packet("public-visitor")
        live["release_id"] += 1
        with self.assertRaisesRegex(ValueError, "subject mismatch"):
            IDENTITY.validate(admission, receipt, live)

    def test_other_native_event_run_or_attempt_cannot_supply_release_receipt(self):
        for key in ("release_event_run_id", "release_event_run_attempt", "release_event_workflow_sha"):
            with self.subTest(key=key):
                admission, receipt, live = packet("release-event")
                receipt["subject"][key] = "9" * 40 if key.endswith("sha") else 99
                with self.assertRaises(ValueError):
                    IDENTITY.validate(admission, receipt, live)

    def test_bool_is_not_a_native_pr_number_or_release_attempt(self):
        for stage, key in (("pr", "pr_number"), ("release-event", "release_event_run_attempt")):
            with self.subTest(stage=stage):
                admission, receipt, live = packet(stage)
                admission["subject"][key] = receipt["subject"][key] = live[key] = True
                with self.assertRaisesRegex(ValueError, "native integer"):
                    IDENTITY.validate(admission, receipt, live)

    def test_different_evidence_or_distribution_inventory_is_rejected(self):
        for key in ("collector_source_sha", "evidence_commit", "manifest_sha256", "artifact_set_sha256"):
            with self.subTest(key=key):
                admission, receipt, live = packet("public-visitor")
                receipt[key] = "9" * len(receipt[key])
                with self.assertRaises(ValueError):
                    IDENTITY.validate(admission, receipt, live)

    def test_parent_report_is_required_and_exact(self):
        for mutation in ("missing", "different", "extra"):
            with self.subTest(mutation=mutation):
                admission, receipt, live = packet("tag")
                if mutation == "missing":
                    receipt["parents"].clear()
                elif mutation == "different":
                    receipt["parents"]["main"] = "9" * 64
                else:
                    receipt["parents"]["pr"] = "9" * 64
                with self.assertRaises(ValueError):
                    IDENTITY.validate(admission, receipt, live)

    def test_failed_or_partial_receipt_and_foreign_host_are_rejected(self):
        for key, value in (("status", "failed"), ("status", "partial"),
                           ("host", "pool"), ("provenance", "EC_POOL")):
            with self.subTest(key=key, value=value):
                admission, receipt, live = packet("tag")
                receipt[key] = value
                with self.assertRaises(ValueError):
                    IDENTITY.validate(admission, receipt, live)

    def test_self_reported_publication_permission_is_rejected(self):
        admission, receipt, live = packet("tag")
        receipt["publication_allowed"] = True
        with self.assertRaises(ValueError):
            IDENTITY.validate(admission, receipt, live)

    def test_lightweight_tag_and_arbitrary_refs_are_rejected(self):
        for stage, key, value in (("tag", "tag_type", "commit"),
                                  ("tag", "tag", "refs/heads/main"),
                                  ("main", "ref", "refs/heads/topic")):
            with self.subTest(stage=stage, key=key):
                admission, receipt, live = packet(stage)
                admission["subject"][key] = receipt["subject"][key] = live[key] = value
                with self.assertRaises(ValueError):
                    IDENTITY.validate(admission, receipt, live)

    def test_duplicate_keys_and_nonfinite_json_are_rejected(self):
        for raw in (b'{"subject":1,"subject":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                IDENTITY.strict_json(raw)

    def test_non_ascii_tag_digits_are_rejected(self):
        admission, receipt, live = packet("tag")
        admission["subject"]["tag"] = receipt["subject"]["tag"] = live["tag"] = "v０.９.１"
        with self.assertRaises(ValueError):
            IDENTITY.validate(admission, receipt, live)

    def test_deep_json_produces_rejection_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = root / "deep.json"
            value.write_bytes(b"[" * 2000 + b"0" + b"]" * 2000)
            output = root / "result.json"
            args = ["--admission", str(value), "--receipt", str(value),
                    "--observation", str(value), "--output", str(output)]
            self.assertEqual(IDENTITY.main(args), 1)
            result = json.loads(output.read_text())
            self.assertEqual(result["status"], "rejected")
            self.assertIs(result["publication_allowed"], False)

    def test_cli_rejection_is_preserved_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = [root / name for name in ("admission.json", "receipt.json", "observation.json")]
            values = packet("tag")
            values[1]["subject"]["tag_object"] = "9" * 40
            for path, value in zip(paths, values):
                path.write_text(json.dumps(value), encoding="utf-8")
            output = root / "result.json"
            args = ["--admission", str(paths[0]), "--receipt", str(paths[1]),
                    "--observation", str(paths[2]), "--output", str(output)]
            self.assertEqual(IDENTITY.main(args), 1)
            self.assertIs(json.loads(output.read_text())["publication_allowed"], False)
            before = output.read_bytes()
            with self.assertRaises(FileExistsError):
                IDENTITY.main(args)
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
