"""The #414 hosted acceptance run (owner ruling 2026-10-19, R26 option A).

`.github/workflows/acceptance-414.yml` runs this on GitHub-hosted runners,
only for a pull request from a `ci/acceptance-414-*` branch of this
repository. The declaration it implements is `docs/acceptance/414-hosted.md`;
the owner approves that declaration before the pull request is opened.

Standard library only: this never imports checkwash. Each engine is installed
from its exact commit into a virtual environment of its own, and its console
script runs as the pre-commit hook and the Claude Code Stop hook run it: from
the scenario repository's root, with no range and no `--repo`.

Subcommands, in workflow order. ROOT is a fresh directory outside the checkout;
`engines` runs from the root of this repository's checkout.

    engines  --root ROOT              install the declared engines
    scaffold --root ROOT --leg LEG    write the scenario project and `git init` it
    bigpack  --root ROOT              write the generated npm tarball (npm-large)
    run      --root ROOT --leg LEG    check the setup is real, commit it, edit one
                                      .py file, run every engine in every mode,
                                      write the receipt; exit 0 only if accepted

The leg's real setup (`python3 -m venv`, `pnpm install`, `npm install`) runs
between `scaffold` and `run` as workflow steps, so the workflow shows it.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
from pathlib import Path

WINDOWS = os.name == "nt"

# (name, exact commit, its tree, role). "required" decides acceptance;
# "report" is recorded beside it; "control" is the code before the fix.
ENGINES = (
    ("main", "0e60832a618653511f764ea7e44994dce92df558", "ee4a31ef28ed68719e1a76977fe9df5d7d0118b6", "required"),
    ("v0.8.0", "f02b5d8a07fa39ee1898881f66c571eb164cb11c", "ada5d81cfa12cbabb6298715d67ebc7f67e9b27e", "report"),
    ("v0.7.0", "d647a65e9734f2b6e57b528ea595b1507dc31094", "14294c318beb7a90e8b6d8cc0d195d0ffea38ba2", "control"),
)

LEGS = ("ubuntu-venv", "ubuntu-pnpm", "ubuntu-npm-large", "windows-pnpm")
PNPM_LEGS = ("ubuntu-pnpm", "windows-pnpm")
MODES = ("term", "hook-json", "stop-hook")

# The scenario of tests/test_issue414_worktree_directory_symlinks.py, on a
# real tree: one package, one test of it, and an honest edit to the package.
EDIT_PATH = "src/pkg/__init__.py"
TOTAL = b"def total():\n    return 78.75\n"
TEST = b"from pkg import total\n\n\ndef test_total():\n    assert total() == 78.75\n"
EDITED = b"def total():\n    return round(78.75, 2)\n"

SEMVER = "7.6.3"
BIG_TARBALL = "big-tree-1.0.0.tgz"
BIG_DIRS = 201
BIG_FILES_PER_DIR = 1000
PATH_LIMIT = 200_000  # MAX_INVENTORY_PATHS in src/checkwash/gitio/snapshot.py at every engine

GIT_CONFIG = (
    ("user.name", "checkwash-acceptance"),
    ("user.email", "acceptance@example.invalid"),
    ("commit.gpgsign", "false"),
    ("core.autocrlf", "false"),
)
SESSION_ID = "acceptance-414"
RUN_TIMEOUT = 900

# What the engines print, by reading their code (the declaration's "Expected").
ENGINE_ERROR = "checkwash engine error:"
NOT_ANALYSED = "checkwash: this change was not analysed, so it was neither passed nor blocked."
SYMLINK_V070 = "strict snapshot inventory cannot follow directory symlinks"
LIMIT_V070 = "strict snapshot inventory exceeds the path limit"
LIMIT_NAMED = f"strict snapshot inventory exceeds the path limit of {PATH_LIMIT} at node_modules/big-tree/"
VERDICT = ("pass", "block")


# --- helpers ------------------------------------------------------------------------------------

def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _write_json(path, value):
    path.write_bytes(_json_bytes(value))


def _git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=600)
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise SystemExit(f"git {' '.join(args)} exited {result.returncode}: {detail}")
    # rstrip only: `git status --porcelain` starts an unstaged change with a space.
    return result.stdout.decode("utf-8", "replace").rstrip()


def _call(argv, cwd=None):
    """Run a setup command with its output in the job log; stop on failure."""
    print("+ " + " ".join(str(part) for part in argv), flush=True)
    result = subprocess.run([str(part) for part in argv], cwd=None if cwd is None else str(cwd), timeout=1800)
    if result.returncode:
        raise SystemExit(f"{argv[0]} exited {result.returncode}")


def _bin(venv, name):
    return venv / ("Scripts" if WINDOWS else "bin") / (name + (".exe" if WINDOWS else ""))


def _entry_link_kind(entry):
    """The link kind of an os.DirEntry (symlink, junction or None), without following it."""
    if entry.is_symlink():
        return "symlink"
    is_junction = getattr(entry, "is_junction", None)  # Python 3.12+
    if is_junction is not None and is_junction():
        return "junction"
    return None


def _path_link_kind(path):
    if os.path.islink(path):
        return "symlink"
    is_junction = getattr(os.path, "isjunction", None)  # Python 3.12+
    if is_junction is not None and is_junction(path):
        return "junction"
    return None


def _readlink(path):
    try:
        return os.readlink(path)
    except (OSError, ValueError) as exc:
        return f"unreadable: {exc}"


# --- engines ------------------------------------------------------------------------------------

def _engines(root):
    source = Path.cwd()
    receipt = root / "receipt"
    receipt.mkdir(parents=True, exist_ok=True)
    installed = []
    for name, commit, tree, role in ENGINES:
        if _git(source, "rev-parse", "--verify", commit + "^{commit}") != commit:
            raise SystemExit(f"engine {name}: {commit} is not a commit of this clone")
        if _git(source, "rev-parse", "--verify", commit + "^{tree}") != tree:
            raise SystemExit(f"engine {name}: {commit} does not have tree {tree}")
        worktree = root / "engines" / name
        worktree.parent.mkdir(parents=True, exist_ok=True)
        _git(source, "worktree", "add", "--detach", str(worktree), commit)
        if _git(worktree, "rev-parse", "HEAD") != commit:
            raise SystemExit(f"engine {name}: the worktree is not at {commit}")
        venv = root / "venvs" / name
        _call([sys.executable, "-m", "venv", venv])
        _call([_bin(venv, "python"), "-m", "pip", "install", "--disable-pip-version-check", "--no-input", worktree])
        script = _bin(venv, "checkwash")
        version = subprocess.run([str(script), "--version"], cwd=str(root), stdin=subprocess.DEVNULL,
                                 capture_output=True, timeout=120)
        installed.append({
            "name": name, "commit": commit, "tree": tree, "role": role, "script": str(script),
            "version_exit": version.returncode,
            "version": version.stdout.decode("utf-8", "replace").strip(),
        })
        print(f"engine {name}: {commit} -> {installed[-1]['version']!r}", flush=True)
    _write_json(receipt / "engines.json", installed)
    return 0


# --- scaffold -----------------------------------------------------------------------------------

def _project(leg):
    files = {EDIT_PATH: TOTAL, "tests/test_total.py": TEST}
    if leg == "ubuntu-venv":
        files[".gitignore"] = b".venv/\n"
    elif leg in PNPM_LEGS:
        # A two-package workspace: `web` links `shared` (workspace:*), and
        # both the root and `shared` depend on a registry package.
        files[".gitignore"] = b"node_modules/\n"
        files["package.json"] = _json_bytes({"name": "acceptance-414", "version": "1.0.0", "private": True,
                                             "devDependencies": {"semver": SEMVER}})
        files["pnpm-workspace.yaml"] = b"packages:\n  - packages/*\n"
        files["packages/shared/package.json"] = _json_bytes({"name": "shared", "version": "1.0.0", "private": True,
                                                             "main": "index.js", "dependencies": {"semver": SEMVER}})
        files["packages/shared/index.js"] = b'module.exports = require("semver").valid("1.2.3");\n'
        files["packages/web/package.json"] = _json_bytes({"name": "web", "version": "1.0.0", "private": True,
                                                          "main": "index.js", "dependencies": {"shared": "workspace:*"}})
        files["packages/web/index.js"] = b'module.exports = require("shared");\n'
    elif leg == "ubuntu-npm-large":
        files[".gitignore"] = b"node_modules/\n"
        files["package.json"] = _json_bytes({"name": "acceptance-414", "version": "1.0.0", "private": True})
    return files


def _scaffold(root, leg):
    repo = root / "repo"
    if repo.exists():
        raise SystemExit(f"{repo} already exists; ROOT must be fresh")
    for path, data in _project(leg).items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _git(repo, "init", "-q", "-b", "main")
    for key, value in GIT_CONFIG:
        _git(repo, "config", key, value)
    print(f"scaffolded {leg} in {repo}", flush=True)
    return 0


# --- bigpack ------------------------------------------------------------------------------------

def _bigpack(root):
    """A generated npm package of BIG_DIRS x BIG_FILES_PER_DIR + 2 files, as a tarball.

    npm extracts a tarball dependency into node_modules; a `file:` directory
    dependency would be a directory symlink, which the walk lists and never
    enters, so it would not count toward the path limit.
    """
    out = root / "bigpack"
    out.mkdir(parents=True, exist_ok=True)
    target = out / BIG_TARBALL
    with tarfile.open(target, "w:gz", compresslevel=1) as tar:
        def add(name, data):
            info = tarfile.TarInfo("package/" + name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))

        add("package.json", _json_bytes({"name": "big-tree", "version": "1.0.0", "license": "MIT",
                                         "main": "index.js"}))
        add("index.js", b"module.exports = {};\n")
        for directory in range(BIG_DIRS):
            for number in range(BIG_FILES_PER_DIR):
                add(f"data/d{directory:03d}/f{number:03d}.txt", b"x\n")
    print(f"wrote {target}: {BIG_DIRS * BIG_FILES_PER_DIR + 2} files, "
          f"sha256 {hashlib.sha256(target.read_bytes()).hexdigest()}", flush=True)
    return 0


# --- run: the setup -----------------------------------------------------------------------------

def _scan(repo):
    """Directory links and inventory entries, following no link of any kind.

    Entries are counted as `WorkingTreeSnapshot.list_paths` counts them on
    Linux: every file (a file symlink included) and every directory symlink,
    with anything named `.git` left out.
    """
    links, entries = [], 0
    stack = [repo]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as iterator:
            items = sorted(iterator, key=lambda item: item.name)
        for entry in items:
            if entry.name == ".git":
                continue
            relative = Path(entry.path).relative_to(repo).as_posix()
            kind = _entry_link_kind(entry)
            if kind is not None and entry.is_dir():
                links.append({"path": relative, "kind": kind, "target": _readlink(entry.path)})
                entries += 1
            elif kind is None and entry.is_dir(follow_symlinks=False):
                stack.append(entry.path)
            else:
                entries += 1
    return sorted(links, key=lambda link: link["path"]), entries


def _setup_facts(repo, leg):
    checks = []

    def need(label, ok, detail=""):
        checks.append({"check": label, "ok": bool(ok), "detail": detail})

    links, entries = _scan(repo)
    if leg == "ubuntu-venv":
        lib64 = repo / ".venv" / "lib64"
        need(".venv/lib64 is a directory symlink", lib64.is_symlink() and lib64.is_dir(),
             _readlink(lib64) if lib64.is_symlink() else "not a symlink")
        need(".venv/bin/python exists", (repo / ".venv" / "bin" / "python").exists())
    elif leg in PNPM_LEGS:
        for path in ("node_modules/semver", "packages/shared/node_modules/semver", "packages/web/node_modules/shared"):
            kind = _path_link_kind(repo / path)
            need(f"{path} is a directory link", kind is not None and (repo / path).is_dir(), kind or "not a link")
    elif leg == "ubuntu-npm-large":
        need(f"the tree holds more than {PATH_LIMIT} inventory entries", entries > PATH_LIMIT, str(entries))
        need("node_modules/.bin/semver exists", os.path.lexists(repo / "node_modules" / ".bin" / "semver"))
        need("node_modules/big-tree/package.json exists", (repo / "node_modules" / "big-tree" / "package.json").is_file())
    facts = {
        "ok": all(check["ok"] for check in checks),
        "checks": checks,
        "inventory_entries_following_no_link": entries,
        "directory_link_count": len(links),
        "directory_link_kinds": sorted({link["kind"] for link in links}),
        "directory_links": links[:200],
    }
    pyvenv = repo / ".venv" / "pyvenv.cfg"
    if pyvenv.is_file():
        facts["pyvenv_cfg"] = pyvenv.read_text(encoding="utf-8", errors="replace")
    return facts


# --- run: the engines ---------------------------------------------------------------------------

def _calls(mode, script, repo):
    """The commands of one mode, each with its stdin object or None; the last one is judged."""
    if mode == "term":  # the pre-commit hook's entry (.pre-commit-hooks.yaml)
        return [([script, "check", "--format", "term"], None)]
    if mode == "hook-json":  # the issue's command; the managed Stop handler of v0.7.0 and v0.8.0
        return [([script, "check", "--format", "hook-json"], None)]
    # The managed SessionStart and Stop handlers on main (#418, hooks.py).
    start = {"session_id": SESSION_ID, "hook_event_name": "SessionStart", "source": "startup", "cwd": str(repo)}
    stop = {"session_id": SESSION_ID, "hook_event_name": "Stop", "stop_hook_active": False, "cwd": str(repo)}
    return [([script, "hook", "session-start"], start),
            ([script, "check", "--format", "hook-json", "--hook-input", "stdin"], stop)]


def _execute(argv, repo, stdin):
    env = dict(os.environ, PYTHONUTF8="1", NO_COLOR="1")
    if stdin is None:
        streams = {"stdin": subprocess.DEVNULL}
    else:
        streams = {"input": json.dumps(stdin).encode("utf-8")}
    try:
        result = subprocess.run(argv, cwd=str(repo), env=env, capture_output=True, timeout=RUN_TIMEOUT, **streams)
        code, out, err = result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired as exc:
        code, out, err = None, exc.stdout or b"", (exc.stderr or b"") + b"\n[acceptance-414: timed out]\n"
    record = {
        "argv": [Path(argv[0]).name, *argv[1:]],
        "stdin": stdin,
        "exit": code,
        "stdout": out.decode("utf-8", "replace"),
        "stderr": err.decode("utf-8", "replace"),
        "stdout_sha256": hashlib.sha256(out).hexdigest(),
        "stderr_sha256": hashlib.sha256(err).hexdigest(),
    }
    return record, out, err


def _classify(mode, record):
    """pass, pass-with-note, block, refusal, silent-exit-2, timeout or other.

    A refusal is an engine error the user is told about: exit 2 with the
    engine-error line in term mode; in hook-json, exit 0 with only a
    `systemMessage` that says the change was not analysed (#414). A silent
    exit 2 is hook-json before #414: exit 2, the line on stderr, nothing on
    stdout. In hook-json a pass is `{}`; a pass-with-note carries only the
    session note (#418), which no row expects: no commit is made during the
    session, so after a recorded SessionStart the Stop prints `{}`, and a note
    ("no start was recorded ...") means the record was not found or not used.
    `hook session-start` exits 0 whatever happens, so its exit cannot show it.
    """
    code, stdout, stderr = record["exit"], record["stdout"], record["stderr"]
    error_line = ENGINE_ERROR in stderr
    if code is None:
        return "timeout"
    if mode == "term":
        verdicts = re.findall(r"\bverdict=(pass|block)\b", stdout)
        if not error_line and code == 0 and verdicts == ["pass"]:
            return "pass"
        if not error_line and code == 1 and verdicts == ["block"]:
            return "block"
        if code == 2 and error_line:
            return "refusal"
        return "other"
    if code == 2 and error_line and not stdout.strip():
        return "silent-exit-2"
    if code != 0:
        return "other"
    try:
        payload = json.loads(stdout)
    except ValueError:
        return "other"
    if not isinstance(payload, dict):
        return "other"
    message = payload.get("systemMessage")
    if isinstance(message, str) and message.startswith(NOT_ANALYSED):
        return "refusal" if error_line and "decision" not in payload else "other"
    if error_line:
        return "other"
    if "decision" not in payload:
        if not payload:
            return "pass"
        if set(payload) == {"systemMessage"} and isinstance(message, str):
            return "pass-with-note"
        return "other"
    reason = payload.get("reason")
    if payload["decision"] == "block" and isinstance(reason, str) and "not analysed" not in reason:
        return "block"
    return "other"


def _expected(leg, engine, mode):
    """(outcomes, message) by reading the engines' code, or None for no expectation."""
    if leg == "ubuntu-npm-large":
        if engine in ("main", "v0.8.0"):
            return ("refusal",), LIMIT_NAMED
        return (("refusal",) if mode == "term" else ("silent-exit-2",)), LIMIT_V070
    if engine in ("main", "v0.8.0"):
        return VERDICT, None
    if leg == "windows-pnpm":
        # By reading, Path.is_symlink() is False for a junction, so v0.7.0
        # refuses only if pnpm made symlinks; the receipt records which.
        return None
    return (("refusal",) if mode == "term" else ("silent-exit-2",)), SYMLINK_V070


def _matches(row, expected):
    outcomes, message = expected
    if row["outcome"] not in outcomes:
        return False
    if any(pre["exit"] != 0 for pre in row["pre"]):
        return False
    if message is None:
        return True
    if row["outcome"] == "refusal" and row["mode"] != "term":
        shown = json.loads(row["stdout"])["systemMessage"]
        return message in shown and message in row["stderr"]
    return message in row["stderr"]


def _rows(repo, rows_dir, leg, engines):
    rows = []
    for engine in engines:
        for mode in MODES:
            if mode == "stop-hook" and engine["name"] != "main":
                continue  # v0.7.0's and v0.8.0's Stop handler is the hook-json mode
            calls = _calls(mode, engine["script"], repo)
            pre = [_execute(argv, repo, stdin)[0] for argv, stdin in calls[:-1]]
            argv, stdin = calls[-1]
            record, out, err = _execute(argv, repo, stdin)
            stem = f"{engine['name']}-{mode}"
            (rows_dir / f"{stem}.stdout").write_bytes(out)
            (rows_dir / f"{stem}.stderr").write_bytes(err)
            row = {"engine": engine["name"], "commit": engine["commit"], "role": engine["role"], "mode": mode,
                   **record, "pre": pre}
            row["outcome"] = _classify(mode, record)
            expected = _expected(leg, engine["name"], mode)
            row["expected"] = None if expected is None else {"outcomes": list(expected[0]), "message": expected[1]}
            row["matches"] = None if expected is None else _matches(row, expected)
            rows.append(row)
            print(f"{stem}: exit {record['exit']}, {row['outcome']}, matches={row['matches']}", flush=True)
    return rows


def _evaluate(setup, rows):
    required = [row for row in rows if row["role"] == "required"]
    controls = [row for row in rows if row["role"] == "control" and row["expected"] is not None]
    if not setup["ok"]:
        status = "setup not reproduced"
    elif not all(row["matches"] for row in required):
        status = "not accepted"
    elif not all(row["matches"] for row in controls):
        status = "inconclusive: the control did not reproduce #414"
    else:
        status = "accepted"
    notes = []
    for row in rows:
        label = f"{row['engine']} {row['mode']}"
        if row["expected"] and "pass" in row["expected"]["outcomes"] and row["outcome"] == "block":
            notes.append(f"{label}: block, where this honest edit was expected to pass")
        if row["outcome"] == "pass-with-note":
            note = json.loads(row["stdout"])["systemMessage"]
            notes.append(f"{label}: a pass with a session note, which no row expects "
                         f"(the SessionStart record was not found or not used): {note}")
        if row["role"] == "report" and row["matches"] is False:
            notes.append(f"{label}: differs from its expectation (report only)")
        if row["expected"] is None:
            notes.append(f"{label}: {row['outcome']} (no expectation; recorded)")
    return status, notes


def _summary(leg, status, setup, rows, notes, receipt_sha256):
    lines = [f"### #414 acceptance: {leg}: {status}", ""]
    for check in setup["checks"]:
        lines.append(f"- setup: {check['check']}: {'yes' if check['ok'] else 'NO'} {check['detail']}".rstrip())
    lines.append(f"- directory links in the tree: {setup['directory_link_count']} "
                 f"({', '.join(setup['directory_link_kinds']) or 'none'})")
    lines += ["", "| engine | role | mode | exit | outcome | expected | matches |", "|---|---|---|---|---|---|---|"]
    for row in rows:
        expected = "-" if row["expected"] is None else " or ".join(row["expected"]["outcomes"])
        lines.append(f"| {row['engine']} | {row['role']} | {row['mode']} | {row['exit']} | {row['outcome']} "
                     f"| {expected} | {row['matches']} |")
    lines += [""] + [f"- {note}" for note in notes]
    lines += ["", f"receipt.json sha256: `{receipt_sha256}`", ""]
    return "\n".join(lines)


def _run(root, leg):
    repo = root / "repo"
    receipt_dir = root / "receipt"
    rows_dir = receipt_dir / "rows"
    rows_dir.mkdir(parents=True, exist_ok=True)
    engines = json.loads((receipt_dir / "engines.json").read_text(encoding="utf-8"))

    setup = _setup_facts(repo, leg)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base: the project after its real setup")
    base = _git(repo, "rev-parse", "HEAD")
    tracked = _git(repo, "ls-files").splitlines()
    (repo / EDIT_PATH).write_bytes(EDITED)
    status_before = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")

    rows = _rows(repo, rows_dir, leg, engines)
    status_after = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    verdict, notes = _evaluate(setup, rows)
    if status_before != f" M {EDIT_PATH}":
        notes.append(f"the change was not exactly the edit: {status_before!r}")
    if status_after != status_before:
        notes.append(f"the runs changed the working tree: {status_after!r}")

    tools = receipt_dir / "tools.txt"
    receipt = {
        "declaration": "docs/acceptance/414-hosted.md",
        "ruling": "owner ruling 2026-10-19, R26 option A",
        "leg": leg,
        "status": verdict,
        "notes": notes,
        "workflow": {key.lower(): os.environ.get(key) for key in (
            "GITHUB_REPOSITORY", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "GITHUB_HEAD_REF",
            "PR_HEAD_SHA", "RUNNER_OS", "RUNNER_ARCH", "ImageOS", "ImageVersion")},
        "host": {"platform": platform.platform(), "python": sys.version, "git": _git(repo, "--version")},
        "tools": tools.read_text(encoding="utf-8", errors="replace") if tools.is_file() else None,
        "engines": engines,
        "setup": setup,
        "scenario": {
            "base_commit": base,
            "tracked_files": tracked,
            "edit": {"path": EDIT_PATH, "before": TOTAL.decode(), "after": EDITED.decode()},
            "status_before_runs": status_before,
            "status_after_runs": status_after,
        },
        "rows": rows,
    }
    receipt_bytes = _json_bytes(receipt)
    (receipt_dir / "receipt.json").write_bytes(receipt_bytes)
    digest = hashlib.sha256(receipt_bytes).hexdigest()
    summary = _summary(leg, verdict, setup, rows, notes, digest)
    (receipt_dir / "summary.md").write_text(summary, encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as handle:
            handle.write(summary + "\n")
    print(summary, flush=True)
    return 0 if verdict == "accepted" else 1


def main(argv=None):
    # -I ignores PYTHONUTF8; the job log must not fail on a non-ASCII byte.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="The #414 hosted acceptance run (docs/acceptance/414-hosted.md).")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("engines", "scaffold", "bigpack", "run"):
        command = commands.add_parser(name)
        command.add_argument("--root", required=True, type=Path)
        if name in ("scaffold", "run"):
            command.add_argument("--leg", required=True, choices=LEGS)
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "engines":
        return _engines(root)
    if args.command == "scaffold":
        return _scaffold(root, args.leg)
    if args.command == "bigpack":
        return _bigpack(root)
    return _run(root, args.leg)


if __name__ == "__main__":
    raise SystemExit(main())
