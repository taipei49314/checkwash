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


# A character that ends a shell command, starts another or redirects one. It
# does so wherever it stands in a word: `pytest -q||exit $?` is two commands.
_OPERATOR_CHARACTERS = "|&;<>()`"
# A word that is an operator from its first character on: `&&`, `|`, `;exit`,
# `>log`, `2>&1`. In `tests/shared;` an argument stands before the operator,
# and a backtick opens a substitution, which is an argument.
_STARTS_AN_OPERATOR = re.compile(r"[|&;()]|[0-9]*[<>]")
# Text this reader splits into other words than a shell does: a backslash,
# which it reads as a slash; a `#` inside a word, where it starts a comment;
# and the quotes `$'...'` and `$"..."`, which it reads as a `$` before a word.
_SPLIT_UNLIKE_A_SHELL = re.compile(r"""\\|[^ \t]#|\$['"]""")
# A YAML file, by its name: `ci.yml`, `pipeline.yaml`, a template or a copy of one (`ci.yml.j2`, `ci.yml~`).
_YAML_NAME = re.compile(r"\.ya?ml")
# A line's indentation, its dashes and the rest. A dash is an entry's where a space or the line's end follows it.
_YAML_LEAD = re.compile(r"( *)((?:-(?: +|$))*)(.*)$", re.DOTALL)
# The anchors and tags that may stand before a node: `&name`, `!tag`, `!!str`.
_YAML_PROPERTIES = re.compile(r"(?:[&!][^ \t]*(?:[ \t]+|$))+")
# A block scalar's header: `|`, `>-`, `|2+`, with a comment after it or not.
_BLOCK_SCALAR = re.compile(r"[|>][+\-]?[1-9]?[+\-]?[ \t]*(?:#.*)?")
# What ends a line for YAML and not for this reader: the next-line, line and
# paragraph separators. (A carriage return ends one for both: `_decode`.)
_YAML_BREAKS = ("\x85", "\N{LINE SEPARATOR}", "\N{PARAGRAPH SEPARATOR}")


def _closing_quote(text: str, quote: str, start: int) -> int | None:
    """Where the text goes on after the quote that closes a YAML scalar opened before `start`, or None."""

    index = start
    while index < len(text):
        character = text[index]
        if quote == '"' and character == "\\":
            index += 2
        elif character != quote:
            index += 1
        elif quote == "'" and text[index + 1:index + 2] == "'":
            index += 2
        else:
            return index + 1
    return None


def _yaml_value(rest: str) -> tuple[bool, str]:
    """Is this text, after a line's dashes, a key with its colon? And what stands after the colon, or the text itself.

    A colon ends a key where a space or the line's end follows it. A quote
    shields a colon only where it opens the text (`"a: b": c`), as YAML has
    it: `- echo "a: b"` is a mapping whose key is `echo "a`. Only a space and
    a tab are blanks, as in YAML: a no-break space is text.
    """

    index = 0
    if rest[:1] in ("'", '"'):
        closed = _closing_quote(rest, rest[0], 1)
        if closed is None:
            return False, rest.strip(" \t")
        index = closed
    while index < len(rest):
        character = rest[index]
        if character == "#" and index and rest[index - 1] in " \t":
            break
        if character == ":" and (index + 1 == len(rest) or rest[index + 1] in " \t"):
            return True, rest[index + 1:].strip(" \t")
        index += 1
    return False, rest.strip(" \t")


def _flow_closes(text: str) -> bool:
    """Does the flow collection that opens this text certainly end on this line, with nothing after it but a comment?

    The answer is yes only where the brackets counted are certainly the
    collection's own. A bracket outside a quoted scalar is. A quote opens a
    quoted scalar where a token starts: after `[`, `{` or `,`, or after a
    colon and a blank. Any other quote character (`{msg: don't}`,
    `{"a":"b"}`) is one this reader does not place, and the answer is no.
    So it is for a `#` inside the collection, which starts a comment after
    a blank and, to PyYAML and libyaml, against a bracket or a comma too;
    for a `?`, which may start a key; for a quoted scalar or a collection
    that is still open at the line's end; and for text after the closing
    bracket.
    """

    depth = 0
    last = ""  # the last character outside a quoted scalar that is no blank
    index = 0
    while index < len(text):
        character = text[index]
        if character in " \t":
            index += 1
            continue
        if character in "#?":
            return False  # a comment may start here, or a key: not placed
        if character in "\"'":
            if last not in ("[", "{", ",") and not (last == ":" and text[index - 1] in " \t"):
                return False
            closed = _closing_quote(text, character, index + 1)
            if closed is None:
                return False
            index = closed
            last = character
            continue
        if character in "[{":
            depth += 1
        elif character in "]}":
            depth -= 1
            if depth == 0:
                after = text[index + 1:].lstrip(" \t")
                return not after or after.startswith("#")
        last = character
        index += 1
    return False


def _complete_lines(path: str, lines: Sequence[str]) -> frozenset[int] | None:
    """The lines of a runner file that certainly end the command they hold, or None when every line may.

    A shell script, a Makefile or a batch file ends a command with its line,
    unless `_own_targets` finds the line one that goes on. A Python file is
    no shell text: no line of it is taken for a complete shell command. YAML
    joins lines in more ways than one line shows, so a YAML file is followed
    line by line, telling the lines that are its structure from those that
    lie in a scalar, and a line is complete only where that is certain:
    - a line of a literal block scalar whose header stands on its key's or
      its entry's line with no tag or anchor (`run: |`). Each of its lines
      is one line of the script;
    - a line of the structure on which a key's value or a sequence entry
      starts and ends: a plain scalar, or a quoted one closed on its line,
      where the next line that is neither blank nor a comment is indented no
      deeper than that key, or that entry's dash. A scalar goes on only in
      deeper lines, unless it is quoted.
    No line in a folded scalar (`run: >-`), in a quoted scalar that is still
    open or in a scalar that starts on the line after its key is taken for
    complete, nor is a line that holds a flow collection (`- {run: ...}`),
    where a bracket or a comma may stand against the command's last word.
    And no line is, from the first one this reader cannot place: text that is
    neither a key, an entry nor a node under one, a node on a document
    mark's line, a flow collection it cannot see the end of on its line
    (`_flow_closes`), a tab in the indentation of a line of the structure,
    or a character that ends a line for YAML alone (`_YAML_BREAKS`). A blank is a space or a tab, as in YAML: a line of a
    no-break space is text, and one that starts with it is no comment.
    """

    lowered = path.lower()
    if lowered.endswith(".py"):
        return frozenset()
    if not _YAML_NAME.search(lowered.rsplit("/", 1)[-1]):
        return None
    texts = [line.rstrip("\r") for line in lines]
    broken = [any(mark in line for mark in _YAML_BREAKS) for line in texts]
    indents = [len(line) - len(line.lstrip(" ")) if line.strip(" \t") else None for line in texts]
    # A tab among a line's leading blanks: YAML forbids it, and a reader that
    # allows it may take the line for a deeper one.
    tabbed = ["\t" in line[:len(line) - len(line.lstrip(" \t"))] for line in texts]
    # For each line, the next one that is neither blank nor a comment.
    following: list[int | None] = [None] * len(texts)
    later: int | None = None
    for number in range(len(texts) - 1, -1, -1):
        following[number] = later
        if indents[number] is not None and (broken[number] or not texts[number].lstrip(" ").startswith("#")):
            later = number
    complete: set[int] = set()
    inside: int | None = None   # lines indented deeper than this lie in a scalar that started above
    literal = False             # and that scalar is a literal block scalar
    quote = ""                  # the quote of a scalar that is still open; its lines stand at any depth
    pending: int | None = None  # after `key:` or `-` alone: what a node on the next lines is deeper than
    for number, line in enumerate(texts):
        if broken[number]:
            break  # two lines to YAML: neither this one nor a later one is known to be complete
        if quote:
            if _closing_quote(line, quote, 0) is not None:
                quote = ""
            continue
        indent = indents[number]
        if indent is None:
            continue
        if inside is not None:
            if indent > inside:
                if literal:
                    complete.add(number)
                continue
            inside, literal = None, False
        if tabbed[number]:
            break
        stripped = line.strip(" \t")
        if stripped.startswith("#"):
            continue
        if indent == 0 and stripped in ("---", "..."):
            pending = None
            continue
        if indent == 0 and line[:4] in ("--- ", "---\t"):
            break  # a node on the document mark's line: `--- {name: ci, ...`
        lead, dashes, rest = _YAML_LEAD.match(line).groups()
        tagged = _YAML_PROPERTIES.match(rest)
        if tagged:
            rest = rest[tagged.end():]
        # A flow collection is no key, whatever colon it holds.
        keyed, value = (False, rest.strip(" \t")) if rest[:1] in ("[", "{") else _yaml_value(rest)
        if keyed or dashes:
            # What the lines of this node are deeper than: its key, or its entry's dash.
            parent = len(lead) + len(dashes) if keyed else len(lead) + len(dashes.rstrip()) - 1
        elif pending is not None and indent > pending:
            parent = pending  # a node that starts on a line of its own
        else:
            break  # text this reader cannot place: no later line is known to be complete
        pending = None
        properties = _YAML_PROPERTIES.match(value)
        if properties:
            value = value[properties.end():]
        if not value or value.startswith("#"):
            if not (keyed or dashes):
                break
            pending = parent
            continue
        if _BLOCK_SCALAR.fullmatch(value):
            inside = parent
            literal = value.startswith("|") and not (tagged or properties) and bool(keyed or dashes)
            continue
        if value[0] in "[{":
            if not _flow_closes(value):
                break  # a flow collection this reader cannot see the end of
            inside = parent
            continue
        if value[0] in "\"'" and _closing_quote(value, value[0], 1) is None:
            quote = value[0]
            continue
        inside = parent
        if keyed or dashes:
            after = following[number]
            if after is None or (indents[after] <= parent and not tabbed[after] and not broken[after]):
                complete.add(number)
    return frozenset(complete)


def _own_targets(args: Sequence[str], line: str, continued: bool = False) -> tuple[str, ...]:
    """The targets `_pytest_cli` reads from words that are certainly the pytest command's own arguments.

    `_pytest_cli` reads every word after `pytest` to the end of the line. It
    reads on past a control operator, so `pytest || exit $?` gives `exit` and
    `$?` as targets, and a line that goes on is read no further than its
    end. Neither is changed here. This gives the targets read from the words
    before the first one that holds an operator character
    (`_OPERATOR_CHARACTERS`), where every word of the line that holds one is
    an operator from its first character on (`||`, `;exit`, `2>&1`). It
    gives none at all where the line's words are not known to be the
    command's:
    - an operator stands against another word, anywhere after `pytest`
      (`tests/shared;`, `tests/shared|tee`, `$(ls`, `tests/shared)`, a
      backtick substitution): the reader takes the whole word for a path no
      directory has, and the run may name one. A word behind the first
      operator counts too: a redirection leaves the words after it the
      run's (`2>&1 tests/shared;`), a quoted `(a or b)` looks like an
      operator once its quotes are gone, and a second run on the line is
      read as words of the first;
    - the line holds text this reader splits unlike a shell
      (`_SPLIT_UNLIKE_A_SHELL`): a backslash, a `#` inside a word, a
      `$'...'` or `$"..."` quote. A backslash at the line's end is one too;
    - the line ends in a caret, which continues a line in cmd. (A backtick
      at its end, which does in PowerShell, is an operator character and
      falls under the first case);
    - the caller says the line is not known to be complete
      (`_complete_lines`).
    A reader that must not take a word of the rest for a path argument asks
    for these (`collection_inventory.opaque_reached`). What `_pytest_cli`
    itself misreads among the own words, an unknown option's value for one,
    is a target here too.
    """

    if continued or line.rstrip().endswith("^") or _SPLIT_UNLIKE_A_SHELL.search(line):
        return ()
    own: list[str] = []
    ended = False
    for word in args:
        if any(character in word for character in _OPERATOR_CHARACTERS):
            if not _STARTS_AN_OPERATOR.match(word):
                return ()
            ended = True
        elif not ended:
            own.append(word)
    return _pytest_cli(own)[0]


def _runner_invocations(path: str, data: bytes | None) -> tuple[_RunnerInvocation, ...]:
    return tuple(invocation for invocation, _own in _runner_invocations_with_own_targets(path, data))


def _runner_invocations_with_own_targets(
    path: str, data: bytes | None
) -> tuple[tuple[_RunnerInvocation, tuple[str, ...]], ...]:
    """Every pytest invocation of a runner file, each with its `_own_targets`."""

    if not data or not _runs_tests(data, path):
        return ()
    persistent: tuple[str, ...] = ()
    invoked: list[tuple[_RunnerInvocation, tuple[str, ...]]] = []
    yaml_environment: tuple[str, ...] | None = None
    lines = _decode(data).split("\n")
    complete = _complete_lines(path, lines)
    for number, line in enumerate(lines):
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
                        (
                            _RunnerInvocation(roots, targets, mode, config_path, ""),
                            _own_targets(args, line, complete is not None and number not in complete),
                        )
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
                (
                    _RunnerInvocation(persistent, targets, mode, config_path, ""),
                    _own_targets(args, line, complete is not None and number not in complete),
                )
            )
    # A YAML env mapping is structural rather than shell execution order; its
    # line may appear after the run key while still governing that step.
    if yaml_environment is not None:
        invoked = [(replace(item, roots=yaml_environment), own) for item, own in invoked]
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
