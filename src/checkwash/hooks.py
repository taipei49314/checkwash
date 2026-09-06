"""Claude command hooks: portable shared CLI or an isolated local runtime.

Exec-form handlers require Claude Code's command/args support. Qualification
records name the runtime tested; writing settings is not a Stop lifecycle test.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile

import checkwash
from checkwash import __version__


_CHECK_ARGS = ["check", "--format", "hook-json"]
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


def build_handler(local: bool) -> dict:
    if local:
        command = os.path.abspath(sys.executable)
        args = ["-I", "-c", _BOOTSTRAP, json.dumps(_local_binding(), sort_keys=True), *_CHECK_ARGS]
        _probe(command, [*args[:-3], "--version"])
        return {"type": "command", "command": command, "args": args}
    executable = shutil.which("checkwash")
    if executable is None or (os.name == "nt" and Path(executable).suffix.lower() != ".exe"):
        raise HookInstallError(
            "shared settings require an installed checkwash CLI on PATH; "
            "install the CLI or use --local for this Python/zipapp installation"
        )
    _probe(executable, ["--version"])
    return {"type": "command", "command": "checkwash", "args": list(_CHECK_ARGS)}


def is_managed_handler(handler: object) -> bool:
    """Only exact installer shapes are eligible for replacement, not custom hooks."""
    if not isinstance(handler, dict) or handler.get("type") != "command":
        return False
    if set(handler) == {"type", "command"}:
        return handler["command"] in _LEGACY_COMMANDS
    if set(handler) != {"type", "command", "args"}:
        return False
    args = handler["args"]
    if handler["command"] == "checkwash" and args == _CHECK_ARGS:
        return True
    if not isinstance(handler["command"], str) or not isinstance(args, list) or len(args) != 7:
        return False
    if args[:3] != ["-I", "-c", _BOOTSTRAP] or args[-3:] != _CHECK_ARGS:
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
    if not isinstance(settings, dict):
        raise HookInstallError("settings must be a JSON object")
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict):
        raise HookInstallError("settings.hooks must be an object")
    stop = hooks.get("Stop", [])
    if not isinstance(stop, list):
        raise HookInstallError("settings.hooks.Stop must be an array")
    handlers = []
    for entry in stop:
        if not isinstance(entry, dict) or not isinstance(entry.get("hooks"), list):
            raise HookInstallError("each Stop group must contain a hooks array")
        if not all(isinstance(handler, dict) for handler in entry["hooks"]):
            raise HookInstallError("each Stop handler must be an object")
        for handler in entry["hooks"]:
            if not isinstance(handler.get("type"), str):
                raise HookInstallError("each Stop handler must have a string type")
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
    for handler in stop_handlers(settings):
        if handler.get("type") != "command":
            continue
        shape = {key: handler[key] for key in ("type", "command", "args") if key in handler}
        if is_managed_handler(shape):
            return True
        if "args" in handler:
            words = [handler["command"], *handler["args"]]
        else:
            try:
                words = shlex.split(handler["command"])
            except ValueError:
                continue
        if not words:
            continue
        name = words[0].replace("\\", "/").rsplit("/", 1)[-1]
        if name in {"checkwash", "checkwash.exe", "greenwash", "greenwash.exe"} and words[1:4] == _CHECK_ARGS:
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
    handler = build_handler(local)
    stop = settings.setdefault("hooks", {}).setdefault("Stop", [])
    # Only unfiltered installer groups are managed. User matchers, timeouts,
    # async flags and other custom handler fields remain exactly as configured.
    matches = [
        (entry, old) for entry in stop if set(entry) == {"hooks"}
        for old in entry["hooks"] if is_managed_handler(old)
    ]
    unchanged = len(matches) == 1 and matches[0][1] == handler
    if not unchanged:
        for entry, old in matches:
            entry["hooks"].remove(old)
        if matches:
            matches[0][0]["hooks"].append(handler)
        else:
            stop.append({"hooks": [handler]})
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
    return (
        f"{action}: Stop hook configuration in {path}\n"
        f"{scope}; version probe passed.\n"
        "Requires Claude Code command/args exec-form support (tested with 2.1.260). "
        "Writing configuration does not verify a Claude Stop event.\n"
    )
