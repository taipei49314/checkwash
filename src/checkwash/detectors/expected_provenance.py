"""The helper/loop provenance channel of EXPECTATION_DEFINITION_CHANGED."""

import json

from checkwash.change import EngineError
from checkwash.findings import Evidence, Finding, make_fingerprint


def detect(ir, existing):
    findings = []
    owned = {(finding.path, finding.unit) for finding in existing}
    for file in ir.files:
        if file.role != "test":
            continue
        records = file.expected_provenance_events
        if not isinstance(records, (tuple, list)) or len(records) > 128:
            raise EngineError("invalid expected provenance evidence")
        units = {unit.qualname: unit for unit in file.units}
        for record in records:
            if (not isinstance(record, (tuple, list)) or len(record) != 9
                    or any(not isinstance(record[i], str) or not record[i] for i in (0, 1, 3, 5, 6, 7, 8))
                    or record[6] not in ("Eq", "Is")
                    or any(not isinstance(record[i], (tuple, list)) or len(record[i]) != 2
                           or any(type(offset) is not int or offset < 0 for offset in record[i])
                           or record[i][0] >= record[i][1] for i in (2, 4))):
                raise EngineError("invalid expected provenance evidence record")
            name, old_text, old_span, new_text, new_span, subject, operator, old_expected, new_expected = record
            unit = units.get(name)
            if (file.path, name) in owned or unit is None or unit.before is None or unit.after is None or unit.delta is None:
                continue
            # Already-concrete root-helper projections belong to the ordinary
            # literal detector; do not report the same call-site edit twice.
            before = {a.id: a for a in unit.before.assertions}
            after = {a.id: a for a in unit.after.assertions}
            if any(pair.before_id in before and pair.after_id in after
                   and tuple(before[pair.before_id].span) == tuple(old_span)
                   and tuple(after[pair.after_id].span) == tuple(new_span)
                   and before[pair.before_id].right_value is not None
                   and after[pair.after_id].right_value is not None
                   and before[pair.before_id].right_value != after[pair.after_id].right_value
                   for pair in unit.delta.assertion_pairs):
                continue
            identity = (name, subject, operator, old_expected, new_expected)
            findings.append(Finding(
                rule="EXPECTATION_DEFINITION_CHANGED", severity="warn", path=file.path, unit=name,
                message=(f"{name}: expected provenance changed {old_expected} -> {new_expected} "
                         f"for the same subject/input {subject}; helper or loop substitution keeps the answer visible"),
                before=Evidence(old_text, tuple(old_span)), after=Evidence(new_text, tuple(new_span)),
                fingerprint=make_fingerprint("EXPECTATION_DEFINITION_CHANGED", file.path, name,
                                             json.dumps(identity, ensure_ascii=True, separators=(",", ":"))),
            ))
    return findings
