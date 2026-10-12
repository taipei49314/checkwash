"""Source-only proposal: metadata observer for the one already-seen requests pair.

This module is not an engine replacement or a verdict classifier. Its caller
must separately capture the unmodified source CLI and verify the exact source.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path


ENGINE = "30cfb8bd39aa702aae0d59bde1d1400654137bad"
PARENT = "f8aa36b92d95e6d2f133489f39f9d5c2412f1bd9"
COMMIT = "4e383642a9ebb82a67eaeed199d0fbbb31991e3c"
SNAPSHOT_SHA256 = "8dfa378d2f0577835439e270682fc2d571ac797c587986e027ab93d48ea87ace"
CLI_SHA256 = "338213a48d337257bb0a39b11b68ed409f96e1c18b1d29f7447451713b129e15"
OID = re.compile(r"(?:[a-f0-9]{40}|[a-f0-9]{64})\Z")
# Observer-only limits, not engine or acceptance budgets. Exhaustion makes the
# diagnostic incomplete, while the original call/result/exception continues.
MAX_CALLS = 2048
MAX_CALLER_FRAMES = 64
MAX_PATHS = 200_000
MAX_RECEIPT_BYTES = 8_000_000


def path_names(value):
    if type(value) is not list or len(value) > MAX_PATHS:
        raise ValueError("unsupported request-set metadata")
    if any(type(path) is not str for path in value):
        raise ValueError("non-string request-set metadata")
    return list(value)


def entry_metadata(value):
    if value is None:
        return None
    if type(value) is not tuple or len(value) != 3:
        raise ValueError("unsupported cached entry metadata")
    mode, oid, size = value
    if type(mode) is not bytes or type(oid) is not bytes or type(size) is not int:
        raise ValueError("unexpected cached entry types")
    mode_text, oid_text = mode.decode("ascii"), oid.decode("ascii")
    if not re.fullmatch(r"[0-7]{6}", mode_text) or not OID.fullmatch(oid_text) or size < 0:
        raise ValueError("invalid cached entry metadata")
    return {"mode": mode_text, "oid": oid_text, "size": size}


class Recorder:
    def __init__(self, source_root):
        self.source_root = Path(source_root).resolve()
        self.started = 0
        self.records = []
        self.failed = False
        self.errors = []

    def failure(self, phase, error):
        # Never serialize exception messages/args, repr, or arbitrary objects.
        self.failed = True
        try:
            self.errors.append({"phase": phase, "type": type(error).__name__})
        except BaseException:
            pass

    def source_location(self, code, line):
        filename = Path(code.co_filename)
        try:
            relative = filename.relative_to(self.source_root).as_posix()
        except ValueError:
            relative = "<outside-engine>"
        return {"file": relative, "function": code.co_name, "line": line}

    def start(self, caller):
        self.started += 1
        if self.started > MAX_CALLS:
            raise ValueError("observer call limit")
        frames = []
        while caller is not None and len(frames) < MAX_CALLER_FRAMES:
            frames.append(self.source_location(caller.f_code, caller.f_lineno))
            caller = caller.f_back
        if caller is not None:
            raise ValueError("observer caller-frame limit")
        return {"call": self.started, "callers": frames}

    def finish(self, token, snapshot, original, result=None, error=None):
        if token is None:
            return
        state = vars(snapshot)
        revision = state.get("revision")
        resolved = state.get("_resolved")
        if type(revision) is not str or (resolved is not None and
                (type(resolved) is not str or not OID.fullmatch(resolved))):
            raise ValueError("unsupported snapshot ref metadata")
        token.update(declared_revision=revision, resolved_revision=resolved)
        token["side"] = "BASE" if resolved == PARENT else "HEAD" if resolved == COMMIT else "OTHER_OR_UNRESOLVED"
        cache = state.get("_tree_entries")
        if cache is not None and type(cache) is not dict:
            raise ValueError("unsupported inventory cache")
        token["cached_inventory_present"] = cache is not None
        if error is None:
            # Original pinned read_many returns a dict containing every selected
            # path, including missing paths. Its byte values are never inspected.
            if type(result) is not dict:
                raise ValueError("unexpected original return type")
            token.update(outcome="RETURNED", requested_state="COMPLETE_FROM_RESULT_KEYS",
                         requested_paths=path_names(sorted(result)), original_frame=None)
        else:
            token.update(outcome="RAISED", exception_type=type(error).__name__,
                         requested_state="UNKNOWN_BEFORE_SELECTION", requested_paths=None,
                         original_frame=None)
            trace = error.__traceback__
            while trace is not None:
                if trace.tb_frame.f_code is original.__code__:
                    frame = trace.tb_frame
                    # Only these named metadata locals are read. Never copy or
                    # serialize f_locals, result, raw blob data, or certificate data.
                    selected = frame.f_locals.get("selected")
                    if selected is not None:
                        token["requested_paths"] = path_names(selected)
                        token["requested_state"] = "COMPLETE_FROM_ORIGINAL_SELECTED"
                    path = frame.f_locals.get("path")
                    active = None
                    if path is not None:
                        if type(path) is not str:
                            raise ValueError("unsupported active-path metadata")
                        mode = frame.f_locals.get("mode")
                        oid = frame.f_locals.get("oid")
                        size = frame.f_locals.get("size")
                        local_entry = None
                        if mode is not None and oid is not None and size is not None:
                            local_entry = entry_metadata((mode, oid, size))
                        active = {"path": path, "local_entry": local_entry,
                                  "cached_entry": entry_metadata(cache.get(path)) if cache is not None else None}
                    token["original_frame"] = {
                        **self.source_location(frame.f_code, trace.tb_lineno),
                        "active_path_metadata": active,
                    }
                    # The line and locals are evidence, not a generic claim that
                    # this path caused every kind of possible read_many failure.
                    break
                trace = trace.tb_next
        self.records.append(token)

    def report(self, engine_exit):
        return {
            "purpose": "REQUESTS_2037_METADATA_DIAGNOSTIC_NOT_A_VERDICT",
            "expected_engine_commit": ENGINE,
            "pair": {"repository": "psf/requests", "ordinal": 2037, "parent": PARENT, "commit": COMMIT},
            "engine_exit": engine_exit,
            "calls_started": self.started,
            "calls_recorded": len(self.records),
            "instrumentation_complete": not self.failed and self.started == len(self.records) and type(engine_exit) is int,
            "instrumentation_errors": self.errors,
            "calls": self.records,
        }


def make_wrapper(original, recorder):
    def observed(snapshot, *args, **kwargs):
        token = None
        try:
            token = recorder.start(sys._getframe(1))
        except BaseException as error:
            recorder.failure("start", error)
        try:
            # Do not look at args/kwargs/paths, iterate an input, call list_paths,
            # resolve a ref, or read a blob before delegating the exact objects.
            result = original(snapshot, *args, **kwargs)
        except BaseException as error:
            try:
                recorder.finish(token, snapshot, original, error=error)
            except BaseException as recording_error:
                recorder.failure("exception_metadata", recording_error)
            raise
        else:
            try:
                recorder.finish(token, snapshot, original, result=result)
            except BaseException as recording_error:
                recorder.failure("return_metadata", recording_error)
            return result
    return observed


def write_report(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(raw) > MAX_RECEIPT_BYTES:
        raise ValueError("observer receipt limit")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("xb") as output:
        output.write(raw)
    # POSIX hosted proposal: publish without replacing an existing receipt.
    os.link(temporary, path)
    temporary.unlink()


def run(source_root, receipt_path, cli_argv):
    """Diagnostic child only. The future outer collector runs native separately.

    Exact Git source/clean tree/full package verification is an outer acquisition
    precondition; these two loaded-module hashes are additional narrow binding.
    """
    source = Path(source_root).resolve()
    receipt = Path(receipt_path)
    if receipt.exists() or not receipt.parent.is_dir() or receipt.resolve().is_relative_to(source):
        raise ValueError("diagnostic needs a fresh external receipt path")
    if len(cli_argv) != 6 or cli_argv[:2] != ["check", PARENT + ".." + COMMIT] or cli_argv[2] != "--repo" or cli_argv[4:] != ["--format", "json"]:
        raise ValueError("only the fixed complete requests pair is supported")
    if receipt.resolve().is_relative_to(Path(cli_argv[3]).resolve()):
        raise ValueError("diagnostic receipt must be outside the corpus")
    sys.path.insert(0, str(source / "src"))
    from checkwash.gitio import snapshot
    from checkwash import cli
    for module, relative, expected in (
        (snapshot, "src/checkwash/gitio/snapshot.py", SNAPSHOT_SHA256),
        (cli, "src/checkwash/cli.py", CLI_SHA256),
    ):
        path = source / relative
        if Path(module.__file__).resolve() != path or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("loaded module source identity differs")
    recorder = Recorder(source)
    original = snapshot.GitSnapshot.read_many
    wrapper = make_wrapper(original, recorder)
    engine_exit = None
    snapshot.GitSnapshot.read_many = wrapper
    try:
        engine_exit = cli.main(cli_argv)
        return engine_exit
    finally:
        if snapshot.GitSnapshot.read_many is not wrapper:
            recorder.failure("restore_identity", RuntimeError())
        snapshot.GitSnapshot.read_many = original
        try:
            write_report(receipt, recorder.report(engine_exit))
        except BaseException:
            # The outer collector requires a valid final report. A missing/partial
            # report is INSTRUMENTATION_FAILURE, never an engine PASS. Preserve
            # the engine's existing return or active exception and raw streams.
            pass
