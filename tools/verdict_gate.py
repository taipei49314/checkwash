"""Previous-release verdict gate (issue #201): the previous release and the candidate on the same inputs.

Both engines run through the CLI only, as
``ABS_PYTHON -B -I ABS.pyz check HEAD~1..HEAD --format json``, inside one fresh
two-commit repository per case. No network, no test code execution: only git and
the selected checkwash processes run. Nothing is looked up at run time, so the
result is a function of the commit and the pinned artifacts.

Engines
-------
* **baseline**: the previous release's ``checkwash.pyz``, pinned in the pins file
  (``tests/verdict_gate/baseline.toml``). It fails unless sha256 and size match,
  its ``checkwash/*`` members equal the pinned commit's ``src/checkwash``
  (``archive_files``, ``package_files`` and ``_require_same`` from
  ``tools/qualify_assertions.py``, imported by path), the source checkout is at
  the pinned commit with no local changes, every report's
  ``run.checkwash_version`` matches, and the clean-range (``HEAD..HEAD``: exit 0,
  verdict pass, no findings, no config errors, no skipped files) and invalid-ref
  (exit 2 with ``engine error`` on stderr) controls behave as in
  ``qualify_assertions.py``.
* **candidate**: built from the checkout with the release recipe and bound the
  same way to ``./src/checkwash``; its version is the checkout's
  ``pyproject.toml`` version.
* **canary**: the pinned ``[canary.old]`` engine against the pinned
  ``[canary.new]`` engine over the T1 cases must reproduce the reviewed
  ``[canary] block_to_pass`` set exactly. Engines with identical sha256 share
  their observations (recorded as ``observations_from``); a shared observation's
  integrity failures are recorded once, under the role that ran it.

Every pinned engine (baseline, canary old and new) is bound like the baseline, so
the workflow needs a checkout of each pinned commit (``--<role>-source``); the
canary's new engine is the baseline release, so it can reuse that checkout.
Beyond the ``checkwash/*`` members, the archive may hold only the release
recipe's root ``__main__.py`` (``checkwash.zipapp_entry:run``), ``checkwash/``
directory entries and bytecode under ``__pycache__``; anything else (a root
module, a sibling ``.pyc``, a backslash name) is a member mismatch.

A sha256 or size mismatch whose member check, commit and version still pass
prints a ``proposed_pin``; a member mismatch is a release incident, not a re-pin.
No unverified engine is executed: when any identity check fails, no case runs.

Cases
-----
* **T1**: ``<cases>/<family>/<row>.vgcase``; ``case`` = ``<family>/<row>``;
  ``input_sha256`` = sha256 of the file bytes.
* **T3**: the records with ``"verdict": "block"`` in
  ``tests/data/javascript_chai_mutations.json`` at the pinned baseline commit
  (``git show``, never the working tree); ``case`` = ``chai:<id>``;
  ``input_sha256`` = sha256 of the record's canonical JSON
  (``json.dumps(record, sort_keys=True, separators=(",", ":"))``); the label is
  the record's ``verdict``. The pins file's ``[t3.cases]`` maps each T3 case to
  its ``input_sha256``; a missing or drifted map fails and names every added,
  dropped and re-hashed case, which is how a rotation shows its T3 changes.

A ``.vgcase`` file is UTF-8 without BOM and LF-only, and holds inputs only. It is
a sequence of sections; every line of the form ``=== ... ===`` must be one of::

    === meta ===                      key: value lines (``#`` comments, blank lines)
    === options ===                   TOML: today, task, fail_on,
                                      expect_config_errors, expect_skipped
    === base: PATH ===                file in the base commit
    === head: PATH ===                file at HEAD (added, or modified if in base)
    === delete: PATH ===              removed at HEAD (empty body)
    === rename: OLD -> NEW ===        moved at HEAD; body is the new content
    === rename-same: OLD -> NEW ===   moved at HEAD with identical bytes (empty body)
    === base-b64: PATH ===            base64 variants, for bytes a text body
    === head-b64: PATH ===            cannot carry (CR, no final newline at a
    === rename-b64: OLD -> NEW ===    section end, invalid UTF-8)

A text body is the exact text between its header line and the next header (or
the end of the file), final newline included. Paths are relative POSIX paths
that are portable to Windows. ``options.today`` sets ``CHECKWASH_TODAY`` and
``GREENWASH_TODAY`` on top of a copy of ``isolated_env()`` (whose own
``GREENWASH_TODAY`` is 2026-01-01); ``task`` adds ``--task PATH`` and must be a
file at HEAD; ``fail_on`` adds ``--fail-on``; the two ``expect_*`` lists default
to empty.

Per case: fresh ``git init -b main`` (``core.autocrlf=false`` and the other pinned
settings written into the repository's own config, an empty ``core.attributesFile``,
``GIT_ATTR_NOSYSTEM=1``, pinned identity and dates, no global or system config, so
the engines' own git calls see the same settings); commit the base tree (including any
``.checkwash/config.toml`` or ``TASK.md``); apply head, delete and rename sections
and commit; verify both commits hold exactly the declared bytes; record the
``--find-renames`` name-status; run the engines; parse with a strict decoder (no
duplicate keys or non-finite numbers); keep ``{exit, verdict, findings: sorted
[rule, severity, path], config_errors, skipped_files, version}``.

Labels (``labels.toml``) are ``block``, ``pass`` or ``undecided``. Acceptance
entries (``tests/gates/verdict_gate_accepted.toml``) are keyed by ``case`` and
``input_sha256``, with ``kind`` ``known-regression`` | ``fp-fix`` |
``pending-ruling``.

Rules (as #201 states them)
---------------------------
For every case, labelled or not, the candidate's pass **needs an accepted entry**
when the baseline blocks it (transition). It also needs one when the label is
``block`` (label anchor), which keeps the shipped regressions gated after the
release becomes the baseline. ``undecided`` only removes the anchor.

The gate fails on:

- an unlisted pass that needs an entry;
- a stale entry: the case no longer needs one (it blocks again, or neither rule
  applies), its ``input_sha256`` differs, its case is unknown, or it is a
  duplicate. No dead entry survives: the fix PR's change to the acceptance file
  removes it;
- ``kind`` inconsistent with the label (``known-regression`` for ``block``,
  ``fp-fix`` for ``pass``, ``pending-ruling`` for ``undecided``), or a file-level
  ``baseline`` that differs from the pin;
- harness integrity: an identity or control failure on any engine; exit not 0/1
  or inconsistent with the verdict; invalid JSON; a timeout; ``config_errors`` or
  ``skipped_files`` that differ from the case's declared ``expect_config_errors``
  / ``expect_skipped`` (default empty, not a blanket rule; compared as sorted
  lists, on every engine that runs the case); a T1 case without a
  label; drift of the pinned ``baseline_blocked = {count, sha256 of sorted ids}``;
  a canary set mismatch; on a tag-push run, a baseline that is not the highest
  other ``v*`` tag merged into HEAD, or a HEAD that is not the pushed tag's commit.

Reported, not failed, in v1: pass -> block, block -> block with a changed set of
blocking findings, and every ``undecided`` row's verdicts. The issue state behind
an entry is metadata only.

Harness details beyond the #201 text, all failing closed: ``baseline_blocked``'s
sha256 is ``digest(sorted ids)`` (the ``qualify_assertions`` helper); a missing
pin (``baseline_blocked``, ``[canary] block_to_pass`` or ``[t3.cases]``) fails and
prints the observed value as a proposal; a missing acceptance file fails; placeholder values
(``<...>``) in an entry fail; a label for an unknown case, or for a ``chai:`` case,
fails; a case file that does not parse or materialize fails; an engine that
changes the case repository fails; a pushed tag that is not merged into HEAD, or
a baseline tag that does not resolve to the pinned commit, fails. The "blocking
findings" of the block -> block report are the findings at or above the case's
threshold (``options.fail_on``, else the base-side ``[gate] fail_on``, else
``high``) that are not allowlisted. The receipt records what the run observed
(``observed``) and prints proposed entries and pins ready to paste only where an
entry or a pin is missing or has drifted (``proposed``); this tool never writes them.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
from typing import NamedTuple
import unicodedata
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[1]


def _load_qualify_assertions():
    spec = importlib.util.spec_from_file_location(
        "verdict_gate_qualify_assertions", Path(__file__).resolve().parent / "qualify_assertions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_QA = _load_qualify_assertions()
isolated_env = _QA.isolated_env
archive_files = _QA.archive_files
package_files = _QA.package_files
digest = _QA.digest
_require_same = _QA._require_same

SCHEMA_VERSION = 1
DEFAULT_TIMEOUT = 120.0
GIT_TIMEOUT = 120.0
SEVERITY_ORDER = {"info": 0, "warn": 1, "high": 2, "critical": 3}
LABELS = ("block", "pass", "undecided")
KIND_FOR_LABEL = {"block": "known-regression", "pass": "fp-fix", "undecided": "pending-ruling"}
KINDS = tuple(KIND_FOR_LABEL.values())
GATE_ROLES = ("baseline", "candidate")
CANARY_ROLES = ("canary-old", "canary-new")
ROLES = GATE_ROLES + CANARY_ROLES
CHAI_PATH = "tests/data/javascript_chai_mutations.json"
INVALID_REF = "MISSING_VERDICT_GATE_REF"
CONFIG_FILES = (".checkwash/config.toml", ".greenwash/config.toml")
GIT_OPTIONS = (
    "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", "-c", "core.quotepath=false",
    "-c", "core.fsmonitor=false", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false",
    "-c", "init.defaultBranch=main", "-c", "gc.auto=0", "-c", "color.ui=false",
)
CONTROL_ID = "control/identity"

_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
_RECORD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SEMVER_TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_VERSION = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_META_KEY = re.compile(r"[a-z][a-z0-9_]*")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_HEADER = re.compile(
    r"=== (?P<kind>meta|options|base|head|delete|rename|rename-same|base-b64|head-b64|rename-b64)"
    r"(?:: (?P<arg>.+?))? ==="
)
# A line that looks like a header but is not one exactly (trailing space, missing
# inner spaces, other letter case) fails instead of being read as body text.
_LOOSE_HEADER = re.compile(
    r"\s*===\s*(?:meta|options|base|head|delete|rename|rename-same|base-b64|head-b64|rename-b64)\b.*===\s*",
    re.IGNORECASE,
)
_PATH_SECTIONS = ("base", "head", "delete", "base-b64", "head-b64")
_RENAME_SECTIONS = ("rename", "rename-same", "rename-b64")
_UNPORTABLE = set('\\:*?"<>|')
_RESERVED = {
    "con", "prn", "aux", "nul", "conin$", "conout$",
    # Windows also reserves COM and LPT with a superscript digit 1-3 (U+00B9, U+00B2, U+00B3).
    *(f"{device}{suffix}" for device in ("com", "lpt") for suffix in (*"123456789", *map(chr, (0xB9, 0xB2, 0xB3)))),
}
_OPTION_KEYS = ("today", "task", "fail_on", "expect_config_errors", "expect_skipped")
# ``python -m zipapp src -m "checkwash.zipapp_entry:run"`` (release.yml) writes
# exactly this root ``__main__.py``; any other root member is unbound code.
ZIPAPP_MAIN = b"# -*- coding: utf-8 -*-\nimport checkwash.zipapp_entry\ncheckwash.zipapp_entry.run()\n"
# Archive errors a corrupt or unusual zip raises besides OSError/ValueError.
_ZIP_ERRORS = (zipfile.BadZipFile, zipfile.LargeZipFile, zlib.error, RuntimeError, NotImplementedError, EOFError)


class GateError(ValueError):
    """An input or harness problem; the gate records it and fails closed."""


# ---------------------------------------------------------------- strict JSON

def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> object:
    raise ValueError(f"non-finite JSON number {name}")


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(f"non-finite JSON number {text}")
    return value


def loads_strict(data: str | bytes) -> object:
    """Parse JSON, rejecting duplicate keys, NaN/Infinity and overflowing floats.

    Every rejection is a ``ValueError``, including nesting too deep to decode.
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    try:
        return json.loads(data, object_pairs_hook=_reject_duplicates,
                          parse_constant=_reject_constant, parse_float=_finite_float)
    except RecursionError:
        raise ValueError("JSON nesting is too deep") from None


# ---------------------------------------------------------------- small helpers

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _toml_str(value: str) -> str:
    out = ['"']
    for char in value:
        code = ord(char)
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif code < 0x20 or code == 0x7F:
            out.append("\\u%04x" % code)
        else:
            out.append(char)
    out.append('"')
    return "".join(out)


def _rmtree(path: Path) -> None:
    """Remove a tree; git object files are read-only on Windows."""
    if not path.exists():
        return

    def retry(function, target, _excinfo):
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=retry)
    else:  # pragma: no cover - exercised on the 3.11 CI legs
        shutil.rmtree(path, onerror=retry)


def _is_placeholder(value: object) -> bool:
    return isinstance(value, str) and value.strip().startswith("<") and value.strip().endswith(">")


def _safe_path(raw: object, where: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise GateError(f"{where}: empty path")
    if raw != raw.strip():
        raise GateError(f"{where}: path {raw!r} has leading or trailing whitespace")
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise GateError(f"{where}: path {raw!r} has a control character")
    if unicodedata.normalize("NFC", raw) != raw:
        raise GateError(f"{where}: path {raw!r} is not in Unicode NFC form, which is not portable to macOS")
    if any(char in _UNPORTABLE for char in raw):
        raise GateError(f"{where}: path {raw!r} has a character that is not portable to Windows")
    if raw.startswith("/") or PurePosixPath(raw).is_absolute():
        raise GateError(f"{where}: path {raw!r} is absolute")
    for part in raw.split("/"):
        if part in ("", ".", ".."):
            raise GateError(f"{where}: path {raw!r} has an empty, '.' or '..' part")
        if part.casefold() == ".git":
            raise GateError(f"{where}: path {raw!r} enters .git")
        if part.endswith((" ", ".")):
            raise GateError(f"{where}: path {raw!r} has a part ending in a space or dot")
        if part.split(".")[0].casefold() in _RESERVED:
            raise GateError(f"{where}: path {raw!r} uses a reserved Windows device name")
    return raw


def _check_tree(tree: dict[str, bytes], where: str) -> None:
    """Reject trees that cannot be written identically on every OS."""
    files: dict[str, str] = {}
    for path in tree:
        folded = path.casefold()
        if folded in files:
            raise GateError(f"{where}: paths {files[folded]!r} and {path!r} differ only in case")
        files[folded] = path
    directories: dict[str, str] = {}
    for path in sorted(tree):
        parts = path.split("/")
        for depth in range(1, len(parts)):
            prefix = "/".join(parts[:depth])
            if prefix.casefold() in files:
                raise GateError(f"{where}: {files[prefix.casefold()]!r} is both a file and a directory of {path!r}")
            seen = directories.setdefault(prefix.casefold(), prefix)
            if seen != prefix:
                raise GateError(f"{where}: directories {seen!r} and {prefix!r} differ only in case")


# ---------------------------------------------------------------- cases

def _default_options() -> dict:
    return {"today": None, "task": None, "fail_on": None, "expect_config_errors": [], "expect_skipped": []}


class Case:
    """One parsed case. A plain class, not a dataclass: tests load this module by
    path without registering it in ``sys.modules``, which dataclasses require."""

    def __init__(self, *, id: str, tier: str, input_sha256: str, meta: dict, options: dict,
                 base: dict[str, bytes], head: dict[str, bytes], ops: list[dict], threshold: str = "high",
                 label: str | None = None) -> None:
        self.id = id
        self.tier = tier
        self.input_sha256 = input_sha256
        self.meta = meta
        self.options = options
        self.base = base
        self.head = head
        self.ops = ops
        self.threshold = threshold
        self.label = label  # T3 only: the record's verdict

    @property
    def issue(self) -> int | None:
        value = self.meta.get("issue", "")
        return int(value) if value.isdigit() and int(value) > 0 else None


def _parse_meta(body: str, fail) -> dict:
    meta: dict[str, str] = {}
    for number, line in enumerate(body.split("\n"), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        key = key.strip()
        if not separator or not _META_KEY.fullmatch(key):
            fail(f"meta line {number} is not 'key: value'")
        if key in meta:
            fail(f"meta key {key!r} appears twice")
        meta[key] = value.strip()
    return meta


def _parse_options(body: str, fail) -> dict:
    try:
        raw = tomllib.loads(body)
    except tomllib.TOMLDecodeError as error:
        fail(f"options are not valid TOML: {error}")
    unknown = sorted(set(raw) - set(_OPTION_KEYS))
    if unknown:
        fail(f"unknown option(s) {', '.join(unknown)}; allowed: {', '.join(_OPTION_KEYS)}")
    options = _default_options()
    if "today" in raw:
        today = raw["today"]
        if type(today) is datetime.date:
            today = today.isoformat()
        if not isinstance(today, str) or not _DATE.fullmatch(today):
            fail("options.today must be a YYYY-MM-DD date")
        try:
            datetime.date.fromisoformat(today)
        except ValueError:
            fail(f"options.today {today!r} is not a valid date")
        options["today"] = today
    if "task" in raw:
        try:
            options["task"] = _safe_path(raw["task"], "options.task")
        except GateError as error:
            fail(str(error))
        if options["task"].startswith("-"):
            fail(f"options.task {options['task']!r} starts with '-', which the CLI would read as an option")
    if "fail_on" in raw:
        if not isinstance(raw["fail_on"], str) or raw["fail_on"] not in SEVERITY_ORDER:
            fail(f"options.fail_on must be one of {', '.join(SEVERITY_ORDER)}")
        options["fail_on"] = raw["fail_on"]
    for key in ("expect_config_errors", "expect_skipped"):
        if key in raw:
            value = raw[key]
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                fail(f"options.{key} must be a list of strings")
            options[key] = list(value)
    return options


def _case_threshold(options: dict, base: dict[str, bytes]) -> str:
    """The severity at which the case's verdict blocks: option, base config, default.

    The base config is read the way the engine's ``load_config`` reads it
    (``utf-8-sig`` with replacement, ``[gate]`` must be a table, ``fail_on`` a
    known severity, else ``high``).
    """
    if options["fail_on"]:
        return options["fail_on"]
    for name in CONFIG_FILES:
        if name in base:
            if not base[name]:
                return "high"
            try:
                raw = tomllib.loads(base[name].decode("utf-8-sig", errors="replace"))
            except tomllib.TOMLDecodeError:
                return "high"
            gate = raw.get("gate", {})
            value = gate.get("fail_on") if isinstance(gate, dict) else None
            return value if isinstance(value, str) and value in SEVERITY_ORDER else "high"
    return "high"


def _sections(text: str, fail) -> list[tuple[str, str | None, int, str]]:
    sections: list[tuple[str, str | None, int, str]] = []
    current: tuple[str, str | None, int] | None = None
    body_start = 0
    position = 0
    for number, line in enumerate(text.split("\n"), 1):
        start = position
        position += len(line) + 1
        if not (line.startswith("=== ") and line.endswith(" ===") and len(line) >= 8):
            if _LOOSE_HEADER.fullmatch(line):
                fail(f"line {number}: malformed section header {line!r}; headers are exactly '=== KIND[: ARG] ==='")
            continue
        match = _HEADER.fullmatch(line)
        if match is None:
            fail(f"line {number}: unknown section header {line!r}")
        if current is None:
            if start:
                fail("text before the first section header")
        else:
            sections.append((*current, text[body_start:start]))
        current = (match.group("kind"), match.group("arg"), number)
        body_start = min(position, len(text))
    if current is None:
        fail("no section headers")
    sections.append((*current, text[body_start:]))
    return sections


def _b64(body: str, fail, number: int) -> bytes:
    compact = "".join(body.split())
    try:
        return base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        fail(f"line {number}: invalid base64 body")


def parse_case(data: bytes, case_id: str, tier: str = "T1") -> Case:
    """Parse one ``.vgcase`` file; every problem raises ``GateError``."""

    def fail(message: str):
        raise GateError(f"{case_id}: {message}")

    if data.startswith(b"\xef\xbb\xbf"):
        fail("starts with a UTF-8 BOM")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        fail(f"not UTF-8 (byte {error.start})")
    if "\r" in text:
        fail("contains a carriage return; case files are LF-only (use a -b64 section for CR bytes)")
    meta: dict | None = None
    options: dict | None = None
    base: dict[str, bytes] = {}
    heads: dict[str, bytes] = {}
    deletes: list[str] = []
    renames: dict[str, tuple[str, bytes | None]] = {}
    ops: list[dict] = []
    for kind, arg, number, body in _sections(text, fail):
        where = f"line {number}"
        if kind in ("meta", "options"):
            if arg is not None:
                fail(f"{where}: === {kind} === takes no argument")
            if kind == "meta":
                if meta is not None:
                    fail(f"{where}: second meta section")
                meta = _parse_meta(body, fail)
            else:
                if options is not None:
                    fail(f"{where}: second options section")
                options = _parse_options(body, fail)
            continue
        if arg is None:
            fail(f"{where}: === {kind} === needs a path")
        if kind in _RENAME_SECTIONS:
            pair = arg.split(" -> ")
            if len(pair) != 2:
                fail(f"{where}: rename needs exactly 'OLD -> NEW'")
            old, new = (_safe_path(item, f"{case_id} {where}") for item in pair)
            if old == new:
                fail(f"{where}: rename source and target are the same path")
            if kind == "rename-same":
                if body:
                    fail(f"{where}: rename-same keeps the bytes and takes an empty body")
                content = None
            else:
                content = _b64(body, fail, number) if kind == "rename-b64" else body.encode("utf-8")
            if old in renames:
                fail(f"{where}: {old!r} is renamed twice")
            renames[old] = (new, content)
            ops.append({"op": kind, "from": old, "to": new})
            continue
        path = _safe_path(arg, f"{case_id} {where}")
        if kind == "delete":
            if body:
                fail(f"{where}: delete takes an empty body")
            if path in deletes:
                fail(f"{where}: {path!r} is deleted twice")
            deletes.append(path)
            ops.append({"op": "delete", "path": path})
            continue
        content = _b64(body, fail, number) if kind.endswith("-b64") else body.encode("utf-8")
        if kind.startswith("base"):
            if path in base:
                fail(f"{where}: base file {path!r} appears twice")
            base[path] = content
        else:
            if path in heads:
                fail(f"{where}: head file {path!r} appears twice")
            heads[path] = content
            ops.append({"op": kind, "path": path})
    touched = [*heads, *deletes, *renames, *(new for new, _ in renames.values())]
    duplicates = sorted({path for path in touched if touched.count(path) > 1})
    if duplicates:
        fail(f"path(s) changed by more than one section: {', '.join(duplicates)}")
    if not touched:
        fail("the case changes nothing (no head, delete or rename section)")
    for path in deletes:
        if path not in base:
            fail(f"delete of {path!r}, which is not a base file")
    for old, (new, _content) in renames.items():
        if old not in base:
            fail(f"rename of {old!r}, which is not a base file")
        if new in base:
            fail(f"rename target {new!r} already exists in base")
    for path, content in heads.items():
        if base.get(path) == content:
            fail(f"head section for {path!r} does not change it")
    head = dict(base)
    for path in deletes:
        del head[path]
    for old, (new, content) in renames.items():
        moved = head.pop(old)
        head[new] = moved if content is None else content
    head.update(heads)
    _check_tree(base, f"{case_id} base")
    _check_tree(head, f"{case_id} head")
    removed = {path.casefold(): path for path in base if path not in head}
    for path in head:
        if path not in base and removed.get(path.casefold(), path) != path:
            fail(f"{removed[path.casefold()]!r} -> {path!r} changes only letter case, which is not portable")
    options = options or _default_options()
    if options["task"] is not None and options["task"] not in head:
        fail(f"options.task {options['task']!r} is not a file at HEAD")
    return Case(
        id=case_id, tier=tier, input_sha256=_sha256(data), meta=meta or {}, options=options,
        base=base, head=head, ops=ops, threshold=_case_threshold(options, base),
    )


def load_cases(cases_dir: Path) -> tuple[list[Case], list[str], list[str]]:
    """Return (parsed T1 cases, ids of files that failed to parse, errors)."""
    if not cases_dir.is_dir():
        raise GateError(f"cases directory {cases_dir.name!r} does not exist")
    cases: list[Case] = []
    invalid: list[str] = []
    errors: list[str] = []
    for path in sorted(cases_dir.rglob("*"), key=lambda item: item.relative_to(cases_dir).as_posix()):
        relative = path.relative_to(cases_dir).as_posix()
        if path.is_symlink():
            errors.append(f"{relative}: symbolic links are not case files")
            continue
        if path.is_dir():
            continue
        parts = relative.split("/")
        if len(parts) != 2 or not parts[1].endswith(".vgcase"):
            errors.append(f"{relative}: unexpected file; case files are <family>/<row>.vgcase")
            continue
        case_id = parts[0] + "/" + parts[1][: -len(".vgcase")]
        if not _CASE_ID.fullmatch(case_id):
            errors.append(f"{relative}: case id {case_id!r} is not [A-Za-z0-9._-]/[A-Za-z0-9._-]")
            continue
        try:
            cases.append(parse_case(path.read_bytes(), case_id))
        except GateError as error:
            errors.append(str(error))
            invalid.append(case_id)
    seen: dict[str, str] = {}
    for case_id in [case.id for case in cases] + invalid:
        if case_id.casefold() in seen:
            errors.append(f"case ids {seen[case_id.casefold()]!r} and {case_id!r} differ only in case")
        seen.setdefault(case_id.casefold(), case_id)
    if not cases and not invalid and not errors:
        errors.append("no .vgcase files under the cases directory")
    return cases, sorted(invalid), errors


def load_chai_cases(path: Path) -> tuple[list[Case], dict]:
    """T3 from a chai mutation file on disk (the ``cases --chai`` listing)."""
    try:
        data = path.read_bytes()
    except OSError as error:
        raise GateError(f"cannot read {CHAI_PATH} in the baseline checkout: {error.strerror}") from None
    return parse_chai_cases(data)


def load_chai_cases_at(source: Path, commit: str) -> tuple[list[Case], dict]:
    """T3 from the pinned baseline commit itself (``git show``), never from the
    checkout's working tree, so a local edit of the file cannot change the cases."""
    try:
        data = _git(source, "show", f"{commit}:{CHAI_PATH}")
    except GateError as error:
        raise GateError(f"cannot read {CHAI_PATH} at the pinned baseline commit: {error}") from None
    cases, info = parse_chai_cases(data)
    return cases, {**info, "commit": commit}


def parse_chai_cases(data: bytes) -> tuple[list[Case], dict]:
    """T3: the block records of the baseline tag's chai mutation file."""
    try:
        document = loads_strict(data)
    except ValueError as error:
        raise GateError(f"{CHAI_PATH}: invalid JSON: {error}") from None
    if not isinstance(document, dict) or not isinstance(document.get("mutations"), list):
        raise GateError(f"{CHAI_PATH}: expected an object with a 'mutations' array")
    cases: list[Case] = []
    seen: set[str] = set()
    other = 0
    for index, record in enumerate(document["mutations"]):
        where = f"{CHAI_PATH} record {index}"
        if not isinstance(record, dict):
            raise GateError(f"{where}: not an object")
        record_id = record.get("id")
        if not isinstance(record_id, str) or not _RECORD_ID.fullmatch(record_id):
            raise GateError(f"{where}: invalid id {record_id!r}")
        if record_id in seen:
            raise GateError(f"{where}: duplicate id {record_id!r}")
        seen.add(record_id)
        for key in ("before", "after"):
            if not isinstance(record.get(key), str):
                raise GateError(f"{where}: {key} is not a string")
        if record.get("verdict") not in ("block", "pass"):
            raise GateError(f"{where}: verdict must be 'block' or 'pass'")
        path_name = _safe_path(record.get("path"), where)
        if record["verdict"] != "block":
            other += 1
            continue
        if record["before"] == record["after"]:
            raise GateError(f"{where}: before and after are identical")
        cases.append(Case(
            id="chai:" + record_id, tier="T3", input_sha256=digest(record), meta={},
            options=_default_options(), base={path_name: record["before"].encode("utf-8")},
            head={path_name: record["after"].encode("utf-8")},
            ops=[{"op": "head", "path": path_name}], label="block",
        ))
    return cases, {"path": CHAI_PATH, "sha256": _sha256(data), "block_records": len(cases), "other_records": other}


# ---------------------------------------------------------------- labels, pins, acceptance

def _load_toml(path: Path, what: str) -> dict:
    try:
        text = path.read_bytes().decode("utf-8")
    except OSError as error:
        raise GateError(f"cannot read {what} {path.name!r}: {error.strerror}") from None
    except UnicodeDecodeError:
        raise GateError(f"{what} {path.name!r} is not UTF-8") from None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise GateError(f"{what} {path.name!r} is not valid TOML: {error}") from None


def _require_keys(table: object, where: str, required: set[str], optional: set[str] = frozenset()) -> dict:
    if not isinstance(table, dict):
        raise GateError(f"{where} must be a table")
    missing = sorted(required - set(table))
    unknown = sorted(set(table) - required - set(optional))
    if missing:
        raise GateError(f"{where}: missing key(s) {', '.join(missing)}")
    if unknown:
        raise GateError(f"{where}: unknown key(s) {', '.join(unknown)}")
    return table


def load_labels(path: Path) -> dict[str, str]:
    document = _require_keys(_load_toml(path, "labels file"), "labels file", {"schema_version", "labels"})
    if document["schema_version"] != SCHEMA_VERSION or isinstance(document["schema_version"], bool):
        raise GateError(f"labels file: schema_version must be {SCHEMA_VERSION}")
    labels = document["labels"]
    if not isinstance(labels, dict):
        raise GateError("labels file: [labels] must be a table")
    for case_id, label in labels.items():
        if label not in LABELS:
            raise GateError(f"labels file: {case_id!r} has label {label!r}; allowed: {', '.join(LABELS)}")
    return dict(sorted(labels.items()))


def _engine_pin(table: object, where: str) -> dict:
    pin = _require_keys(table, where, {"tag", "version", "commit", "sha256", "size"})
    if not isinstance(pin["version"], str) or not _VERSION.fullmatch(pin["version"]):
        raise GateError(f"{where}.version must be MAJOR.MINOR.PATCH")
    if pin["tag"] != "v" + pin["version"]:
        raise GateError(f"{where}.tag must be 'v' + version")
    if not isinstance(pin["commit"], str) or not _HEX40.fullmatch(pin["commit"]):
        raise GateError(f"{where}.commit must be a full lowercase commit sha")
    if not isinstance(pin["sha256"], str) or not _HEX64.fullmatch(pin["sha256"]):
        raise GateError(f"{where}.sha256 must be 64 lowercase hex digits")
    if type(pin["size"]) is not int or pin["size"] <= 0:
        raise GateError(f"{where}.size must be a positive integer")
    return dict(pin)


def load_pins(path: Path) -> dict:
    document = _require_keys(_load_toml(path, "pins file"), "pins file",
                             {"schema_version", "baseline"}, {"baseline_blocked", "canary", "t3"})
    if document["schema_version"] != SCHEMA_VERSION or isinstance(document["schema_version"], bool):
        raise GateError(f"pins file: schema_version must be {SCHEMA_VERSION}")
    pins = {"baseline": _engine_pin(document["baseline"], "[baseline]"), "baseline_blocked": None, "canary": None,
            "t3": None}
    if "t3" in document:
        cases = _require_keys(document["t3"], "[t3]", {"cases"})["cases"]
        if not isinstance(cases, dict):
            raise GateError("[t3.cases] must be a table of chai case id = input_sha256")
        for case_id, sha in cases.items():
            if not case_id.startswith("chai:") or not _RECORD_ID.fullmatch(case_id[len("chai:"):]):
                raise GateError(f"[t3.cases]: {case_id!r} is not a chai:<id> case id")
            if not isinstance(sha, str) or not _HEX64.fullmatch(sha):
                raise GateError(f"[t3.cases]: {case_id!r} must map to 64 lowercase hex digits")
        pins["t3"] = dict(sorted(cases.items()))
    if "baseline_blocked" in document:
        blocked = _require_keys(document["baseline_blocked"], "[baseline_blocked]", {"count", "sha256"})
        if type(blocked["count"]) is not int or blocked["count"] < 0:
            raise GateError("[baseline_blocked].count must be a non-negative integer")
        if not isinstance(blocked["sha256"], str) or not _HEX64.fullmatch(blocked["sha256"]):
            raise GateError("[baseline_blocked].sha256 must be 64 lowercase hex digits")
        pins["baseline_blocked"] = dict(blocked)
    if "canary" in document:
        canary = _require_keys(document["canary"], "[canary]", {"old", "new"}, {"block_to_pass"})
        pins["canary"] = {"old": _engine_pin(canary["old"], "[canary.old]"),
                          "new": _engine_pin(canary["new"], "[canary.new]"), "block_to_pass": None}
        if "block_to_pass" in canary:
            ids = canary["block_to_pass"]
            if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                raise GateError("[canary].block_to_pass must be a list of case ids")
            if len(set(ids)) != len(ids):
                raise GateError("[canary].block_to_pass has duplicate ids")
            pins["canary"]["block_to_pass"] = sorted(ids)
    return pins


def load_acceptance(path: Path) -> dict:
    document = _require_keys(_load_toml(path, "acceptance file"), "acceptance file", {"baseline"}, {"accept"})
    if not isinstance(document["baseline"], str):
        raise GateError("acceptance file: baseline must be a tag string")
    raw_entries = document.get("accept", [])
    if not isinstance(raw_entries, list):
        raise GateError("acceptance file: accept must be an array of tables ([[accept]])")
    entries = []
    for index, raw in enumerate(raw_entries, 1):
        where = f"[[accept]] #{index}"
        kind = raw.get("kind") if isinstance(raw, dict) else None
        required = {"case", "input_sha256", "kind", "reason", "reviewed_in"}
        if kind in ("known-regression", "pending-ruling"):
            required = required | {"issue"}
        entry = _require_keys(raw, where, required, {"issue"})
        if not isinstance(entry["case"], str) or not entry["case"]:
            raise GateError(f"{where}: case must be a case id")
        where = f"{where} ({entry['case']})"
        if not isinstance(entry["input_sha256"], str) or not _HEX64.fullmatch(entry["input_sha256"]):
            raise GateError(f"{where}: input_sha256 must be 64 lowercase hex digits")
        if kind not in KINDS:
            raise GateError(f"{where}: kind must be one of {', '.join(KINDS)}")
        if "issue" in entry and (type(entry["issue"]) is not int or entry["issue"] <= 0):
            raise GateError(f"{where}: issue must be a positive issue number")
        if not isinstance(entry["reason"], str) or not entry["reason"].strip() or _is_placeholder(entry["reason"]):
            raise GateError(f"{where}: reason must be a filled-in, non-empty string")
        reviewed = entry["reviewed_in"]
        if not ((type(reviewed) is int and reviewed > 0) or (isinstance(reviewed, str) and reviewed.isdigit()
                                                             and reviewed.isascii() and int(reviewed) > 0)):
            raise GateError(f"{where}: reviewed_in must be the number of the PR that adds the entry")
        entries.append({**entry, "index": index})
    return {"baseline": document["baseline"], "entries": entries}


# ---------------------------------------------------------------- git and materialization

def base_env() -> dict[str, str]:
    """A copy of ``isolated_env()`` that also ignores the system gitattributes file."""
    env = dict(isolated_env())
    env["GIT_ATTR_NOSYSTEM"] = "1"
    return env


def _scrub_forms(path: Path) -> tuple[str, ...]:
    """Every spelling of a path that git or an engine may print, for stderr scrubbing."""
    forms = {str(path), path.as_posix()}
    try:
        resolved = path.resolve()
        forms |= {str(resolved), resolved.as_posix()}
    except OSError:
        pass
    return tuple(sorted(forms, key=len, reverse=True))


def _git(repo: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(["git", *GIT_OPTIONS, *args], cwd=repo, env=base_env(),
                                stdin=subprocess.DEVNULL, capture_output=True, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as error:
        raise GateError(f"git {args[0]} could not run: {error}") from None
    if result.returncode:
        message = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise GateError(f"git {args[0]} failed: {message[-1] if message else 'exit ' + str(result.returncode)}")
    return result.stdout


def _git_text(repo: Path, *args: str) -> str:
    return _git(repo, *args).decode("utf-8", "replace").strip()


def _tree_listing(repo: Path, revision: str) -> dict[str, tuple[str, str]]:
    listing = {}
    for record in _git(repo, "ls-tree", "-r", "-z", "--full-tree", revision).split(b"\0"):
        if not record:
            continue
        meta, _, name = record.partition(b"\t")
        mode, _kind, sha = meta.decode("ascii").split(" ")
        listing[name.decode("utf-8")] = (mode, sha)
    return listing


def _verify_tree(repo: Path, revision: str, tree: dict[str, bytes], where: str) -> None:
    expected = {path: ("100644", _blob_sha1(data)) for path, data in tree.items()}
    actual = _tree_listing(repo, revision)
    changed = sorted(path for path in set(expected) | set(actual) if expected.get(path) != actual.get(path))
    if changed:
        raise GateError(f"{where}: {revision} does not hold the declared bytes: {', '.join(changed[:8])}")


def _name_status(repo: Path) -> list[list[str]]:
    tokens = _git(repo, "diff", "--find-renames", "--name-status", "-z", "HEAD~1", "HEAD").split(b"\0")
    rows: list[list[str]] = []
    index = 0
    while index < len(tokens) and tokens[index]:
        status = tokens[index].decode("ascii")
        width = 2 if status[:1] in ("R", "C") else 1
        rows.append([status, *(token.decode("utf-8") for token in tokens[index + 1:index + 1 + width])])
        index += 1 + width
    return rows


def _write_file(repo: Path, path: str, data: bytes) -> None:
    target = repo.joinpath(*path.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def _remove_file(repo: Path, path: str) -> None:
    target = repo.joinpath(*path.split("/"))
    target.unlink()
    parent = target.parent
    while parent != repo and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


REPO_CONFIG = (("core.autocrlf", "false"), ("core.safecrlf", "false"), ("core.quotepath", "false"),
               ("core.fsmonitor", "false"))
EMPTY_ATTRIBUTES = "verdict-gate-empty-attributes"


def _pin_repo_config(repo: Path) -> None:
    """Write the pinned git settings into the case repository's own config, so the
    engine's git processes see them too, and point ``core.attributesFile`` at an empty
    file so no host-wide gitattributes (``~/.config/git/attributes``) applies."""
    for key, value in REPO_CONFIG:
        _git(repo, "config", key, value)
    empty = repo / ".git" / EMPTY_ATTRIBUTES
    empty.write_bytes(b"")
    _git(repo, "config", "core.attributesFile", empty.resolve().as_posix())


def materialize_safely(case: Case, repo: Path) -> tuple[list[list[str]] | None, str | None]:
    """``materialize`` with every failure as a message: (name-status rows, None) or (None, why)."""
    try:
        return materialize(case, repo), None
    except GateError as error:
        return None, str(error)
    except OSError as error:
        return None, f"{case.id}: cannot write the case repository: {error.strerror or type(error).__name__}"


def remove_safely(path: Path) -> str | None:
    """Remove a scratch tree; return why it could not be removed, without the host path."""
    try:
        _rmtree(path)
    except OSError as error:
        return f"cannot remove a scratch directory: {error.strerror or type(error).__name__}"
    return None


def materialize(case: Case, repo: Path) -> list[list[str]]:
    """Build the two-commit repository for a case; return the name-status rows."""
    if repo.exists() and any(repo.iterdir()):
        raise GateError(f"{case.id}: materialization target is not empty")
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "--object-format=sha1", "-b", "main")
    _pin_repo_config(repo)
    for path, data in sorted(case.base.items()):
        _write_file(repo, path, data)
    _git(repo, "add", "--all", "--force")
    _git(repo, "commit", "-q", "--allow-empty", "--no-verify", "-m", "base " + case.id)
    for path in sorted(set(case.base) - set(case.head)):
        _remove_file(repo, path)
    for path, data in sorted(case.head.items()):
        if case.base.get(path) != data:
            _write_file(repo, path, data)
    _git(repo, "add", "--all", "--force")
    _git(repo, "commit", "-q", "--no-verify", "-m", "head " + case.id)
    _verify_tree(repo, "HEAD~1", case.base, case.id)
    _verify_tree(repo, "HEAD", case.head, case.id)
    if _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored"):
        raise GateError(f"{case.id}: worktree differs from HEAD after materialization")
    return _name_status(repo)


CONTROL_CASE = Case(
    id=CONTROL_ID, tier="control", input_sha256="0" * 64, meta={}, options=_default_options(),
    base={"control.txt": b"before\n"}, head={"control.txt": b"after\n"},
    ops=[{"op": "head", "path": "control.txt"}],
)


# ---------------------------------------------------------------- engines

class Engine(NamedTuple):
    role: str
    python: str
    pyz: Path
    source: Path
    pin: dict | None = None


def _project_version(source: Path) -> str:
    try:
        version = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError):
        raise GateError("cannot read project.version from the source checkout's pyproject.toml") from None
    if not isinstance(version, str):
        raise GateError("project.version in the source checkout is not a string")
    return version


def _stderr_tail(stderr: bytes, scrub: tuple[str, ...]) -> str:
    text = stderr.decode("utf-8", "replace")
    for value in scrub:
        if value:
            text = text.replace(value, "<repo>")
    text = " ".join(text.split())
    return text[-300:] if text else "(no stderr)"


def _empty_observation(exit_code: int | None) -> dict:
    return {"exit": exit_code, "verdict": None, "findings": [], "blocking": [], "config_errors": None,
            "skipped_files": None, "version": None, "errors": []}


def _finding_key(row: list) -> tuple:
    return (row[0], row[1], row[2] is None, row[2] or "")


def observe(returncode: int, stdout: bytes, stderr: bytes, *, version: str, threshold: str = "high",
            scrub: tuple[str, ...] = ()) -> dict:
    """Reduce one engine run to the kept fields; every integrity problem lands in ``errors``."""
    observation = _empty_observation(returncode)
    errors = observation["errors"]
    if returncode not in (0, 1):
        errors.append(f"exit {returncode} (expected 0 or 1): {_stderr_tail(stderr, scrub)}")
    try:
        payload = loads_strict(stdout)
    except ValueError as error:
        errors.append(f"invalid JSON report: {error}")
        return observation
    if not isinstance(payload, dict):
        errors.append("invalid JSON report: root is not an object")
        return observation
    verdict = payload.get("verdict")
    if verdict not in ("pass", "block"):
        errors.append(f"verdict {verdict!r} is not 'pass' or 'block'")
    else:
        observation["verdict"] = verdict
        if returncode in (0, 1) and returncode != (1 if verdict == "block" else 0):
            errors.append(f"exit {returncode} is inconsistent with verdict {verdict!r}")
    findings = payload.get("findings")
    if not isinstance(findings, list) or any(not isinstance(row, dict) for row in findings):
        errors.append("findings is not an array of objects")
    else:
        kept, blocking = [], []
        for row in findings:
            rule, severity, path = row.get("rule"), row.get("severity"), row.get("path")
            allowlisted = row.get("allowlisted", False)
            if (not isinstance(rule, str) or not isinstance(severity, str) or severity not in SEVERITY_ORDER
                    or not (path is None or isinstance(path, str)) or not isinstance(allowlisted, bool)):
                errors.append(f"malformed finding {json.dumps(row, sort_keys=True)[:200]}")
                continue
            kept.append([rule, severity, path])
            if not allowlisted and SEVERITY_ORDER[severity] >= SEVERITY_ORDER[threshold]:
                blocking.append([rule, severity, path])
        observation["findings"] = sorted(kept, key=_finding_key)
        observation["blocking"] = sorted(blocking, key=_finding_key)
    for key in ("config_errors", "skipped_files"):
        value = payload.get(key)
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(f"{key} is not an array of strings")
        else:
            observation[key] = list(value)
    run = payload.get("run")
    reported = run.get("checkwash_version") if isinstance(run, dict) else None
    observation["version"] = reported if isinstance(reported, str) else None
    if reported != version:
        errors.append(f"run.checkwash_version {reported!r} differs from the engine version {version!r}")
    return observation


def _run_cli(engine: Engine, args: list[str], cwd: Path, env: dict[str, str], timeout: float):
    return subprocess.run([engine.python, "-B", "-I", str(engine.pyz), *args], cwd=cwd, env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)


def case_env(case: Case) -> dict[str, str]:
    env = base_env()
    if case.options["today"]:
        env["CHECKWASH_TODAY"] = case.options["today"]
        env["GREENWASH_TODAY"] = case.options["today"]
    return env


def case_arguments(case: Case) -> list[str]:
    args = ["check", "HEAD~1..HEAD", "--format", "json"]
    if case.options["task"]:
        args += ["--task", case.options["task"]]
    if case.options["fail_on"]:
        args += ["--fail-on", case.options["fail_on"]]
    return args


def run_engine(engine: Engine, version: str, case: Case, repo: Path, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Run one verified engine on a materialized case."""
    try:
        result = _run_cli(engine, case_arguments(case), repo, case_env(case), timeout)
    except subprocess.TimeoutExpired:
        observation = _empty_observation(None)
        observation["errors"].append(f"timeout after {timeout:g} s")
        return observation
    except OSError as error:
        observation = _empty_observation(None)
        observation["errors"].append(f"engine could not start: {error.strerror}")
        return observation
    observation = observe(result.returncode, result.stdout, result.stderr, version=version,
                          threshold=case.threshold, scrub=_scrub_forms(repo))
    try:
        if _git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored"):
            observation["errors"].append("engine changed the case repository")
    except GateError as error:
        observation["errors"].append(str(error))
    return observation


def archive_extras(artifact: Path) -> list[str]:
    """Members that ``archive_files`` does not bind, each a problem unless it is the
    recipe's ``__main__.py``, a ``checkwash/`` directory entry, or bytecode under
    ``__pycache__`` (zipimport never loads it from there)."""
    problems = []
    with zipfile.ZipFile(artifact) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            problems.append("artifact has duplicate member names")
        for name in sorted(set(names)):
            if "\\" in name:
                problems.append(f"artifact member {name!r} has a backslash")
            elif name == "__main__.py":
                if archive.read(name) != ZIPAPP_MAIN:
                    problems.append("artifact __main__.py is not the release recipe's "
                                    "'checkwash.zipapp_entry:run' entry point")
            elif not name.startswith("checkwash/"):
                problems.append(f"artifact member {name!r} is outside checkwash/")
            elif name.endswith(".pyc") and "__pycache__" not in PurePosixPath(name).parts:
                problems.append(f"artifact member {name!r} is bytecode that zipimport would load")
    return problems


def source_changes(source: Path) -> list[str]:
    """Changed, untracked or ignored files under ``src/checkwash`` and ``pyproject.toml``,
    except the bytecode ``package_files`` skips too."""
    output = _git(source, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored", "--",
                  "src/checkwash", "pyproject.toml")
    tokens = output.split(b"\0")
    changed = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        status, path = token[:2].decode("ascii", "replace"), token[3:].decode("utf-8", "replace")
        if "R" in status or "C" in status:
            index += 1  # the rename or copy source follows as its own token
        if status == "!!" and ("__pycache__" in PurePosixPath(path).parts or path.endswith(".pyc")):
            continue
        changed.append(path)
    return sorted(changed)


def verify_identity(engine: Engine, work_dir: Path, timeout: float = DEFAULT_TIMEOUT,
                    reuse: dict | None = None) -> dict:
    """Pin, member, commit, version and control checks; never runs bytes that fail a static check.

    ``reuse``: a passed record of another role with the same sha256 and version; its
    process checks (``--version`` and the two controls) are copied, not re-run, and the
    copy is recorded as ``controls_from``. The static checks always run per role.
    """
    pin = engine.pin
    record = {
        "role": engine.role, "artifact": engine.pyz.name, "pin": pin, "sha256": None, "size": None,
        "members": None, "members_sha256": None, "source_commit": None, "source_version": None,
        "expected_version": pin["version"] if pin else None, "cli_version": None,
        "controls": {"clean_range": "not run", "invalid_ref": "not run"},
        "proposed_pin": None, "observations_from": None, "controls_from": None, "errors": [],
    }
    errors = record["errors"]
    try:
        data = engine.pyz.read_bytes()
    except OSError as error:
        errors.append(f"cannot read artifact {engine.pyz.name!r}: {error.strerror}")
        return record
    record["sha256"], record["size"] = _sha256(data), len(data)
    bytes_pinned = True
    if pin is not None:
        if record["sha256"] != pin["sha256"]:
            errors.append(f"sha256 {record['sha256']} differs from the pinned {pin['sha256']}")
            bytes_pinned = False
        if record["size"] != pin["size"]:
            errors.append(f"size {record['size']} differs from the pinned {pin['size']}")
            bytes_pinned = False
    other_checks_ok = True
    try:
        expected = package_files(engine.source / "src" / "checkwash")
        if not expected:
            raise ValueError("source checkout has no src/checkwash package")
        members = archive_files(engine.pyz)
        record["members"], record["members_sha256"] = len(members), digest(members)
        _require_same(expected, members, "artifact checkwash/* members")
        extras = archive_extras(engine.pyz)
        if extras:
            raise ValueError("; ".join(extras))
    except OSError as error:
        errors.append(f"cannot read the source package or the artifact: {error.strerror or type(error).__name__}")
        other_checks_ok = False
    except ValueError as error:
        errors.append(str(error))
        other_checks_ok = False
    except _ZIP_ERRORS as error:
        errors.append(f"artifact unreadable as a zip: {type(error).__name__}: {error}")
        other_checks_ok = False
    try:
        record["source_commit"] = _git_text(engine.source, "rev-parse", "--verify", "HEAD^{commit}")
        if pin is not None and record["source_commit"] != pin["commit"]:
            errors.append(f"source checkout is at {record['source_commit']}, not the pinned {pin['commit']}")
            other_checks_ok = False
        if source_changes(engine.source):
            errors.append("source checkout has local changes under src/checkwash or pyproject.toml")
            other_checks_ok = False
    except GateError as error:
        errors.append(f"source checkout: {error}")
        other_checks_ok = False
    try:
        record["source_version"] = _project_version(engine.source)
        if record["expected_version"] is None:
            record["expected_version"] = record["source_version"]
        elif record["source_version"] != record["expected_version"]:
            errors.append(f"source version {record['source_version']} differs from the pinned "
                          f"{record['expected_version']}")
            other_checks_ok = False
    except GateError as error:
        errors.append(str(error))
        other_checks_ok = False
    if pin is not None and not bytes_pinned and other_checks_ok:
        record["proposed_pin"] = {"sha256": record["sha256"], "size": record["size"]}
    if errors:
        return record
    version = record["expected_version"]
    if (reuse is not None and not reuse["errors"] and reuse["sha256"] == record["sha256"]
            and reuse["expected_version"] == version):
        record["cli_version"] = reuse["cli_version"]
        record["controls"] = dict(reuse["controls"])
        record["controls_from"] = reuse["controls_from"] or reuse["role"]
        return record
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        errors.append(f"cannot create the identity work directory: {error.strerror or type(error).__name__}")
        return record
    try:
        result = _run_cli(engine, ["--version"], work_dir, base_env(), timeout)
    except subprocess.TimeoutExpired:
        errors.append(f"--version timed out after {timeout:g} s")
        return record
    except OSError as error:
        errors.append(f"engine could not start: {error.strerror}")
        return record
    record["cli_version"] = result.stdout.decode("utf-8", "replace").strip()
    if result.returncode != 0 or record["cli_version"] != "checkwash " + version:
        errors.append(f"--version printed {record['cli_version']!r} with exit {result.returncode}; "
                      f"expected 'checkwash {version}'")
        return record
    control = work_dir / "control repo"
    try:
        _rmtree(control)
        materialize(CONTROL_CASE, control)
        clean = _run_cli(engine, ["check", "HEAD..HEAD", "--format", "json"], control, base_env(), timeout)
        observed = observe(clean.returncode, clean.stdout, clean.stderr, version=version,
                           scrub=_scrub_forms(control))
        problems = list(observed["errors"])
        if observed["verdict"] != "pass" or observed["exit"] != 0:
            problems.append(f"verdict {observed['verdict']!r} with exit {observed['exit']}; expected pass with exit 0")
        if observed["findings"] or observed["config_errors"] or observed["skipped_files"]:
            problems.append("findings, config errors or skipped files on an empty range")
        record["controls"]["clean_range"] = "ok" if not problems else "; ".join(problems)
        errors.extend("clean-range control: " + problem for problem in problems)
        invalid = _run_cli(engine, ["check", INVALID_REF + "..HEAD", "--format", "json"], control,
                           base_env(), timeout)
        if invalid.returncode == 2 and b"engine error" in invalid.stderr:
            record["controls"]["invalid_ref"] = "ok"
        else:
            record["controls"]["invalid_ref"] = f"exit {invalid.returncode}"
            errors.append(f"invalid-ref control: exit {invalid.returncode}; expected exit 2 with "
                          "'engine error' on stderr")
    except subprocess.TimeoutExpired:
        errors.append(f"control run timed out after {timeout:g} s")
    except OSError as error:
        errors.append(f"control: {error.strerror or type(error).__name__}")
    except GateError as error:
        errors.append(f"control: {error}")
    finally:
        problem = remove_safely(control)
        if problem:
            errors.append("control: " + problem)
    return record


def finalize_identity(engine: Engine, record: dict) -> None:
    """The artifact must not change while the gate uses it."""
    if record["sha256"] is None:
        return
    try:
        current = _sha256(engine.pyz.read_bytes())
    except OSError as error:
        record["errors"].append(f"artifact unreadable after the run: {error.strerror}")
        return
    if current != record["sha256"]:
        record["errors"].append("artifact changed while the gate was running")


# ---------------------------------------------------------------- rules

def _failure(code: str, message: str, case: str | None = None) -> dict:
    return {"code": code, "case": case, "message": message}


def _sorted_items(items: list[dict]) -> list[dict]:
    return sorted(items, key=lambda item: (item["code"], item["case"] or "", item["message"]))


def _integrity(row: dict, roles: tuple[str, ...], failures: list[dict],
               checked_roles: tuple[str, ...] = ()) -> list[str]:
    """Record harness-integrity failures for a row; return why its rules cannot be evaluated.

    Roles share one observation when their engines have the same bytes
    (``observations_from``). A shared observation's failures are recorded once,
    under the first role that owns it, here or in ``checked_roles`` (roles whose
    failures an earlier call already recorded); later sharers only stop evaluation.
    """
    problems = []
    seen = [row["runs"][role] for role in checked_roles if row["runs"].get(role) is not None]
    for role in roles:
        observation = row["runs"].get(role)
        if observation is None:
            if row.get("not_run"):
                problems.append(f"{role} not run: {row['not_run']}")
            else:
                failures.append(_failure("engine-run", f"{role}: no observation", row["id"]))
                problems.append(f"{role}: no observation")
            continue
        shared = any(observation is other for other in seen)
        seen.append(observation)
        found = []
        for error in observation["errors"]:
            found.append(_failure("engine-run", f"{role}: {error}", row["id"]))
            problems.append(f"{role}: {error}")
        for key, expect_key, code in (("config_errors", "expect_config_errors", "config-errors"),
                                      ("skipped_files", "expect_skipped", "skipped-files")):
            actual, expected = observation[key], row.get(expect_key, [])
            # The declaration is a set of messages; the engine's order is kept in the receipt only.
            if actual is not None and sorted(actual) != sorted(expected):
                found.append(_failure(code, f"{role}: {key} {json.dumps(actual)} differ from the declared "
                                            f"{expect_key} {json.dumps(expected)}", row["id"]))
                problems.append(f"{role}: {key} differ")
        if not shared:
            failures.extend(found)
        if not observation["errors"] and observation["verdict"] is None:
            problems.append(f"{role}: no verdict")
    return problems


def proposed_entry(row: dict, label: str | None) -> dict:
    kind = KIND_FOR_LABEL.get(label or "", "<set the label first>")
    entry = {"case": row["id"], "input_sha256": row["input_sha256"], "kind": kind,
             "reason": "<why this pass is accepted>", "reviewed_in": "<number of the PR that adds this entry>"}
    if row.get("issue") is not None:
        entry["issue"] = row["issue"]
    elif kind != "fp-fix":
        entry["issue"] = 0
    return entry


def evaluate(rows: list[dict], *, labels: dict[str, str], acceptance: dict | None, pin_tag: str,
             baseline_blocked: dict | None, invalid_ids: tuple[str, ...] | list[str] = (),
             complete: bool = True) -> dict:
    """Apply the #201 rules to observed rows. Pure: no I/O.

    ``rows``: ``{id, tier, input_sha256, label (T3 only), issue, expect_config_errors,
    expect_skipped, runs: {"baseline": obs, "candidate": obs}, not_run}``.
    ``acceptance``: ``load_acceptance`` output, or None when it could not be read (that
    failure is recorded by the caller).
    """
    failures: list[dict] = []
    reported: list[dict] = []
    proposals: list[dict] = []
    results: list[dict] = []
    ids = {row["id"] for row in rows}
    known = ids | set(invalid_ids)
    for row in rows:
        if row["tier"] == "T1" and row["id"] not in labels:
            failures.append(_failure("label-missing", "T1 case has no label in labels.toml", row["id"]))
    for case_id in labels:
        if case_id.startswith("chai:"):
            failures.append(_failure("label-unknown", "T3 labels come from the chai record, not labels.toml", case_id))
        elif case_id not in known:
            failures.append(_failure("label-unknown", "label names a case that does not exist", case_id))
    entries: dict[str, dict] = {}
    if acceptance is not None:
        if acceptance["baseline"] != pin_tag:
            failures.append(_failure("acceptance-baseline", f"acceptance file baseline {acceptance['baseline']!r} "
                                                            f"differs from the pinned baseline {pin_tag!r}"))
        for entry in acceptance["entries"]:
            if entry["case"] in entries:
                failures.append(_failure("entry-duplicate", f"stale entry: duplicate (entry #{entry['index']})",
                                         entry["case"]))
                continue
            entries[entry["case"]] = entry
            if entry["case"] not in known:
                failures.append(_failure("entry-unknown-case", "stale entry: its case is unknown", entry["case"]))
    for row in sorted(rows, key=lambda item: item["id"]):
        case_id = row["id"]
        label = row.get("label") if row["tier"] == "T3" else labels.get(case_id)
        entry = entries.get(case_id)
        result = {"id": case_id, "label": label, "transition": None, "needs_entry": [],
                  "entry": None if entry is None else {"kind": entry["kind"], "state": "not evaluated"},
                  "rules": "evaluated"}
        results.append(result)
        problems = _integrity(row, GATE_ROLES, failures)
        if problems:
            result["rules"] = "not evaluated: " + "; ".join(problems)
            continue
        baseline, candidate = row["runs"]["baseline"], row["runs"]["candidate"]
        before, after = baseline["verdict"], candidate["verdict"]
        result["transition"] = f"{before}->{after}"
        needs = []
        if after == "pass" and before == "block":
            needs.append("transition")
        if after == "pass" and label == "block":
            needs.append("label-anchor")
        result["needs_entry"] = needs
        if needs and entry is None:
            failures.append(_failure("unlisted-pass", f"candidate passes ({' + '.join(needs)}; label {label}) "
                                                      "with no accepted entry", case_id))
            proposals.append(proposed_entry(row, label))
        if entry is not None:
            state = "accepted"
            if not needs:
                why = "the candidate blocks it again" if after == "block" else "neither the transition nor the label anchor applies"
                failures.append(_failure("entry-not-needed", f"stale entry: the case no longer needs one ({why})", case_id))
                state = "stale"
            if entry["input_sha256"] != row["input_sha256"]:
                failures.append(_failure("entry-input-changed", f"stale entry: input_sha256 {entry['input_sha256']} "
                                                                f"differs from the case's {row['input_sha256']}", case_id))
                state = "stale"
            if label in KIND_FOR_LABEL and entry["kind"] != KIND_FOR_LABEL[label]:
                failures.append(_failure("entry-kind", f"kind {entry['kind']!r} is inconsistent with label {label!r} "
                                                       f"(expected {KIND_FOR_LABEL[label]!r})", case_id))
                state = "stale"
            result["entry"]["state"] = state
        if before == "pass" and after == "block":
            reported.append(_failure("pass-to-block", "baseline passes, candidate blocks", case_id))
        if before == after == "block" and baseline["blocking"] != candidate["blocking"]:
            reported.append(_failure("blocking-findings-changed", f"blocking findings {json.dumps(baseline['blocking'])}"
                                                                  f" -> {json.dumps(candidate['blocking'])}", case_id))
        if label == "undecided":
            reported.append(_failure("undecided", f"baseline {before}, candidate {after}", case_id))
    blocked_ids = None
    observed = None
    proposal = None
    if complete and not invalid_ids and all(item["transition"] for item in results):
        blocked_ids = sorted(row["id"] for row in rows if row["runs"]["baseline"]["verdict"] == "block")
        observed = {"count": len(blocked_ids), "sha256": digest(blocked_ids)}
        if baseline_blocked is None:
            failures.append(_failure("baseline-blocked-unpinned", f"baseline_blocked is not pinned; observed count "
                                                                  f"{observed['count']}, sha256 {observed['sha256']}"))
            proposal = observed
        elif baseline_blocked != observed:
            failures.append(_failure("baseline-blocked-drift", f"pinned count {baseline_blocked['count']}, sha256 "
                                                               f"{baseline_blocked['sha256']}; observed count "
                                                               f"{observed['count']}, sha256 {observed['sha256']}"))
            proposal = observed
    return {"failures": _sorted_items(failures), "reported": _sorted_items(reported), "rows": results,
            "proposed_entries": sorted(proposals, key=lambda item: item["case"]),
            "baseline_blocked": observed, "baseline_blocked_ids": blocked_ids,
            "baseline_blocked_proposal": proposal}


def evaluate_canary(rows: list[dict], *, pinned: list[str] | None, complete: bool = True,
                    checked_roles: tuple[str, ...] = ()) -> dict:
    """The canary pair must reproduce the reviewed block -> pass set exactly. Pure: no I/O.

    ``checked_roles``: roles whose integrity failures ``evaluate`` already recorded
    (``GATE_ROLES`` in gate mode); a canary role sharing their observation adds none.
    """
    failures: list[dict] = []
    results = []
    evaluated = True
    proposal = None
    for row in sorted(rows, key=lambda item: item["id"]):
        problems = _integrity(row, CANARY_ROLES, failures, checked_roles)
        if problems:
            evaluated = False
            results.append({"id": row["id"], "transition": None, "rules": "not evaluated: " + "; ".join(problems)})
            continue
        old, new = row["runs"]["canary-old"]["verdict"], row["runs"]["canary-new"]["verdict"]
        results.append({"id": row["id"], "transition": f"{old}->{new}", "rules": "evaluated"})
    observed = None
    if evaluated and complete:
        observed = sorted(item["id"] for item in results if item["transition"] == "block->pass")
        if pinned is None:
            failures.append(_failure("canary-unpinned", f"[canary] block_to_pass is not pinned; observed "
                                                        f"{len(observed)} block -> pass cases"))
            proposal = observed
        elif sorted(pinned) != observed:
            missing = sorted(set(pinned) - set(observed))
            extra = sorted(set(observed) - set(pinned))
            failures.append(_failure("canary-mismatch", f"canary set differs from the pin: missing {missing}, "
                                                        f"unexpected {extra}"))
            proposal = observed
    return {"failures": _sorted_items(failures), "rows": results, "block_to_pass": observed, "proposal": proposal}


def compare_t3(observed: dict[str, str] | None, pinned: dict[str, str] | None) -> dict:
    """The T3 cases read at the baseline commit against the pinned ``[t3.cases]``. Pure.

    Names every added, dropped and re-hashed ``chai:`` case, so a rotation shows
    its T3 changes (#201, release integration step 4).
    """
    if observed is None:
        return {"failures": [], "changes": None, "proposal": None}
    if pinned is None:
        return {"failures": [_failure("t3-unpinned", f"[t3.cases] is not pinned; observed {len(observed)} T3 cases")],
                "changes": None, "proposal": dict(sorted(observed.items()))}
    changes = {"added": sorted(set(observed) - set(pinned)), "dropped": sorted(set(pinned) - set(observed)),
               "rehashed": sorted(case for case in set(observed) & set(pinned) if observed[case] != pinned[case])}
    if not any(changes.values()):
        return {"failures": [], "changes": changes, "proposal": None}
    message = (f"T3 cases differ from the pinned [t3.cases]: added {changes['added']}, dropped {changes['dropped']}, "
               f"re-hashed {changes['rehashed']}")
    return {"failures": [_failure("t3-drift", message)], "changes": changes, "proposal": dict(sorted(observed.items()))}


# ---------------------------------------------------------------- tag rule

def highest_other_tag(pushed: str, tags: list[str]) -> tuple[str | None, list[str]]:
    """Highest ``vX.Y.Z`` tag other than ``pushed``; also the ``v*`` tags that are not ``vX.Y.Z``."""
    parsed = {}
    ignored = []
    for tag in tags:
        match = _SEMVER_TAG.fullmatch(tag)
        if match:
            parsed[tag] = tuple(int(part) for part in match.groups())
        else:
            ignored.append(tag)
    others = [tag for tag in parsed if tag != pushed]
    return (max(others, key=parsed.__getitem__) if others else None), sorted(ignored)


def check_tag_rule(repo: Path, pushed: str, pin: dict) -> tuple[list[str], dict]:
    errors = []
    info = {"pushed": pushed, "highest_other": None, "ignored_tags": []}
    if not _SEMVER_TAG.fullmatch(pushed):
        return [f"pushed tag {pushed!r} is not vX.Y.Z"], info
    try:
        tags = _git_text(repo, "tag", "--merged", "HEAD", "--list", "v*").split()
    except GateError as error:
        return [str(error)], info
    if pushed not in tags:
        errors.append(f"pushed tag {pushed} is not merged into HEAD")
    else:
        # The release gate runs on the exact tagged SHA, not on a descendant.
        try:
            tagged = _git_text(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{pushed}^{{commit}}")
            head = _git_text(repo, "rev-parse", "--verify", "HEAD^{commit}")
            if tagged != head:
                errors.append(f"HEAD {head} is not the commit of the pushed tag {pushed} ({tagged})")
        except GateError as error:
            errors.append(f"pushed tag {pushed}: {error}")
    highest, info["ignored_tags"] = highest_other_tag(pushed, tags)
    info["highest_other"] = highest
    if highest != pin["tag"]:
        errors.append(f"baseline {pin['tag']} is not the highest other v* tag merged into HEAD ({highest})")
    try:
        commit = _git_text(repo, "rev-parse", "--verify", "--quiet", f"refs/tags/{pin['tag']}^{{commit}}")
        if commit != pin["commit"]:
            errors.append(f"tag {pin['tag']} is {commit}, not the pinned commit {pin['commit']}")
    except GateError:
        errors.append(f"tag {pin['tag']} does not resolve in the checkout")
    return errors, info


# ---------------------------------------------------------------- proposals

def render_proposals(proposed: dict) -> str:
    """TOML snippets ready to paste; never written by this tool."""
    lines: list[str] = []
    entries = proposed.get("accept_entries") or []
    if entries:
        lines.append("# tests/gates/verdict_gate_accepted.toml: fill in reason, issue and reviewed_in")
        for entry in entries:
            lines.append("[[accept]]")
            for key in ("case", "input_sha256", "kind", "issue", "reason", "reviewed_in"):
                if key in entry:
                    value = entry[key]
                    lines.append(f"{key:<12} = " + (str(value) if type(value) is int else _toml_str(value)))
            lines.append("")
    blocked = proposed.get("baseline_blocked")
    if blocked is not None:
        lines += ["# pins file", "[baseline_blocked]", f"count = {blocked['count']}",
                  f"sha256 = {_toml_str(blocked['sha256'])}", ""]
    canary = proposed.get("canary_block_to_pass")
    if canary is not None:
        lines += ["# pins file, inside [canary]", "block_to_pass = ["]
        lines += [f"  {_toml_str(case_id)}," for case_id in canary]
        lines += ["]", ""]
    t3_cases = proposed.get("t3_cases")
    if t3_cases is not None:
        lines += ["# pins file", "[t3.cases]"]
        lines += [f"{_toml_str(case_id)} = {_toml_str(sha)}" for case_id, sha in sorted(t3_cases.items())]
        lines.append("")
    for role, pin in sorted((proposed.get("engine_pins") or {}).items()):
        lines += [f"# pins file, {role} engine (re-pin only after review: members, commit and version matched)",
                  f"sha256 = {_toml_str(pin['sha256'])}", f"size = {pin['size']}", ""]
    return "\n".join(lines)


# ---------------------------------------------------------------- orchestration

def _file_sha256(path: Path | None) -> str | None:
    try:
        return _sha256(path.read_bytes()) if path is not None else None
    except OSError:
        return None


def _row(case: Case) -> dict:
    return {"id": case.id, "tier": case.tier, "input_sha256": case.input_sha256, "label": case.label,
            "issue": case.issue, "expect_config_errors": case.options["expect_config_errors"],
            "expect_skipped": case.options["expect_skipped"], "runs": {}, "not_run": None, "git_shape": None}


def run_gate(*, mode: str, pins_path: Path, cases_dir: Path, engines: dict[str, tuple[Path, Path]],
             python: str | None = None, labels_path: Path | None = None, accepted_path: Path | None = None,
             work_dir: Path | None = None, timeout: float = DEFAULT_TIMEOUT, tag_run: str | None = None,
             repo: Path | None = None, context: dict[str, str] | None = None) -> dict:
    """Run the gate (``mode="gate"``) or the canary alone (``mode="canary"``); return the receipt."""
    if mode not in ("gate", "canary"):
        raise ValueError("mode must be 'gate' or 'canary'")
    roles = ROLES if mode == "gate" else CANARY_ROLES
    failures: list[dict] = []
    receipt: dict = {
        "schema_version": SCHEMA_VERSION, "mode": mode, "status": "failed",
        "context": dict(sorted((context or {}).items())),
        "inputs": {"pins_sha256": _file_sha256(pins_path), "labels_sha256": _file_sha256(labels_path),
                   "accepted_sha256": _file_sha256(accepted_path), "cases_sha256": None, "t3": None},
        "tag_rule": None, "engines": {}, "cases": [], "failures": [], "reported": [],
        # What this run saw; ``proposed`` only carries what is missing or drifted from a pin.
        "observed": {"baseline_blocked": None, "baseline_blocked_ids": None, "canary_block_to_pass": None,
                     "t3_cases": None, "t3_changes": None},
        "proposed": {"accept_entries": [], "baseline_blocked": None, "canary_block_to_pass": None,
                     "t3_cases": None, "engine_pins": {}, "toml": ""},
        "summary": {},
    }

    def finish() -> dict:
        receipt["failures"] = _sorted_items(failures)
        receipt["status"] = "passed" if not failures else "failed"
        receipt["proposed"]["toml"] = render_proposals(receipt["proposed"])
        transitions: dict[str, int] = {}
        for row in receipt["cases"]:
            for key in ("transition", "canary_transition"):
                if row.get(key):
                    name = ("canary " if key == "canary_transition" else "") + row[key]
                    transitions[name] = transitions.get(name, 0) + 1
        receipt["summary"] = {
            "cases": len(receipt["cases"]),
            "t1": sum(row["tier"] == "T1" for row in receipt["cases"]),
            "t3": sum(row["tier"] == "T3" for row in receipt["cases"]),
            "failures": len(failures), "reported": len(receipt["reported"]),
            "transitions": dict(sorted(transitions.items())),
        }
        return receipt

    if python is None:
        python = sys.executable
    python = os.path.abspath(python)
    if not Path(python).is_file():
        failures.append(_failure("usage", "Python executable does not exist"))
        return finish()
    missing_roles = [role for role in roles if role not in engines]
    if missing_roles:
        failures.append(_failure("usage", "no artifact/source for engine(s) " + ", ".join(missing_roles)))
        return finish()
    try:
        pins = load_pins(pins_path)
    except GateError as error:
        failures.append(_failure("pins-invalid", str(error)))
        return finish()
    engine_pins = {"baseline": pins["baseline"], "candidate": None}
    if pins["canary"] is not None:
        engine_pins.update({"canary-old": pins["canary"]["old"], "canary-new": pins["canary"]["new"]})
    elif any(role in CANARY_ROLES for role in roles):
        failures.append(_failure("pins-invalid", "pins file has no [canary] table with old and new engines"))
        return finish()

    try:
        t1_cases, invalid_ids, case_errors = load_cases(cases_dir)
    except GateError as error:
        t1_cases, invalid_ids, case_errors = [], [], [str(error)]
    failures.extend(_failure("case-invalid", message) for message in case_errors)
    complete = not case_errors
    receipt["inputs"]["cases_sha256"] = digest({case.id: case.input_sha256 for case in t1_cases})
    t3_cases: list[Case] = []
    labels: dict[str, str] = {}
    acceptance = None
    if mode == "gate":
        try:
            t3_cases, receipt["inputs"]["t3"] = load_chai_cases_at(
                Path(os.path.abspath(engines["baseline"][1])), pins["baseline"]["commit"])
        except GateError as error:
            failures.append(_failure("t3-invalid", str(error)))
            complete = False
        else:
            observed_t3 = {case.id: case.input_sha256 for case in t3_cases}
            t3 = compare_t3(observed_t3, pins["t3"])
            failures.extend(t3["failures"])
            receipt["observed"]["t3_cases"] = dict(sorted(observed_t3.items()))
            receipt["observed"]["t3_changes"] = t3["changes"]
            receipt["proposed"]["t3_cases"] = t3["proposal"]
        if labels_path is None:
            failures.append(_failure("labels-invalid", "no labels file given"))
        else:
            try:
                labels = load_labels(labels_path)
            except GateError as error:
                failures.append(_failure("labels-invalid", str(error)))
        if accepted_path is None or not accepted_path.is_file():
            failures.append(_failure("acceptance-missing", "the acceptance file does not exist; "
                                                           "every pass that needs an entry is unlisted"))
            acceptance = {"baseline": pins["baseline"]["tag"], "entries": []}
        else:
            try:
                acceptance = load_acceptance(accepted_path)
            except GateError as error:
                failures.append(_failure("acceptance-invalid", str(error)))
        if tag_run is not None:
            errors, receipt["tag_rule"] = check_tag_rule(repo or ROOT, tag_run, pins["baseline"])
            failures.extend(_failure("tag-baseline", message) for message in errors)

    created = work_dir is None
    # Resolved, so the scrubbed spelling is the one git and the engines print
    # (macOS /private/var, Windows 8.3 short names).
    work = (Path(tempfile.mkdtemp(prefix="checkwash verdict gate ")) if created else work_dir).resolve()
    try:
        if not created:
            if work.exists() and any(work.iterdir()):
                failures.append(_failure("usage", "work directory is not empty"))
                return finish()
            work.mkdir(parents=True, exist_ok=True)
        engine_objects = {
            role: Engine(role=role, python=python, pyz=Path(os.path.abspath(engines[role][0])),
                         source=Path(os.path.abspath(engines[role][1])), pin=engine_pins[role])
            for role in roles
        }
        identities: dict[str, dict] = {}
        for role in roles:
            earlier = next((record for record in identities.values()
                            if not record["errors"] and record["sha256"] is not None
                            and record["sha256"] == _file_sha256(engine_objects[role].pyz)), None)
            identities[role] = verify_identity(engine_objects[role], work / f"identity {role}", timeout, earlier)
        owners: dict[str, str] = {}
        for role in roles:
            owner = owners.setdefault(identities[role]["sha256"] or role, role)
            if owner != role:
                identities[role]["observations_from"] = owner
        identity_ok = all(not record["errors"] for record in identities.values())
        cases = sorted(t1_cases + t3_cases, key=lambda case: case.id)
        rows = {case.id: _row(case) for case in cases}
        for index, case in enumerate(cases):
            row = rows[case.id]
            if not identity_ok:
                row["not_run"] = "engine identity failed"
                continue
            case_dir = work / "cases" / f"{index:04d} {case.id.replace('/', ' ').replace(':', ' ')}"
            row["git_shape"], problem = materialize_safely(case, case_dir)
            if problem is not None:
                failures.append(_failure("case-materialize", problem, case.id))
                row["not_run"] = "materialization failed"
                problem = remove_safely(case_dir)
                if problem:
                    failures.append(_failure("case-cleanup", problem, case.id))
                continue
            needed = roles if case.tier == "T1" else GATE_ROLES
            for role in needed:
                owner = identities[role]["observations_from"] or role
                if owner in row["runs"]:
                    row["runs"][role] = row["runs"][owner]
                    continue
                version = identities[owner]["expected_version"]
                row["runs"][role] = run_engine(engine_objects[owner], version, case, case_dir, timeout)
                if owner != role:
                    row["runs"][owner] = row["runs"][role]
            row["runs"] = {role: row["runs"][role] for role in needed}
            problem = remove_safely(case_dir)
            if problem:
                failures.append(_failure("case-cleanup", problem, case.id))
        for role in roles:
            finalize_identity(engine_objects[role], identities[role])
            failures.extend(_failure("engine-identity", f"{role}: {error}") for error in identities[role]["errors"])
            if identities[role]["proposed_pin"]:
                receipt["proposed"]["engine_pins"][role] = identities[role]["proposed_pin"]
        receipt["engines"] = identities
    finally:
        if created:
            problem = remove_safely(work)
            if problem:
                failures.append(_failure("work-cleanup", problem))

    gate_rows = [rows[case.id] for case in cases]
    canary_rows = [rows[case.id] for case in cases if case.tier == "T1"]
    results: dict[str, dict] = {case.id: {} for case in cases}
    if mode == "gate":
        verdicts = evaluate(gate_rows, labels=labels, acceptance=acceptance, pin_tag=pins["baseline"]["tag"],
                            baseline_blocked=pins["baseline_blocked"], invalid_ids=invalid_ids, complete=complete)
        failures.extend(verdicts["failures"])
        receipt["reported"] = verdicts["reported"]
        receipt["proposed"]["accept_entries"] = verdicts["proposed_entries"]
        receipt["proposed"]["baseline_blocked"] = verdicts["baseline_blocked_proposal"]
        receipt["observed"]["baseline_blocked"] = verdicts["baseline_blocked"]
        receipt["observed"]["baseline_blocked_ids"] = verdicts["baseline_blocked_ids"]
        for result in verdicts["rows"]:
            results[result["id"]].update(result)
    canary = evaluate_canary(canary_rows, pinned=pins["canary"]["block_to_pass"], complete=complete,
                             checked_roles=GATE_ROLES if mode == "gate" else ())
    failures.extend(canary["failures"])
    receipt["observed"]["canary_block_to_pass"] = canary["block_to_pass"]
    receipt["proposed"]["canary_block_to_pass"] = canary["proposal"]
    for result in canary["rows"]:
        results[result["id"]]["canary_transition"] = result["transition"]
        if mode == "canary":
            results[result["id"]]["rules"] = result["rules"]
    for case in cases:
        row = rows[case.id]
        receipt["cases"].append({
            "id": case.id, "tier": case.tier, "input_sha256": case.input_sha256,
            "label": results[case.id].get("label", case.label), "git_shape": row["git_shape"],
            "runs": row["runs"], "not_run": row["not_run"],
            "transition": results[case.id].get("transition"),
            "canary_transition": results[case.id].get("canary_transition"),
            "needs_entry": results[case.id].get("needs_entry", []),
            "entry": results[case.id].get("entry"), "rules": results[case.id].get("rules"),
        })
    return finish()


# ---------------------------------------------------------------- summary

def _cell(value: object) -> str:
    text = "-" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_summary(receipt: dict) -> str:
    """Markdown for $GITHUB_STEP_SUMMARY."""
    lines = [f"## verdict gate ({receipt['mode']}): {receipt['status'].upper()}", ""]
    summary = receipt.get("summary", {})
    lines.append(f"{summary.get('cases', 0)} cases (T1 {summary.get('t1', 0)}, T3 {summary.get('t3', 0)}), "
                 f"{summary.get('failures', 0)} failure(s), {summary.get('reported', 0)} reported.")
    lines.append("")
    if receipt.get("engines"):
        lines += ["| engine | artifact | sha256 | size | version | commit | errors |", "|---|---|---|---|---|---|---|"]
        for role, record in sorted(receipt["engines"].items()):
            lines.append("| " + " | ".join(_cell(value) for value in (
                role, record["artifact"], record["sha256"], record["size"], record["cli_version"],
                record["source_commit"], len(record["errors"]))) + " |")
        lines.append("")
    if receipt.get("failures"):
        lines += ["### Failures", ""]
        lines += [f"- `{item['code']}` {_cell(item['case'])}: {_cell(item['message'])}" for item in receipt["failures"]]
        lines.append("")
    if receipt.get("reported"):
        lines += ["### Reported, not failed", ""]
        lines += [f"- `{item['code']}` {_cell(item['case'])}: {_cell(item['message'])}" for item in receipt["reported"]]
        lines.append("")
    if receipt.get("cases"):
        lines += ["### Cases", "", "| case | tier | label | baseline -> candidate | canary | entry | rules |",
                  "|---|---|---|---|---|---|---|"]
        for row in receipt["cases"]:
            entry = row["entry"]
            lines.append("| " + " | ".join(_cell(value) for value in (
                row["id"], row["tier"], row["label"], row["transition"], row["canary_transition"],
                None if entry is None else f"{entry['kind']} ({entry['state']})", row["rules"])) + " |")
        lines.append("")
    toml_text = receipt.get("proposed", {}).get("toml")
    if toml_text:
        lines += ["### Proposed entries and pins (never written by the gate)", "", "```toml", toml_text.rstrip(), "```", ""]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- CLI

def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8", newline="\n")


def _context(values: list[str]) -> dict[str, str]:
    context = {}
    for value in values:
        key, separator, item = value.partition("=")
        if not separator or not key:
            raise SystemExit(f"--context takes KEY=VALUE, got {value!r}")
        if key in context:
            raise SystemExit(f"--context key {key!r} is given twice")
        context[key] = item
    return context


def _emit(receipt: dict, args: argparse.Namespace) -> int:
    _write_json(args.receipt, receipt)
    if args.summary is not None:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(render_summary(receipt), encoding="utf-8", newline="\n")
    print(json.dumps({"mode": receipt["mode"], "status": receipt["status"], "summary": receipt["summary"],
                      "failures": [" ".join(filter(None, (item["code"], item["case"]))) + ": " + item["message"]
                                   for item in receipt["failures"][:50]]}, sort_keys=True, indent=1))
    return 0 if receipt["status"] == "passed" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Previous-release verdict gate (#201); see the module docstring.")
    commands = parser.add_subparsers(dest="command", required=True)

    def engine_args(sub, roles):
        for role in roles:
            sub.add_argument(f"--{role}-pyz", type=Path, required=True, help=f"{role} checkwash.pyz")
            sub.add_argument(f"--{role}-source", type=Path, required=role != "candidate", default=ROOT,
                             help=f"checkout of the {role} commit (src/checkwash, pyproject.toml)")

    def common(sub):
        sub.add_argument("--pins", type=Path, required=True, help="tests/verdict_gate/baseline.toml")
        sub.add_argument("--cases", type=Path, required=True, help="tests/verdict_gate/cases")
        sub.add_argument("--python", default=sys.executable, help="absolute Python that runs every pyz")
        sub.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds per engine run")
        sub.add_argument("--work-dir", type=Path, help="empty scratch directory (default: a new temporary one)")
        sub.add_argument("--context", action="append", default=[], metavar="KEY=VALUE",
                         help="recorded verbatim in the receipt (run id, commit, event)")
        sub.add_argument("--receipt", type=Path, required=True, help="JSON receipt to write")
        sub.add_argument("--summary", type=Path, help="Markdown summary to write")

    gate = commands.add_parser("gate", help="run baseline, candidate and canary; apply every rule")
    common(gate)
    gate.add_argument("--labels", type=Path, required=True, help="tests/verdict_gate/labels.toml")
    gate.add_argument("--accepted", type=Path, required=True, help="tests/gates/verdict_gate_accepted.toml")
    gate.add_argument("--tag-run", metavar="vX.Y.Z", help="the pushed tag, on a tag-push run")
    gate.add_argument("--repo", type=Path, default=ROOT, help="checkout with tags, for --tag-run")
    engine_args(gate, ROLES)

    canary = commands.add_parser("canary", help="run only the canary pair over the T1 cases")
    common(canary)
    engine_args(canary, CANARY_ROLES)

    identity = commands.add_parser("identity", help="verify one engine's pin, members, version and controls")
    identity.add_argument("--role", choices=ROLES, required=True)
    identity.add_argument("--pins", type=Path, help="required unless --role candidate")
    identity.add_argument("--pyz", type=Path, required=True)
    identity.add_argument("--source", type=Path, required=True)
    identity.add_argument("--python", default=sys.executable)
    identity.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)

    listing = commands.add_parser("cases", help="parse every case (no engine runs) and list ids and input_sha256")
    listing.add_argument("--cases", type=Path, required=True)
    listing.add_argument("--labels", type=Path)
    listing.add_argument("--chai", type=Path, help="a chai mutation JSON file for the T3 cases")

    build = commands.add_parser("materialize", help="write one case's two-commit repository (no engine runs)")
    build.add_argument("--case", type=Path, required=True, help="<family>/<row>.vgcase")
    build.add_argument("--out", type=Path, required=True, help="empty or missing directory")

    propose = commands.add_parser("propose", help="print the proposed entries and pins of a receipt")
    propose.add_argument("--receipt", type=Path, required=True)

    args = parser.parse_args(argv)
    if args.command in ("gate", "canary"):
        roles = ROLES if args.command == "gate" else CANARY_ROLES
        engines = {role: (getattr(args, role.replace("-", "_") + "_pyz"), getattr(args, role.replace("-", "_") + "_source"))
                   for role in roles}
        receipt = run_gate(
            mode=args.command, pins_path=args.pins, cases_dir=args.cases, engines=engines, python=args.python,
            labels_path=getattr(args, "labels", None), accepted_path=getattr(args, "accepted", None),
            work_dir=args.work_dir, timeout=args.timeout, tag_run=getattr(args, "tag_run", None),
            repo=getattr(args, "repo", None), context=_context(args.context))
        return _emit(receipt, args)
    if args.command == "identity":
        pin = None
        if args.role != "candidate":
            if args.pins is None:
                parser.error("--pins is required for a pinned role")
            try:
                pins = load_pins(args.pins)
            except GateError as error:
                print(json.dumps({"errors": [str(error)]}, sort_keys=True))
                return 1
            if args.role == "baseline":
                pin = pins["baseline"]
            elif pins["canary"] is None:
                print(json.dumps({"errors": ["pins file has no [canary] table"]}, sort_keys=True))
                return 1
            else:
                pin = pins["canary"]["old" if args.role == "canary-old" else "new"]
        engine = Engine(role=args.role, python=os.path.abspath(args.python), pyz=Path(os.path.abspath(args.pyz)),
                        source=Path(os.path.abspath(args.source)), pin=pin)
        with tempfile.TemporaryDirectory(prefix="checkwash verdict gate identity ") as temporary:
            record = verify_identity(engine, Path(temporary).resolve(), args.timeout)
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0 if not record["errors"] else 1
    if args.command == "cases":
        try:
            cases, invalid, errors = load_cases(args.cases)
        except GateError as error:
            cases, invalid, errors = [], [], [str(error)]
        labels: dict[str, str] = {}
        if args.chai is not None:
            try:
                cases += load_chai_cases(args.chai)[0]
            except GateError as error:
                errors.append(str(error))
        if args.labels is not None:
            try:
                labels = load_labels(args.labels)
            except GateError as error:
                errors.append(str(error))
            errors += [f"{case.id}: no label" for case in cases if case.tier == "T1" and case.id not in labels]
            # Same rule as evaluate(): T3 labels come from the chai record.
            known = {case.id for case in cases if case.tier == "T1"} | set(invalid)
            errors += [f"{case_id}: T3 labels come from the chai record, not labels.toml"
                       for case_id in labels if case_id.startswith("chai:")]
            errors += [f"{case_id}: label for an unknown case" for case_id in labels
                       if not case_id.startswith("chai:") and case_id not in known]
        print(json.dumps({"cases": [{"id": case.id, "tier": case.tier, "input_sha256": case.input_sha256,
                                     "label": case.label or labels.get(case.id), "ops": case.ops}
                                    for case in sorted(cases, key=lambda item: item.id)],
                          "invalid": invalid, "errors": errors}, indent=1, sort_keys=True))
        return 1 if errors else 0
    if args.command == "materialize":
        case_path = args.case.resolve()
        try:
            case = parse_case(case_path.read_bytes(), f"{case_path.parent.name}/{case_path.stem}")
            shape = materialize(case, args.out)
        except (OSError, GateError) as error:
            print(json.dumps({"errors": [str(error)]}, sort_keys=True))
            return 1
        print(json.dumps({"case": case.id, "git_shape": shape}, indent=1, sort_keys=True))
        return 0
    try:
        receipt = loads_strict(args.receipt.read_bytes())
        print(render_proposals(receipt["proposed"]), end="")
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"cannot read receipt: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
