"""Does one command invoke a test runner? The runner-site predicate (#196 191.5).

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
"""
from __future__ import annotations

import bisect
import re

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
    """Does this command run a test runner, as far as its text can say?"""
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
