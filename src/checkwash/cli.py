"""checkwash CLI.

    checkwash check [BASE..HEAD] [--task FILE] [--format term|json|sarif]
                    [--fail-on SEV] [--emit-ir] [--repo PATH]
    checkwash allow FINGERPRINT --reason "..." [--expires YYYY-MM-DD]
    checkwash bench [--local] [--corpus DIR] [--run-sweep]

Exit codes (SPEC §9): 0 pass, 1 block, 2 engine error.
`bench` uses 0 / 2 only — it never reports a verdict.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

from checkwash import __version__
from checkwash.allowlist import MAX_EXPIRY_DAYS, load_allowlist
from checkwash.config import SEVERITY_ORDER, load_config, read_base_config_file, resolve_config_file
from checkwash.contract import Contract, parse_contract
from checkwash.deps import MANIFESTS, parse_manifest, project_names
from checkwash.engine import analyze
from checkwash.pyenv import known_baseline
from checkwash.gitio import (
    GitError,
    grep_head_paths,
    list_range_changes,
    list_worktree_changes,
    merge_base,
    read_base_file,
    rev_parse,
)
from checkwash.report.jsonout import findings_to_json, ir_to_json
from checkwash.report.sarif import findings_to_sarif
from checkwash.report.term import render
from checkwash.sweep import sweep


def _today() -> datetime.date:
    override = os.environ.get("CHECKWASH_TODAY") or os.environ.get("GREENWASH_TODAY")
    if override:
        return datetime.date.fromisoformat(override)
    return datetime.date.today()


def _write_machine(text: str) -> None:
    """Machine-readable output is always UTF-8 bytes.

    Writing str to a cp1252/cp950 pipe made the JSON locale-dependent and
    lossy ('?' for CJK evidence), breaking both the byte-identical promise
    and `json.loads(out.decode("utf-8"))` (confirmed red-team finding).
    """
    data = text.encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    sys.stdout.flush()
    buffer.write(data)
    buffer.flush()


def _write_term(text: str) -> None:
    """Human report: degrade unencodable glyphs rather than crash (SPEC §9)."""
    enc = getattr(sys.stdout, "encoding", None)
    if enc:
        try:
            text.encode(enc)
        except (UnicodeEncodeError, LookupError):
            text = text.encode(enc, errors="replace").decode(enc, errors="replace")
    sys.stdout.write(text)


def _cmd_check(args: argparse.Namespace) -> int:
    repo = args.repo
    if args.range:
        if "..." in args.range:
            # Three-dot means merge-base(A,B)..B — the standard PR-diff
            # idiom. Silently downgrading it to two dots pulled base-branch
            # prod commits into the diff, which disarmed E1 on every open PR
            # whose base branch had moved (confirmed red-team finding).
            left, _, right = args.range.partition("...")
            right = right.lstrip(".")
            if not left or not right:
                print(f"error: range must be BASE...HEAD, got {args.range!r}", file=sys.stderr)
                return 2
            base = merge_base(repo, left, right)
            head = right
        elif ".." in args.range:
            base, _, head = args.range.partition("..")
        else:
            print(f"error: range must be BASE..HEAD, got {args.range!r}", file=sys.stderr)
            return 2
        if not base or not head:
            print(f"error: range must be BASE..HEAD, got {args.range!r}", file=sys.stderr)
            return 2
        changes = list_range_changes(repo, base, head)
        base_label = rev_parse(repo, base)
        head_label = rev_parse(repo, head)
        config_side = base

        # D6 resolves skip-condition constants imported from files outside
        # the diff; the head snapshot is where those files live.
        def head_reader(path: str, _rev: str = head) -> bytes | None:
            return read_base_file(repo, _rev, path)

        def head_searcher(needles: list[str], _rev: str = head) -> list[str]:
            return grep_head_paths(repo, _rev, needles)
    else:
        base = "HEAD"
        changes = list_worktree_changes(repo)
        base_label = rev_parse(repo, "HEAD")
        head_label = "worktree"
        config_side = "HEAD"

        def head_reader(path: str) -> bytes | None:
            # Worktree mode's head snapshot is the working tree itself, the
            # same place list_worktree_changes reads the after side from.
            disk = os.path.join(repo, path.replace("/", os.sep))
            try:
                with open(disk, "rb") as fh:
                    return fh.read()
            except OSError:
                return None

        def head_searcher(needles: list[str]) -> list[str]:
            # Working-tree grep, bounded: .py files only, artifact dirs
            # pruned, first 64 hits win. Only runs when a test unit
            # disappeared from the working diff.
            wanted = [n.encode("utf-8") for n in needles]
            hits: list[str] = []
            skip_dirs = {".git", "__pycache__", "node_modules", "dist", "build", ".venv", "venv", ".tox", ".nox", ".eggs", "htmlcov"}
            for root, dirs, files in os.walk(repo):
                dirs[:] = sorted(d for d in dirs if d not in skip_dirs and not d.startswith("."))
                for fn in sorted(files):
                    if not fn.endswith(".py"):
                        continue
                    full = os.path.join(root, fn)
                    try:
                        with open(full, "rb") as fh:
                            data = fh.read(1_000_000)
                    except OSError:
                        continue
                    if any(n in data for n in wanted):
                        hits.append(os.path.relpath(full, repo).replace(os.sep, "/"))
                        if len(hits) >= 64:
                            return hits
            return hits

    config_path, config_data = read_base_config_file(repo, config_side, "config.toml")
    config, config_error, config_warnings = load_config(config_data, path=config_path)
    if args.fail_on:
        config.fail_on = args.fail_on
    allow_path, allow_data = read_base_config_file(repo, config_side, "allow.toml")
    allow_entries, allow_error = load_allowlist(allow_data, path=allow_path)
    # A config that silently fails to parse used to revert a hardened gate to
    # defaults with no diagnostic anywhere (confirmed red-team finding).
    # Value-level warnings are visible in the same channels but never fatal:
    # the one value a warning can concern (on_engine_error itself) must not
    # become the engine error it describes (audit 2026-08-19).
    errors = [e for e in (config_error, allow_error) if e]
    diagnostics = errors + config_warnings
    for message in diagnostics:
        print(f"checkwash: {message}", file=sys.stderr)
    if errors and config.on_engine_error == "block":
        return 2

    contract = Contract()
    if args.task:
        # The contract carries oracle_freeze and the scope globs, so reading
        # it from the head side let a diff edit TASK.md to disarm E2 and E7
        # for itself. Same rule as config and the allowlist: base side wins
        # (SPEC §1); the working-tree copy is only a fallback when the task
        # file is untracked.
        rel = os.path.relpath(args.task, repo).replace("\\", "/")
        data = read_base_file(repo, config_side, rel)
        if data is not None:
            contract = parse_contract(data.decode("utf-8", errors="replace"))
        else:
            with open(args.task, encoding="utf-8") as fh:
                contract = parse_contract(fh.read())

    known_modules: set[str] | None = None
    declared: set[str] = set()
    # The project's own name, kept apart from what it depends on: "declared"
    # answers yes for `flask` inside flask, and a first-party check built on it
    # would deny the first party.
    self_modules: set[str] = set()
    found_manifest = False
    for manifest in MANIFESTS:
        data = read_base_file(repo, config_side, manifest)
        if data is None:
            continue
        found_manifest = True
        declared |= parse_manifest(manifest, data)
        self_modules |= project_names(manifest, data)
    if found_manifest:
        known_modules = known_baseline() | declared

    ir, findings, verdict = analyze(
        changes,
        config,
        contract,
        allow_entries,
        _today(),
        base_label=base_label,
        head_label=head_label,
        known_modules=known_modules,
        self_modules=self_modules,
        head_reader=head_reader,
        head_searcher=head_searcher,
    )

    if args.emit_ir:
        _write_machine(ir_to_json(ir))
        return 0
    if args.format == "json":
        _write_machine(findings_to_json(ir, findings, verdict, diagnostics))
    elif args.format == "sarif":
        _write_machine(findings_to_sarif(ir, findings))
    elif args.format == "hook-json":
        # Claude Code Stop-hook protocol: JSON on stdout carries the decision,
        # exit 0 either way (non-zero would read as a hook failure).
        import json as _json

        if verdict == "block":
            threshold = SEVERITY_ORDER[config.fail_on]
            visible = [
                f for f in findings
                if not f.allowlisted
                and SEVERITY_ORDER[f.severity] >= threshold
            ]
            head = visible[0] if visible else None
            reason = "checkwash: " + (
                f"{len(visible)} finding(s) blocking. "
                + (f"{head.rule} {head.path}"
                   + (f" :: {head.unit}" if head.unit else "")
                   + f" — {head.message}. " if head else "")
                + "Fix the production code, or record a reviewed exemption: "
                + (f'checkwash allow "{head.fingerprint}" --reason "..."' if head else "")
            )
            _write_machine(_json.dumps({"decision": "block", "reason": reason}) + "\n")
        else:
            _write_machine("{}\n")
        return 0
    else:
        _write_term(render(
            ir, findings, verdict, config.fail_on, errors=diagnostics,
            ledger_path=resolve_config_file(repo, "allow.toml"),
        ))
    return 1 if verdict == "block" else 0


# The remote form first, because it is the one that works on a machine that
# does not already have checkwash: pre-commit builds it in its own
# environment. This command used to print only the `repo: local` /
# `language: system` variant, which silently requires checkwash on PATH — so
# the CLI handed users the more fragile of the two answers while the README
# published the other, and nothing said when to pick which (field integration
# 2026-08-07). The rev is interpolated rather than typed, because a hardcoded
# version in a printed snippet is a claim that drifts.
_PRECOMMIT_SNIPPET = """\
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/taipei49314/checkwash
    rev: v{version}
    hooks:
      - id: checkwash

# Alternative, if checkwash is already installed in the environment your hooks
# run in (faster, and no network on first install; fails if it is not there):
#
#   - repo: local
#     hooks:
#       - id: checkwash
#         name: checkwash (oracle-tampering tripwire)
#         entry: checkwash check --format term
#         language: system
#         pass_filenames: false
#         always_run: true
"""


def _cmd_hook_install(args: argparse.Namespace) -> int:
    import json as _json

    if args.agent == "pre-commit":
        if args.local:
            print("error: --local applies to --agent claude-code only", file=sys.stderr)
            return 2
        # Nothing to write for them — their config is theirs; print the block.
        sys.stdout.write(_PRECOMMIT_SNIPPET.format(version=__version__))
        return 0

    # settings.local.json is Claude Code's machine-local file (conventionally
    # git-ignored). It exists as a target because installing into the shared
    # settings.json edits a guardrail file inside the repo — a change this
    # tool's own GUARDRAIL_TOUCHED detector then flags on the next diff. A
    # first-party installer should not force a guardrail commit just to try
    # the gate: trial locally, share by choice.
    filename = "settings.local.json" if args.local else "settings.json"
    settings_path = os.path.join(args.repo, ".claude", filename)
    settings: dict = {}
    if os.path.exists(settings_path):
        # utf-8-sig, not utf-8: Windows tooling routinely writes settings.json
        # with a BOM (PowerShell 5.1's `Out-File -Encoding utf8` always does),
        # and json.load rejects a BOM outright — so the installer refused
        # perfectly healthy files as "not valid JSON". The sig codec accepts
        # both forms; the write below normalizes to BOM-less UTF-8.
        with open(settings_path, encoding="utf-8-sig") as fh:
            try:
                settings = _json.load(fh)
            except _json.JSONDecodeError:
                print(f"error: {settings_path} is not valid JSON; not touching it", file=sys.stderr)
                return 2
    command = "checkwash check --format hook-json"
    hooks = settings.setdefault("hooks", {})
    stop = hooks.setdefault("Stop", [])
    already = any(
        h.get("command") == command
        for entry in stop
        if isinstance(entry, dict)
        for h in entry.get("hooks", [])
        if isinstance(h, dict)
    )
    if not already:
        stop.append({"hooks": [{"type": "command", "command": command}]})
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w", encoding="utf-8", newline="\n") as fh:
        _json.dump(settings, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(
        f"{'already installed' if already else 'installed'}: Stop hook in {settings_path}\n"
        "checkwash will run when the agent finishes and block the stop on high findings."
    )
    return 0


def _toml_str(value: str) -> str:
    """TOML basic string. Naive quoting produced invalid TOML for any reason
    mentioning a Windows path, which silently voided the entire exemption
    ledger on the next run (confirmed red-team finding)."""
    out = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _cmd_allow(args: argparse.Namespace) -> int:
    if not args.reason.strip():
        print("error: --reason must not be empty", file=sys.stderr)
        return 2
    today = _today()
    expires = args.expires or (today + datetime.timedelta(days=90)).isoformat()
    if (datetime.date.fromisoformat(expires) - today).days > MAX_EXPIRY_DAYS:
        print(f"error: expiry exceeds {MAX_EXPIRY_DAYS} days", file=sys.stderr)
        return 2
    path = os.path.join(args.repo, *resolve_config_file(args.repo, "allow.toml").split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    entry = (
        "\n[[allow]]\n"
        f"fingerprint = {_toml_str(args.fingerprint)}\n"
        f"rule = {_toml_str(args.fingerprint.split('/', 1)[0])}\n"
        f"reason = {_toml_str(args.reason)}\n"
        f"author = {_toml_str(args.author)}\n"
        f"created = {_toml_str(today.isoformat())}\n"
        f"expires = {_toml_str(expires)}\n"
    )
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(entry)
    print(f"recorded exemption in {path} (expires {expires}); commit it through review")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="checkwash")
    parser.add_argument("--version", action="version", version=f"checkwash {__version__}")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="analyse a diff for verification-layer tampering")
    check.add_argument("range", nargs="?", help="BASE..HEAD; omit to check HEAD..worktree")
    check.add_argument("--task", help="task manifest file (TASK.md style)")
    check.add_argument("--format", choices=["term", "json", "hook-json", "sarif"], default="term")
    check.add_argument("--fail-on", choices=list(SEVERITY_ORDER), default=None)
    check.add_argument("--emit-ir", action="store_true", help="print the IR JSON and exit")
    check.add_argument("--repo", default=".")

    sweep_p = sub.add_parser(
        "sweep", help="measure finding rates over a repo's commit history"
    )
    sweep_p.add_argument("revs", nargs="?", default="HEAD", help="rev-list range, e.g. HEAD or main")
    sweep_p.add_argument("--limit", type=int, default=200)
    sweep_p.add_argument("--fail-on", choices=list(SEVERITY_ORDER), default=None)
    sweep_p.add_argument("--repo", default=".")

    hook = sub.add_parser("hook", help="integration helpers")
    hook_sub = hook.add_subparsers(dest="hook_command")
    hook_install = hook_sub.add_parser("install", help="wire checkwash into an agent or tool")
    hook_install.add_argument("--agent", choices=["claude-code", "pre-commit"], required=True)
    hook_install.add_argument("--repo", default=".")
    hook_install.add_argument(
        "--local",
        action="store_true",
        help="write .claude/settings.local.json (machine-local, git-ignored) instead of the shared settings.json",
    )

    sub.add_parser("demo", help="replay real tampering cases offline")

    doctor = sub.add_parser(
        "doctor", help="is this installation able to block anything?"
    )
    doctor.add_argument("--repo", default=".")

    bench = sub.add_parser(
        "bench",
        help="reproduce published numbers from this checkout",
    )
    bench.add_argument(
        "--repo",
        default=".",
        help="checkwash checkout (walks up looking for benchmarks/README.md)",
    )
    bench.add_argument(
        "--corpus",
        default=None,
        help="directory of the six sweep clones (or set GREENWASH_CORPUS)",
    )
    bench.add_argument(
        "--local",
        action="store_true",
        help="skip the third-party sweep clones; run only what this clone contains",
    )
    bench.add_argument(
        "--run-sweep",
        action="store_true",
        help="re-run the 1800-commit sweep (slow; requires every clone and pin)",
    )

    allow = sub.add_parser("allow", help="record a reviewed exemption")
    allow.add_argument("fingerprint")
    allow.add_argument("--reason", required=True)
    allow.add_argument("--expires", default=None)
    allow.add_argument("--author", default=os.environ.get("USERNAME") or os.environ.get("USER") or "")
    allow.add_argument("--repo", default=".")
    return parser


_SUBCOMMANDS = ("check", "allow", "sweep", "hook", "demo", "doctor", "bench")


def _edit_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 2:
        return 3
    prev = list(range(len(right) + 1))
    for i, ca in enumerate(left, 1):
        cur = [i]
        for j, cb in enumerate(right, 1):
            cur.append(
                min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            )
        prev = cur
    return prev[-1]


def _closest_command(token: str) -> str | None:
    """A misspelled subcommand, not a git rev that check should accept."""
    if not token.isalpha() or len(token) < 3:
        return None
    folded = token.lower()
    best: str | None = None
    best_d = 3
    for name in _SUBCOMMANDS:
        dist = _edit_distance(folded, name)
        if dist < best_d:
            best_d = dist
            best = name
    if best is not None and 1 <= best_d <= 2:
        return best
    return None


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["check"]
    # Every subcommand must be listed here as well as in the parser: an
    # unlisted name is silently reinterpreted as a `check` range, so a typo'd
    # or newly added command reports a verdict instead of an error.
    elif argv[0] not in (
        "check", "allow", "sweep", "hook", "demo", "doctor", "bench",
        "-h", "--help", "--version",
    ):
        hint = _closest_command(argv[0])
        if hint:
            print(
                f"error: unknown command {argv[0]!r}. Did you mean {hint!r}?",
                file=sys.stderr,
            )
            return 2
        argv = ["check", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return _cmd_check(args)
        if args.command == "allow":
            return _cmd_allow(args)
        if args.command == "hook":
            if getattr(args, "hook_command", None) == "install":
                return _cmd_hook_install(args)
            parser.parse_args(["hook", "--help"])
            return 2
        if args.command == "sweep":
            result = sweep(args.repo, args.revs, args.limit, _today(), args.fail_on)
            _write_machine(result.to_json())
            return 0
        if args.command == "demo":
            from checkwash.demo import run as run_demo

            return run_demo()
        if args.command == "doctor":
            from checkwash.doctor import run as run_doctor

            return run_doctor(args.repo)
        if args.command == "bench":
            from checkwash.bench import run as run_bench

            return run_bench(
                args.repo,
                corpus=args.corpus,
                local_only=args.local,
                run_sweep=args.run_sweep,
            )
        parser.print_help()
        return 2
    except (GitError, OSError, RecursionError) as exc:
        print(f"checkwash engine error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - crash must never read as a verdict
        # Exit 1 means "block" (SPEC §9); an unhandled traceback exiting 1
        # is indistinguishable from a real finding for CI (confirmed
        # red-team finding). Engine errors are always 2.
        print(f"checkwash engine error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
