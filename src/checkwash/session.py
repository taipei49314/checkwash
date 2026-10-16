"""Claude Code session bases for the Stop hook (#418).

The managed SessionStart handler (`checkwash hook session-start`) records the
commit a session starts from, once per `session_id`, under
`<git-dir>/checkwash/sessions/<sha256(session_id)>`. The managed Stop handler
(`checkwash check --format hook-json --hook-input stdin`) reads that commit
back, so work the agent commits during the session is still analysed, and so
policy it commits during the session governs only the next one.

A record lives under `.git`, which the agent can write (THREATMODEL item 2).
It narrows the hook's window; the required CI check remains the gate.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from checkwash.gitio import GitError, git_dir, resolve_commit

# Claude Code writes one small JSON object. Anything larger is not read
# further and counts as unparsable hook input.
INPUT_BYTE_CAP = 1_000_000
# Claude Code closes stdin after writing; a pipe that stays open with nothing
# on it must not hang the hook.
INPUT_WAIT_SECONDS = 10.0
# Records older than this are pruned when a session starts. A session resumed
# after that has no record, and its Stop says so.
RECORD_MAX_AGE_DAYS = 30
_OID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


@dataclass(frozen=True)
class HookInput:
    """Hook input that arrived on stdin. `data` is None when it did not parse
    as a JSON object within the byte cap."""

    data: dict | None

    @property
    def session_id(self) -> str | None:
        value = (self.data or {}).get("session_id")
        return value if isinstance(value, str) and value else None

    @property
    def source(self) -> str | None:
        value = (self.data or {}).get("source")
        return value if isinstance(value, str) else None


def read_hook_input(stream, *, cap: int = INPUT_BYTE_CAP, wait: float = INPUT_WAIT_SECONDS) -> HookInput | None:
    """The Claude Code hook input on `stream`, or None when none arrived.

    None for a missing or closed stream, a TTY, an empty stream, and a stream
    that sends nothing within `wait` seconds. Bytes that do not parse as one
    JSON object within `cap` are hook input all the same: `HookInput(None)`.
    """
    if stream is None:
        return None
    try:
        if stream.isatty():
            return None
    except (OSError, ValueError, AttributeError):
        return None
    # The descriptor itself where there is one: a thread still blocked in the
    # buffered reader at exit holds its lock, and Python's shutdown then
    # aborts. Otherwise read1, which returns what has arrived, so input that
    # stops short of EOF is still seen when the wait runs out.
    try:
        descriptor = stream.fileno()
    except (OSError, ValueError, AttributeError):
        descriptor = None
    if descriptor is not None:
        def read(size: int) -> bytes:
            return os.read(descriptor, size)
    else:
        buffer = getattr(stream, "buffer", stream)
        read = getattr(buffer, "read1", buffer.read)
    chunks: list[bytes] = []
    done = threading.Event()

    def reader() -> None:
        try:
            total = 0
            while total <= cap:
                chunk = read(min(65_536, cap + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
        except (OSError, ValueError):
            pass
        finally:
            done.set()

    threading.Thread(target=reader, name="checkwash-hook-input", daemon=True).start()
    finished = done.wait(wait)
    raw = b"".join(chunks)
    if not raw:
        return None
    if not finished or len(raw) > cap:
        return HookInput(None)
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return HookInput(None)
    return HookInput(data if isinstance(data, dict) else None)


def _sessions_dir(repo: str) -> Path:
    return Path(git_dir(repo)) / "checkwash" / "sessions"


def _record_name(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8", "surrogatepass")).hexdigest()


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse_record(data: bytes) -> tuple[str, datetime.datetime] | None:
    try:
        record = json.loads(data.decode("utf-8"))
        head, created = record["head"], datetime.datetime.fromisoformat(record["created"])
    except (UnicodeDecodeError, ValueError, TypeError, KeyError, RecursionError):
        return None
    if not isinstance(head, str) or not _OID.fullmatch(head) or created.tzinfo is None:
        return None
    return head, created


def _commit_exists(repo: str, oid: str) -> bool:
    try:
        return resolve_commit(repo, oid) == oid
    except GitError:
        return False


def _prune(repo: str, directory: Path, now: datetime.datetime) -> None:
    """Remove records by age or a missing commit, never by count."""
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return
    limit = datetime.timedelta(days=RECORD_MAX_AGE_DAYS)
    for entry in entries:
        if not re.fullmatch(r"[0-9a-f]{64}", entry.name):
            continue
        try:
            if not entry.is_file(follow_symlinks=False) or entry.stat(follow_symlinks=False).st_size > 4096:
                continue
            parsed = _parse_record(Path(entry.path).read_bytes())
            if parsed is None or now - parsed[1] > limit or not _commit_exists(repo, parsed[0]):
                os.unlink(entry.path)
        except OSError:
            continue


def record_session_start(repo: str, hook_input: HookInput | None) -> None:
    """Record HEAD as the session's base, once. Never raises.

    Nothing is written on compaction, when the input has no `session_id`, or
    when HEAD has no commit. An existing record is never replaced.
    """
    try:
        if hook_input is None or hook_input.session_id is None or hook_input.source == "compact":
            return
        head = resolve_commit(repo, "HEAD")
        directory = _sessions_dir(repo)
        now = _now()
        _prune(repo, directory, now)
        directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"version": 1, "head": head, "created": now.isoformat(timespec="seconds")}, sort_keys=True,
        ).encode("utf-8") + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(directory / _record_name(hook_input.session_id), flags, 0o600)
        except FileExistsError:
            return
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
    except Exception:  # noqa: BLE001 - a session start must never fail on checkwash
        return


def session_base(repo: str, hook_input: HookInput | None) -> str | None:
    """The recorded base commit for this hook input's session, or None."""
    if hook_input is None or hook_input.session_id is None:
        return None
    try:
        path = _sessions_dir(repo) / _record_name(hook_input.session_id)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            return None
        parsed = _parse_record(path.read_bytes())
    except (OSError, GitError):
        return None
    if parsed is None or not _commit_exists(repo, parsed[0]):
        return None
    return parsed[0]
