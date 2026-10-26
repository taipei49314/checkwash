"""Use ASCII decoration in legacy streams while preserving source evidence."""

import io

import pytest

from checkwash.demo import run
from checkwash.findings import Evidence, Finding
from checkwash.ir.model import IR
from checkwash.report.term import render
from checkwash.report.textio import write_text


@pytest.mark.parametrize("encoding", ("cp950", "cp1252", "ascii", "utf-8"))
def test_demo_owned_decoration_matches_safe_writer(encoding):
    data = io.BytesIO()
    stream = io.TextIOWrapper(data, encoding=encoding, errors="strict", write_through=True)
    assert run(stream) == 0
    text = data.getvalue().decode(encoding)
    title = next(line for line in text.splitlines() if line.startswith("checkwash demo"))
    summary = next(line for line in text.splitlines() if "tampering cases blocked" in line)
    if encoding == "utf-8":
        assert "—" in title and "·" in summary
    else:
        assert "demo - replaying" in title
        assert r"\u2014" not in title and r"\xb7" not in summary
        # Case origins are evidence: their Unicode is visibly escaped, not rewritten.
        assert r"\u2014" in text


@pytest.mark.parametrize("encoding", ("cp950", "cp1252", "ascii", "utf-8"))
def test_term_owned_decoration_keeps_evidence_lossless(encoding):
    data = io.BytesIO()
    stream = io.TextIOWrapper(data, encoding=encoding, errors="strict", write_through=True)
    finding = Finding("BROAD_EXCEPT_ADDED", "high", "source evidence — 發票", "test_發票.py", "test_api",
                      before=Evidence("a" * 180, (0, 180)), fingerprint="BROAD_EXCEPT_ADDED/test.py/test_api/123456789abc")
    write_text(render(IR("HEAD", "worktree"), [finding], "block", "high", stream=stream), stream)
    text = data.getvalue().decode(encoding)
    instruction = next(line for line in text.splitlines() if "then commit" in line)
    evidence = next(line for line in text.splitlines() if "before  " in line)
    if encoding == "utf-8":
        assert " — " in instruction and evidence.endswith("…")
        assert "test_發票.py" in text
    else:
        assert "allow.toml - it is read" in instruction and evidence.endswith("...")
        assert r"test_\u767c\u7968.py" in text
        assert r"source evidence \u2014 \u767c\u7968" in text
