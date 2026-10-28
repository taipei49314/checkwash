"""Claude command hooks: portable shared CLI or an isolated local runtime.

Exec-form handlers require Claude Code's command/args support. Qualification
records name the runtime tested; writing settings is not a Stop lifecycle test.

The installer writes two managed handlers (#418): a Stop handler that checks
the working tree and the session's commits, and a SessionStart handler, in a
group of its own, that records where each session starts. Machine-local
settings, the default since 0.11, get a third (D-189): a PreToolUse handler,
in a group matching Edit, Write and MultiEdit, that asks before a test is
weakened. Shared settings do not: a teammate whose PATH holds an older
checkwash would answer every edit with a usage error, exit 2, which blocks it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile

import checkwash
from checkwash import __version__


_CHECK_ARGS = ["check", "--format", "hook-json", "--hook-input", "stdin"]
# The managed Stop handler before #418. It stays managed, so an install
# replaces it, and a custom handler is still recognized by this prefix.
_LEGACY_CHECK_ARGS = ["check", "--format", "hook-json"]
_SESSION_ARGS = ["hook", "session-start"]
_PRE_TOOL_ARGS = ["hook", "pre-tool-use"]
_PRE_TOOL_MATCHER = "Edit|Write|MultiEdit"
# Matchers earlier versions wrote, so an install moves the handler from them.
_LEGACY_PRE_TOOL_MATCHERS: tuple[str, ...] = ()
_LEGACY_COMMANDS = {
    "checkwash check --format hook-json",
    "greenwash check --format hook-json",
}
# A constant program and a separate data argument keep paths out of Python and
# shell syntax. -I excludes cwd, PYTHONPATH and user site packages. The selected
# package origin is checked before calling it; a repo's checkwash.py cannot win.
_BOOTSTRAP = """# checkwash managed hook v1
import json, os, runpy, sys
binding = json.loads(sys.argv.pop(1))
if binding["kind"] == "zipapp":
    runpy.run_path(binding["path"], run_name="__main__")
else:
    sys.path.insert(0, binding["path"])
    import checkwash
    if os.path.realpath(checkwash.__file__) != binding["origin"]:
        raise SystemExit("checkwash hook: selected package origin changed; reinstall the hook")
    from checkwash.cli import main
    raise SystemExit(main())
"""
# The PreToolUse handler's own program (D-189). Exit 2 from a PreToolUse hook
# blocks the tool call, and an older checkwash left at the bound path answers
# `hook pre-tool-use` with a usage error, exit 2. So whatever the bound
# runtime does, this exits 0: at worst the hook says nothing.
_PRE_TOOL_BOOTSTRAP = """# checkwash managed PreToolUse hook v1
import json, os, runpy, sys
try:
    binding = json.loads(sys.argv.pop(1))
    if binding["kind"] == "zipapp":
        runpy.run_path(binding["path"], run_name="__main__")
    else:
        sys.path.insert(0, binding["path"])
        import checkwash
        if os.path.realpath(checkwash.__file__) == binding["origin"]:
            from checkwash.cli import main
            main()
except BaseException:
    pass
try:
    sys.stdout.flush()
finally:
    os._exit(0)
"""


class HookInstallError(ValueError):
    pass


def _local_binding() -> dict[str, str]:
    archive = getattr(checkwash.__loader__, "archive", None)
    if archive:
        return {"kind": "zipapp", "path": str(Path(archive).resolve())}
    origin = Path(checkwash.__file__).resolve()
    return {"kind": "package", "path": str(origin.parent.parent), "origin": str(origin)}


def _probe(command: str, args: list[str]) -> None:
    try:
        # Never run a version probe from the user's repository. Local handlers
        # are isolated as well, so their later cwd can safely be the project.
        with tempfile.TemporaryDirectory(prefix="checkwash-probe-") as cwd:
            result = subprocess.run(
                [command, *args], cwd=cwd, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
                check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HookInstallError(f"cannot execute the selected checkwash runtime: {exc}") from exc
    if result.returncode or result.stdout.decode("utf-8", "replace").strip() != f"checkwash {__version__}":
        raise HookInstallError(
            f"selected runtime did not report checkwash {__version__}; "
            "install that CLI version or use --local to bind this installation"
        )


def _shared_executable() -> str | None:
    """Search explicit absolute PATH entries, never Windows' implicit cwd.

    Python 3.11 shutil.which prepends the current directory on Windows even
    when a PATH argument is supplied. Joining an absolute entry ourselves also
    excludes empty, relative and drive-relative entries. The final portable
    hook still depends on the PATH used by each teammate's Claude runtime.
    """
    filename = "checkwash.exe" if os.name == "nt" else "checkwash"
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(entry)
        if not entry or not directory.is_absolute():
            continue
        candidate = directory / filename
        if candidate.is_file() and os.access(candidate, os.F_OK | os.X_OK):
            return str(candidate)
    return None


def build_handler(local: bool) -> dict:
    """The managed Stop handler, after a version probe of its runtime."""
    if local:
        command = os.path.abspath(sys.executable)
        args = ["-I", "-c", _BOOTSTRAP, json.dumps(_local_binding(), sort_keys=True), *_CHECK_ARGS]
        _probe(command, [*args[:-len(_CHECK_ARGS)], "--version"])
        return {"type": "command", "command": command, "args": args}
    executable = _shared_executable()
    if executable is None:
        raise HookInstallError(
            "shared settings require an installed checkwash CLI on PATH; "
            "install the CLI or use --local for this Python/zipapp installation"
        )
    _probe(executable, ["--version"])
    return {"type": "command", "command": "checkwash", "args": list(_CHECK_ARGS)}


def session_handler(stop: dict) -> dict:
    """The managed SessionStart handler on the same runtime as `stop` (#418)."""
    return {**stop, "args": [*stop["args"][:-len(_CHECK_ARGS)], *_SESSION_ARGS]}


def pre_tool_use_handler(stop: dict) -> dict:
    """The managed PreToolUse handler on the local runtime of `stop` (D-189).

    It runs `_PRE_TOOL_BOOTSTRAP`, which exits 0 whatever the bound runtime
    does, and is probed with an empty event, which must answer `{}`.
    """
    command, args = stop["command"], stop["args"]
    handler = {"type": "command", "command": command,
               "args": ["-I", "-c", _PRE_TOOL_BOOTSTRAP, args[3], *_PRE_TOOL_ARGS]}
    try:
        with tempfile.TemporaryDirectory(prefix="checkwash-probe-") as cwd:
            result = subprocess.run(
                [command, *handler["args"]], cwd=cwd, input=b"{}",
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HookInstallError(f"cannot execute the PreToolUse hook: {exc}") from exc
    if result.returncode or result.stdout.decode("utf-8", "replace").strip() != "{}":
        raise HookInstallError("the PreToolUse hook did not answer an empty event with {}; not installing it")
    return handler


def is_managed_handler(handler: object) -> bool:
    """Only exact installer shapes are eligible for replacement, not custom hooks."""
    if isinstance(handler, dict) and handler.get("type") == "command" and set(handler) == {"type", "command"}:
        return handler["command"] in _LEGACY_COMMANDS
    return _managed_shape(handler, (_CHECK_ARGS, _LEGACY_CHECK_ARGS))


def is_managed_session_handler(handler: object) -> bool:
    """The installer's SessionStart shapes, shared or local (#418)."""
    return _managed_shape(handler, (_SESSION_ARGS,))


def is_managed_pre_tool_use_handler(handler: object) -> bool:
    """The installer's PreToolUse shape: local only (D-189)."""
    return _managed_shape(handler, (_PRE_TOOL_ARGS,), bootstrap=_PRE_TOOL_BOOTSTRAP, shared=False)


def _managed_shape(handler: object, tails: tuple[list[str], ...], *, bootstrap: str = _BOOTSTRAP,
                   shared: bool = True) -> bool:
    if not isinstance(handler, dict) or handler.get("type") != "command":
        return False
    if set(handler) != {"type", "command", "args"}:
        return False
    args = handler["args"]
    if shared and handler["command"] == "checkwash" and args in tails:
        return True
    if not isinstance(handler["command"], str) or not isinstance(args, list):
        return False
    if args[:3] != ["-I", "-c", bootstrap] or not any(
        len(args) == 4 + len(tail) and args[4:] == tail for tail in tails
    ):
        return False
    try:
        binding = json.loads(args[3])
    except (TypeError, ValueError):
        return False
    return isinstance(binding, dict) and (
        set(binding) == {"kind", "path"} and binding.get("kind") == "zipapp"
        or set(binding) == {"kind", "path", "origin"} and binding.get("kind") == "package"
    ) and all(isinstance(value, str) for value in binding.values())


def stop_handlers(settings: object) -> list[dict]:
    """Validate the layers we must merge; leave unrelated settings untouched."""
    return _event_handlers(settings, "Stop")


def session_start_handlers(settings: object) -> list[dict]:
    return _event_handlers(settings, "SessionStart")


def pre_tool_use_handlers(settings: object) -> list[dict]:
    return _event_handlers(settings, "PreToolUse")


def _event_handlers(settings: object, event: str) -> list[dict]:
    if not isinstance(settings, dict):
        raise HookInstallError("settings must be a JSON object")
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise HookInstallError("settings.hooks must be an object")
    groups = hooks.get(event, [])
    if not isinstance(groups, list):
        raise HookInstallError(f"settings.hooks.{event} must be an array")
    handlers = []
    for entry in groups:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            raise HookInstallError(f"each {event} group must contain a hooks array")
        if not all(isinstance(handler, dict) for handler in entry["hooks"]):
            raise HookInstallError(f"each {event} handler must be an object")
        for handler in entry["hooks"]:
            if not isinstance(handler.get("type"), str):
                raise HookInstallError(f"each {event} handler must have a string type")
            if handler["type"] == "command" and (
                not isinstance(handler.get("command"), str)
                or "args" in handler and (
                    not isinstance(handler["args"], list)
                    or not all(isinstance(arg, str) for arg in handler["args"])
                )
            ):
                raise HookInstallError("command hooks require a string command and string args")
        handlers.extend(entry["hooks"])
    return handlers


def has_stop_hook(settings: object) -> bool:
    """Recognize configuration only; never execute it or infer effective policy."""
    return _has_hook(stop_handlers(settings), is_managed_handler, _LEGACY_CHECK_ARGS)


def has_session_start_hook(settings: object) -> bool:
    """A managed or custom `checkwash hook session-start` handler (#418)."""
    return _has_hook(session_start_handlers(settings), is_managed_session_handler, _SESSION_ARGS)


def has_pre_tool_use_hook(settings: object) -> bool:
    """A managed or custom `checkwash hook pre-tool-use` handler (D-189).

    Recognized whatever its group's matcher is: doctor reads configuration,
    never effective policy. Any other checkwash command under PreToolUse is
    not this hook.
    """
    return _has_hook(pre_tool_use_handlers(settings), is_managed_pre_tool_use_handler, _PRE_TOOL_ARGS)


def shared_settings_managed(repo: str) -> bool:
    """Whether `<repo>/.claude/settings.json` holds a managed Stop or SessionStart handler.

    Reads only; anything unreadable is False, and the installer reports it.
    """
    path = Path(repo) / ".claude" / "settings.json"
    try:
        if path.is_symlink() or not path.is_file():
            return False
        settings = json.loads(path.read_bytes().decode("utf-8-sig"))
        return any(map(is_managed_handler, stop_handlers(settings))) or any(
            map(is_managed_session_handler, session_start_handlers(settings)))
    except (OSError, ValueError, UnicodeError, HookInstallError):
        return False


def stop_reads_hook_input(settings: object) -> bool:
    """A Stop handler that hands checkwash its hook input (#418)."""
    for handler in stop_handlers(settings):
        if handler.get("type") != "command":
            continue
        shape = {key: handler[key] for key in ("type", "command", "args") if key in handler}
        if _managed_shape(shape, (_CHECK_ARGS,)):
            return True
        words = _checkwash_words(handler)
        if words and words[1:4] == _LEGACY_CHECK_ARGS and any(
            words[i:i + 2] == ["--hook-input", "stdin"] for i in range(4, len(words))
        ):
            return True
    return False


def _checkwash_words(handler: dict) -> list[str] | None:
    """A command handler's words when it runs a checkwash executable, else None."""
    if "args" in handler:
        words = [handler["command"], *handler["args"]]
    else:
        try:
            words = shlex.split(handler["command"])
        except ValueError:
            return None
    if not words:
        return None
    name = words[0].replace("\\", "/").rsplit("/", 1)[-1]
    return words if name in {"checkwash", "checkwash.exe", "greenwash", "greenwash.exe"} else None


def _has_hook(handlers: list[dict], managed, prefix: list[str]) -> bool:
    for handler in handlers:
        if handler.get("type") != "command":
            continue
        shape = {key: handler[key] for key in ("type", "command", "args") if key in handler}
        if managed(shape):
            return True
        words = _checkwash_words(handler)
        if words and words[1:1 + len(prefix)] == prefix:
            return True
    return False


def install_claude(repo: str, local: bool) -> str:
    path = Path(repo) / ".claude" / ("settings.local.json" if local else "settings.json")
    if any(p.is_symlink() or p.exists() and (
        getattr(p.lstat(), "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ) for p in (path, path.parent)):
        raise HookInstallError(f"{path} is linked; not touching it")
    original = path.read_bytes() if path.exists() else None
    try:
        settings = json.loads(original.decode("utf-8-sig")) if original is not None else {}
    except (ValueError, UnicodeError) as exc:
        raise HookInstallError(f"{path} is not valid UTF-8 JSON; not touching it") from exc
    stop_handlers(settings)
    session_start_handlers(settings)
    if local:
        pre_tool_use_handlers(settings)
    handler = build_handler(local)
    hooks = settings.setdefault("hooks", {})
    merged = [
        _merge(hooks.setdefault("Stop", []), handler, is_managed_handler),
        _merge(hooks.setdefault("SessionStart", []), session_handler(handler), is_managed_session_handler),
    ]
    if local:
        merged.append(_merge(hooks.setdefault("PreToolUse", []), pre_tool_use_handler(handler),
                             is_managed_pre_tool_use_handler, matcher=_PRE_TOOL_MATCHER,
                             legacy=_LEGACY_PRE_TOOL_MATCHERS))
    unchanged = all(same for same, _ in merged)
    matches = any(found for _, found in merged)
    data = (json.dumps(settings, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if data != original:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".checkwash-", delete=False) as output:
                temporary = Path(output.name)
                output.write(data)
            if (path.read_bytes() if path.exists() else None) != original:
                raise HookInstallError(f"{path} changed during installation; not replacing it")
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    action = "already installed" if unchanged else "updated" if matches else "installed"
    scope = "local runtime is bound to this installation" if local else "shared command requires checkwash on Claude's PATH"
    pre_tool = (
        "A PreToolUse hook in the same file asks you before an Edit or Write weakens a test "
        "(ASSERT_WEAKENED, ASSERT_REMOVED, TEST_DISABLED, TOLERANCE_LOOSENED or BROAD_EXCEPT_ADDED "
        "at high or above); in a -p run nobody can answer, so such an edit is denied. A -p run "
        "on Claude Code 2.1.260 denied an ASSERT_WEAKENED Edit under bypassPermissions too; the "
        "interactive prompt is not verified in any mode.\n"
        if local else
        "No PreToolUse hook is installed in shared settings: a teammate whose PATH holds an older "
        "checkwash would have every Edit and Write blocked. Each teammate can add it with "
        "`checkwash hook install --agent claude-code --local`.\n"
    )
    return (
        f"{action}: Stop hook configuration in {path}\n"
        "A SessionStart hook in the same file records where each session starts, so the Stop "
        "hook also checks what the session commits.\n"
        + pre_tool +
        f"{scope}; version probe passed.\n"
        "Requires Claude Code command/args exec-form support (tested with 2.1.260). "
        "Writing configuration does not verify a Claude Stop event.\n"
    )


def _merge(groups: list, handler: dict, managed, *, matcher: str | None = None,
           legacy: tuple[str, ...] = ()) -> tuple[bool, bool]:
    """Put `handler` in place of the managed ones in `groups`.

    Only installer groups are managed: unfiltered ones, or with `matcher`
    (PreToolUse, D-189) a group holding just that matcher or a `legacy` one.
    User matchers, timeouts, async flags and other custom handler fields
    remain exactly as configured, and a group's matcher is never rewritten.
    Returns (unchanged, whether a managed handler was there).
    """
    def owned(entry: dict) -> bool:
        if matcher is None:
            return set(entry) == {"hooks"}
        return set(entry) == {"matcher", "hooks"} and entry["matcher"] in (matcher, *legacy)

    matches = [
        (entry, old) for entry in groups if owned(entry)
        for old in entry["hooks"] if managed(old)
    ]
    unchanged = (len(matches) == 1 and matches[0][1] == handler
                 and (matcher is None or matches[0][0]["matcher"] == matcher))
    if not unchanged:
        for entry, old in matches:
            entry["hooks"].remove(old)
        target = next((entry for entry, _ in matches if matcher is None or entry["matcher"] == matcher), None)
        if target is not None:
            target["hooks"].append(handler)
        else:
            groups.append({"hooks": [handler]} if matcher is None else {"matcher": matcher, "hooks": [handler]})
    return unchanged, bool(matches)
