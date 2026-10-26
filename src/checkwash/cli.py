"""checkwash CLI.

    checkwash check [BASE..HEAD] [--task FILE] [--format term|json|sarif]
                    [--fail-on SEV] [--emit-ir] [--repo PATH] [--coverage-report FILE]
    checkwash allow FINGERPRINT --reason "..." [--expires YYYY-MM-DD] [--repo PATH]
    checkwash bench [--local] [--corpus DIR] [--run-sweep]

`--repo` (default: the current directory) may be any directory of a Git work
tree. `check`, `sweep`, `allow`, `doctor` and the repository-reading `quality`
modes run from that repository's root and say so in one stderr line when it
is not `--repo` itself (#416). `hook install` writes under `--repo` as given.

Exit codes (SPEC §9): 0 pass, 1 block, 2 engine error. `check --format
hook-json` exits 0 on a verdict and on an engine error: its JSON carries a
block, or the engine error as a non-blocking `systemMessage` (#414). One
engine error blocks there instead: a size refusal of a path in the verdict
diff whose head or worktree side is over the limit (#456). `--format json`
keeps exit 2 on a size refusal of the analysis, and its stdout names the
refused side in an `unread` entry, outside any findings document (#454). With
`--hook-input stdin` (the managed Stop hook) it also reads the session's start
from what `hook session-start` (the managed SessionStart hook) recorded, which
prints nothing and always exits 0 (#418).
`bench` uses 0 / 2 only — it never reports a verdict.
"""

from __future__ import annotations

import argparse
import datetime
import os
import posixpath
import sys
from dataclasses import dataclass

from checkwash import __version__
from checkwash.allowlist import AllowEntry, MAX_EXPIRY_DAYS, fingerprint_diagnostics, fingerprint_issue, load_allowlist, namespace_diagnostics
from checkwash.change import SourceOverLimit, UnreadSide
from checkwash.config import CONFIG_DIRS, SEVERITY_ORDER, load_config, read_base_config_file, resolve_config_file
from checkwash.contract import Contract, contract_diagnostics, parse_contract
from checkwash.deps import MANIFESTS, SKIPPABLE_OVERSIZED, parse_manifest, project_names
from checkwash.engine import analyze
from checkwash.pyenv import known_baseline
from checkwash.gitio import (
    GitError,
    GitRootUnresolved,
    GitSourceOverLimit,
    RepositoryRoot,
    base_alias,
    grep_head_paths,
    list_range_changes,
    list_session_changes,
    list_worktree_changes,
    merge_base,
    read_base_file,
    resolve_repository_root,
    rev_parse,
    resolve_commit,
    session_merge_base,
)
from checkwash.gitio.snapshot import GitSnapshot, TreeAlias, WorkingTreeSnapshot
from checkwash.gitio.pytest_configs import PairedPytestConfigs
from checkwash.report.jsonout import findings_to_json, ir_to_json, size_refusal_to_json
from checkwash.report.sarif import findings_to_sarif
from checkwash.report.context import ReportContext
from checkwash.report.coverage import coverage_to_json
from checkwash.report.term import render
from checkwash.report.textio import write_text
from checkwash.session import HookInput, read_hook_input, record_session_start, session_base
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
    """Human report: preserve evidence with escapes when the encoding needs it."""
    write_text(text)


def _range_usage_error(spec: str) -> str | None:
    """The usage error `_cmd_check` gives a malformed range, or None (#416).

    `main()` checks the string before the root lookup, so a malformed range
    stays a usage error with exit 2 in every format, as before #416. Where the
    lookup fails it would otherwise be the lookup's engine error, which
    hook-json reports with exit 0 (#414). `_cmd_check` keeps its own checks.
    """
    if "..." in spec:
        left, _, right = spec.partition("...")
        if not left or not right.lstrip("."):
            return f"error: range must be BASE...HEAD, got {spec!r}\n"
        return None
    base, dots, head = spec.partition("..")
    if not dots or not base or not head:
        return f"error: range must be BASE..HEAD, got {spec!r}\n"
    return None


@dataclass
class _Window:
    """Where the Stop hook's session started, for `--hook-input stdin` (#418).

    `base` is the commit policy is read from and the session's commits are
    diffed from: the recorded session base when HEAD descends from it, else
    their merge base. It is None when there is no usable record; `missing`
    then says why, and the run is today's HEAD..worktree check.
    """

    head: str
    base: str | None = None
    missing: str | None = None


def _session_window(repo: str, hook_input: HookInput) -> _Window:
    head = resolve_commit(repo, "HEAD")
    if hook_input.data is None:
        return _Window(head, missing="the hook input could not be read")
    if hook_input.session_id is None:
        return _Window(head, missing="the hook input carries no session id")
    recorded = session_base(repo, hook_input)
    if recorded is None:
        return _Window(head, missing=(
            "no start was recorded for this session (a resumed session, or no SessionStart "
            "hook; `checkwash hook install` adds it)"
        ))
    try:
        base = session_merge_base(repo, recorded, head)
    except GitError as exc:
        # A record naming a commit Git cannot walk is no usable record: the
        # verdict is today's, never an engine error the record chose.
        return _Window(head, missing=f"the commit this session started from could not be compared with HEAD ({exc})")
    if base is None:
        return _Window(head, missing="HEAD shares no history with the commit this session started from")
    return _Window(head, base=base)


@dataclass
class _Run:
    ir: object
    findings: list
    verdict: str
    config: object
    diagnostics: list[str]
    report_context: ReportContext
    changes: list


def _task_alias_error(task: str, rel: str, alias: TreeAlias) -> str:
    """The engine error for a root `--task` path the base tree holds by another name (#500)."""
    entry = alias.entry if alias.entry.isprintable() else repr(alias.entry)
    if alias.whole:
        return (f"--task {task} maps to {rel}, which the base tree holds only in another case, "
                f"as {entry}; name the task file as the base tree spells it")
    return (f"--task {task} maps to {rel}, but {entry} in the base tree is {alias.kind}, not a "
            "directory; name the task file by its path in the base tree")


def _analyse(args: argparse.Namespace, changes, config_side: str, *, base_label: str, head_label: str,
             head_reader, head_searcher, root_snapshot, pytest_configs, quiet: bool = False) -> _Run | int:
    """One analysis of `changes` with policy read from `config_side`.

    `quiet` leaves stderr to an earlier run with the same `config_side`, so a
    session's second leg (#418) does not repeat its diagnostics, and makes
    the early returns write nothing to stdout either: the first leg owns the
    one JSON object the hook prints.
    """
    repo = args.repo

    def advise(text: str) -> None:
        if not quiet:
            write_text(text, sys.stderr)

    config_path, config_data = read_base_config_file(repo, config_side, "config.toml")
    config, config_error, config_warnings = load_config(config_data, path=config_path)
    if args.fail_on:
        config.fail_on = args.fail_on
    allow_path, allow_data = read_base_config_file(repo, config_side, "allow.toml")
    allow_entries, allow_error = load_allowlist(allow_data, path=allow_path)
    # Unsupported exemptions are not TOML parse errors. Keep machine stdout
    # intact and report the ignored base-side keys on stderr in every format.
    for message in fingerprint_diagnostics(allow_entries):
        advise(f"checkwash: {allow_path}: ignored exemption: {message}\n")
    for message in namespace_diagnostics(allow_entries):
        advise(f"checkwash: {allow_path}: exemption warning: {message}\n")
    # A config that silently fails to parse used to revert a hardened gate to
    # defaults with no diagnostic anywhere (confirmed red-team finding).
    # Value-level warnings are visible in the same channels but never fatal:
    # the one value a warning can concern (on_engine_error itself) must not
    # become the engine error it describes (audit 2026-08-19).
    errors = [e for e in (config_error, allow_error) if e]
    diagnostics = errors + config_warnings
    for message in diagnostics:
        advise(f"checkwash: {message}\n")
    if errors and config.on_engine_error == "block":
        # The diagnostics are already on stderr; hook-json warns instead (#414).
        if quiet:
            return 2
        return _hook_not_analysed("; ".join(errors)) if _hook_json(args) else 2

    contract = Contract()
    if args.task:
        # The contract carries oracle_freeze and the scope globs, so reading
        # it from the head side let a diff edit TASK.md to disarm E2 and E7
        # for itself. Same rule as config and the allowlist: base side wins
        # (SPEC §1). The working-tree copy is a fallback only at the root,
        # and only when the base tree holds nothing the path can stand for
        # on disk (#500). Nothing checks that the file is untracked.
        prefix = getattr(args, "repo_prefix", "")
        if prefix:
            # Re-rooted (#416): relative to the directory `--repo` named, then
            # into the root with Git's prefix, lexically. Never realpath: a
            # head-side symlink at the task path would choose which base file
            # supplies the contract, or hand the fallback attacker bytes.
            rel = posixpath.normpath(prefix + os.path.relpath(args.task, args.repo_given).replace("\\", "/"))
        else:
            rel = os.path.relpath(args.task, repo).replace("\\", "/")
        data = read_base_file(repo, config_side, rel)
        if data is not None:
            task_text = data.decode("utf-8", errors="replace")
            contract = parse_contract(task_text)
        elif prefix:
            # Git spells the prefix as the directory is on disk. On a
            # case-insensitive checkout the head chooses that spelling (`PKG/`
            # for the base's `pkg/`), so the mapped path can miss the base
            # contract while the working-tree copy is the head's. A symlink or
            # junction on the way to `--repo` moves the prefix the same way.
            # From a subdirectory a base miss is therefore an engine error
            # (owner's ruling on #416, 2026-10-15).
            if quiet:
                return 2
            return _engine_error(
                args,
                f"--task {args.task} maps to {rel}, which the base tree does not hold; "
                "from a subdirectory only the base copy is read, so run from the "
                "repository root to use an untracked task file",
            )
        else:
            # At the root Git reads no path through a tree entry that is not
            # a directory and matches names byte for byte, while the working
            # tree follows a symlink and, on a case-insensitive checkout,
            # matches any case. So `ci/TASK.md` over a committed directory
            # symlink `ci`, or `task.md` for a committed `TASK.md`, misses the
            # base contract and opens the head's. Such a path is an engine
            # error naming the base entry (#500); the fallback stays for a
            # task file the base really lacks, with one stderr line.
            alias = base_alias(repo, config_side, rel)
            if alias is not None:
                if quiet:
                    return 2
                return _engine_error(args, _task_alias_error(args.task, rel, alias))
            with open(args.task, encoding="utf-8") as fh:
                task_text = fh.read()
                contract = parse_contract(task_text)
            if not quiet:
                _advise(f"checkwash: --task {args.task}: the base tree has no file at {rel}, so the "
                        "contract is read from the working-tree copy, which the change controls; "
                        "commit the task file to read it from the base\n")
        task_source = "BASE" if data is not None else "working-tree fallback"
        for message in contract_diagnostics(task_text):
            advise(f"checkwash: --task {rel!r} ({task_source}): {message}\n")

    known_modules: set[str] | None = None
    declared: set[str] = set()
    # The project's own name, kept apart from what it depends on: "declared"
    # answers yes for `flask` inside flask, and a first-party check built on it
    # would deny the first party.
    self_modules: set[str] = set()
    found_manifest = False
    for manifest in MANIFESTS:
        try:
            data = read_base_file(repo, config_side, manifest)
        except GitSourceOverLimit as exc:
            # A root lockfile is read on every run, touched or not. Over the
            # limit, it is skipped as if absent, with a note (#415).
            if manifest not in SKIPPABLE_OVERSIZED:
                raise
            advise(f"checkwash: skipped {exc.unread.described()}: over the source byte limit; "
                   "the run continues without its declared modules\n")
            continue
        if data is None:
            continue
        found_manifest = True
        declared |= parse_manifest(manifest, data)
        self_modules |= project_names(manifest, data)
    if found_manifest:
        known_modules = known_baseline() | declared

    report_context = ReportContext(collect_locations=args.format == "sarif")
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
        report_context=report_context,
        root_reader=root_snapshot.read,
        root_searcher=root_snapshot.search,
        root_path_lister=root_snapshot.list_paths,
        root_batch_reader=root_snapshot.read_many,
        pytest_configs=pytest_configs,
    )
    return _Run(ir, findings, verdict, config, diagnostics, report_context, changes)


def _visible(run: _Run) -> list:
    """Findings at or above `fail_on` that no exemption covers."""
    threshold = SEVERITY_ORDER[run.config.fail_on]
    return [f for f in run.findings if not f.allowlisted and SEVERITY_ORDER[f.severity] >= threshold]


def _session_note(args: argparse.Namespace, window: _Window, readers: dict) -> str | None:
    """The non-blocking note on what the session's commits hold, for a pass (#418).

    On a pass the first leg reports nothing at or above `fail_on`, so every
    such finding of the second leg is one only the session's window holds;
    nothing is matched away. A block leaves the note to a later Stop, so the
    second leg never delays a block.
    """
    if window.missing is not None:
        return ("checkwash: commits made during this session were not analysed, because "
                f"{window.missing}. The working tree was checked against HEAD.")
    if window.base == window.head:
        return None
    unread = "checkwash: commits made during this session were not analysed. "
    try:
        leg = _analyse(args, list_session_changes(args.repo, window.base), window.base,
                       base_label=rev_parse(args.repo, window.base), head_label="worktree",
                       quiet=True, **readers)
    except Exception as exc:  # noqa: BLE001 - leg 1's verdict stands; say what was not analysed
        return unread + f"Engine error: {type(exc).__name__}: {exc}"
    if isinstance(leg, int):
        return unread + "Their policy could not be read."
    found = sorted(_visible(leg), key=lambda f: -SEVERITY_ORDER[f.severity])
    if not found:
        return None
    listed = "; ".join(
        f"{f.rule} {f.path}" + (f" :: {f.unit}" if f.unit else "") + f" — {f.message}" for f in found[:5]
    ) + (f"; and {len(found) - 5} more" if len(found) > 5 else "")
    return (f"checkwash: commits made during this session hold {len(found)} finding(s) at or above "
            f"fail_on that this Stop does not block; the required check will judge them: {listed}.")


def _cmd_check(args: argparse.Namespace) -> int:
    repo = args.repo
    pytest_configs = None
    window = None
    if getattr(args, "hook_input", None) and not args.emit_ir:
        hook_input = read_hook_input(sys.stdin)
        if hook_input is not None:
            window = _session_window(repo, hook_input)
    if args.range:
        if "..." in args.range:
            # Three-dot means merge-base(A,B)..B — the standard PR-diff
            # idiom. Silently downgrading it to two dots pulled base-branch
            # prod commits into the diff, which disarmed E1 on every open PR
            # whose base branch had moved (confirmed red-team finding).
            left, _, right = args.range.partition("...")
            right = right.lstrip(".")
            if not left or not right:
                write_text(f"error: range must be BASE...HEAD, got {args.range!r}\n", sys.stderr)
                return 2
            left, head = resolve_commit(repo, left), resolve_commit(repo, right)
            base = merge_base(repo, left, head)
        elif ".." in args.range:
            base, _, head = args.range.partition("..")
        else:
            write_text(f"error: range must be BASE..HEAD, got {args.range!r}\n", sys.stderr)
            return 2
        if not base or not head:
            write_text(f"error: range must be BASE..HEAD, got {args.range!r}\n", sys.stderr)
            return 2
        base, head = resolve_commit(repo, base), resolve_commit(repo, head)
        changes = list_range_changes(repo, base, head)
        base_label = rev_parse(repo, base)
        head_label = rev_parse(repo, head)
        config_side = base

        # D6 resolves skip-condition constants imported from files outside
        # the diff; the head snapshot is where those files live.
        head_snapshot = GitSnapshot(repo, head, side="head")
        pytest_configs = PairedPytestConfigs(GitSnapshot(repo, base, side="base"), head_snapshot)
        head_reader = head_snapshot.read
        root_snapshot = head_snapshot

        def head_searcher(needles: list[str], _rev: str = head) -> list[str]:
            return grep_head_paths(repo, _rev, needles)
    else:
        base = resolve_commit(repo, "HEAD") if window is None else window.head
        changes = list_worktree_changes(repo, base=base)
        base_label = rev_parse(repo, base)
        head_label = "worktree"
        # In a recorded session, policy comes from where it started: what the
        # agent commits during the session governs the next one (#418).
        config_side = base if window is None or window.base is None else window.base

        worktree_snapshot = WorkingTreeSnapshot(repo)
        head_reader = worktree_snapshot.read
        head_searcher = worktree_snapshot.search
        root_snapshot = worktree_snapshot

    readers = {"head_reader": head_reader, "head_searcher": head_searcher,
               "root_snapshot": root_snapshot, "pytest_configs": pytest_configs}
    try:
        run = _analyse(args, changes, config_side, base_label=base_label, head_label=head_label, **readers)
    except SourceOverLimit as exc:
        # Only a head or worktree side of the verdict diff blocks the stop
        # (#456); the session-commits analysis keeps its note. Json keeps
        # exit 2 and names the refused side (#454 (d)). Any other size
        # refusal reaches main()'s #414 path, as every other engine error does.
        side = _verdict_side_over_limit(changes, exc.unread) if _hook_json(args) else None
        if side is not None:
            # The stderr line every format writes; never on stdout ahead of the JSON.
            _advise(f"checkwash engine error: {type(exc).__name__}: {exc}\n")
            return _hook_size_block(side)
        if args.format == "json" and not args.emit_ir:
            return _json_size_refusal(exc)
        raise
    if isinstance(run, int):
        return run
    ir, findings, verdict, config = run.ir, run.findings, run.verdict, run.config
    diagnostics, report_context = run.diagnostics, run.report_context

    # Sides over the source byte limit that no detector must read (#415).
    # Json, sarif and term name them too, sorted; hook-json and --emit-ir
    # keep their bytes (#454 ruling, item 6). The notes keep the diff's order.
    unread_sides = [side for change in changes for side in change.unread]
    for side in unread_sides:
        write_text(f"checkwash: {side.note()}\n", sys.stderr)
    for gap in report_context.coverage_gaps:
        write_text(f"checkwash: {gap.message()}\n", sys.stderr)
    if args.coverage_report:
        if args.coverage_report == "-":
            write_text("error: --coverage-report requires a file path, not stdout\n", sys.stderr)
            return 2
        with open(args.coverage_report, "w", encoding="utf-8", newline="\n") as report:
            report.write(coverage_to_json(ir, report_context))

    if args.emit_ir:
        _write_machine(ir_to_json(ir))
        return 0
    if args.format == "json":
        _write_machine(findings_to_json(ir, findings, verdict, diagnostics, unread=unread_sides))
    elif args.format == "sarif":
        _write_machine(findings_to_sarif(ir, findings, report_context, unread=unread_sides))
    elif args.format == "hook-json":
        # Claude Code Stop-hook protocol: JSON on stdout carries the decision,
        # exit 0 either way (non-zero would read as a hook failure).
        import json as _json

        payload: dict[str, str] = {}
        if verdict == "block":
            visible = _visible(run)
            head = visible[0] if visible else None
            reason = "checkwash: " + (
                f"{len(visible)} finding(s) blocking. "
                + (f"{head.rule} {head.path}"
                   + (f" :: {head.unit}" if head.unit else "")
                   + f" — {head.message}. " if head else "")
                + "Fix the production code, or record a reviewed exemption: "
                + (f'checkwash allow "{head.fingerprint}" --reason "..."' if head else "")
            )
            if window is not None and window.base is not None and window.base != window.head:
                reason = reason.rstrip(": ") + (
                    ". An exemption, config change or hook upgrade committed during this "
                    "session applies from the next session; /clear starts one."
                )
            payload = {"decision": "block", "reason": reason}
        elif window is not None:
            # The session note is for a pass only (#418 ruling 2 and 4).
            note = _session_note(args, window, readers)
            if note is not None:
                payload["systemMessage"] = note
        _write_machine((_json.dumps(payload) if payload else "{}") + "\n")
        return 0
    else:
        _write_term(render(
            ir, findings, verdict, config.fail_on, errors=diagnostics,
            ledger_path=resolve_config_file(repo, "allow.toml"),
            context=report_context, unread=unread_sides,
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
# Template only: no files were written and no hook was installed.
# Save or merge this into .pre-commit-config.yaml in your repository.
# Install the pre-commit runner in your development environment, then run:
#   pre-commit install
#   pre-commit run checkwash --all-files
# --repo does not change this print-only operation.
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
    if args.agent == "pre-commit":
        if args.local:
            write_text("error: --local applies to --agent claude-code only\n", sys.stderr)
            return 2
        # Nothing to write for them — their config is theirs; print the block.
        sys.stdout.write(_PRECOMMIT_SNIPPET.format(version=__version__))
        return 0

    from checkwash.hooks import HookInstallError, install_claude

    try:
        message = install_claude(args.repo, args.local)
    except HookInstallError as exc:
        write_text(f"error: {exc}\n", sys.stderr)
        return 2
    _write_term(message)
    return 0


def _cmd_session_start(args: argparse.Namespace) -> int:
    """The managed SessionStart hook (#418): record HEAD, print nothing.

    Claude Code adds a SessionStart hook's stdout to the model's context, so
    nothing is ever printed there, and a session start never fails on
    checkwash: every outcome exits 0.
    """
    try:
        _reroot(args, required=False)
        record_session_start(args.repo, read_hook_input(sys.stdin))
    except Exception:  # noqa: BLE001 - a session start must never fail on checkwash
        pass
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
    from checkwash.quality.model import ALLOW_PATH as QUALITY_ALLOW_PATH, RULES as QUALITY_RULES

    if args.fingerprint.split("/", 1)[0] in QUALITY_RULES:
        write_text(
            f"error: quality fingerprints do not belong in check's allow.toml; "
            f"review {QUALITY_ALLOW_PATH} with its target_id and quality exemption schema. "
            "Only supported strong quality findings can be exempted; see docs/quality.md.\n",
            sys.stderr,
        )
        return 2
    issue = fingerprint_issue(args.fingerprint)
    if issue is not None:
        write_text(f"error: {issue}\n", sys.stderr)
        return 2
    for message in namespace_diagnostics([AllowEntry(args.fingerprint, "", "", "", "", "")]):
        write_text(f"warning: {message}\n", sys.stderr)
    if not args.reason.strip():
        write_text("error: --reason must not be empty\n", sys.stderr)
        return 2
    today = _today()
    expires = args.expires or (today + datetime.timedelta(days=90)).isoformat()
    if (datetime.date.fromisoformat(expires) - today).days > MAX_EXPIRY_DAYS:
        write_text(f"error: expiry exceeds {MAX_EXPIRY_DAYS} days\n", sys.stderr)
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
    write_text(f"recorded exemption in {path} (expires {expires}); commit it through review\n")
    return 0


class _ArgumentParser(argparse.ArgumentParser):
    def _print_message(self, message, file=None):
        if message:
            write_text(message, file or sys.stderr)


_REPO_HELP = "any directory of the Git repository (default: .); runs from the repository root"


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="checkwash")
    parser.add_argument("--version", action="version", version=f"checkwash {__version__}")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="analyse a diff for verification-layer tampering")
    check.add_argument("range", nargs="?", help="BASE..HEAD; omit to check HEAD..worktree")
    check.add_argument("--task", help="task manifest file (TASK.md style)")
    check.add_argument("--format", choices=["term", "json", "hook-json", "sarif"], default="term")
    check.add_argument("--fail-on", choices=list(SEVERITY_ORDER), default=None)
    check.add_argument("--emit-ir", action="store_true", help="print the IR JSON and exit")
    check.add_argument("--coverage-report", metavar="FILE", help="write a separate JS assertion-coverage JSON report")
    check.add_argument("--repo", default=".", help=_REPO_HELP)
    check.add_argument(
        "--hook-input", choices=["stdin"], default=None,
        help="read the Claude Code Stop hook input from stdin and check the session's commits too "
             "(only with --format hook-json and no range)",
    )

    quality = sub.add_parser("quality", help="review bounded quality configuration weakening")
    quality.add_argument("range", nargs="?", help="BASE..HEAD, BASE...HEAD, init, doctor, profiles or explain")
    quality.add_argument("rule", nargs="?", help="rule ID for quality explain")
    quality.add_argument("--format", choices=["term", "json", "sarif"], default=None,
                         help="output format (default: JSON for profiles; terminal otherwise)")
    quality.add_argument("--repo", default=".", help=_REPO_HELP + " (not for profiles or explain)")
    quality.add_argument("--root", help="init only: repository-relative target root")
    quality.add_argument("--paths", action="append", help="init only: literal source file or directory ending /; repeatable")
    quality.add_argument("--tool", action="append", choices=["coverage", "ruff", "mypy"], help="init only: requested tool; repeatable")
    quality.add_argument("--details", action="store_true", help="profiles only: include supported settings and qualification receipts")

    sweep_p = sub.add_parser(
        "sweep", help="measure finding rates over a repo's commit history"
    )
    sweep_p.add_argument("revs", nargs="?", default="HEAD", help="rev-list range, e.g. HEAD or main")
    sweep_p.add_argument("--limit", type=int, default=200)
    sweep_p.add_argument("--fail-on", choices=list(SEVERITY_ORDER), default=None)
    sweep_p.add_argument("--repo", default=".", help=_REPO_HELP)

    hook = sub.add_parser("hook", help="integration helpers")
    hook_sub = hook.add_subparsers(dest="hook_command", required=True)
    hook_install = hook_sub.add_parser(
        "install", help="write Claude settings or print a pre-commit template",
        description="For claude-code, write Stop hook settings. For pre-commit, print a YAML template only; save it and run pre-commit install yourself.",
    )
    hook_install.add_argument("--agent", choices=["claude-code", "pre-commit"], required=True)
    hook_install.add_argument(
        "--repo", default=".",
        help="directory whose .claude/ receives the settings, used as given (default: .)",
    )
    hook_install.add_argument(
        "--local",
        action="store_true",
        help="write machine-local .claude/settings.local.json instead of shared settings.json; this installer does not configure Git ignore",
    )
    hook_session = hook_sub.add_parser(
        "session-start", help="record where a Claude Code session starts (the managed SessionStart hook)",
        description="Read the SessionStart hook input from stdin and record HEAD as the session's base, "
                    "once per session. Prints nothing and always exits 0.",
    )
    hook_session.add_argument("--repo", default=".", help=_REPO_HELP)

    sub.add_parser("demo", help="replay real tampering cases offline")

    doctor = sub.add_parser(
        "doctor", help="is this installation able to block anything?"
    )
    doctor.add_argument("--repo", default=".", help=_REPO_HELP + "; outside Git, the directory as given")

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
    allow.add_argument("--repo", default=".", help=_REPO_HELP + "; outside Git, the directory as given")
    return parser


_SUBCOMMANDS = ("check", "allow", "sweep", "hook", "demo", "doctor", "bench", "quality")


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


def _reroot(args: argparse.Namespace, *, required: bool, **lookup) -> None:
    """Point `args.repo` at the repository root when it names a subdirectory (#416).

    For a `required` command (check, sweep) a GitError reaches the engine
    error path; the others keep `--repo` as given when Git cannot answer,
    outside Git or with no git binary, as they ran before. When Git has
    named a subdirectory but not its root, one stderr line says so and why;
    stdout and the exit code are unchanged. `repo_given` and `repo_prefix`
    keep what a `--task` path is mapped from. `lookup` goes to
    `resolve_repository_root`: doctor's environment, timeout and stdin
    (#416, #500).
    """
    given = args.repo
    try:
        root = resolve_repository_root(given, **lookup)
    except GitError as exc:
        if required:
            raise
        if isinstance(exc, GitRootUnresolved):
            reason = " ".join(str(exc).splitlines())
            _advise(f"checkwash: could not resolve the repository root: {reason}; using --repo as given\n")
        root = RepositoryRoot(given)
    args.repo, args.repo_given, args.repo_prefix = root.path, given, root.prefix
    if root.prefix:
        _advise(_root_note(root))


def _advise(line: str) -> None:
    """Write an advisory stderr line that can never reach stdout or the exit code (#416).

    `write_text` falls back to stdout when `sys.stderr` is None (fd 2 closed,
    pythonw), which would land ahead of a JSON or SARIF report, and a broken
    stderr pipe must not turn a run into an engine error.
    """
    if sys.stderr is None:
        return
    try:
        write_text(line, sys.stderr)
    except (OSError, ValueError):
        pass


def _root_note(root: RepositoryRoot) -> str:
    """The one stderr line of a re-rooted run (#416).

    It names the root, and every `.checkwash/` or `.greenwash/` directory from
    the invoked directory up to the root as not read: only the root's policy
    applies, and a stricter one below it must not be dropped without a word
    (SPEC §9). It never changes the exit code. In hook
    mode the working tree is the agent's, and an engine error is a
    non-blocking "not analysed" there (#414).
    """
    parts = root.prefix[:-1].split("/")
    unread = [
        "/".join(parts[:end]) + f"/{name}/"
        for end in range(len(parts), 0, -1)
        for name in CONFIG_DIRS
        if os.path.isdir(os.path.join(root.path, *parts[:end], name))
    ]
    line = f"checkwash: using the repository root {root.path}, not its subdirectory {root.prefix}"
    if unread:
        line += f"; not read: {', '.join(unread)} (only the root's .checkwash/ or .greenwash/ applies)"
    return line + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["check"]
    # Every subcommand must be listed here as well as in the parser: an
    # unlisted name is silently reinterpreted as a `check` range, so a typo'd
    # or newly added command reports a verdict instead of an error.
    elif argv[0] not in (
        "check", "allow", "sweep", "hook", "demo", "doctor", "bench", "quality",
        "-h", "--help", "--version",
    ):
        hint = _closest_command(argv[0])
        if hint:
            write_text(
                f"error: unknown command {argv[0]!r}. Did you mean {hint!r}?\n",
                sys.stderr,
            )
            return 2
        argv = ["check", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            usage = _range_usage_error(args.range) if args.range else None
            if args.hook_input and (args.format != "hook-json" or args.range):
                usage = "error: --hook-input stdin requires --format hook-json and no range\n"
            if usage:
                write_text(usage, sys.stderr)
                return 2
            _reroot(args, required=True)
            return _cmd_check(args)
        if args.command == "quality":
            from checkwash.quality.cli import run as run_quality

            if args.format is None:
                args.format = "json" if args.range == "profiles" else "term"
            # profiles and explain read no repository, so they never ask Git.
            # Elsewhere an unanswered root keeps `--repo`, and quality's own
            # JSON error reporting applies as before (#416).
            if args.range not in ("profiles", "explain"):
                _reroot(args, required=False)
            output, code = run_quality(args, _today())
            (_write_term if args.format == "term" else _write_machine)(output)
            return code
        if args.command == "allow":
            # Outside Git, or with no answer from it, the ledger stays under
            # `--repo` as given, as before (#416).
            _reroot(args, required=False)
            return _cmd_allow(args)
        if args.command == "hook":
            # The subparser is required, so argparse has already rejected a
            # missing subcommand with usage on stderr and exit 2. This used to
            # print `hook --help` instead, which argparse exits 0 for, so a CI
            # step that omitted `install` reported success (issue #70).
            # Settings are written under `--repo` as given, never re-rooted.
            if args.hook_command == "session-start":
                return _cmd_session_start(args)
            return _cmd_hook_install(args)
        if args.command == "sweep":
            _reroot(args, required=True)
            result = sweep(args.repo, args.revs, args.limit, _today(), args.fail_on)
            _write_machine(result.to_json())
            return 0
        if args.command == "demo":
            from checkwash.demo import run as run_demo

            return run_demo()
        if args.command == "doctor":
            import subprocess

            from checkwash.doctor import QUERY_TIMEOUT, discovery_env, run as run_doctor

            # Doctor's own sanitized Git environment, or the caller's GIT_DIR
            # could name a repository its later queries never see (#416). Its
            # own timeout and no stdin too, so a Git that hangs stalls the lookup
            # 5 seconds per query (about 10 seconds from a subdirectory) (#500).
            _reroot(args, required=False, env=discovery_env(), timeout=QUERY_TIMEOUT,
                    stdin=subprocess.DEVNULL)
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
        return _engine_error(args, str(exc))
    except Exception as exc:  # noqa: BLE001 - crash must never read as a verdict
        # Exit 1 means "block" (SPEC §9); an unhandled traceback exiting 1
        # is indistinguishable from a real finding for CI (confirmed
        # red-team finding). Engine errors are 2, except in hook-json mode.
        return _engine_error(args, f"{type(exc).__name__}: {exc}")


def _engine_error(args: argparse.Namespace, detail: str) -> int:
    """Report an engine error: exit 2, or the hook-json warning (#414)."""
    write_text(f"checkwash engine error: {detail}\n", sys.stderr)
    return _hook_not_analysed(detail) if _hook_json(args) else 2


def _hook_json(args: argparse.Namespace) -> bool:
    return (getattr(args, "command", None) == "check" and getattr(args, "format", None) == "hook-json"
            and not getattr(args, "emit_ir", False))


def _hook_not_analysed(detail: str) -> int:
    """A non-blocking hook-json payload for an engine error (#414).

    A Claude Code Stop hook that exits 2 blocks the stop and hands stderr to
    the agent, which cannot fix an engine error and would loop on it. The
    hook is an author-side check; the required CI check remains the gate. So
    `check --format hook-json` exits 0 with a JSON payload whose
    `systemMessage` tells the user the change was not analysed and why, and
    carries no `decision`, so the agent may stop. Every other mode keeps 2.
    The one engine error that blocks the stop instead is `_hook_size_block`'s
    (#456).
    """
    import json as _json

    message = ("checkwash: this change was not analysed, so it was neither passed nor blocked. "
               f"Engine error: {detail}")
    try:
        _write_machine(_json.dumps({"systemMessage": message}, ensure_ascii=False, sort_keys=True) + "\n")
    except (OSError, ValueError):
        return 2
    return 0


def _verdict_side_over_limit(changes: list, refused: UnreadSide) -> UnreadSide | None:
    """The head or worktree side over the limit of the change `refused` is from (#456).

    `changes` is the diff that decides the verdict. A refusal names one side
    of a change in it, its first unread side and so the base side when both
    are, so the change is judged on all its unread sides. A side the diff
    does not hold, such as a context read of an unchanged file, matches no
    change, and a change with only its base side over the limit has no such
    side: the session's edit did not make it, and reverting would restore
    the oversized original. Both are None. (A root manifest, config,
    exemption list or task file that `_analyse` reads first refuses with a
    `GitSourceOverLimit`, a `GitError`, which never reaches here; a base side
    the engine reads for a change in the diff does, and is judged as that
    change is.)
    """
    for change in changes:
        if refused in change.unread:
            return next((side for side in change.unread if side.side in ("head", "worktree")), None)
    return None


def _json_size_refusal(exc: SourceOverLimit) -> int:
    """`--format json` on a size refusal of the analysis: exit 2, naming the side (#454 (d)).

    The run stopped before any finding or verdict, so the change under
    review was not analysed. Stdout says so explicitly instead of staying
    empty: `size_refusal_to_json` writes the findings JSON's `unread` entry
    for the side the refusal names, outside any findings document. stderr
    keeps the one engine-error line `main()` writes for the refusal in every
    other format. Term, sarif, `--emit-ir` and other engine errors keep an
    empty stdout. So does a root manifest, config, exemption list or task
    file over the limit at the base: it is read inside the guarded `_analyse`
    call, but refuses as a `GitSourceOverLimit`, a `GitError` and not a
    `SourceOverLimit`, which the `except SourceOverLimit` clause does not catch.
    """
    _advise(f"checkwash engine error: {type(exc).__name__}: {exc}\n")
    try:
        _write_machine(size_refusal_to_json(exc.unread))
    except (OSError, ValueError):
        pass
    return 2


def _hook_size_block(side: UnreadSide) -> int:
    """The hook-json block for a size refusal of the change itself (#456).

    A path in the verdict diff that the analysis must read has its head or
    worktree side over the source byte limit, so the change was not
    analysed. That side is usually the session's own edit, and one edit
    removes it, so unlike the other engine errors (#414) it blocks the stop,
    on every stop, as a finding does. No exemption covers a refusal, so the
    reason does not offer `checkwash allow`. It does not say what CI makes of
    the change: that depends on the CI's version, and an untracked file never
    reaches CI. Every other mode keeps exit 2.
    """
    import json as _json

    reason = ("checkwash: this change was not analysed, so the stop is blocked. A file checkwash must "
              f"read is over the source byte limit: {side.described()}. Shrink or split the file, or "
              "revert your change to it. Do not delete or truncate a file you did not create or change "
              "in this task; tell the user instead.")
    try:
        _write_machine(_json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False, sort_keys=True) + "\n")
    except (OSError, ValueError):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
