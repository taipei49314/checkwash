"""Does one command invoke a test runner? The runner-site predicate (#196 191.5, #216).

Row 69's `_runs_tests` asks whether a CI *file* ran a suite, and answers
generously: a runner token anywhere in its text. Deleting a file that ran a
suite is a weakening, so there the generous answer errs towards the finding,
and the deletion check and the opaque-exemption denial keep it.

A runner site (`ci_control_flow`) is one workflow step or pre-commit hook, and
a site that can no longer run reads as a disabled suite. There the generous
answer gave false reasons: `if: false` on `pip install pytest`, on
`./deploy-majestic.sh` or on `uses: pmeier/pytest-results-action` blocked as a
weakened test command. This predicate reads one command, and keeps a runner
name unless the command is known not to run it:

- A name counts as a whole word only. `jest` in `deploy-majestic.sh` and `tox`
  in `.tox` do not count; `pytest` in `run-pytest.sh` and in `pytest.exe` does.
  A tool with a subcommand (`make test`, `npm test`) needs the tool as a whole
  word, and the target may go on (`make tests`, `yarn test:unit`), as before.
- These contexts do not run it: the words of an `echo` or `printf` command; a
  heredoc body that `cat`, `tee`, `echo` or `printf` takes; the packages an
  install command names (`pip`, `python -m pip`, `uv pip` and `pipx install`,
  `poetry add`, `npm i`/`install`/`ci`, `yarn add`, `apt-get` and `brew
  install`); a shell comment. A name in one of them still counts where its
  text runs: inside a command substitution, in output piped to another
  command or written into a process substitution, in a heredoc body that
  expands a command substitution.
- Every other command keeps its runner: a wrapper (`bash -c`, `docker compose
  run`, `nix develop --command`, `sudo`, `env`) and any command checkwash does
  not know. Text the lexer cannot follow (an unterminated quote, an unbalanced
  substitution, a heredoc without its terminator or inside a substitution)
  keeps every name it holds.

The lexer reads bash. Other shells are read with bash's rules: PowerShell
spells `;`, `&&`, `|`, `#` and `echo` the same way, and where it differs (a
backtick escape) the text usually fails to lex and keeps its names.

#216 adds runners that count only where a command starts
(`invokes_positional_runner`): `node --test`, `mocha`, `ava`, `tap`, `bun
test`, `deno test`, `hatch test`, `just test`, `poe test` and `pdm test`.
`tap` is also an rxjs operator and `just` an English word, so one of these
counts as the first word of a simple command, past assignments, wrappers,
package launchers, `sh -c` and `eval`, or inside a command substitution or a
heredoc a shell reads, and never as a word elsewhere in the text.
`invokes_test_runner` asks both questions. Row 69's `_runs_tests`, the
opaque-exemption denial and the collection inventory keep the names above
alone.
"""
from __future__ import annotations

import bisect
import re
import shlex

from checkwash.roles import _TEST_RUNNER_TOKENS


def _runner_names() -> re.Pattern[str]:
    words = sorted((token for token in _TEST_RUNNER_TOKENS if " " not in token), key=len, reverse=True)
    tools = [token.split(" ", 1) for token in _TEST_RUNNER_TOKENS if " " in token]
    single = "|".join(re.escape(word) for word in words)
    paired = "|".join(re.escape(tool) + r"[ \t]+" + re.escape(sub) for tool, sub in tools)
    # A dot before a name makes it part of another name (`.tox`); a dot after
    # it may be an extension (`pytest.exe`, `tox.ini`), which keeps it.
    return re.compile(rf"(?<![\w.])(?:(?:{single})(?!\w)|{paired})", re.IGNORECASE | re.ASCII)


_RUNNER = _runner_names()

# Commands that print their words and run none of them.
_PRINTERS = frozenset({"echo", "printf"})
# Commands that take a heredoc body and run none of it.
_HEREDOC_READERS = frozenset({"cat", "tee"}) | _PRINTERS
# Words that may precede the command name of a simple command.
_RESERVED = frozenset({"!", "{", "if", "then", "elif", "else", "while", "until", "do", "time"})
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
_PIP = re.compile(r"pip(?:3(?:\.\d+)?)?")
_PIP_INSTALL = frozenset({"install"})
# npm's own aliases of `install` and `ci`. Never `install-test` (`it`) or
# `install-ci-test` (`cit`), which run the test script after installing.
_NPM_INSTALL = frozenset({
    "install", "i", "in", "ins", "inst", "insta", "instal", "isnt", "isnta", "isntal", "isntall", "add",
    "ci", "clean-install", "ic", "install-clean", "isntall-clean",
})
_INSTALLERS = {
    "pipx": frozenset({"install"}),
    "poetry": frozenset({"add"}),
    "npm": _NPM_INSTALL,
    "yarn": frozenset({"add"}),
    "apt-get": frozenset({"install"}),
    "brew": frozenset({"install"}),
}
_EXPANDS = re.compile(r"\$\(|`")
# Runs of characters with no meaning to the lexer, skipped in one step.
_BLANKS = re.compile(r"[ \t\r]+")
_PLAIN = re.compile(r"""[^ \t\r\n;&|()<>\\'"`$]+""")
_PLAIN_QUOTED = re.compile(r"""[^"\\`$]+""")
_CASE = re.compile(r"case\b")
# Nesting of quotes and substitutions the lexer follows before it gives up.
_MAX_NESTING = 64


def names_test_runner(text: str) -> bool:
    """Does this text name a test runner as a whole word, in any context?"""
    return _RUNNER.search(text) is not None


def invokes_test_runner(command: str) -> bool:
    """Does this command run a test runner, as far as its text can say?

    A name of `_TEST_RUNNER_TOKENS` counts as a whole word outside the
    contexts known not to run it (`invokes_named_runner`); a name #216 adds
    counts only where a command starts (`invokes_positional_runner`).
    """
    return invokes_named_runner(command) or invokes_positional_runner(command)


def invokes_named_runner(command: str) -> bool:
    """Does this command run a runner of `_TEST_RUNNER_TOKENS`? (#196 191.5)"""
    hits = [match.start() for match in _RUNNER.finditer(command)]
    if not hits:
        return False
    lexer = _Lexer(command)
    try:
        lexer.lex()
    except _Unread:
        return True
    quiet, runs = _Spans(lexer.quiet()), _Spans(lexer.runs)
    return any(runs.holds(hit) or not quiet.holds(hit) for hit in hits)


# The runners #216 adds, ruled with 191.5's predicate. Each counts only in
# command position: the first word of a simple command, after its
# assignments and reserved words and after the wrappers and package
# launchers below, never as a word anywhere in a file. `tap` is an rxjs
# operator and `mocha` a colour, so prose and identifiers must not run them.
_POSITION_NAMES = frozenset({"mocha", "ava", "tap"})
# Tools whose first argument is their test command (`bun test`, `just
# test`). The subcommand may go on (`just test-unit`, `poe test:fast`), as
# `make tests` does for `make test`.
_POSITION_TOOLS = frozenset({"bun", "deno", "hatch", "just", "poe", "pdm"})
# Commands that run their remaining words as a command.
_WRAPPERS = frozenset({
    "env", "sudo", "time", "timeout", "nice", "nohup", "exec", "command", "cross-env", "nyc", "c8", "xvfb-run",
})
# Package launchers that run the binary their first argument names, and the
# subcommand that makes one of them a launcher (none: it always is one).
# `yarn mocha` and `pnpm mocha` run the binary too.
_LAUNCHERS = {
    "npx": None, "pnpx": None, "bunx": None,
    "npm": frozenset({"exec", "x"}), "pnpm": frozenset({"exec", "dlx"}),
    "yarn": frozenset({"exec", "dlx"}), "bun": frozenset({"x"}),
}
_BINARY_LAUNCHERS = frozenset({"yarn", "pnpm"})
# Launcher options that take the next word as their value.
_LAUNCHER_VALUES = frozenset({"-p", "--package", "-w", "--workspace", "--prefix", "-C", "--dir"})
_SHELLS = frozenset({"sh", "bash", "zsh", "dash"})
# Shell options that take the next word as their value (`bash -o pipefail`).
_SHELL_VALUES = frozenset({"--rcfile", "--init-file"})
# A script node runs: past it, `--test` is the script's argument, not node's.
_NODE_SCRIPT = re.compile(r"\.(?:[cm]?js|[cm]?ts)$", re.IGNORECASE)
# Every word a positional runner can start with; text holding none is skipped.
_POSITION_HINT = re.compile(
    r"(?<![\w.])(?:mocha|ava|tap|bun|deno|hatch|just|poe|pdm|node)(?![\w-])", re.IGNORECASE | re.ASCII)
# The command words this reader follows. After a wrapper's option, a word
# that is none of them is read as the option's value (`nice -n 10 mocha`).
_STARTS = _POSITION_NAMES | _POSITION_TOOLS | _WRAPPERS | _SHELLS | frozenset(_LAUNCHERS) | {"node", "eval"}
_QUOTING = re.compile(r"""['"\\\s]""")
# Nesting of `sh -c '...'`, `eval` and substitutions the reader follows.
# Text nested deeper keeps every name it holds, as text the lexer cannot
# follow does.
_MAX_SHELL_DEPTH = 4


def invokes_positional_runner(command: str, depth: int = 0) -> bool:
    """Does a command in this text run one of #216's runners from command position?

    `node --test`, `mocha`, `ava`, `tap`, `bun test`, `deno test`, `hatch
    test`, `just test`, `poe test` and `pdm test`, behind assignments,
    wrappers (`env`, `cross-env`, `nyc`, `c8`, `sudo`, `time`, `timeout`),
    package launchers (`npx`, `npm exec`, `pnpm dlx`, `yarn`, `bunx`), `sh -c`
    and `eval`, and inside a command substitution or a heredoc a shell reads.
    Words a printer or an installer takes are no command's first word, and
    neither is a comment, `command -v` or the body of a heredoc `cat` writes
    out. Text the lexer cannot follow is split on its command separators
    instead, so a name in command position there still counts.
    """
    if not _POSITION_HINT.search(command):
        return False
    if depth > _MAX_SHELL_DEPTH:
        return True
    lexer = _Lexer(command)
    try:
        lexer.lex()
    except _Unread:
        segments = re.split(r"[;&|()\n`]+|\$\(", command)
        return any(_runs_from_position([_dequote(word) for word in segment.split()], depth)
                   for segment in segments if segment.split())
    for item in lexer.commands:
        words = [_dequote(command[start:end]) for start, end in item.words]
        if words and _runs_from_position(words, depth):
            return True
        # `bash <<EOF` runs its body; `cat <<EOF` writes it out.
        if item.heredocs and any(_basename(word) in _SHELLS for word in words) and any(
                invokes_positional_runner(command[start:end], depth + 1) for start, end, _ in item.heredocs):
            return True
    # A substitution's text runs wherever it sits: `out=$(mocha)`, `echo `tap``.
    return any(invokes_positional_runner(_substituted(command[start:end]), depth + 1)
               for start, end in lexer.runs)


def _substituted(text: str) -> str:
    """The command list inside `$(...)`, `<(...)`, `>(...)` or backticks."""
    return text[1:-1] if text.startswith("`") else text[2:-1]


def _dequote(word: str) -> str:
    # A word with no quote or escape is its own value, and shlex costs most
    # of the time a large script takes to read.
    if not _QUOTING.search(word):
        return word
    try:
        parts = shlex.split(word)
    except ValueError:
        return word
    return " ".join(parts) if parts else word


def _runs_from_position(words: list[str], depth: int) -> bool:
    """Does this simple command, as its words, start one of #216's runners?"""
    index = 0
    # `time` is a wrapper here, so that its options are read as options.
    while index < len(words) and (
            (words[index] in _RESERVED and words[index] != "time") or _ASSIGNMENT.match(words[index])):
        index += 1
    while index < len(words):
        # A make recipe's `@`, `-` and `+` prefixes are not part of the name.
        name = _basename(words[index].lstrip("@-+"))
        rest = index + 1
        if name in _WRAPPERS:
            index = _wrapped(words, rest)
            if index is None or (name == "command" and _prints_only(words[rest:index])):
                return False  # `command -v mocha` looks the name up and runs nothing
            if name == "timeout":
                index += 1  # its duration
            continue
        if name == "eval":
            return invokes_positional_runner(" ".join(words[rest:]), depth + 1)
        if name in _SHELLS:
            return _shell_command(words, rest, depth)
        if name in _LAUNCHERS:
            subcommands = _LAUNCHERS[name]
            at = _skip_options(words, rest)
            if subcommands is None:
                index = at
            elif at < len(words) and words[at] in subcommands:
                index = at + 1
            elif name in _BINARY_LAUNCHERS and at < len(words) and _basename(words[at]) in _POSITION_NAMES:
                index = at
            elif name in _POSITION_TOOLS:
                return at < len(words) and words[at].lower().startswith("test")
            else:
                return False
            while index < len(words) and words[index].startswith("-"):
                index += 2 if words[index] in _LAUNCHER_VALUES else 1
            continue
        if name in _POSITION_NAMES:
            return True
        if name in _POSITION_TOOLS:
            at = _skip_options(words, rest)
            return at < len(words) and words[at].lower().startswith("test")
        if name == "node":
            for word in words[rest:]:
                if word == "--test":
                    return True
                if _NODE_SCRIPT.search(word):
                    return False
            return False
        return False
    return False


def _wrapped(words: list[str], index: int) -> int | None:
    """Where the command a wrapper runs starts: past its options and assignments.

    An option may take the next word as its value. That word is read as one
    unless it starts a command this reader follows, so `nice -n 10 mocha` and
    `sudo -u ci mocha` reach `mocha`, while `sudo -E apt-get install tap`
    reaches `install`, which runs nothing.
    """
    while index < len(words):
        word = words[index]
        if _ASSIGNMENT.match(word):
            index += 1
        elif word.startswith("-") and word != "-":
            index += 1
            if ("=" not in word and word != "--" and index < len(words)
                    and not words[index].startswith("-") and _basename(words[index]) not in _STARTS):
                index += 1
        else:
            return index
    return None


def _prints_only(options: list[str]) -> bool:
    return any(not option.startswith("--") and ("v" in option[1:] or "V" in option[1:]) for option in options)


def _shell_command(words: list[str], index: int, depth: int) -> bool:
    """Does `sh -c '...'` (any of `_SHELLS`) run a runner in its command string?

    The string is the first word past the options, which `-c` must be among.
    Without `-c` the shell runs a script file, which is not a command string.
    """
    reads_string = False
    while index < len(words) and words[index][:1] in ("-", "+") and words[index] not in ("-", "+"):
        option = words[index]
        index += 1
        if option == "--":
            break
        if option.startswith("--"):
            index += option in _SHELL_VALUES
            continue
        flags = option[1:]
        reads_string = reads_string or "c" in flags
        # `-o pipefail`, `+O extglob`: each takes the next word.
        index += flags.count("o") + flags.count("O")
    return reads_string and index < len(words) and invokes_positional_runner(words[index], depth + 1)


class _Unread(Exception):
    """Text the lexer cannot follow: every runner name in it counts."""


class _Spans:
    """Half-open text spans, merged, for membership by bisection."""

    def __init__(self, spans: list[tuple[int, int]]):
        merged: list[list[int]] = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        self.starts = [start for start, _ in merged]
        self.ends = [end for _, end in merged]

    def holds(self, position: int) -> bool:
        index = bisect.bisect_right(self.starts, position) - 1
        return index >= 0 and position < self.ends[index]


class _Command:
    """One simple command: its words, every span it owns, its heredoc bodies."""

    def __init__(self):
        self.words: list[tuple[int, int]] = []
        self.spans: list[tuple[int, int]] = []
        self.heredocs: list[tuple[int, int, bool]] = []  # body span, and whether it expands
        self.piped = False  # its output goes to another command
        self.substituted = False  # a process substitution reads or writes it


def _basename(word: str) -> str:
    name = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _skip_options(words: list[str], index: int) -> int:
    while index < len(words) and words[index].startswith("-"):
        index += 1
    return index


def _install_arguments(words: list[str]) -> int | None:
    """Index of the first word an install command takes as a package, if any.

    `pip` is a word of its own in `python -m pip install` and `uv pip
    install` too. Options may stand between the tool and its subcommand
    (`apt-get -y install`); an option with a separate value does not, and the
    command then keeps its names.
    """
    for index, word in enumerate(words):
        name = _basename(word)
        subcommands = _PIP_INSTALL if _PIP.fullmatch(name) else _INSTALLERS.get(name)
        if subcommands is None:
            continue
        after = _skip_options(words, index + 1)
        if after < len(words) and words[after] in subcommands:
            return after + 1
    return None


class _Lexer:
    """A bounded bash lexer: simple commands, substitutions, heredocs, comments."""

    def __init__(self, text: str):
        self.text = text
        self.size = len(text)
        self.commands: list[_Command] = []
        self.runs: list[tuple[int, int]] = []  # substitutions: their text runs wherever it sits
        self.comments: list[tuple[int, int]] = []
        self.current = _Command()
        self.pending: list[tuple[str, bool, bool, _Command]] = []  # heredocs awaiting a body
        self.subshells = 0
        self.nesting = 0

    # -- top level ---------------------------------------------------------

    def lex(self) -> None:
        text, size = self.text, self.size
        index = 0
        while index < size:
            char = text[index]
            if char in " \t\r":
                index = _BLANKS.match(text, index).end()
            elif char == "\\" and text.startswith("\n", index + 1):
                index += 2
            elif char == "\n":
                self._end(None)
                index = self._bodies(index + 1)
            elif char == "#":
                end = text.find("\n", index)
                end = size if end < 0 else end
                self.comments.append((index, end))
                index = end
            elif text.startswith(("<(", ">("), index):
                end = self._substitution(index)
                self.current.substituted = True
                self.current.words.append((index, end))
                self.current.spans.append((index, end))
                index = end
            elif char in "<>" or (char.isdigit() and self._fd_redirect(index)):
                index = self._redirect(index)
            elif text.startswith(("&>>", "&>"), index):
                index = self._redirect(index)
            elif char in ";&|()":
                index = self._operator(index)
            else:
                index = self._word(index)
        self._end(None)
        if self.pending or self.subshells:
            raise _Unread

    def _end(self, operator: str | None) -> None:
        command = self.current
        if command.spans or command.heredocs:
            command.piped = operator in ("|", "|&")
            self.commands.append(command)
            self.current = _Command()

    def _operator(self, index: int) -> int:
        text = self.text
        for operator in ("&&", "||", "|&", ";;&", ";;", ";&", "|", "&", ";", "(", ")"):
            if text.startswith(operator, index):
                break
        if operator == "(":
            self.subshells += 1
        elif operator == ")":
            if not self.subshells:
                raise _Unread  # a `case` pattern, or text the lexer lost its place in
            self.subshells -= 1
        self._end(operator)
        return index + len(operator)

    def _bodies(self, index: int) -> int:
        """Read the heredoc bodies opened on the line that just ended."""
        text, size = self.text, self.size
        for delimiter, strip, expands, command in self.pending:
            start = index
            while True:
                if index >= size:
                    raise _Unread
                newline = text.find("\n", index)
                end = size if newline < 0 else newline
                line = text[index:end]
                if (line.lstrip("\t") if strip else line).rstrip("\r") == delimiter:
                    command.heredocs.append((start, index, expands))
                    index = size if newline < 0 else newline + 1
                    break
                if newline < 0:
                    raise _Unread
                index = newline + 1
        self.pending = []
        return index

    # -- redirections ------------------------------------------------------

    def _fd_redirect(self, index: int) -> bool:
        while index < self.size and self.text[index].isdigit():
            index += 1
        return index < self.size and self.text[index] in "<>"

    def _redirect(self, index: int) -> int:
        text, size = self.text, self.size
        start = index
        while index < size and text[index].isdigit():
            index += 1
        for operator in ("<<<", "<<-", "<<", "<>", "<&", "<", ">>", ">&", ">|", ">", "&>>", "&>"):
            if text.startswith(operator, index):
                break
        index += len(operator)
        self.current.spans.append((start, index))
        while index < size and text[index] in " \t":
            index += 1
        if text.startswith(("<(", ">("), index):
            end = self._substitution(index)
            self.current.substituted = True
        else:
            end = self._word(index, record=False)
        if end == index:
            raise _Unread  # a redirection with no target
        self.current.spans.append((index, end))
        if operator in ("<<", "<<-"):
            raw = text[index:end]
            delimiter = re.sub(r"""\\(.)|['"]""", lambda m: m.group(1) or "", raw)
            expands = not any(char in raw for char in "'\"\\")
            self.pending.append((delimiter, operator == "<<-", expands, self.current))
        return end

    # -- words -------------------------------------------------------------

    def _word(self, index: int, *, record: bool = True) -> int:
        text, size = self.text, self.size
        start = index
        while index < size:
            plain = _PLAIN.match(text, index)
            if plain:
                index = plain.end()
                continue
            if text[index] in " \t\r\n;&|()<>":
                break
            index = self._part(index)
        if index > size:
            raise _Unread  # a trailing backslash
        if record and index > start:
            self.current.words.append((start, index))
            self.current.spans.append((start, index))
        return index

    def _part(self, index: int) -> int:
        """Skip one character or one quoted or substituted part of a word."""
        text = self.text
        char = text[index]
        if char == "\\":
            return index + 2
        if char == "'":
            return self._single(index)
        if char == '"':
            return self._double(index)
        if char == "`":
            return self._backtick(index)
        if text.startswith("$(", index):
            return self._substitution(index)
        if text.startswith("${", index):
            return self._parameter(index)
        if text.startswith("$'", index):
            return self._ansi(index)
        return index + 1

    def _enter(self) -> None:
        self.nesting += 1
        if self.nesting > _MAX_NESTING:
            raise _Unread

    def _single(self, index: int) -> int:
        end = self.text.find("'", index + 1)
        if end < 0:
            raise _Unread
        return end + 1

    def _ansi(self, index: int) -> int:
        text, size = self.text, self.size
        index += 2
        while index < size:
            if text[index] == "\\":
                index += 2
            elif text[index] == "'":
                return index + 1
            else:
                index += 1
        raise _Unread

    def _double(self, index: int) -> int:
        self._enter()
        text, size = self.text, self.size
        index += 1
        while index < size:
            plain = _PLAIN_QUOTED.match(text, index)
            if plain:
                index = plain.end()
                continue
            char = text[index]
            if char == '"':
                self.nesting -= 1
                return index + 1
            if char == "\\":
                index += 2
            elif char == "`" or text.startswith(("$(", "${"), index):
                index = self._part(index)
            else:
                index += 1
        raise _Unread

    def _backtick(self, index: int) -> int:
        text, size = self.text, self.size
        end = index + 1
        while end < size:
            if text[end] == "\\":
                end += 2
            elif text[end] == "`":
                self.runs.append((index, end + 1))
                return end + 1
            else:
                end += 1
        raise _Unread

    def _parameter(self, index: int) -> int:
        """`${...}`, which may hold quotes and substitutions of its own."""
        self._enter()
        text, size = self.text, self.size
        depth = 1
        index += 2
        while index < size:
            char = text[index]
            if char == "}":
                depth -= 1
                if not depth:
                    self.nesting -= 1
                    return index + 1
                index += 1
            elif text.startswith("${", index):
                depth += 1
                index += 2
            elif char in "\\'\"`" or text.startswith("$(", index):
                index = self._part(index)
            else:
                index += 1
        raise _Unread

    def _substitution(self, index: int) -> int:
        """`$(...)`, `<(...)` or `>(...)`: a command list whose text runs."""
        self._enter()
        text, size = self.text, self.size
        start = index
        depth = 1
        index += 2
        word_start = True
        while index < size:
            char = text[index]
            if word_start and char == "#":
                newline = text.find("\n", index)
                if newline < 0:
                    raise _Unread
                index = newline
                continue
            if word_start and _CASE.match(text, index):
                raise _Unread  # a `case` pattern's `)` would close the substitution early
            if text.startswith("<<", index) and not text.startswith("<<<", index):
                raise _Unread  # a heredoc inside a substitution
            if char == "(":
                depth += 1
                index += 1
            elif char == ")":
                depth -= 1
                index += 1
                if not depth:
                    self.runs.append((start, index))
                    self.nesting -= 1
                    return index
            elif char in "\\'\"`" or text.startswith(("$(", "${", "$'"), index):
                index = self._part(index)
            else:
                index += 1
            word_start = char in " \t\n;&|()"
        raise _Unread

    # -- what does not run -------------------------------------------------

    def quiet(self) -> list[tuple[int, int]]:
        """Spans whose runner names this text does not run."""
        text = self.text
        quiet = list(self.comments)
        for command in self.commands:
            if command.piped or command.substituted:
                continue  # another command may run what this one writes
            words = [text[start:end] for start, end in command.words]
            name = next((_basename(word) for word in words
                         if word not in _RESERVED and not _ASSIGNMENT.match(word)), None)
            if name in _PRINTERS:
                quiet.extend(command.spans)
            if name in _HEREDOC_READERS:
                quiet.extend((start, end) for start, end, expands in command.heredocs
                             if not (expands and _EXPANDS.search(text, start, end)))
            first = _install_arguments(words)
            if first is not None:
                quiet.extend(command.words[first:])
        return quiet
