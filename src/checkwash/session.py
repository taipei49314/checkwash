"""Claude Code session bases for the Stop hook (#418).

The managed SessionStart handler (`checkwash hook session-start`) records the
commit a session starts from, once per `session_id`, under
`<git-dir>/checkwash/sessions/<sha256(session_id)>`. The managed Stop handler
(`checkwash check --format hook-json --hook-input stdin`) reads that commit
back, so work the agent commits during the session is still analysed, and so
policy it commits during the session governs only the next one.

A record lives under `.git`, which the agent can write (THREATMODEL item 2).
It narrows the hook's window; the required CI check remains the gate. Beside
it, `<name>.stop` holds what the Stop hook last blocked on in the session, so
a continuation on the same set is released with a note (D-189).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import stat
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
# Other sessions' records older than this are pruned when a session starts.
# Resume never writes, so a session resumed after its record was pruned has
# none, and its Stop says so.
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

    @property
    def stop_hook_active(self) -> bool:
        """Claude Code sets it while Claude continues because of a stop hook.

        Only JSON `true` counts; anything else stops as it always did (D-189).
        """
        return (self.data or {}).get("stop_hook_active") is True


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


def _read_record(path: str | Path) -> bytes | None:
    """A record's bytes, or None unless it is a regular file of at most 4096.

    Opened without following a link and without blocking, then checked on the
    open descriptor, so a link, FIFO or device swapped in is never read.
    """
    flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_NONBLOCK", 0))
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        data = os.read(descriptor, 4097)
    except OSError:
        return None
    finally:
        os.close(descriptor)
    return data if len(data) <= 4096 else None


def _prune(repo: str, directory: Path, now: datetime.datetime, keep: str) -> None:
    """Remove other sessions' records by age or a missing commit, never by count.

    `keep` is the starting session's own record, which is never pruned. A
    record that does not parse is left alone: it may be one another session
    is still writing.
    """
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return
    limit = datetime.timedelta(days=RECORD_MAX_AGE_DAYS)
    for entry in entries:
        if entry.name == keep + _STOP_SUFFIX:
            continue
        if re.fullmatch(r"[0-9a-f]{64}" + re.escape(_STOP_SUFFIX), entry.name):
            # A Stop record holds no commit; it goes by its own age (D-189).
            try:
                age = now - datetime.datetime.fromtimestamp(entry.stat(follow_symlinks=False).st_mtime,
                                                            datetime.timezone.utc)
                if age > limit:
                    os.unlink(entry.path)
            except (OSError, OverflowError, ValueError):
                pass
            continue
        if entry.name == keep or not re.fullmatch(r"[0-9a-f]{64}", entry.name):
            continue
        data = _read_record(entry.path)
        parsed = _parse_record(data) if data is not None else None
        if parsed is None:
            continue
        try:
            if now - parsed[1] > limit or not _commit_exists(repo, parsed[0]):
                os.unlink(entry.path)
        except OSError:
            continue


def record_session_start(repo: str, hook_input: HookInput | None) -> None:
    """Record HEAD as the session's base, once. Never raises.

    Nothing is written on compaction or resume, when the input has no
    `session_id`, or when HEAD has no commit; a resumed session with no
    record keeps none, so its Stop says its commits were not analysed. An
    existing record is never replaced. Other sessions' records are pruned
    after the write, so planted records cannot delay it.
    """
    try:
        if hook_input is None or hook_input.session_id is None or hook_input.source in ("compact", "resume"):
            return
        head = resolve_commit(repo, "HEAD")
        directory = _sessions_dir(repo)
        now = _now()
        name = _record_name(hook_input.session_id)
        directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"version": 1, "head": head, "created": now.isoformat(timespec="seconds")}, sort_keys=True,
        ).encode("utf-8") + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(directory / name, flags, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
        _prune(repo, directory, now, keep=name)
    except Exception:  # noqa: BLE001 - a session start must never fail on checkwash
        return


def session_base(repo: str, hook_input: HookInput | None) -> str | None:
    """The recorded base commit for this hook input's session, or None."""
    if hook_input is None or hook_input.session_id is None:
        return None
    try:
        data = _read_record(_sessions_dir(repo) / _record_name(hook_input.session_id))
    except (OSError, GitError):
        return None
    parsed = _parse_record(data) if data is not None else None
    if parsed is None or not _commit_exists(repo, parsed[0]):
        return None
    return parsed[0]


# What the Stop hook last blocked on in a session (D-189): a stop that arrives
# with `stop_hook_active` true and the same blocking set is not blocked again.
_STOP_SUFFIX = ".stop"


def blocking_digest(fingerprints) -> str:
    """One digest for a blocking set: its fingerprints, sorted, one per line."""
    joined = "\n".join(sorted(fingerprints))
    return hashlib.sha256(joined.encode("utf-8", "surrogatepass")).hexdigest()


def _stop_path(repo: str, hook_input: HookInput | None) -> Path | None:
    if hook_input is None or hook_input.session_id is None:
        return None
    return _sessions_dir(repo) / (_record_name(hook_input.session_id) + _STOP_SUFFIX)


def last_stop_digest(repo: str, hook_input: HookInput | None) -> str | None:
    """The blocking set the Stop hook last blocked on in this session, or None."""
    try:
        path = _stop_path(repo, hook_input)
        data = _read_record(path) if path is not None else None
        record = json.loads(data.decode("utf-8")) if data is not None else None
    except (OSError, GitError, UnicodeDecodeError, ValueError, RecursionError):
        return None
    value = record.get("blocking") if isinstance(record, dict) and record.get("version") == 1 else None
    return value if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) else None


def record_stop(repo: str, hook_input: HookInput | None, digest: str) -> None:
    """Remember the set this Stop blocks on. Never raises."""
    try:
        path = _stop_path(repo, hook_input)
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "blocking": digest}, sort_keys=True).encode("utf-8") + b"\n"
        temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        os.replace(temporary, path)
    except Exception:  # noqa: BLE001 - a Stop must never fail on its own record
        return


def clear_stop(repo: str, hook_input: HookInput | None) -> None:
    """Forget the last blocking set, on a pass. Never raises."""
    try:
        path = _stop_path(repo, hook_input)
        if path is not None:
            path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - as record_stop
        return
