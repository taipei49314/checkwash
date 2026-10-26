"""Independent authority/rename controls; fixture bytes are never executed."""
import pytest

from checkwash.change import EngineError, FileChange
from checkwash.contract import load_contract
from checkwash.gitio import git as gitio


@pytest.mark.parametrize("glob", ['**"', "**'", "'\"**\"'", '"\'**\'"', "''**''", '"""**"""'])
def test_authority_validator_rejects_quote_forms_that_decoder_would_broaden(glob):
    text = "---\ncheckwash:\n  scope:\n    allow:\n      - " + glob + "\n---\n"
    # Historical strip-all-quotes decoding turns each malformed/unsupported
    # token into **. Authority validation must refuse instead of widening scope.
    with pytest.raises(EngineError):
        load_contract(text, source="synthetic BASE TASK")


def test_crlf_pairing_normalization_work_is_linear_in_input_bytes(monkeypatch):
    # All pairs differ at their prefix: raw equality is cheap, while decoding
    # both full payloads inside the nested loop needlessly scans them O(n*m).
    changes = [FileChange(path=f"test_old_{i}.py", status="deleted",
                          before=f"deleted-{i}:".encode() + b"x" * 4096 + b"\n", after=None)
               for i in range(8)]
    changes += [FileChange(path=f"test_new_{i}.py", status="added", before=None,
                           after=f"added-{i}:".encode() + b"x" * 4096 + b"\r\n")
                for i in range(8)]
    original = gitio._rename_content_key
    normalized_bytes = 0

    def counted(data):
        nonlocal normalized_bytes
        normalized_bytes += len(data)
        return original(data)

    monkeypatch.setattr(gitio, "_rename_content_key", counted)
    result = gitio._detect_worktree_renames(changes)
    assert result == changes
    input_bytes = sum(len(change.before or change.after) for change in changes)
    assert normalized_bytes <= 2 * input_bytes
