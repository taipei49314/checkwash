"""A closed JS grammar in which one plain suite cannot affect an oracle.

This is an optional source certificate, not a wrapper/text projection. Every
token belongs to a known framework import, a closed literal-return producer,
one parameterless arrow test, or its optional parameterless describe envelope.
Unknown calls, bindings, hooks and observers therefore have no proof path.
The complete side snapshot must contain this one file only, and comments are
unsupported: repository setup/config/siblings and environment docblocks cannot
silently install a suite-name observer. External plugins remain unsupported.
The ordinary frontend still owns assertions, collection and liveness.
"""
from __future__ import annotations

import json
import re


_TOKEN = re.compile(
    r"(?P<space>[\t\n\v\f\r \u00a0\ufeff\u2028\u2029]+)|"
    r"(?P<string>\"[^\"\\\r\n]*\"|'[^'\\\r\n]*')|"
    r"(?P<number>-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?)|"
    r"(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)|=>|[(){}.,;]"
)
# Syntax keywords cannot be producer bindings. Framework identifiers are
# separately reserved by the required import; this is not an observer list.
_KEYWORDS = frozenset((
    "await break case catch class const continue debugger default delete do else "
    "enum export extends false finally for function if implements import in "
    "instanceof interface let new null package private protected public return "
    "static super switch this throw true try typeof var void while with yield eval arguments"
).split())
_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*\Z")


class _Unknown(ValueError):
    pass


class _Program:
    def __init__(self, text):
        self.text = text
        self.tokens = []
        cursor = 0
        while cursor < len(text):
            match = _TOKEN.match(text, cursor)
            if match is None:
                raise _Unknown
            if match.lastgroup != "space":
                self.tokens.append((match.group(), match.start(), match.end(), match.lastgroup))
                if len(self.tokens) > 4096:
                    raise _Unknown
            cursor = match.end()
        self.cursor = 0

    def peek(self):
        return self.tokens[self.cursor][0] if self.cursor < len(self.tokens) else ""

    def take(self, value=None):
        if self.cursor >= len(self.tokens):
            raise _Unknown
        token = self.tokens[self.cursor]
        if value is not None and token[0] != value:
            raise _Unknown
        self.cursor += 1
        return token

    def literal(self, *, string=False):
        token = self.take()
        if token[3] == "string" or (not string and (
                token[3] == "number" or token[0] in {"true", "false", "null"})):
            return token
        raise _Unknown

    def arrow_start(self):
        self.take("(")
        closing = self.take(")")
        arrow = self.take("=>")
        if any(char in self.text[closing[2]:arrow[1]] for char in "\r\n\u2028\u2029"):
            raise _Unknown  # ArrowFunction has a no-LineTerminator restriction.
        self.take("{")

    def read(self, side):
        # A named import supplies positive framework authority. No aliases,
        # side-effect imports, local substitutes or unknown bootstrap run.
        self.take("import")
        self.take("{")
        imported = []
        while True:
            imported.append(self.take()[0])
            if self.peek() != ",":
                break
            self.take(",")
        self.take("}")
        self.take("from")
        module = self.literal(string=True)[0][1:-1]
        self.take(";")
        if (module not in {"vitest", "@jest/globals"}
                or len(imported) != 3 or len(set(imported)) != 3
                or set(imported) not in ({"describe", "expect", "it"}, {"describe", "expect", "test"})):
            raise _Unknown
        unit_word = "it" if "it" in imported else "test"

        producers = []
        names = set(imported)
        while self.peek() == "function":
            self.take("function")
            name = self.take()[0]
            if not _IDENTIFIER.fullmatch(name) or name in _KEYWORDS or name in names:
                raise _Unknown
            names.add(name)
            self.take("(")
            self.take(")")
            self.take("{")
            returned = self.take("return")
            value = self.literal()
            # JavaScript ASI also applies across newlines inside comments.
            if any(char in self.text[returned[2]:value[1]] for char in "\r\n\u2028\u2029"):
                raise _Unknown
            self.take(";")
            self.take("}")
            producers.append((name, value[0]))
            if len(producers) > 64:
                raise _Unknown

        wrapped = self.peek() == "describe"
        if wrapped:
            self.take("describe")
            self.take("(")
            self.literal(string=True)
            self.take(",")
            self.arrow_start()
        unit_start = self.take(unit_word)[1]
        self.take("(")
        self.literal(string=True)
        self.take(",")
        self.arrow_start()
        assertions = 0
        while self.peek() == "expect":
            self.take("expect")
            self.take("(")
            if self.peek() in {name for name, _value in producers}:
                self.take()
                self.take("(")
                self.take(")")
            else:
                self.literal()
            self.take(")")
            self.take(".")
            self.take("toBe")
            self.take("(")
            self.literal()
            self.take(")")
            self.take(";")
            assertions += 1
        self.take("}")
        unit_end = self.take(")")[2]
        self.take(";")
        if wrapped:
            self.take("}")
            self.take(")")
            self.take(";")
        if (self.cursor != len(self.tokens) or not assertions or side.span != (unit_start, unit_end)
                or len(side.assertions) != assertions or side.markers or side.param_rows_unknown
                or side.param_rows or side.param_cases is not None):
            raise _Unknown
        # Only the unobservable suite envelope is absent. The framework and
        # every producer name/value remain side-bound; changed pure producers
        # do not become equivalent merely because both passed this grammar.
        return json.dumps(("closed-plain-describe-v1", module, sorted(imported), producers))


def closed_describe_environment(source, units, *, path, read, path_lister):
    """Return a narrow environment identity, or None when any token is unknown."""
    if (len(units) != 1 or type(source) is not bytes or len(source) > 65536
            or not callable(read) or not callable(path_lister)
            or not isinstance(path, str) or path.startswith("/") or ":" in path or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))):
        return None
    # Complete path metadata is an independent capability: missing metadata
    # is unknown, never an assertion that config/bootstrap does not exist.
    try:
        paths = path_lister()
        observed = read(path)
    except Exception:
        return None
    if (type(paths) not in (list, tuple) or list(paths) != [path]
            or type(observed) is not bytes or observed != source):
        return None
    try:
        text = source.decode("utf-8-sig").replace("\r\n", "\n")
        return _Program(text).read(units[0][1])
    except (_Unknown, UnicodeError):
        return None
