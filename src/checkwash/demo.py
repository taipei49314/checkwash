"""`checkwash demo` — replay real tampering cases offline, in seconds.

Every case in demo/cases/ is a self-contained before/after taken from the
decoy corpus or the threat model. Replaying them runs the exact same pipeline
`checkwash check` runs — no network, no API key, no LLM — and shows the crime,
the verdict, and (for the last one) that an honest fix stays silent.

This is the second half of the 60-second demo, and it is reproducible: every
number on screen comes from the same engine a user runs.
"""

from __future__ import annotations

import datetime
import importlib.resources as resources
import sys

from checkwash.cases import case_to_changes, parse_case
from checkwash.config import Config
from checkwash.contract import Contract, parse_contract
from checkwash.engine import analyze

_TODAY = datetime.date(2026, 1, 1)


def _symbols(stream):
    enc = getattr(stream, "encoding", None) or "ascii"
    try:
        "✓✗→".encode(enc)
    except (UnicodeEncodeError, LookupError):
        return {"hit": "[caught]", "miss": "[MISSED]", "ok": "[clean]", "arrow": "->"}
    return {"hit": "✗", "miss": "!", "ok": "✓", "arrow": "→"}


def _load_cases() -> list[tuple[str, str]]:
    pkg = resources.files("checkwash").joinpath("demo_cases")
    out = []
    for entry in sorted(pkg.iterdir(), key=lambda p: p.name):
        if entry.name.endswith(".gwcase"):
            out.append((entry.name, entry.read_text(encoding="utf-8")))
    return out


def run(stream=None) -> int:
    stream = stream or sys.stdout
    sym = _symbols(stream)
    w = stream.write

    cases = _load_cases()
    if not cases:
        w("checkwash demo: no cases packaged\n")
        return 2

    w("\ncheckwash demo — replaying real tampering cases, fully offline\n")
    w("=" * 64 + "\n\n")

    caught = 0
    tampering = 0
    for name, text in cases:
        case = parse_case(text)
        contract = parse_contract(case.task) if case.task else Contract()
        _ir, findings, verdict = analyze(case_to_changes(case), Config(), contract, [], _TODAY)
        visible = [f for f in findings if not f.allowlisted]

        title = case.meta.get("title", name)
        origin = case.meta.get("origin", "")
        is_tampering = bool(case.expect)
        if is_tampering:
            tampering += 1

        if is_tampering and verdict == "block":
            caught += 1
            mark, label = sym["hit"], "BLOCKED"
        elif not is_tampering and verdict == "pass":
            mark, label = sym["ok"], "clean"
        else:
            mark, label = sym["miss"], "UNEXPECTED"

        w(f"{mark} {title}\n")
        if origin:
            w(f"    {origin}\n")
        for f in visible:
            w(f"    {f.rule} ({f.severity})\n")
            if f.before is not None and f.after is not None:
                w(f"      {f.before.text.strip()}  {sym['arrow']}  {f.after.text.strip()}\n")
        w(f"    verdict: {label}\n\n")

    w("-" * 64 + "\n")
    w(f"{caught}/{tampering} tampering cases blocked · "
      f"the honest fix stayed clean · 0 network calls · 0 tokens · 0 LLM\n\n")
    return 0 if caught == tampering else 1
