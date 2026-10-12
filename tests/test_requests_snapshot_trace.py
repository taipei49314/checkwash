"""Proposed observer controls: fake methods only; no product/corpus execution."""
import importlib.util
import json
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[1] / "tools" / "requests_snapshot_trace.py"
SPEC = importlib.util.spec_from_file_location("requests_snapshot_trace_owned", PATH)
observer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observer)


class OriginalFailure(Exception):
    pass


class FakeSnapshot:
    def __init__(self):
        self.revision = observer.PARENT
        self._resolved = None
        self._tree_entries = None
        self.inventory_calls = 0
        self.seen_argument = None
        self.last_result = None
        self.failure = OriginalFailure("DO_NOT_SERIALIZE_EXCEPTION_ARGUMENTS")

    def list_paths(self):
        self.inventory_calls += 1
        self._resolved = observer.PARENT
        self._tree_entries = {
            "ordinary.py": (b"100644", b"a" * 40, 9),
            "tests/certs/ca": (b"120000", b"b" * 40, 13),
        }

    def read_many(self, paths):
        self.seen_argument = paths
        self.list_paths()
        selected = sorted(set(paths))
        result = {}
        for path in selected:
            entry = self._tree_entries.get(path)
            if entry is None:
                result[path] = None
                continue
            mode, oid, size = entry
            if mode != b"100644":
                certificate_body = b"DO_NOT_SERIALIZE_CERTIFICATE_CONTENT"
                credential = "DO_NOT_SERIALIZE_CREDENTIAL"
                raise self.failure
            result[path] = b"DO_NOT_SERIALIZE_SOURCE_BYTES"
        self.last_result = result
        return result


class OnePass:
    def __init__(self, values):
        self.values = values
        self.iterations = 0

    def __iter__(self):
        self.iterations += 1
        assert self.iterations == 1
        yield from self.values


def setup_observer(tmp_path, original=FakeSnapshot.read_many):
    recorder = observer.Recorder(tmp_path)
    return recorder, observer.make_wrapper(original, recorder)


@pytest.mark.parametrize("keyword", [False, True])
def test_success_forwards_same_one_shot_object_and_result_without_extra_inventory(tmp_path, keyword):
    recorder, wrapped = setup_observer(tmp_path)
    snapshot = FakeSnapshot()
    paths = OnePass(["ordinary.py", "missing.py", "ordinary.py"])
    result = wrapped(snapshot, paths=paths) if keyword else wrapped(snapshot, paths)
    assert snapshot.seen_argument is paths and result is snapshot.last_result
    assert paths.iterations == snapshot.inventory_calls == 1
    record = recorder.records[0]
    assert record["requested_paths"] == ["missing.py", "ordinary.py"]
    assert record["requested_state"] == "COMPLETE_FROM_RESULT_KEYS"
    assert record["resolved_revision"] == observer.PARENT and record["side"] == "BASE"
    assert "DO_NOT_SERIALIZE_SOURCE_BYTES" not in json.dumps(recorder.report(0))
    assert recorder.report(0)["instrumentation_complete"] is True


def test_failure_preserves_exception_and_full_selected_metadata_without_secrets(tmp_path):
    recorder, wrapped = setup_observer(tmp_path)
    snapshot = FakeSnapshot()
    paths = OnePass(["ordinary.py", "tests/certs/ca", "zzz_missing.py"])
    with pytest.raises(OriginalFailure) as caught:
        wrapped(snapshot, paths)
    assert caught.value is snapshot.failure
    assert snapshot.seen_argument is paths and paths.iterations == snapshot.inventory_calls == 1
    record = recorder.records[0]
    assert record["requested_paths"] == ["ordinary.py", "tests/certs/ca", "zzz_missing.py"]
    assert record["requested_state"] == "COMPLETE_FROM_ORIGINAL_SELECTED"
    active = record["original_frame"]["active_path_metadata"]
    assert active["path"] == "tests/certs/ca"
    assert active["local_entry"] == active["cached_entry"] == {"mode": "120000", "oid": "b" * 40, "size": 13}
    serialized = json.dumps(recorder.report(2))
    assert "DO_NOT_SERIALIZE" not in serialized
    assert recorder.report(2)["engine_exit"] == 2
    assert recorder.report(2)["calls"][0]["outcome"] == "RAISED"


def test_failure_before_selection_remains_unknown_and_does_not_consume_input(tmp_path):
    marker = OriginalFailure()
    def early(snapshot, paths):
        raise marker
    recorder, wrapped = setup_observer(tmp_path, early)
    paths = OnePass(["ordinary.py"])
    with pytest.raises(OriginalFailure) as caught:
        wrapped(FakeSnapshot(), paths)
    assert caught.value is marker and paths.iterations == 0
    assert recorder.records[0]["requested_state"] == "UNKNOWN_BEFORE_SELECTION"
    assert recorder.records[0]["requested_paths"] is None


def test_keyword_typeerror_does_not_become_empty_requested_set(tmp_path):
    recorder, wrapped = setup_observer(tmp_path)
    with pytest.raises(TypeError):
        wrapped(FakeSnapshot(), unexpected=object())
    record = recorder.records[0]
    assert record["requested_paths"] is None and record["original_frame"] is None


@pytest.mark.parametrize("failure_phase", ["start", "finish"])
@pytest.mark.parametrize("original_raises", [False, True])
def test_recording_fault_preserves_original_result_or_exception(tmp_path, monkeypatch, failure_phase, original_raises):
    recorder, wrapped = setup_observer(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("DO_NOT_SERIALIZE_RECORDING_ERROR")
    monkeypatch.setattr(recorder, failure_phase, fail)
    snapshot = FakeSnapshot()
    if original_raises:
        with pytest.raises(OriginalFailure) as caught:
            wrapped(snapshot, ["tests/certs/ca"])
        assert caught.value is snapshot.failure
    else:
        assert wrapped(snapshot, ["ordinary.py"]) is snapshot.last_result
    report = recorder.report(2 if original_raises else 0)
    assert report["instrumentation_complete"] is False
    assert "DO_NOT_SERIALIZE" not in json.dumps(report)


def test_return_metadata_error_preserves_opaque_result_and_marks_incomplete(tmp_path):
    opaque = object()
    def original(snapshot, paths):
        return opaque
    recorder, wrapped = setup_observer(tmp_path, original)
    assert wrapped(FakeSnapshot(), object()) is opaque
    assert recorder.report(0)["instrumentation_complete"] is False


def test_call_limit_is_observer_incomplete_without_suppressing_original_call(tmp_path, monkeypatch):
    monkeypatch.setattr(observer, "MAX_CALLS", 0)
    recorder, wrapped = setup_observer(tmp_path)
    snapshot = FakeSnapshot()
    assert wrapped(snapshot, ["ordinary.py"]) is snapshot.last_result
    assert snapshot.inventory_calls == 1
    assert recorder.report(0)["instrumentation_complete"] is False


def test_output_is_exclusive_and_existing_receipt_is_not_replaced(tmp_path):
    path = tmp_path / "report.json"
    path.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        observer.write_report(path, {"new": True})
    assert path.read_bytes() == b"original"


def test_oversized_report_fails_without_a_final_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(observer, "MAX_RECEIPT_BYTES", 1)
    path = tmp_path / "report.json"
    with pytest.raises(ValueError):
        observer.write_report(path, {"large": "value"})
    assert not path.exists()


def test_exit_two_can_be_complete_metadata_but_is_never_a_pass_record(tmp_path):
    recorder, wrapped = setup_observer(tmp_path)
    with pytest.raises(OriginalFailure):
        wrapped(FakeSnapshot(), ["tests/certs/ca"])
    report = recorder.report(2)
    assert report["instrumentation_complete"] is True
    assert report["engine_exit"] == 2
    assert "verdict" not in report
    assert report["purpose"] == "REQUESTS_2037_METADATA_DIAGNOSTIC_NOT_A_VERDICT"
