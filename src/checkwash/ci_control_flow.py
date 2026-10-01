"""CI control flow: where a pipeline runs the suite, and whether it still can.

E6's token scan (`ci.py`) reads the lines a diff adds. A condition, a trigger
or a hook inventory stops a runner without touching one: `if: false` under
`- run: pytest`, the `pull_request` trigger dropped from a workflow whose
`push` fires only on `main`, the pytest hook deleted from
`.pre-commit-config.yaml`. Each added line is innocent on its own, so all of
those diffs passed at warn while `pytest || true` blocked (issue #181).

The shared definition is the *runner site*: a workflow step or a pre-commit
hook whose own command invokes a test runner (`_runs_tests`, the predicate
row 69 already uses), and whether it can execute for a pull request's
commits. A site is dead only for a reason that holds statically:

- a step or job `if:` that is false whatever the run looks like, or false for
  every event that can run the workflow on a pull request. `github.event_name`
  is the one context bound. Status functions read as they do on a run that
  is otherwise green, the only run in which a runner can turn a passing
  check red: `failure()` and `cancelled()` are false, `success()` and
  `always()` true. `contains`, `startsWith`, `endsWith` and `fromJSON` fold
  on literal arguments. Every other context, function or output is unknown
  and keeps the site live;
- a job that `needs:` a dead job and has no status function (`always()`,
  `failure()`, `cancelled()`) to run anyway: GitHub skips it, and a skipped
  job reports success;
- a trigger set with no event that runs on a pull request's commits. An
  unfiltered `push` still runs on the PR's own branch, so dropping
  `pull_request` beside it keeps the suite;
- a pre-commit hook parked on the `manual` stage.

Two predicates read the inventory. *Disabled*: a runner command lost a live
site and gained a dead one, so the suite is still written there and cannot
execute. A runner reworded as it is disabled counts when the inventory moved
a site, one live fewer and one dead more; a runner born dead beside a
reworded live one disabled nothing that ran. *Removed*
(row 69's two-sided rule, hook inventory only): the file ran a suite at base
and runs none at head. Removal is not judged for workflows: a step that
leaves one may have moved to a reusable workflow, a composite action or a
script, and one file's head side cannot tell that from deletion.

Not evaluated: path filters, `pull_request` branch filters and activity
`types`, matrix legs, GitLab `rules:`. YAML outside the reader's subset
(tags, complex keys, directives, tab indentation) leaves the file at the
existing warn.
"""
from __future__ import annotations

import re
from collections import Counter

from checkwash.roles import _runs_tests

_MAX_BYTES = 1_000_000
_MAX_DEPTH = 48
_MAX_FLOW_LINES = 200
# A merge key copies entries where an alias shares them, so a chain of
# `<<: *previous` copies quadratically: the total one document merges is bounded.
_MAX_MERGED = 100_000
# GitHub defines a few dozen events. A trigger block listing more binds none,
# rather than judging every step once per listed event.
_MAX_EVENTS = 64


class _Unsupported(Exception):
    """YAML outside the modelled subset; `_read_yaml` turns it into None."""


class _ExprError(Exception):
    """An expression the evaluator cannot parse; its value is unknown."""


class _Quoted(str):
    """A scalar written in quotes: always a string, never a null or boolean."""


# ---------------------------------------------------------------- YAML subset

# `key: |`, `- |`, `- key: >-`: a block scalar indicator ending the line.
_BLOCK_INDICATOR = re.compile(r"(?:^-|:) +([|>][1-9+-]{0,2})$")
# A mapping key and the rest of its line. A plain key stops at the first
# colon, which keeps the match linear however long the line is.
_KEY = re.compile(
    r"""(?:"(?P<double>(?:[^"\\]|\\.)*)" *|'(?P<single>(?:[^']|'')*)' *"""
    r"""|(?P<plain>[^\s"'#&*!|>%@`{}\[\],?:][^:]*?)):(?: +(?P<rest>.*))?$"""
)
_DASHES = re.compile(r"(?:- +)*")
_ESCAPE = re.compile(r"\\(.)")
_WHITESPACE = re.compile(r"[ \t\r\n]+")


def _unquoted(text: str):
    """(index, character) for every character outside a quoted scalar.

    A quote opens a quoted scalar only where a scalar can start: at the
    start, or after `:`, `-`, `[`, `{` or `,`. Inside a plain scalar
    (`run: echo it's`) it is an ordinary character, as YAML reads it.
    """
    quote = ""
    previous = ""
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if quote == '"' and char == "\\":
                index += 2
                continue
            if char == quote:
                if quote == "'" and text[index + 1:index + 2] == "'":
                    index += 2
                    continue
                quote = ""
                previous = char
        elif char in "\"'" and previous in ("", ":", "-", "[", "{", ","):
            quote = char
        else:
            yield index, char
            if char not in " \t":
                previous = char
        index += 1


def _strip_comment(line: str) -> str:
    for index, char in _unquoted(line):
        if char == "#" and (index == 0 or line[index - 1] in " \t"):
            return line[:index]
    return line


def _flow_depth(text: str) -> int:
    return sum((char in "[{") - (char in "]}") for _, char in _unquoted(text))


def _opens_flow(content: str) -> bool:
    """Does this line's value open a flow collection it does not close?"""
    rest = content[_DASHES.match(content).end():]
    key = _KEY.match(rest)
    if key:
        rest = key.group("rest") or ""
    return rest[:1] in ("[", "{") and _flow_depth(rest) > 0


def _logical_lines(text: str) -> list[tuple[int, str, str | None]]:
    """(indent, content, block scalar) for each line that carries YAML.

    Comments are dropped, a block scalar's body is attached to the line that
    opens it, and a flow collection spread over several lines is joined onto
    the line that opens it.
    """
    raw = text.split("\n")
    out: list[tuple[int, str, str | None]] = []
    index = 0
    while index < len(raw):
        body = _strip_comment(raw[index]).rstrip()
        index += 1
        content = body.lstrip(" ")
        if not content:
            continue
        if content[0] in "\t%":
            raise _Unsupported  # tab indentation, or a directive
        indent = len(body) - len(content)
        if content in ("---", "..."):
            if out:
                raise _Unsupported  # a second document
            continue
        block = None
        indicator = _BLOCK_INDICATOR.search(content)
        if indicator:
            dashes = _DASHES.match(content).end()
            # The body runs while it is indented past the key that owns it
            # (for a bare `- |`, past the dash).
            owner = indent + (max(dashes - 2, 0) if content[dashes:dashes + 1] in ("|", ">") else dashes)
            lines: list[str] = []
            while index < len(raw):
                stripped = raw[index].lstrip(" ")
                if stripped.strip() and len(raw[index]) - len(stripped) <= owner:
                    break
                lines.append(raw[index])
                index += 1
            while lines and not lines[-1].strip():
                lines.pop()
            cut = min((len(line) - len(line.lstrip(" ")) for line in lines if line.strip()), default=0)
            block = "\n".join(line[cut:] for line in lines)
            content = content[:indicator.start(1)].rstrip()
        elif _opens_flow(content):
            depth = _flow_depth(content)
            parts = [content]
            while depth > 0:
                if index >= len(raw) or len(parts) > _MAX_FLOW_LINES:
                    raise _Unsupported
                part = _strip_comment(raw[index]).strip()
                index += 1
                if part:
                    parts.append(part)
                    depth += _flow_depth(part)
            content = " ".join(parts)
        out.append((indent, content, block))
    return out


def _is_dash(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _unescape(text: str) -> str:
    return _ESCAPE.sub(lambda match: {"n": "\n", "t": "\t"}.get(match.group(1), match.group(1)), text)


def _split_key(text: str) -> tuple[str, str]:
    match = _KEY.match(text)
    if match is None:
        raise _Unsupported
    if match.group("double") is not None:
        key = _unescape(match.group("double"))
    elif match.group("single") is not None:
        key = match.group("single").replace("''", "'")
    else:
        key = match.group("plain").rstrip()
    return key, (match.group("rest") or "").strip()


def _split_anchor(text: str) -> tuple[str | None, str]:
    """`&name rest` -> (name, rest); anything else -> (None, text)."""
    if not text.startswith("&"):
        return None, text
    name, _, rest = text.partition(" ")
    if len(name) < 2:
        raise _Unsupported
    return name[1:], rest.strip()


def _flow_items(inner: str) -> list[str]:
    """The comma-separated items inside a flow collection."""
    items: list[str] = []
    depth = 0
    start = 0
    for index, char in _unquoted(inner):
        if char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == "," and depth == 0:
            items.append(inner[start:index])
            start = index + 1
    if depth:
        raise _Unsupported
    items.append(inner[start:])
    return [item.strip() for item in items if item.strip()]


class _Reader:
    """Block-style YAML as dict / list / str / None.

    The subset workflow and pre-commit files are written in: block mappings
    and sequences (indentless ones too), plain, quoted and block scalars,
    flow collections, anchors, aliases and merge keys.
    """

    def __init__(self, lines: list[tuple[int, str, str | None]]):
        self.lines = lines
        self.anchors: dict[str, object] = {}
        self.merged = 0

    def document(self):
        node, end = self.node(0, 0)
        if end != len(self.lines):
            raise _Unsupported
        return node

    def node(self, index: int, depth: int):
        if depth > _MAX_DEPTH:
            raise _Unsupported
        indent, text, _block = self.lines[index]
        if _is_dash(text):
            return self.sequence(index, indent, depth)
        return self.mapping(index, indent, depth)

    def sequence(self, index: int, indent: int, depth: int):
        items: list[object] = []
        while (index < len(self.lines) and self.lines[index][0] == indent
               and _is_dash(self.lines[index][1])):
            _, text, block = self.lines[index]
            anchor, rest = _split_anchor(text[1:].strip())
            if rest and (_is_dash(rest) or _KEY.match(rest)):
                # The item's first entry shares the dash's line: read it in place.
                self.lines[index] = (indent + len(text) - len(rest), rest, block)
                item, index = self.node(index, depth + 1)
            else:
                item, index = self.value(rest, block, index + 1, indent, depth, indentless=False)
            if anchor is not None:
                self.anchors[anchor] = item
            items.append(item)
        return items, index

    def mapping(self, index: int, indent: int, depth: int):
        out: dict[str, object] = {}
        while index < len(self.lines) and self.lines[index][0] == indent:
            _, text, block = self.lines[index]
            if _is_dash(text):
                raise _Unsupported
            key, rest = _split_key(text)
            anchor, rest = _split_anchor(rest)
            value, index = self.value(rest, block, index + 1, indent, depth, indentless=True)
            if anchor is not None:
                self.anchors[anchor] = value
            if key == "<<":
                # A merge key: explicit keys win, wherever they are written.
                for source in value if isinstance(value, list) else [value]:
                    if not isinstance(source, dict):
                        raise _Unsupported
                    self.merged += len(source)
                    if self.merged > _MAX_MERGED:
                        raise _Unsupported
                    for name, item in source.items():
                        out.setdefault(name, item)
            else:
                out[key] = value
        return out, index

    def value(self, rest: str, block: str | None, index: int, indent: int, depth: int, *, indentless: bool):
        """The value after `key:` or `-` on a line at `indent`; `index` is the next line."""
        lines = self.lines
        if block is not None:
            if rest:
                raise _Unsupported
            return block, index
        deeper = index < len(lines) and lines[index][0] > indent
        if not rest and deeper and (_is_dash(lines[index][1]) or _KEY.match(lines[index][1])):
            return self.node(index, depth + 1)
        if rest or deeper:
            # A scalar, possibly continued (or begun) on more-indented lines.
            parts = [rest] if rest else []
            while index < len(lines) and lines[index][0] > indent:
                parts.append(lines[index][1])
                index += 1
            return self.scalar(" ".join(parts), depth), index
        if indentless and index < len(lines) and lines[index][0] == indent and _is_dash(lines[index][1]):
            return self.sequence(index, indent, depth + 1)
        return None, index

    def scalar(self, text: str, depth: int):
        if depth > _MAX_DEPTH:
            raise _Unsupported
        text = text.strip()
        if text.startswith("*"):
            if text[1:] not in self.anchors:
                raise _Unsupported
            return self.anchors[text[1:]]
        anchor, text = _split_anchor(text)
        result: object
        if not text or text in ("~", "null", "Null", "NULL"):
            result = None
        elif text[0] == "[" and text.endswith("]"):
            result = [self.scalar(item, depth + 1) for item in _flow_items(text[1:-1])]
        elif text[0] == "{" and text.endswith("}"):
            mapping: dict[str, object] = {}
            for item in _flow_items(text[1:-1]):
                key, rest = _split_key(item) if _KEY.match(item) else (item, "")
                mapping[key] = self.scalar(rest, depth + 1)
            result = mapping
        elif text[0] in "\"'":
            if len(text) < 2 or text[-1] != text[0]:
                raise _Unsupported
            inner = text[1:-1]
            result = _Quoted(_unescape(inner) if text[0] == '"' else inner.replace("''", "'"))
        elif text[0] in "!%@`|>[{":
            raise _Unsupported  # a tag, a reserved indicator, an unclosed collection
        else:
            result = text
        if anchor is not None:
            self.anchors[anchor] = result
        return result


def _read_yaml(data: bytes | None):
    """The parsed document, or None when absent or outside the subset."""
    if not data or len(data) > _MAX_BYTES:
        return None
    text = data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    try:
        lines = _logical_lines(text)
        return _Reader(lines).document() if lines else None
    except _Unsupported:
        return None


# ------------------------------------------------- GitHub Actions expressions

_UNKNOWN = object()  # value and truthiness both unknown
_SOME_TRUE = object()  # truthy, value unknown
_SOME_FALSE = object()  # falsy, value unknown

_EXPR_TOKEN = re.compile(
    r"\s*(?:(?P<string>'(?:[^']|'')*')"
    r"|(?P<number>-?(?:0[xX][0-9A-Fa-f]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?))"
    r"|(?P<op>&&|\|\||==|!=|<=|>=|[!<>()\[\].,*])"
    r"|(?P<name>[A-Za-z_][A-Za-z0-9_-]*))"
)
_STATUS_FUNCTION = re.compile(r"\b(?:always|failure|cancelled)\s*\(", re.IGNORECASE)


def _truth(value) -> bool | None:
    """GitHub's truthiness when it is statically known, else None."""
    if value is _UNKNOWN:
        return None
    if value is _SOME_TRUE:
        return True
    if value is _SOME_FALSE or value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value == value and value != 0  # NaN and zero are falsy
    return value != ""


def _compare(operator: str, left, right):
    if any(side is _UNKNOWN or side is _SOME_TRUE or side is _SOME_FALSE for side in (left, right)):
        return _UNKNOWN
    if type(left) is not type(right):
        return _UNKNOWN  # GitHub coerces mixed types; not modelled
    if isinstance(left, str):
        if not (left.isascii() and right.isascii()):
            return _UNKNOWN  # case folding beyond ASCII differs between Unicode versions
        left, right = left.lower(), right.lower()  # GitHub compares strings ignoring case
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if isinstance(left, float):
        return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[operator]
    return _UNKNOWN


# Status functions as they read on a run that is otherwise green, the only run
# in which a runner can turn a passing check red: a step or job gated on
# failure() or cancelled() runs only once the check is already red.
_STATUS_VALUES = {"success": True, "always": True, "failure": False, "cancelled": False}
_JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")


def _call(name: str, arguments: list):
    """A function's value when it is statically known, else unknown."""
    if name in _STATUS_VALUES:
        return _UNKNOWN if arguments else _STATUS_VALUES[name]
    if not all(isinstance(argument, str) and argument.isascii() for argument in arguments):
        return _UNKNOWN  # a context, a non-string literal, or case folding beyond ASCII
    if name in ("contains", "startswith", "endswith") and len(arguments) == 2:
        # The string forms, which GitHub compares ignoring case.
        subject, search = (argument.lower() for argument in arguments)
        if name == "contains":
            return search in subject
        return subject.startswith(search) if name == "startswith" else subject.endswith(search)
    if name == "fromjson" and len(arguments) == 1:
        literal = arguments[0].strip()
        if literal in ("true", "false"):
            return literal == "true"
        if literal == "null":
            return None
        if _JSON_NUMBER.fullmatch(literal):
            return float(literal)
    return _UNKNOWN


class _Expression:
    """Constant folding over GitHub's expression grammar.

    Literals, `!`, comparisons, `&&`, `||` and parentheses are evaluated with
    GitHub's value semantics, so `x && false` is falsy whatever `x` is.
    Contexts, indexing and calls parse but stay unknown, except the bound
    `github.event_name` and the calls `_call` knows.
    """

    def __init__(self, text: str, event):
        self.tokens: list[tuple[str, str]] = []
        text = text.strip()
        position = 0
        while position < len(text):
            match = _EXPR_TOKEN.match(text, position)
            if match is None:
                raise _ExprError
            self.tokens.append((match.lastgroup, match.group(match.lastgroup)))
            position = match.end()
        self.index = 0
        self.event = event
        self.depth = 0

    def peek(self) -> str | None:
        return self.tokens[self.index][1] if self.index < len(self.tokens) else None

    def take(self, expected: str | None = None) -> tuple[str, str]:
        if self.index >= len(self.tokens):
            raise _ExprError
        kind, text = self.tokens[self.index]
        if expected is not None and (kind != "op" or text != expected):
            raise _ExprError
        self.index += 1
        return kind, text

    def evaluate(self):
        value = self.either()
        if self.index != len(self.tokens):
            raise _ExprError
        return value

    def either(self):
        value = self.both()
        while self.peek() == "||":
            self.index += 1
            right = self.both()
            truth = _truth(value)
            if truth is False:
                value = right
            elif truth is None:
                value = _SOME_TRUE if _truth(right) is True else _UNKNOWN
        return value

    def both(self):
        value = self.comparison()
        while self.peek() == "&&":
            self.index += 1
            right = self.comparison()
            truth = _truth(value)
            if truth is True:
                value = right
            elif truth is None:
                value = _SOME_FALSE if _truth(right) is False else _UNKNOWN
        return value

    def comparison(self):
        value = self.unary()
        while self.peek() in ("==", "!=", "<", "<=", ">", ">="):
            operator = self.take()[1]
            value = _compare(operator, value, self.unary())
        return value

    def unary(self):
        self.depth += 1
        if self.depth > 64:
            raise _ExprError
        if self.peek() == "!":
            self.index += 1
            truth = _truth(self.unary())
            value = _UNKNOWN if truth is None else not truth
        else:
            value = self.primary()
        self.depth -= 1
        return value

    def primary(self):
        kind, text = self.take()
        path: list[str] | None = None
        if kind == "op" and text == "(":
            value = self.either()
            self.take(")")
        elif kind == "string":
            value = text[1:-1].replace("''", "'")
        elif kind == "number":
            try:
                value = float(int(text, 16)) if "x" in text.lower() else float(text)
            except OverflowError:  # a hex literal past any float: its value is not modelled
                value = _UNKNOWN
        elif kind == "name" and text in ("true", "false"):
            value = text == "true"
        elif kind == "name" and text == "null":
            value = None
        elif kind == "name" and self.peek() == "(":
            self.take("(")
            arguments: list = []
            if self.peek() != ")":
                arguments.append(self.either())
                while self.peek() == ",":
                    self.index += 1
                    arguments.append(self.either())
            self.take(")")
            value = _call(text.lower(), arguments)
        elif kind == "name":
            value = _UNKNOWN
            path = [text.lower()]
        else:
            raise _ExprError
        while self.peek() in (".", "["):
            if self.take()[1] == ".":
                kind, text = self.take()
                if kind != "name" and text != "*":
                    raise _ExprError
                path = None if path is None else path + [text.lower()]
            else:
                self.either()
                self.take("]")
                path = None
            value = _UNKNOWN
        if path == ["github", "event_name"]:
            value = self.event
        return value


def _evaluate(text: str, event):
    try:
        return _Expression(text, event).evaluate()
    except _ExprError:
        return _UNKNOWN


def _never_true(condition, event) -> bool:
    """Is this `if:` false for this event, on every run that is otherwise green?"""
    if not isinstance(condition, str):
        return False  # absent, or a shape no condition takes
    text = condition.strip()
    if not isinstance(condition, _Quoted) and text in ("False", "FALSE", "True", "TRUE"):
        text = text.lower()  # YAML 1.2 core booleans, as GitHub's parser reads them
    if text.startswith("${{") and text.endswith("}}") and text.count("${{") == 1:
        text = text[3:-2]
    elif "${{" in text:
        return False  # interpolated into a longer string: not a bare condition
    return _truth(_evaluate(text, event)) is False


def _runs_after_skipped_needs(condition) -> bool:
    """Does this job `if:` let the job run when a job it needs was skipped?"""
    if condition is None:
        return False
    return not isinstance(condition, str) or _STATUS_FUNCTION.search(condition) is not None


# --------------------------------------------------------------- runner sites

# Events that never run on a pull request's commits. Every other event (the
# pull_request family, merge_group, workflow_call, workflow_run, comment
# triggers, anything newer than this list) counts as able to, which is the
# direction that reports nothing.
_NON_PR_EVENTS = frozenset({"workflow_dispatch", "schedule", "release", "create", "delete"})


def _brief(value, limit: int = 120) -> str:
    return _WHITESPACE.sub(" ", str(value)).strip()[:limit]


def _patterns(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _push_reaches_pr_branches(filters) -> bool:
    """Does this `push` trigger fire on a pull request's own branch?

    Unfiltered, it fires on every branch, the PR's included, which is why
    dropping `pull_request` beside it loses nothing for a same-repository
    branch. A `branches` list fires only where it names, so only `*` or `**`
    reach an arbitrary PR branch, and `tags` alone means no branch push runs.
    """
    if not isinstance(filters, dict):
        return True
    if "branches" in filters:
        return any(pattern in ("*", "**") for pattern in _patterns(filters["branches"]))
    if "branches-ignore" in filters:
        return "**" not in _patterns(filters["branches-ignore"])
    return "tags" not in filters and "tags-ignore" not in filters


def _pr_events(on) -> list[str] | None:
    """Events that can run the workflow for a pull request's commits.

    None when the trigger block has a shape this reader does not take, which
    the caller treats as "may run".
    """
    if isinstance(on, str):
        spec: dict = {on: None}
    elif isinstance(on, list) and all(isinstance(event, str) for event in on):
        spec = dict.fromkeys(on)
    elif isinstance(on, dict):
        spec = on
    else:
        return None
    return sorted(
        str(event) for event, filters in spec.items()
        if (_push_reaches_pr_branches(filters) if event == "push" else event not in _NON_PR_EVENTS)
    )


def _workflow_sites(tree) -> tuple[list[str], list[tuple[str, str]]] | None:
    """Live runner commands and dead (command, cause) runner sites of a workflow."""
    if not isinstance(tree, dict) or not isinstance(tree.get("jobs"), dict):
        return None
    events = _pr_events(tree["on"]) if "on" in tree else None
    if events is not None and len(events) > _MAX_EVENTS:
        events = None  # more events than GitHub defines: bind none
    # github.event_name is the one context bound. Inside a called workflow it
    # is the caller's event, so workflow_call binds nothing.
    bindings = [_UNKNOWN] if events is None else [
        _UNKNOWN if event == "workflow_call" else event for event in events
    ]
    jobs = {name: job for name, job in tree["jobs"].items() if isinstance(job, dict)}
    # A job that needs a skipped job is skipped too, unless its condition
    # carries a status function, and a skipped job reports success. Deadness
    # spreads from the jobs whose own `if:` is never true to the jobs that
    # need them over a worklist, so a `needs:` chain of any length costs no
    # stack and each job is judged once per binding.
    dependants: dict[str, list[str]] = {}
    for name, job in jobs.items():
        if not _runs_after_skipped_needs(job.get("if")):
            for need in _patterns(job.get("needs")):
                dependants.setdefault(need, []).append(name)
    skipped_by_binding: dict[int, set[str]] = {}

    def job_dead(name: str, binding: int) -> bool:
        if binding not in skipped_by_binding:
            event = bindings[binding]
            skipped = {other for other, spec in jobs.items() if _never_true(spec.get("if"), event)}
            queue = list(skipped)
            while queue:
                for dependant in dependants.get(queue.pop(), ()):
                    if dependant not in skipped:
                        skipped.add(dependant)
                        queue.append(dependant)
            skipped_by_binding[binding] = skipped
        return name in skipped_by_binding[binding]

    live: list[str] = []
    dead: list[tuple[str, str]] = []
    for name, job in jobs.items():
        steps = job.get("steps")
        for step in steps if isinstance(steps, list) else ():
            if not isinstance(step, dict):
                continue
            command = step.get("run") if isinstance(step.get("run"), str) else step.get("uses")
            if not isinstance(command, str) or not _runs_tests(command.encode("utf-8")):
                continue
            condition = step.get("if")
            if any(
                not job_dead(name, binding) and not _never_true(condition, event)
                for binding, event in enumerate(bindings)
            ):
                live.append(_brief(command))
                continue
            if not bindings:
                cause = "no trigger runs it on a pull request"
            elif all(_never_true(condition, event) for event in bindings):
                cause = "if: " + _brief(condition, 60)
            elif all(_never_true(job.get("if"), event) for event in bindings):
                cause = f"job {name} if: " + _brief(job.get("if"), 60)
            elif _patterns(job.get("needs")):
                cause = f"job {name} needs a job that cannot run"
            else:
                cause = f"job {name} cannot run on a pull request"
            dead.append((_brief(command), cause))
    return live, dead


def _precommit_sites(tree) -> tuple[list[str], list[tuple[str, str]]] | None:
    """Live and dead runner hooks of a pre-commit config, by their `entry`.

    The entry is the hook's command. A hook without one runs code from its
    own repository, and the packages it installs (`additional_dependencies:
    [pytest]` on mypy) are not a test command.
    """
    if not isinstance(tree, dict) or not isinstance(tree.get("repos"), list):
        return None
    default_stages = tree.get("default_stages")
    live: list[str] = []
    dead: list[tuple[str, str]] = []
    for repo in tree["repos"]:
        hooks = repo.get("hooks") if isinstance(repo, dict) else None
        for hook in hooks if isinstance(hooks, list) else ():
            entry = hook.get("entry") if isinstance(hook, dict) else None
            if not isinstance(entry, str) or not _runs_tests(entry.encode("utf-8")):
                continue
            stages = _patterns(hook["stages"] if "stages" in hook else default_stages)
            if stages and all(stage == "manual" for stage in stages):
                dead.append((_brief(entry), "stages: [manual]"))
            else:
                live.append(_brief(entry))
    return live, dead


def control_flow_weakenings(path: str, before: bytes | None, after: bytes | None) -> list[str]:
    """Why this CI file's runners stopped executing, as `ci_weakening_lines` reasons."""
    p = path.replace("\\", "/")
    if p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml")):
        read_sites, inventory = _workflow_sites, False
    elif p == ".pre-commit-config.yaml":
        read_sites, inventory = _precommit_sites, True
    else:
        return []
    old, new = read_sites(_read_yaml(before)), read_sites(_read_yaml(after))
    if old is None or new is None:
        return []
    (old_live, old_dead), (new_live, new_dead) = old, new
    stopped = Counter(old_live) - Counter(new_live)
    parked = Counter(command for command, _ in new_dead) - Counter(command for command, _ in old_dead)
    # The runner that stopped must be the runner that was parked: a runner
    # born dead (a placeholder job, a push-only benchmark) beside a reworded
    # live one (`pytest` -> `pytest --cov`) disables nothing that ran. A text
    # edit applied to a live and an already-dead site alike (`-q` added
    # everywhere) moves nothing between them, hence `shifted`.
    shifted = len(new_dead) > len(old_dead) or len(new_live) < len(old_live)
    disabled = stopped & parked if shifted else Counter()
    if not disabled and len(new_live) < len(old_live) and len(new_dead) > len(old_dead):
        # The inventory moved a site, one live fewer and one dead more: a
        # runner reworded as it was disabled (`pytest` -> `python -m pytest`
        # under `if: false`) is still the runner that stopped.
        disabled = parked
    if disabled:
        command, cause = min(site for site in new_dead if site[0] in disabled)
        return [f"{command} is disabled ({cause})"]
    if inventory and old_live and not new_live:
        return [f"{min(old_live)} is no longer run by any pre-commit hook"]
    return []
