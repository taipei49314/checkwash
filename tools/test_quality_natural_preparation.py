"""Synthetic acceptance-preparation checks, separate from detector evaluation."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
