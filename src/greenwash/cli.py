"""greenwash CLI.

    greenwash check [BASE..HEAD] [--task FILE] [--format term|json]
                    [--fail-on SEV] [--emit-ir] [--repo PATH]
    greenwash allow FINGERPRINT --reason "..." [--expires YYYY-MM-DD]

Exit codes (SPEC §9): 0 pass, 1 block, 2 engine error.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys

from greenwash import __version__
from greenwash.allowlist import MAX_EXPIRY_DAYS, load_allowlist
from greenwash.config import SEVERITY_ORDER, load_config
from greenwash.contract import Contract, parse_contract
from greenwash.deps import MANIFESTS, parse_manifest
from greenwash.engine import analyze
from greenwash.pyenv import known_baseline
from greenwash.gitio import (
    GitError,
    list_range_changes,
    list_worktree_changes,
    merge_base,
    read_base_file,
    rev_parse,
)
from greenwash.report.jsonout import findings_to_json, ir_to_json
from greenwash.report.term import render
from greenwash.sweep import sweep


def _today() -> datetime.date:
    override = os.environ.get("GREENWASH_TODAY")
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
    else:
        base = "HEAD"
        changes = list_worktree_changes(repo)
        base_label = rev_parse(repo, "HEAD")
        head_label = "worktree"
        config_side = "HEAD"

    config, config_error = load_config(read_base_file(repo, config_side, ".greenwash/config.toml"))
    if args.fail_on:
        config.fail_on = args.fail_on
    allow_entries, allow_error = load_allowlist(
        read_base_file(repo, config_side, ".greenwash/allow.toml")
    )
    # A config that silently fails to parse used to revert a hardened gate to
    # defaults with no diagnostic anywhere (confirmed red-team finding).
    errors = [e for e in (config_error, allow_error) if e]
    for message in errors:
        print(f"greenwash: {message}", file=sys.stderr)
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
    found_manifest = False
    for manifest in MANIFESTS:
        data = read_base_file(repo, config_side, manifest)
        if data is None:
            continue
        found_manifest = True
        declared |= parse_manifest(manifest, data)
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
    )

    if args.emit_ir:
        _write_machine(ir_to_json(ir))
        return 0
    if args.format == "json":
        _write_machine(findings_to_json(ir, findings, verdict, errors))
    else:
        _write_term(render(ir, findings, verdict, config.fail_on, errors=errors))
    return 1 if verdict == "block" else 0


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
    path = os.path.join(args.repo, ".greenwash", "allow.toml")
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
    parser = argparse.ArgumentParser(prog="greenwash")
    parser.add_argument("--version", action="version", version=f"greenwash {__version__}")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="analyse a diff for verification-layer tampering")
    check.add_argument("range", nargs="?", help="BASE..HEAD; omit to check HEAD..worktree")
    check.add_argument("--task", help="task manifest file (TASK.md style)")
    check.add_argument("--format", choices=["term", "json"], default="term")
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

    allow = sub.add_parser("allow", help="record a reviewed exemption")
    allow.add_argument("fingerprint")
    allow.add_argument("--reason", required=True)
    allow.add_argument("--expires", default=None)
    allow.add_argument("--author", default=os.environ.get("USERNAME") or os.environ.get("USER") or "")
    allow.add_argument("--repo", default=".")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["check"]
    elif argv[0] not in ("check", "allow", "sweep", "-h", "--help", "--version"):
        argv = ["check", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return _cmd_check(args)
        if args.command == "allow":
            return _cmd_allow(args)
        if args.command == "sweep":
            result = sweep(args.repo, args.revs, args.limit, _today(), args.fail_on)
            _write_machine(result.to_json())
            return 0
        parser.print_help()
        return 2
    except (GitError, OSError, RecursionError) as exc:
        print(f"greenwash engine error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 - crash must never read as a verdict
        # Exit 1 means "block" (SPEC §9); an unhandled traceback exiting 1
        # is indistinguishable from a real finding for CI (confirmed
        # red-team finding). Engine errors are always 2.
        print(f"greenwash engine error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
