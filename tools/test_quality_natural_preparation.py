"""Synthetic acceptance-preparation checks, separate from detector evaluation."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import prepare_quality_natural_review as subject


class NaturalPreparationTests(unittest.TestCase):
    def test_manifest_and_source_authentication(self):
        data = b"[tool.mypy]\nstrict = true\n"
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        protocol = json.dumps({"repository_candidates": [{"repo": "example/demo", "path": "pyproject.toml"}],
                               "initial_candidates_per_repository": 1}).encode()
        row = {"repo": "example/demo", "source_order": 0, "path": "pyproject.toml", "label": "UNREVIEWED",
               "base": "a" * 40, "head": "b" * 40,
               "sources": {side: {"state": "present", "git_blob": blob, "sha256": subject.digest(data),
                                    "content_base64": base64.b64encode(data).decode()} for side in ("base", "head")}}
        manifest = {"protocol_sha256": subject.digest(protocol), "reviewed_count": 0, "evaluation": "NOT_RUN", "candidates": [row]}
        raw = json.dumps(manifest).encode()
        prereg = {"original_manifest_sha256": subject.digest(raw)}
        subject.validate_initial(raw, protocol, prereg)
        with self.assertRaisesRegex(ValueError, "manifest digest"):
            subject.validate_initial(raw + b" ", protocol, prereg)
        row["sources"]["base"]["content_base64"] = base64.b64encode(b"changed").decode()
        tampered = json.dumps(manifest).encode()
        with self.assertRaisesRegex(ValueError, "source digest"):
            subject.validate_initial(tampered, protocol, {"original_manifest_sha256": subject.digest(tampered)})

    def test_selection_preserves_order_and_omissions(self):
        rows = [{"sha": "b" * 40, "parents": [{"sha": "a" * 40}]},
                {"sha": "c" * 40, "parents": [{"sha": "a" * 40}, {"sha": "b" * 40}]},
                {"sha": "d" * 40, "parents": [{"sha": "e" * 40}]},
                {"sha": "f" * 40, "parents": []}]
        selected, omitted = subject.select_history([rows[:2], rows[2:]], [{"head": "b" * 40, "base": "a" * 40}], 2)
        self.assertEqual([r["head"] for r in selected], ["b" * 40, "d" * 40])
        self.assertEqual([r["parent_count"] for r in omitted], [2, 0])

    def test_changed_prefix_and_duplicate_history_fail(self):
        row = {"sha": "b" * 40, "parents": [{"sha": "a" * 40}]}
        with self.assertRaisesRegex(ValueError, "prefix"):
            subject.select_history([[row]], [{"head": "c" * 40, "base": "a" * 40}], 2)
        with self.assertRaisesRegex(ValueError, "repeated"):
            subject.select_history([[row], [row]], [], 2)

    def test_comment_and_dependency_changes_do_not_invent_relevance(self):
        result = subject.table_differences(b'[project]\nversion="1"\n[tool.mypy]\nstrict=true\n',
                                           b'[project]\nversion="2"\n# comment\n[tool.mypy]\nstrict=true\n')
        self.assertFalse(any(result["tools"].values()))
        self.assertEqual(result["human_relevance"], "UNREVIEWED")

    def test_deletion_addition_and_types_remain_visible(self):
        result = subject.table_differences(b'[tool.mypy]\nstrict=false\n[tool.ruff.lint]\nignore=["E"]\n',
                                           b'[tool.mypy]\nstrict=0\n[tool.coverage.report]\nfail_under=80\n')
        self.assertTrue(all(result["tools"].values()))
        self.assertFalse(result["tools"]["coverage"][0]["base_present"])
        self.assertFalse(result["tools"]["ruff"][-1]["head_present"])
        self.assertEqual(result["human_label"], "UNREVIEWED")

    def test_invalid_sources_are_unknown(self):
        for invalid in (b"not toml", b"\xff", b"tool = 1"):
            self.assertEqual(subject.table_differences(invalid, b"")["state"], "unknown")

    def test_bounded_context_discovery(self):
        for path in ("pyproject.toml", "src/ruff.toml", "requirements/dev.txt", ".github/workflows/test.yml", "uv.lock"):
            self.assertTrue(subject.wanted_context(path), path)
        for path in ("src/main.py", "setup.py", "README.md", "nested/uv.lock", "assets/image.png"):
            self.assertFalse(subject.wanted_context(path), path)

    def test_symlink_and_byte_limits_never_become_present(self):
        entries = b"120000 blob " + b"a" * 40 + b"\tmypy.ini\0" + b"100644 blob " + b"b" * 40 + b"\tpyproject.toml\0"
        with tempfile.TemporaryDirectory() as directory, patch.object(subject, "git", return_value=entries), patch.object(subject, "object_bytes", return_value=(None, 1000001)) as read:
            result = subject.read_snapshot(Path(directory), "c" * 40, {"files_per_snapshot": 128, "bytes_per_file": 1000000, "total_bytes_per_snapshot": 16777216}, {}, Path(directory))
            self.assertEqual(result["sources"]["mypy.ini"]["reason"], "non-regular-file")
            self.assertEqual(result["sources"]["pyproject.toml"]["reason"], "source-byte-limit")
            self.assertEqual(read.call_count, 1)
            self.assertEqual(result["closure_status"], "UNESTABLISHED")

    def test_snapshot_total_budget_and_content_address(self):
        entries = b"100644 blob " + b"a" * 40 + b"\tmypy.ini\0" + b"100644 blob " + b"b" * 40 + b"\tpyproject.toml\0"
        with tempfile.TemporaryDirectory() as directory, patch.object(subject, "git", return_value=entries), patch.object(subject, "object_bytes", return_value=(b"test", 4)):
            result = subject.read_snapshot(Path(directory), "c" * 40, {"files_per_snapshot": 2, "bytes_per_file": 10, "total_bytes_per_snapshot": 6}, {}, Path(directory))
            self.assertEqual(result["sources"]["pyproject.toml"]["sha256"], subject.digest(b"test"))
            self.assertEqual(result["sources"]["mypy.ini"]["reason"], "snapshot-byte-limit")

    def test_pins_are_only_evidence_and_ranges_are_not_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inputs = {"requirements.txt": b"mypy==1.10.0\ncoverage>=7.0\nruff==0.1.*\n", "uv.lock": b'[[package]]\nname="ruff"\nversion="0.8.0"\n', ".pre-commit-config.yaml": b"repos:\n- repo: https://github.com/pre-commit/mirrors-mypy\n  rev: v1.11.2\n"}
            sources = {}
            for index, (path, data) in enumerate(inputs.items()):
                (root / str(index)).write_bytes(data)
                sources[path] = {"state": "present", "object": str(index)}
            result = subject.version_evidence(sources, root)
            self.assertEqual({r["version"] for r in result["mypy"]["exact_version_candidates"]}, {"1.10.0", "1.11.2"})
            self.assertEqual([r["version"] for r in result["ruff"]["exact_version_candidates"]], ["0.8.0"])
            self.assertEqual(result["coverage"]["exact_version_candidates"], [])
            self.assertTrue(all(r["effective_version"] is None for r in result.values()))

    def test_counts_never_promote_screening_to_acceptance(self):
        rows = [{"repo": "example/demo", "triage": {"state": "parsed", "tools": {"mypy": [{"change": True}]}}}] * 100
        result = subject.summarize(rows, [], [])
        self.assertEqual(result["preparation_only_counts"]["table_changed_candidates"], 100)
        self.assertIsNone(result["qualified_relevant_count"])
        self.assertEqual(result["human_reviewed_count"], 0)
        self.assertEqual(result["acceptance"], "NOT_RUN")

    def test_preparation_errors_cannot_be_hidden_by_counts(self):
        result = subject.summarize([], [], [{"repo": "example/demo", "error_type": "ValueError"}])
        self.assertEqual(result["status"], "PREPARATION_INCOMPLETE")

    def test_dependency_filename_variants_are_captured(self):
        for path in ("test-requirements.txt", "docs-requirements.in", "requirements-skip/tests-min.txt",
                     "ci/test-constraints.txt", "constraints/versions.in"):
            self.assertTrue(subject.wanted_context(path), path)
        self.assertFalse(subject.wanted_context("docs/notrequirements.txt"))

    def test_relative_constraint_and_requirement_references(self):
        data = b'-r ../shared/deps.lock\n--constraint="pins/base.lock"\n-c constraints.txt\n'
        refs = list(subject.static_references("deps/test-requirements.in", data))
        self.assertEqual([r["target_path"] for r in refs], ["shared/deps.lock", "deps/pins/base.lock", "deps/constraints.txt"])
        self.assertTrue(all(r["activation"] == "UNESTABLISHED" for r in refs))

    def test_workflow_references_remain_candidates_and_dynamic_stays_unknown(self):
        data = b'run: python -m pip install -r "pins/deps.lock" -c $CONSTRAINTS\nrun: python -c "print(1)"\n'
        refs = list(subject.static_references(".github/workflows/test.yml", data))
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0]["target_path"], "pins/deps.lock")
        self.assertEqual(refs[0]["anchor"], "repository-root-candidate")
        self.assertEqual(refs[1]["reason"], "dynamic-reference")

    def test_reference_boundaries_and_tox_anchor(self):
        refs = list(subject.static_references("requirements/main.in", b'-r ../../outside\n-r https://example.test/deps\n'))
        self.assertEqual([r["reason"] for r in refs], ["outside-repository-or-invalid", "external-reference"])
        ref = list(subject.static_references("tox.ini", b'deps = -r{toxinidir}/pins/deps.lock\n'))[0]
        self.assertEqual(ref["target_path"], "pins/deps.lock")

    def test_nested_references_capture_nonstandard_names_and_stop_cycles(self):
        entries = b"100644 blob " + b"a"*40 + b"\ttest-requirements.txt\0" + b"100644 blob " + b"b"*40 + b"\tpins/deps.lock\0"
        data = {"a"*40: b'-r pins/deps.lock\n-c missing.lock\n', "b"*40: b'-r ../test-requirements.txt\nmypy==1.4.1\n'}
        def read(_repo, blob, _limit):
            return data[blob], len(data[blob])
        with tempfile.TemporaryDirectory() as directory, patch.object(subject, "git", return_value=entries), patch.object(subject, "object_bytes", side_effect=read) as reader:
            result = subject.read_snapshot(Path(directory), "c"*40, {"files_per_snapshot": 128, "bytes_per_file": 1000000, "total_bytes_per_snapshot": 16777216}, {}, Path(directory))
            self.assertEqual(reader.call_count, 2)
            self.assertEqual(result["sources"]["pins/deps.lock"]["state"], "present")
            self.assertEqual([r["reason"] for r in result["static_references"] if r["state"] == "unresolved"], ["not-in-tracked-tree"])

    def test_reference_capture_respects_source_limits(self):
        entries = b"100644 blob " + b"a"*40 + b"\ttest-requirements.txt\0" + b"100644 blob " + b"b"*40 + b"\tpins/deps.lock\0"
        data = b'-r pins/deps.lock\n'
        with tempfile.TemporaryDirectory() as directory, patch.object(subject, "git", return_value=entries), patch.object(subject, "object_bytes", return_value=(data, len(data))):
            result = subject.read_snapshot(Path(directory), "c"*40, {"files_per_snapshot": 1, "bytes_per_file": 1000000, "total_bytes_per_snapshot": 16777216}, {}, Path(directory))
            self.assertEqual(result["static_references"][0]["reason"], "snapshot-file-limit")
            self.assertEqual(result["closure_status"], "UNESTABLISHED")

    def test_temporal_values_serialize_without_losing_types(self):
        before = b'[tool.coverage.report]\nunknown_setting=2025-01-01\ntime=12:34:56\nstamp=2025-01-01T12:34:56Z\n'
        after = b'[tool.coverage.report]\nunknown_setting="2025-01-01"\ntime="12:34:56"\nstamp="2025-01-01T12:34:56+00:00"\n'
        result = subject.table_differences(before, after)
        changes = result["tools"]["coverage"]
        self.assertEqual(len(changes), 3)
        self.assertEqual({c["base_value_types"][0]["toml_type"] for c in changes}, {"date", "time", "datetime"})
        self.assertTrue(all(c["head_value_types"] == [] for c in changes))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "manifest.json"
            subject.dump(target, result)
            self.assertEqual(json.loads(target.read_bytes()), result)

    def test_nested_nonfinite_values_use_standard_json(self):
        before = b'[[tool.mypy.overrides]]\nvalues=[nan, inf, -inf, 2025-01-01]\n'
        after = b'[[tool.mypy.overrides]]\nvalues=["nan", "inf", "-inf", "2025-01-01"]\n'
        result = subject.table_differences(before, after)
        change = result["tools"]["mypy"][0]
        self.assertEqual([t["path"] for t in change["base_value_types"]], [[0, "values", i] for i in range(4)])
        self.assertEqual(change["head_value_types"], [])
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        self.assertFalse(any(subject.table_differences(before, before)["tools"].values()))

    def test_table_array_key_order_is_equivalent_but_array_order_is_visible(self):
        before = b'[[tool.mypy.overrides]]\nmodule=["a", "b"]\nstrict=true\n'
        reordered = b'[[tool.mypy.overrides]]\nstrict=true\nmodule=["a", "b"]\n'
        changed = b'[[tool.mypy.overrides]]\nstrict=true\nmodule=["b", "a"]\n'
        self.assertEqual(subject.table_differences(before, reordered)["tools"]["mypy"], [])
        self.assertTrue(subject.table_differences(before, changed)["tools"]["mypy"])

    def test_unconverted_nonfinite_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            subject.dump(Path(directory) / "manifest.json", {"unconverted": float("nan")})


class DurableSeedTests(unittest.TestCase):
    def make_seed(self, directory, mutate=None, extra=None):
        data = b'[tool.mypy]\nstrict=true\n'
        source = {"state": "present", "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest(),
                  "sha256": subject.digest(data), "git_mode": "100644", "content_base64": base64.b64encode(data).decode()}
        protocol = {"repository_candidates": [{"repo": "example/demo", "path": "pyproject.toml"}], "initial_candidates_per_repository": 1, "cutoff_utc": "2026-01-01T00:00:00Z"}
        encoded = lambda value: json.dumps(value).encode()
        protocol_raw = encoded(protocol)
        row = {"id": "example--demo-" + "b"*12, "repo": "example/demo", "path": "pyproject.toml", "source_order": 0,
               "base": "a"*40, "head": "b"*40, "intake": "original", "label": "UNREVIEWED"}
        original = {"protocol_sha256": subject.digest(protocol_raw), "reviewed_count": 0, "evaluation": "NOT_RUN",
                    "candidates": [{**row, "sources": {s: source for s in ("base", "head")}}]}
        original_raw = encoded(original)
        snapshots = {s: {"commit": row[s], "inventory_sha256": "c"*64, "tracked_entries": 1,
                         "sources": {"pyproject.toml": source}} for s in ("base", "head")}
        previous = {"original_manifest_sha256": subject.digest(original_raw), "engine_commit": "d"*40, "engine_tree": "e"*40,
                    "candidates": [{**row, "snapshots": snapshots}],
                    "summary": {"acceptance": "NOT_RUN", "predictions": "NOT_RUN", "human_reviewed_count": 0, "candidate_count": 1}}
        history = {"repo": row["repo"], "path": row["path"], "cutoff": protocol["cutoff_utc"], "desired_count": 1, "selected_count": 1,
                   "pages": [[{"sha": row["head"], "parents": [{"sha": row["base"]}]}]], "omitted": []}
        if mutate:
            mutate(previous, history)
        previous_raw = encoded(previous)
        entries = {"candidate-manifest.json": original_raw, "protocol.json": protocol_raw, "prepared-manifest.json": previous_raw,
                   "history/example--demo.json": encoded(history)}
        if extra:
            entries.update(extra)
        path = Path(directory) / "seed.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, raw in entries.items():
                archive.writestr(name, raw)
        repair = {"seed_bytes": path.stat().st_size, "seed_sha256": subject.digest(path.read_bytes()), "maximum_seed_expanded_bytes": 100000,
                  "source_prepared_manifest_sha256": subject.digest(previous_raw), "original_manifest_sha256": subject.digest(original_raw), "candidate_count": 1}
        prereg = {"original_manifest_sha256": subject.digest(original_raw), "additional_candidates_per_repository": 0,
                  "engine_commit": previous["engine_commit"], "engine_tree": previous["engine_tree"]}
        return path, repair, prereg

    def test_seed_replays_without_artifact_or_history_network(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(subject, "api", side_effect=AssertionError("network forbidden")):
            result = subject.load_seed(*self.make_seed(directory))
            self.assertEqual(len(result[4]["candidates"]), 1)
            self.assertEqual(result[5][0]["selected_count"], 1)

    def test_seed_authentication_and_expansion_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            path, repair, prereg = self.make_seed(directory)
            with self.assertRaisesRegex(ValueError, "expansion limit"):
                subject.load_seed(path, {**repair, "maximum_seed_expanded_bytes": 1}, prereg)
            path.write_bytes(path.read_bytes() + b"changed")
            with self.assertRaisesRegex(ValueError, "digest/size"):
                subject.load_seed(path, repair, prereg)

    def test_unexpected_archive_paths_are_never_extracted(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "unexpected seed entries"):
                subject.load_seed(*self.make_seed(directory, extra={"../escape": b"untrusted"}))
            self.assertFalse((Path(directory).parent / "escape").exists())

    def test_history_and_candidate_identity_remain_frozen(self):
        for change, reason in ((lambda p, h: h["pages"][0][0].update(sha="f"*40), "prefix"),
                               (lambda p, h: p["candidates"][0].update(source_order=1), "identity"),
                               (lambda p, h: p["candidates"][0].update(label="unsupported"), "state changed")):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(ValueError, reason):
                subject.load_seed(*self.make_seed(directory, mutate=change))

    def test_previous_source_bytes_cannot_be_lost_to_new_context(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = subject.load_seed(*self.make_seed(directory))[4]["candidates"][0]["snapshots"]["base"]
            subject.preserve_snapshot(previous, previous)
            changed = json.loads(json.dumps(previous))
            changed["sources"]["pyproject.toml"].update(state="unknown", reason="snapshot-file-limit")
            with self.assertRaisesRegex(ValueError, "bytes missing/changed"):
                subject.preserve_snapshot(changed, previous)
            changed["sources"] = {}
            with self.assertRaisesRegex(ValueError, "source missing/changed"):
                subject.preserve_snapshot(changed, previous)


if __name__ == "__main__":
    unittest.main(verbosity=2)
