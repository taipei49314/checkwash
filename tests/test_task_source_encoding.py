"""Authority reads refuse malformed BASE encoding and never consult HEAD policy."""
import pytest

from test_task_repo_relative_authority import FREEZE, _assert_freeze, _git, _repository, _review, _write


TEXT = FREEZE.decode("utf-8")
ENCODINGS = [
    pytest.param(b"\xff\xfe" + TEXT.encode("utf-16-le"), id="utf16-le-bom"),
    pytest.param(b"\xfe\xff" + TEXT.encode("utf-16-be"), id="utf16-be-bom"),
    pytest.param(TEXT.encode("utf-16-le"), id="utf16-without-bom"),
    pytest.param(b"\xffinvalid UTF8 TASK", id="invalid-utf8"),
    pytest.param(b"\xef\xbb\xbf" + FREEZE, id="utf8-bom-rejected-by-subset"),
]


@pytest.mark.parametrize("raw", ENCODINGS)
@pytest.mark.parametrize("fmt", ["json", "hook-json"])
def test_invalid_base_task_is_refused_without_silently_dropping_freeze(tmp_path, monkeypatch, capsys, raw, fmt):
    fixture = _repository(tmp_path, root_task=raw)
    repo, caller, *_ = fixture
    code, payload, stderr = _review(fixture, monkeypatch, capsys, caller, repo, "TASK.md", fmt=fmt)
    assert code == (0 if fmt == "hook-json" else 2)
    assert "checkwash engine error:" in stderr
    assert "--task 'TASK.md' (BASE)" in stderr
    assert "UTF-8 required" in stderr or "invalid TASK contract" in stderr
    assert "working-tree copy" not in stderr
    if fmt == "json":
        assert payload is None
    else:
        assert "decision" not in payload and "systemMessage" in payload


@pytest.mark.parametrize("raw", ENCODINGS)
def test_valid_utf8_base_still_governs_when_head_task_encoding_is_invalid(tmp_path, monkeypatch, capsys, raw):
    fixture = _repository(tmp_path)
    repo, caller, base, head = fixture
    _git(repo, "read-tree", head)
    _write(repo, "TASK.md", raw)
    _git(repo, "add", "TASK.md")
    _git(repo, "commit", "-q", "-m", "invalid HEAD is not authority")
    candidate = _git(repo, "rev-parse", "HEAD")
    code, payload, stderr = _review((repo, caller, base, candidate), monkeypatch, capsys,
                                     caller, repo, str(repo / "TASK.md"))
    _assert_freeze(code, payload, True)
    assert "invalid TASK contract" not in stderr
    assert "UTF-8 required" not in stderr
