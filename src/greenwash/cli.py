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
from greenwash.engine import analyze
from greenwash.gitio import GitError, list_range_changes, list_worktree_changes, read_base_file, rev_parse
from greenwash.report.jsonout import findings_to_json, ir_to_json
from greenwash.report.term import render


def _today() -> datetime.date:
    override = os.environ.get("GREENWASH_TODAY")
    if override:
        return datetime.date.fromisoformat(override)
    return datetime.date.today()


def _write_stdout(text: str) -> None:
    """Belt-and-braces encode guard: report content includes repo-controlled
    text (evidence lines), and a UnicodeEncodeError on a legacy-locale pipe
    must never turn into a bogus exit code (SPEC §9)."""
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
        if ".." not in args.range:
            print(f"error: range must be BASE..HEAD, got {args.range!r}", file=sys.stderr)
            return 2
        base, _, head = args.range.partition("..")
        head = head.lstrip(".")  # tolerate triple-dot
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

    config = load_config(read_base_file(repo, config_side, ".greenwash/config.toml"))
    if args.fail_on:
        config.fail_on = args.fail_on
    allow_entries = load_allowlist(read_base_file(repo, config_side, ".greenwash/allow.toml"))

    contract = Contract()
    if args.task:
        with open(args.task, encoding="utf-8") as fh:
            contract = parse_contract(fh.read())

    ir, findings, verdict = analyze(
        changes,
        config,
        contract,
        allow_entries,
        _today(),
        base_label=base_label,
        head_label=head_label,
    )

    if args.emit_ir:
        _write_stdout(ir_to_json(ir))
        return 0
    if args.format == "json":
        _write_stdout(findings_to_json(ir, findings, verdict))
    else:
        _write_stdout(render(ir, findings, verdict, config.fail_on))
    return 1 if verdict == "block" else 0


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
        f'fingerprint = "{args.fingerprint}"\n'
        f'rule = "{args.fingerprint.split("/", 1)[0]}"\n'
        f'reason = "{args.reason.replace(chr(34), chr(39))}"\n'
        f'author = "{args.author}"\n'
        f'created = "{today.isoformat()}"\n'
        f'expires = "{expires}"\n'
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
    elif argv[0] not in ("check", "allow", "-h", "--help", "--version"):
        argv = ["check", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            return _cmd_check(args)
        if args.command == "allow":
            return _cmd_allow(args)
        parser.print_help()
        return 2
    except GitError as exc:
        print(f"greenwash engine error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"greenwash engine error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
