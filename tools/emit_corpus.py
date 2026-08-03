"""Emit findings+IR JSON for the whole fixture corpus to stdout.

CI runs this on every OS/Python combination and byte-compares the artifacts:
the cross-platform determinism gate (SPEC §8) is enforced by machines, not
by promises.
"""

import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from greenwash.cases import case_to_changes, parse_case  # noqa: E402
from greenwash.config import Config  # noqa: E402
from greenwash.contract import Contract, parse_contract  # noqa: E402
from greenwash.engine import analyze  # noqa: E402
from greenwash.report.jsonout import findings_to_json, ir_to_json  # noqa: E402

CASES = sorted((pathlib.Path(__file__).resolve().parent.parent / "tests" / "cases").glob("*.gwcase"))
TODAY = datetime.date(2026, 1, 1)


def _write(text: str) -> None:
    """Bytes, never text mode.

    `sys.stdout.write` translates \\n to \\r\\n on Windows, so this harness —
    the one that *proves* the byte-identical claim — emitted different bytes
    on Windows than on POSIX and the CI byte-compare job failed. The product
    path (`cli._write_machine`) always wrote bytes and was never affected;
    this script was the only thing lying.
    """
    data = text.encode("utf-8")
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    buffer.write(data)


def main() -> None:
    for case_path in CASES:
        case = parse_case(case_path.read_text(encoding="utf-8"))
        contract = parse_contract(case.task) if case.task else Contract()
        head = {p: c.encode("utf-8") for p, c in case.head.items()}
        ir, findings, verdict = analyze(
            case_to_changes(case), Config(), contract, [], TODAY,
            head_reader=head.get if head else None,
        )
        _write(f"# {case_path.name}\n")
        _write(findings_to_json(ir, findings, verdict))
        _write(ir_to_json(ir))


if __name__ == "__main__":
    main()
