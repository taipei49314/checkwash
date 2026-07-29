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


def main() -> None:
    out = sys.stdout
    for case_path in CASES:
        case = parse_case(case_path.read_text(encoding="utf-8"))
        contract = parse_contract(case.task) if case.task else Contract()
        ir, findings, verdict = analyze(case_to_changes(case), Config(), contract, [], TODAY)
        out.write(f"# {case_path.name}\n")
        out.write(findings_to_json(ir, findings, verdict))
        out.write(ir_to_json(ir))


if __name__ == "__main__":
    main()
