"""Runner script and CI pytest CLI parsing, glob expansion, and command alignment."""

from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import replace
from fnmatch import fnmatchcase
from typing import Sequence

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.roles import _is_runner_script, _runs_tests
from checkwash.shadow_models import (
    _RunnerInvocation,
    _decode,
    _dedupe_roots,
    _normalise_root,
    _split_path_value,
)

_POWERSHELL_PYTHONPATH = re.compile(
    r"^\s*\$env:PYTHONPATH\s*=\s*([\"'])(.*?)\1\s*(?:#.*)?$",
    re.IGNORECASE,
)
_BATCH_PYTHONPATH = re.compile(
    r"^\s*set\s+(?:\"PYTHONPATH=(.*?)\"|PYTHONPATH\s*=\s*(.*?))\s*$",
    re.IGNORECASE,
)
_YAML_PYTHONPATH = re.compile(
    r"^\s*PYTHONPATH\s*:\s*([\"']?)(.*?)\1\s*(?:#.*)?$",
    re.IGNORECASE,
)


def _shell_pythonpath(line: str) -> tuple[str, bool] | None:
    """A literal shell assignment, optionally prefixing the test command."""

    try:
        words = shlex.split(line.replace("\\", "/"), comments=True, posix=True)
    except ValueError:
        return None
    exported = bool(words and words[0].lower() == "export")
    if exported:
        words = words[1:]
    if not words or "=" not in words[0]:
        return None
    name, value = words[0].split("=", 1)
    if name.lower() != "pythonpath":
        return None
    # Any prefix assignment with a following command is command-scoped.  It
    # must never become persistent merely because that command is `echo`
    # rather than pytest.
    command_scoped = not exported and len(words) > 1
    return value, command_scoped


# The options that take the next word as their value when it is not joined
# with `=`: pytest's own and the common plugins'. Every explicit target is
# read through them, a command's and a root config's addopts alike (#173),
# so `-n auto` or `-W error` is never a target.
_PYTEST_OPTIONS_WITH_VALUE = frozenset(
    {
        "-k",
        "-m",
        "-c",
        "--config-file",
        "--rootdir",
        "--confcutdir",
        "--basetemp",
        "--override-ini",
        "-o",
        "--ignore",
        "--ignore-glob",
        "--deselect",
        "--junitxml",
        "--junit-xml",
        "--junit-prefix",
        "--maxfail",
        "--durations",
        "--durations-min",
        "--import-mode",
        "-p",
        "-W",
        "--pythonwarnings",
        "-r",
        "--tb",
        "--capture",
        "--show-capture",
        "--color",
        "--code-highlight",
        "--pastebin",
        "--pdbcls",
        "--lfnf",
        "--last-failed-no-failures",
        "--verbosity",
        "--doctest-glob",
        "--doctest-report",
        "--log-level",
        "--log-format",
        "--log-date-format",
        "--log-cli-level",
        "--log-cli-format",
        "--log-cli-date-format",
        "--log-file",
        "--log-file-mode",
        "--log-file-level",
        "--log-file-format",
        "--log-file-date-format",
        "--log-auto-indent",
        "--log-disable",
        # pytest-xdist
        "-n",
        "--numprocesses",
        "--maxprocesses",
        "--dist",
        "--tx",
        "--rsyncdir",
        # pytest-cov
        "--cov-report",
        "--cov-config",
        "--cov-fail-under",
        "--cov-context",
        # pytest-timeout, pytest-rerunfailures, pytest-html, pytest-randomly,
        # pytest-django, pytest-asyncio and hypothesis
        "--timeout",
        "--timeout-method",
        "--reruns",
        "--reruns-delay",
        "--only-rerun",
        "--html",
        "--css",
        "--randomly-seed",
        "--ds",
        "--dc",
        "--asyncio-mode",
        "--hypothesis-profile",
        "--hypothesis-seed",
        "--hypothesis-verbosity",
    }
)
# Options whose value is optional: they take the next word unless it is an
# option itself, as argparse reads them (`--cov src tests` covers src).
_PYTEST_OPTIONS_WITH_OPTIONAL_VALUE = frozenset({"--cov", "--debug", "--cache-show"})


def _line_words(line: str) -> list[str]:
    try:
        return shlex.split(line.replace("\\", "/"), comments=True, posix=True)
    except ValueError:
        return []


def _pytest_args(words: Sequence[str]) -> list[str] | None:
    """Arguments after an actual pytest command, never a textual mention."""

    cleaned = list(words)
    while cleaned and cleaned[0] in ("-", "run:", "command:"):
        cleaned.pop(0)
    if not cleaned:
        return None
    executable = posixpath.basename(cleaned[0]).lower()
    if executable in ("echo", "printf", "write-output", "rem", "::"):
        return None
    for index, word in enumerate(cleaned):
        base = posixpath.basename(word).lower()
        if base in ("pytest", "pytest.exe", "py.test", "py.test.exe"):
            return cleaned[index + 1 :]
        if (
            (base.startswith("python") or base in ("py", "pypy", "pypy3"))
            and index + 2 < len(cleaned)
            and cleaned[index + 1] == "-m"
            and cleaned[index + 2] == "pytest"
        ):
            return cleaned[index + 3 :]
    return None


def _pytest_cli(args: Sequence[str]) -> tuple[tuple[str, ...], str | None, str | None]:
    targets: list[str] = []
    mode: str | None = None
    config_path: str | None = None
    skip_value = False
    for index, argument in enumerate(args):
        if skip_value:
            skip_value = False
            continue
        if argument.startswith("--import-mode="):
            candidate = argument.split("=", 1)[1]
            if candidate in ("prepend", "append", "importlib"):
                mode = candidate
            continue
        if argument == "--import-mode" and index + 1 < len(args):
            candidate = args[index + 1]
            if candidate in ("prepend", "append", "importlib"):
                mode = candidate
            skip_value = True
            continue
        if argument in ("-c", "--config-file") and index + 1 < len(args):
            config_path = _normalise_root(args[index + 1])
            skip_value = True
            continue
        if argument.startswith("--config-file="):
            config_path = _normalise_root(argument.split("=", 1)[1])
            continue
        if argument in _PYTEST_OPTIONS_WITH_VALUE:
            skip_value = True
            continue
        if argument in _PYTEST_OPTIONS_WITH_OPTIONAL_VALUE:
            skip_value = index + 1 < len(args) and not args[index + 1].startswith("-")
            continue
        if argument.startswith("-") or argument in ("&&", "||", ";", "|"):
            continue
        target = argument.split("::", 1)[0]
        normalised = _normalise_root(target)
        if normalised in (None, ""):
            # `pytest .` is an unscoped repository invocation.
            if normalised == "":
                targets.clear()
                break
            continue
        targets.append(normalised)
    return _dedupe_roots(targets), mode, config_path


def _runner_invocations(path: str, data: bytes | None) -> tuple[_RunnerInvocation, ...]:
    if not data or not _runs_tests(data, path):
        return ()
    persistent: tuple[str, ...] = ()
    invoked: list[_RunnerInvocation] = []
    yaml_environment: tuple[str, ...] | None = None
    for line in _decode(data).split("\n"):
        words = _line_words(line)
        shell = _shell_pythonpath(line)
        if shell is not None:
            value, command_scoped = shell
            roots = _split_path_value(value, inherited=persistent)
            if command_scoped:
                args = _pytest_args(words[1:])
                if args is not None:
                    targets, mode, config_path = _pytest_cli(args)
                    invoked.append(
                        _RunnerInvocation(roots, targets, mode, config_path, "")
                    )
            else:
                persistent = roots
            continue
        powershell = _POWERSHELL_PYTHONPATH.match(line)
        if powershell:
            persistent = _split_path_value(
                powershell.group(2), inherited=persistent
            )
            continue
        batch = _BATCH_PYTHONPATH.match(line)
        if batch:
            persistent = _split_path_value(
                batch.group(1) if batch.group(1) is not None else batch.group(2),
                inherited=persistent,
            )
            continue
        yaml = _YAML_PYTHONPATH.match(line)
        if yaml:
            yaml_environment = _split_path_value(
                yaml.group(2), inherited=persistent
            )
            persistent = yaml_environment
            continue
        args = _pytest_args(words)
        if args is not None:
            targets, mode, config_path = _pytest_cli(args)
            invoked.append(
                _RunnerInvocation(persistent, targets, mode, config_path, "")
            )
    # A YAML env mapping is structural rather than shell execution order; its
    # line may appear after the run key while still governing that step.
    if yaml_environment is not None:
        invoked = [replace(item, roots=yaml_environment) for item in invoked]
    return tuple(invoked)


def _runner_pythonpath(path: str, data: bytes | None) -> tuple[str, ...]:
    """Compatibility view: roots at the last actual pytest invocation."""

    invocations = _runner_invocations(path, data)
    return invocations[-1].roots if invocations else ()


def _scope_applies(scope_dir: str, test_path: str) -> bool:
    if not scope_dir:
        return True
    return test_path == scope_dir or test_path.startswith(scope_dir.rstrip("/") + "/")


def _invocation_applies(invocation: _RunnerInvocation, test_path: str) -> bool:
    if invocation.scope is not None:
        return test_path in invocation.scope
    if not invocation.targets:
        return True
    for target in invocation.targets:
        if target.endswith(".py"):
            if test_path == target:
                return True
        elif _scope_applies(target, test_path):
            return True
    return False


_SHELL_GLOB_MAGIC = frozenset("*?[")


def _shell_glob_match(pattern: str, path: str) -> bool:
    """Match a literal, single-level POSIX shell pathname expansion.

    ``**`` depends on shell options and is therefore not claimed.  Ordinary
    ``*``, ``?`` and bracket expressions are provable from the repository
    inventory; unlike ``fnmatch`` over a whole string, they never cross ``/``.
    """

    pattern_parts = pattern.strip("/").split("/")
    path_parts = path.strip("/").split("/")
    if len(pattern_parts) != len(path_parts) or "**" in pattern_parts:
        return False
    return all(
        not (part.startswith(".") and not glob.startswith("."))
        and fnmatchcase(part, glob)
        for glob, part in zip(pattern_parts, path_parts)
    )


def _expand_invocation_targets(
    invocation: _RunnerInvocation, test_paths: Sequence[str]
) -> _RunnerInvocation | None:
    """Resolve targets and their exact test scope against one side's inventory."""

    candidates = set(test_paths)
    for path in test_paths:
        directory = path.rpartition("/")[0]
        while directory:
            candidates.add(directory)
            directory = directory.rpartition("/")[0]
    expanded: list[str] = []
    for target in invocation.targets:
        if not any(char in target for char in _SHELL_GLOB_MAGIC):
            expanded.append(target)
            continue
        matches = sorted(
            path for path in candidates if _shell_glob_match(target, path)
        )
        if not matches:
            # Shell behaviour for an unmatched pattern is environment-specific
            # (literal, nullglob, or hard failure), so it cannot safely widen
            # the invocation to every test.
            return None
        expanded.extend(matches)
    normalised_targets = _dedupe_roots(expanded)
    if not invocation.targets:
        scope = tuple(sorted(test_paths))
    else:
        selected: set[str] = set()
        for target in normalised_targets:
            if target in test_paths:
                selected.add(target)
            else:
                selected.update(
                    path
                    for path in test_paths
                    if _scope_applies(target, path)
                )
        scope = tuple(sorted(selected))
    return replace(
        invocation,
        targets=normalised_targets,
        scope=scope,
        raw_targets=(
            invocation.targets
            if invocation.raw_targets is None
            else invocation.raw_targets
        ),
    )


def _invocation_scope_score(
    before: _RunnerInvocation, after: _RunnerInvocation
) -> int:
    """How strongly two commands identify the same pytest oracle scope."""

    if (
        before.raw_targets is not None
        and before.raw_targets == after.raw_targets
        and before.cwd == after.cwd
    ):
        return 5
    if before.scope is not None and after.scope is not None:
        if not before.scope or before.scope != after.scope:
            return 0
        return 4 if before.cwd == after.cwd else 3
    before_targets = frozenset(before.targets)
    after_targets = frozenset(after.targets)
    return 4 if before_targets == after_targets else 0


def _align_runner_invocations(
    before: Sequence[_RunnerInvocation], after: Sequence[_RunnerInvocation]
) -> tuple[tuple[_RunnerInvocation, _RunnerInvocation], ...]:
    """Align commands by oracle scope and retain every head invocation.

    Exact unchanged commands are paired first so reordering is inert.  A
    duplicate head command may reuse the matching base command: otherwise an
    appended stand-in invocation would disappear.  A genuinely new scope gets
    a conservative repository-environment baseline with the same targets.
    Removed head commands cannot affect the runtime oracle and are omitted.
    """

    unused = set(range(len(before)))
    pairs: list[tuple[_RunnerInvocation, _RunnerInvocation]] = []
    for after_index, current in enumerate(after):
        ranked: list[tuple[int, int, int, int, int]] = []
        for before_index, candidate in enumerate(before):
            score = _invocation_scope_score(candidate, current)
            if not score:
                continue
            identical = int(candidate == current)
            available = int(before_index in unused)
            distance = -abs(before_index - after_index)
            ranked.append((identical, score, available, distance, before_index))
        if ranked:
            before_index = max(ranked)[-1]
            unused.discard(before_index)
            baseline = before[before_index]
        else:
            baseline = replace(
                current,
                roots=(),
                mode=None,
                config_path=None,
            )
        pairs.append((baseline, current))
    return tuple(pairs)


def _runner_control(path: str, change: FileChange, config: Config) -> bool:
    """Only actual runner/CI files can make an environment assignment live."""

    before, after = _runner_invocation_sides(path, change, config)
    return before != after


def _runner_invocation_sides(
    path: str, change: FileChange, config: Config
) -> tuple[tuple[_RunnerInvocation, ...], tuple[_RunnerInvocation, ...]]:
    old_path = (change.old_path or path).replace("\\", "/")
    return (
        _runner_invocations_live(old_path, change.before, config),
        _runner_invocations_live(path, change.after, config),
    )


def _runner_search_sides(
    path: str, change: FileChange, config: Config
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Live runner roots on each side, including a rename across roles."""

    before_invocations, after_invocations = _runner_invocation_sides(path, change, config)
    before = before_invocations[-1].roots if before_invocations else ()
    after = after_invocations[-1].roots if after_invocations else ()
    return before, after


def _runner_invocations_live(
    path: str, data: bytes | None, config: Config
) -> tuple[_RunnerInvocation, ...]:
    live = config.role_of(path) == "ci" or _is_runner_script(path, data, data)
    return _runner_invocations(path, data) if live else ()


def _runner_roots(path: str, data: bytes | None, config: Config) -> tuple[str, ...]:
    invocations = _runner_invocations_live(path, data, config)
    return invocations[-1].roots if invocations else ()


def _could_be_extensionless_runner(path: str) -> bool:
    """Could this inventory path need a shebang read to identify a runner?"""

    base = path.rsplit("/", 1)[-1]
    return bool(base) and "." not in base
