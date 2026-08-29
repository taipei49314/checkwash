"""`greenwash doctor` — conservatively prove a load-bearing CI gate."""

from __future__ import annotations

import datetime
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from greenwash.allowlist import MAX_EXPIRY_DAYS, summarize_allowlist


@dataclass
class Note:
    level: str  # "ok" | "warn" | "problem" | "info"
    title: str
    detail: str


_EVENT = "pull_request"
_BANNED = {"if", "continue-on-error", "env", "defaults", "strategy", "container"}
_PINS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "actions/setup-python": "a26af69be951a213d495a4c3e4e4022e16d87065",
    # The one-release trust lag: the newest stable tag's peeled commit, moved
    # forward with every release (v0.1.46 here, per the v0.1.47 round).
    "taipei49314/greenwash/action": "840596b2c4c6e33c3cec23d587e4b8cec476b34a",
}


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _decode_workflow(data: bytes) -> str | None:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    # A narrow YAML-printable subset. NEL, LS, and PS are valid YAML line
    # breaks, but supporting them would require another parsing grammar.
    for char in text:
        codepoint = ord(char)
        if char in "\t\n\r" or 0x20 <= codepoint <= 0x7E:
            continue
        if (
            0xA0 <= codepoint <= 0xD7FF
            or 0xE000 <= codepoint <= 0xFFFD
            or 0x10000 <= codepoint <= 0x10FFFF
        ) and codepoint not in {0x2028, 0x2029}:
            continue
        return None
    return text


def _without_comment(line: str) -> str:
    quote = ""
    escaped = False
    for index, char in enumerate(line):
        if quote == '"' and char == "\\" and not escaped:
            escaped = True
            continue
        if char in "\"'" and not escaped:
            if not quote:
                quote = char
            elif quote == char:
                quote = ""
        if char == "#" and not quote and (index == 0 or line[index - 1] in " \t"):
            return line[:index].rstrip(" ")
        escaped = False
    return line.rstrip(" ")


def _lines(text: str) -> list[str]:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return [clean for line in text.split("\n") if (clean := _without_comment(line)).strip(" ")]


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _mapping(line: str, indent: int) -> tuple[str, str] | None:
    match = re.fullmatch(rf" {{{indent}}}([A-Za-z_][A-Za-z0-9_-]*):(?: +(.*))?", line)
    return (match.group(1), match.group(2) or "") if match else None


def _unfiltered_event(lines: list[str], on_index: int, on_value: str) -> bool:
    if on_value:
        match = re.fullmatch(r"\[ *([A-Za-z_]+) *\]", on_value)
        return bool(match and match.group(1) == _EVENT)
    end = next((i for i in range(on_index + 1, len(lines)) if _indent(lines[i]) == 0), len(lines))
    if end != on_index + 2:
        return False
    item = _mapping(lines[on_index + 1], 2)
    return bool(item and item[0] == _EVENT and not item[1])


def _step(lines: list[str]) -> tuple[dict[str, str], dict[str, str]] | None:
    first = re.fullmatch(r"      - ([a-z][a-z0-9-]*):(?: +(.*))?", lines[0])
    if not first:
        return None
    props = {first.group(1): first.group(2) or ""}
    with_values: dict[str, str] = {}
    in_with = first.group(1) == "with" and not props["with"]
    for line in lines[1:]:
        indent = _indent(line)
        item = _mapping(line, indent)
        if indent == 8 and item:
            if item[0] in props:
                return None
            props[item[0]] = item[1]
            in_with = item[0] == "with" and not item[1]
        elif indent == 10 and item and in_with:
            if item[0] in with_values:
                return None
            with_values[item[0]] = item[1]
        else:
            return None
    return props, with_values


def _plain_chain(root: Path, relative: str | Path) -> bool:
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        return False
    current = root
    for part in relative.parts:
        try:
            with os.scandir(current) as entries:
                matches = [entry.name for entry in entries if entry.name.casefold() == part.casefold()]
            if matches != [part]:
                return False
            current /= matches[0]
            info = current.lstat()
        except OSError:
            return False
        if current.is_symlink() or (
            getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        ):
            return False
    return True


def _regular_bytes(path: Path) -> bytes | None:
    descriptor = -1
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = -1
            return handle.read()
    except OSError:
        return None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _git_query(root: Path, *args: str) -> subprocess.CompletedProcess[bytes] | None:
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update({
        "GIT_CEILING_DIRECTORIES": str(root.parent.resolve()),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_DISCOVERY_ACROSS_FILESYSTEM": "0",
        "GIT_NO_LAZY_FETCH": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
    })
    try:
        result = subprocess.run(
            [
                "git", "--no-optional-locks", "--no-replace-objects",
                "-c", "core.fsmonitor=false",
                "--literal-pathspecs", *args,
            ],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result


def _tracked_blob(root: Path, relative: str | Path) -> bytes | None:
    relative = Path(relative)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    requested = relative.as_posix()
    try:
        encoded = requested.encode("utf-8")
    except UnicodeEncodeError:
        return None
    result = _git_query(root, "ls-files", "--stage", "-z", "--", requested)
    if result is None:
        return None
    records = result.stdout.split(b"\0")
    if result.returncode or len(records) != 2 or records[1]:
        return None
    header, separator, actual = records[0].partition(b"\t")
    fields = header.split(b" ")
    if not (
        separator
        and actual == encoded
        and len(fields) == 3
        and fields[0] in {b"100644", b"100755"}
        and re.fullmatch(rb"[0-9a-f]{40}|[0-9a-f]{64}", fields[1])
        and fields[2] == b"0"
    ):
        return None
    oid = fields[1].decode("ascii")
    blob = _git_query(root, "cat-file", "blob", oid)
    worktree = _regular_bytes(root / relative)
    if blob is None or blob.returncode or worktree is None:
        return None
    normalized_blob = blob.stdout.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    normalized_worktree = worktree.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    if worktree != blob.stdout and normalized_worktree != normalized_blob:
        return None
    return blob.stdout


def _uses(props: dict[str, str], owner: str) -> bool:
    return set(props) == {"uses", "with"} and props["uses"] == f"{owner}@{_PINS[owner]}"


def _healthy_job(body: list[str]) -> bool:
    job_items: list[tuple[int, str, str]] = []
    for index, line in enumerate(body[1:], 1):
        if _indent(line) == 4:
            item = _mapping(line, 4)
            if item is None or item[0] in _BANNED or any(old[1] == item[0] for old in job_items):
                return False
            job_items.append((index, item[0], item[1]))
        elif _indent(line) < 6:
            return False
    if job_items != [
        (1, "runs-on", "ubuntu-latest"), (2, "steps", "")
    ]:
        return False
    step_lines = body[job_items[1][0] + 1:]
    starts = [i for i, line in enumerate(step_lines) if _indent(line) == 6]
    if starts[:1] != [0] or len(starts) != 3 or any(
        not step_lines[i].startswith("      - ") for i in starts
    ):
        return False
    parsed = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(step_lines)
        value = _step(step_lines[start:end])
        if value is None:
            return False
        parsed.append(value)
    checkout, setup, gate = parsed
    if not _uses(checkout[0], "actions/checkout") or checkout[1] != {
        "fetch-depth": "0", "persist-credentials": "false"
    }:
        return False
    if not _uses(setup[0], "actions/setup-python") or setup[1] != {"python-version": '"3.12"'}:
        return False
    props, with_values = gate
    remote = set(props) == {"uses"} and not with_values and props["uses"] == (
        "taipei49314/greenwash/action@" + _PINS["taipei49314/greenwash/action"]
    )
    return remote


def _workflow(data: bytes) -> tuple[list[str], bool]:
    text = _decode_workflow(data)
    if text is None:
        return [], True
    lines = _lines(text)
    blob = "\n".join(lines)
    candidate = "greenwash" in blob.lower() or "uses: ./action" in blob
    if not lines or any("\t" in line for line in lines) or re.search(
        r"(^|[ \t])<<:|(^|[ \t])[*&][A-Za-z_]", blob
    ):
        return [], candidate
    top: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        if _indent(line) == 0:
            item = _mapping(line, 0)
            if item is None or any(old[1] == item[0] for old in top):
                return [], candidate
            top.append((index, item[0], item[1]))
    keys = [key for _, key, _ in top]
    if keys not in (["on", "permissions", "jobs"], ["name", "on", "permissions", "jobs"]):
        return [], candidate
    if _BANNED.intersection(keys):
        return [], candidate
    on = [item for item in top if item[1] == "on"]
    jobs = [item for item in top if item[1] == "jobs"]
    if len(on) != 1 or len(jobs) != 1 or jobs[0][2] or not _unfiltered_event(lines, on[0][0], on[0][2]):
        return [], candidate
    permissions = next(item for item in top if item[1] == "permissions")
    name_offset = 1 if keys[0] == "name" else 0
    if top[0][0] != 0 or (name_offset and (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._-]*", top[0][2]) or on[0][0] != 1
    )):
        return [], candidate
    expected_permission = on[0][0] + (1 if on[0][2] else 2)
    if permissions[0] != expected_permission:
        return [], candidate
    permission_end = next(
        (i for i in range(permissions[0] + 1, len(lines)) if _indent(lines[i]) == 0), len(lines)
    )
    if (permissions[2] or permission_end != permissions[0] + 2
            or lines[permissions[0] + 1] != "  contents: read"):
        return [], candidate
    end = next((i for i in range(jobs[0][0] + 1, len(lines)) if _indent(lines[i]) == 0), len(lines))
    starts: list[tuple[int, str]] = []
    for index in range(jobs[0][0] + 1, end):
        if _indent(lines[index]) == 2:
            item = _mapping(lines[index], 2)
            if item is None or item[1] or any(name == item[0] for _, name in starts):
                return [], candidate
            starts.append((index, item[0]))
        elif _indent(lines[index]) < 4:
            return [], candidate
    if starts != [(jobs[0][0] + 1, "greenwash")]:
        return [], candidate
    healthy = []
    for pos, (start, name) in enumerate(starts):
        stop = starts[pos + 1][0] if pos + 1 < len(starts) else end
        if _healthy_job(lines[start:stop]):
            healthy.append(name)
    return healthy, candidate


def _workflow_gates(root: Path) -> tuple[list[tuple[str, str]], list[str]]:
    gates, incomplete = [], []
    directory = root / ".github" / "workflows"
    if not directory.is_dir():
        return gates, incomplete
    if not _plain_chain(root, ".github/workflows"):
        return gates, [".github/workflows (linked path)"]
    for path in sorted(p for p in directory.iterdir() if p.is_file() and p.suffix in {".yml", ".yaml"}):
        relative = path.relative_to(root)
        blob = _tracked_blob(root, relative) if _plain_chain(root, relative) else None
        if blob is None:
            incomplete.append(relative.as_posix())
            continue
        names, candidate = _workflow(blob)
        rel = path.relative_to(root).as_posix()
        gates.extend((rel, name) for name in names)
        if candidate and not names:
            incomplete.append(rel)
    return gates, incomplete


def collect(root: Path) -> list[Note]:
    notes: list[Note] = []
    jobs, incomplete = _workflow_gates(root)
    hook_installed = "greenwash" in _read(root / ".claude" / "settings.json")
    precommit_installed = "greenwash" in _read(root / ".pre-commit-config.yaml")

    if jobs:
        detail = ", ".join(f"{path} :: {job}" for path, job in jobs)
        notes.append(Note("ok", f"{len(jobs)} CI job(s) invoke greenwash", detail))
        notes.append(Note("ok", "at least one greenwash gate runs unconditionally", detail))
    elif incomplete:
        notes.append(Note(
            "warn", "workflow analysis incomplete",
            "No exact supported gate was proven in " + ", ".join(incomplete) + ". "
            "Use the three-step, hash-pinned workflow from the README; direct run steps are never trusted.",
        ))
    else:
        where = [name for name, present in (
            ("a Claude Code stop-hook", hook_installed), ("pre-commit", precommit_installed)
        ) if present]
        if where:
            notes.append(Note(
                "problem", "greenwash runs locally but not in CI",
                "Found " + " and ".join(where) + ", and no exact supported workflow under "
                ".github/workflows. A local hook can be skipped and cannot stop someone else's merge.",
            ))
        else:
            notes.append(Note(
                "problem", "no greenwash installation found",
                "No exact supported workflow invokes greenwash and no local hook was found. "
                "See the Required check section of the README.",
            ))

    notes.append(Note(
        "info", "greenwash cannot tell whether the check is *required*",
        "Branch protection lives behind GitHub API token scopes this tool does not ask for. "
        "A green job that is not a required status check does not prevent a merge. Make the "
        "job's status check required. The README step 2 command is: gh api "
        "repos/OWNER/REPO/rulesets --method POST --input action/required-ruleset.json",
    ))
    notes.append(Note(
        "info", "greenwash cannot block when it does not run",
        "A change that deletes or disables the greenwash job disarms it in the same diff. "
        "Protect the workflow file with code owners or required review on .github/**.",
    ))
    cfg = root / ".greenwash" / "config.toml"
    allow = root / ".greenwash" / "allow.toml"
    notes.append(Note(
        "info", "configuration is read from the BASE side of the diff",
        f"config: {'present' if cfg.exists() else 'absent (defaults)'}; "
        f"allowlist: {'present' if allow.exists() else 'absent'}. A new allowlist entry "
        "takes effect on the next diff and must be committed.",
    ))
    ledger = summarize_allowlist(allow.read_bytes() if allow.exists() else None, datetime.date.today())
    if ledger.parse_error:
        notes.append(Note("warn", "allow.toml could not be parsed; no exemptions are active", ledger.parse_error))
    else:
        detail = (
            f"{ledger.entries} entries in .greenwash/allow.toml; {ledger.active} active today, "
            f"{ledger.expired} expired, {ledger.over_cap} over the {MAX_EXPIRY_DAYS}-day cap (ignored on read)."
            if ledger.present else
            f"no allow.toml yet. `greenwash allow` writes one; expiry is capped at "
            f"{MAX_EXPIRY_DAYS} days. Commit it and put `.greenwash/` in CODEOWNERS."
        )
        notes.append(Note("info", f"allowlist expiry is capped at {MAX_EXPIRY_DAYS} days", detail))
    notes.append(Note(
        "info", "use a three-dot range for pull requests",
        "`greenwash check BASE...HEAD` resolves through the merge base. A two-dot range drags "
        "in base-branch commits; a single range cannot see a wash split across PRs.",
    ))
    return notes


_SYMBOL = {"ok": "OK  ", "warn": "WARN", "problem": "FAIL", "info": "note"}


def run(root: str = ".", stream=None) -> int:
    """Print the report. 0 when nothing is wrong, 1 when something is."""
    import sys

    stream = stream or sys.stdout
    notes = collect(Path(root))
    for note in notes:
        stream.write(f"{_SYMBOL[note.level]}  {note.title}\n")
        for line in _wrap(note.detail):
            stream.write(f"      {line}\n")
        stream.write("\n")
    problems = [n for n in notes if n.level == "problem"]
    warns = [n for n in notes if n.level == "warn"]
    stream.write(
        f"summary: {len(problems)} problem(s), {len(warns)} warning(s). "
        "greenwash cannot verify branch protection; see the note above.\n"
    )
    return 1 if problems or warns else 0


def _wrap(text: str, width: int = 76) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines
