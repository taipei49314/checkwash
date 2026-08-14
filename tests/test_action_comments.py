"""T2.2: Action-side review comments are built from findings, no network."""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "post_review", ROOT / "action" / "post_review.py"
)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_comments_skip_allowlisted_and_warn():
    comments = mod.comments_from_findings(
        [
            {
                "rule": "ASSERT_WEAKENED",
                "severity": "high",
                "message": "strength dropped",
                "path": "tests/test_a.py",
                "unit": "test_a",
                "allowlisted": False,
            },
            {
                "rule": "ASSERT_WEAKENED",
                "severity": "high",
                "message": "exempt",
                "path": "tests/test_b.py",
                "allowlisted": True,
            },
            {
                "rule": "CI_WORKFLOW_TOUCHED",
                "severity": "warn",
                "message": "workflow",
                "path": ".github/workflows/ci.yml",
            },
        ]
    )
    assert len(comments) == 1
    assert comments[0]["path"] == "tests/test_a.py"
    assert comments[0]["line"] == 1
    assert "ASSERT_WEAKENED" in comments[0]["body"]
