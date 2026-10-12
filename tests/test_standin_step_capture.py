"""Pure receipt/byte controls; never import Checkwash or launch a child."""
import copy
import importlib.util
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[1] / "tools" / "standin_step_capture.py"
SPEC = importlib.util.spec_from_file_location("standin_step_capture_owned", PATH)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
OLD = "/fixed/original.py"
NEW = "/draft/extended.py"
PRODUCT = "/fixed/engine.pyz/checkwash/engine.py"


def receipts():
    frames = [
        {"file": OLD, "line": 143, "function": "main"},
        {"file": PRODUCT, "line": 99, "function": "analyze"},
        {"file": OLD, "line": 125, "function": "measured"},
    ]
    error = {
        "type": "ValueError", "message": "original refusal",
        "first_frames": frames, "last_frames": copy.deepcopy(frames),
        "traceback": (
            'Traceback (most recent call last):\n'
            f'  File "{OLD}", line 143, in main\n'
            '    code = cli._cmd_check(parsed)\n'
            f'  File "{PRODUCT}", line 99, in analyze\n'
            '    unchanged_product_call()\n'
            f'  File "{OLD}", line 125, in measured\n'
            '    result = original(*a, **kw)\n'
            'ValueError: original refusal\n'
        ),
    }
    original = {
        "complete": True, "recorder_errors": [], "cli_exit": None,
        "diagnostic_cli_outcome_exit": 2, "exit_code": 2, "first_failure_phase": "STANDIN",
        "exception": error, "standin": {"state": "RAISED", "elapsed_seconds": 0.4, "exception": copy.deepcopy(error)},
        "diagnostic_cli_seconds": 1.2, "process_usage": {"ru_maxrss": 40},
        "sources": [{"named_side": "before", "state": "PARSED", "source_sha256": "f" * 64,
                     "raw_source": "old.diagnostic-before.source", "standalone_parse_count_seconds": 0.1,
                     "commands": [{"argv": ["git", "cat-file", "blob", "a" * 40], "exit_code": 0,
                                   "raw_prefix": "old.diagnostic-before.source-git-00"}]}],
    }
    extended = copy.deepcopy(original)
    extended["diagnostic_cli_seconds"] = 9.9
    extended["process_usage"] = {"ru_maxrss": 80}
    extended["standin"]["elapsed_seconds"] = 4.0
    # This component does not interpret an absent step frame as successful
    # analysis. Full observer state validation belongs to run(), not compare().
    extended["standin"]["step_observation"] = {"state": "NO_STEP_FRAME", "counters": None}
    for value in (extended["exception"], extended["standin"]["exception"]):
        for key in ("first_frames", "last_frames"):
            for frame in value[key]:
                if frame["file"] == OLD:
                    frame["file"] = NEW
                    frame["line"] = {143: 160, 125: 126}[frame["line"]]
        value["traceback"] = value["traceback"].replace(
            f'File "{OLD}", line 143, in main', f'File "{NEW}", line 160, in main'
        ).replace(f'File "{OLD}", line 125, in measured', f'File "{NEW}", line 126, in measured')
    extended["sources"][0].update(raw_source="new.diagnostic-before.source", standalone_parse_count_seconds=0.2)
    extended["sources"][0]["commands"][0]["raw_prefix"] = "new.diagnostic-before.source-git-00"
    return original, extended


def comparison(original, extended, *, streams=None, exits=None):
    if streams is None:
        streams = {kind: {"stdout": b"", "stderr": b""} for kind in collector.KINDS}
        streams["native"]["stderr"] = b"native cli.main refusal\n"
    if exits is None:
        exits = dict.fromkeys(collector.KINDS, 2)
    return collector.compare(original, extended, "old.diagnostic", "new.diagnostic", OLD, NEW, streams, exits)


def test_exact_harness_mapping_preserves_refusal_full_traceback_and_inputs():
    original, extended = receipts()
    before = copy.deepcopy((original, extended))
    result = comparison(original, extended)
    assert result["transparent"] is True
    assert result["native_original_extended_exits"] == {"native": 2, "original": 2, "extended": 2}
    assert result["native_stderr_comparison"].startswith("NOT_EXPECTED_EQUAL")
    assert (original, extended) == before
    assert extended["standin"]["step_observation"] == {"state": "NO_STEP_FRAME", "counters": None}


@pytest.mark.parametrize("change", [
    "exception_type", "exception_message", "middle_traceback_text", "product_frame",
    "event_count", "cli_exit", "complete", "recorder_errors",
])
def test_every_non_cost_semantic_difference_is_preserved(change):
    original, extended = receipts()
    if change == "exception_type":
        extended["exception"]["type"] = "RuntimeError"
    elif change == "exception_message":
        extended["exception"]["message"] = "different refusal"
    elif change == "middle_traceback_text":
        # Only the complete text changes: first/last frame summaries remain
        # identical. A comparator that drops full traceback would miss this.
        extended["exception"]["traceback"] = extended["exception"]["traceback"].replace(
            "unchanged_product_call()", "changed_product_call()")
    elif change == "product_frame":
        extended["exception"]["first_frames"][1]["line"] += 1
    elif change == "event_count":
        extended["standin"]["event_count"] = 1
    elif change == "cli_exit":
        extended["cli_exit"] = 0
    elif change == "complete":
        extended["complete"] = False
    else:
        extended["recorder_errors"] = ["recorder failure"]
    result = comparison(original, extended)
    assert result["complete_diagnostic_core_equal"] is False
    assert result["transparent"] is False


def test_unreviewed_harness_line_is_rejected_even_if_other_fields_match():
    original, extended = receipts()
    extended["exception"]["first_frames"][0]["line"] = 161
    with pytest.raises(ValueError, match="unreviewed diagnostic harness frame"):
        comparison(original, extended)


def test_similar_basename_in_another_path_is_never_rewritten():
    original, extended = receipts()
    extended["exception"]["traceback"] = extended["exception"]["traceback"].replace(NEW, "/unrelated/extended.py")
    result = comparison(original, extended)
    assert result["complete_diagnostic_core_equal"] is False
    assert result["transparent"] is False


def test_unexpected_metadata_output_filename_is_rejected():
    original, extended = receipts()
    extended["sources"][0]["commands"][0]["raw_prefix"] = "unrelated.source-git-00"
    with pytest.raises(ValueError, match="metadata command filename differs"):
        comparison(original, extended)


def test_native_exit_difference_cannot_be_hidden_by_equal_diagnostics():
    original, extended = receipts()
    result = comparison(original, extended, exits={"native": 0, "original": 2, "extended": 2})
    assert result["complete_diagnostic_core_equal"] is True
    assert result["native_original_extended_exits"]["native"] == 0
    assert result["transparent"] is False


@pytest.mark.parametrize("invalid", [True, 3, None])
def test_invalid_or_unknown_exit_is_not_a_valid_equal_result(invalid):
    original, extended = receipts()
    with pytest.raises(ValueError, match="invalid child exit"):
        comparison(original, extended, exits=dict.fromkeys(collector.KINDS, invalid))


def test_native_stdout_difference_is_not_hidden_by_matching_exits():
    original, extended = receipts()
    streams = {kind: {"stdout": b"", "stderr": b""} for kind in collector.KINDS}
    streams["native"]["stdout"] = b'{"verdict":"pass"}\n'
    result = comparison(original, extended, streams=streams)
    assert result["native_original_stdout_equal"] is False
    assert result["transparent"] is False


def test_original_extended_stderr_difference_remains_a_difference():
    original, extended = receipts()
    streams = {kind: {"stdout": b"", "stderr": b""} for kind in collector.KINDS}
    streams["extended"]["stderr"] = b"new warning\n"
    result = comparison(original, extended, streams=streams)
    assert result["original_extended_raw_streams_equal"] is False
    assert result["transparent"] is False
