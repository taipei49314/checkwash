"""Strict base-only quality target and exemption policy."""
from __future__ import annotations

import datetime
import re
import tomllib

from .model import QualityError, STRONG_RULES, TARGET_ID, Target, safe_path


def toml(data, *, policy=False):
    from decimal import Decimal
    try:
        return tomllib.loads(data.decode("utf-8-sig"), parse_float=Decimal)
    except (UnicodeError, tomllib.TOMLDecodeError, ValueError) as exc:
        raise QualityError("POLICY_INVALID" if policy else "SOURCE_INVALID",
                           "Invalid UTF-8 TOML source", kind="error") from exc


def load_policy(data):
    if data is None:
        return "report", []
    raw = toml(data, policy=True)
    if set(raw) != {"schema_version", "mode", "targets"} or type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise QualityError("POLICY_INVALID", "Expected quality schema 1, mode and targets only", kind="error")
    if raw["mode"] not in {"report", "enforce"}:
        raise QualityError("POLICY_INVALID", "Invalid quality mode", kind="error")
    rows = raw["targets"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 32:
        raise QualityError("POLICY_INVALID", "Expected 1 to 32 quality targets", kind="error")
    targets, ids = [], set()
    required = {"id", "tool", "root", "config", "profile", "paths"}
    for row in rows:
        if not isinstance(row, dict) or not required <= set(row) or set(row) - required - {"version_files"}:
            raise QualityError("POLICY_INVALID", "Unknown or missing target key", kind="error")
        if not all(isinstance(row[k], str) for k in required - {"paths"}):
            raise QualityError("POLICY_INVALID", "Target identifiers must be strings", kind="error")
        if not TARGET_ID.fullmatch(row["id"]) or row["id"] in ids or row["tool"] not in {"coverage", "ruff", "mypy"}:
            raise QualityError("POLICY_INVALID", "Invalid or duplicate target identity", kind="error")
        safe_path(row["root"], root=True)
        if row["config"] != "auto":
            safe_path(row["config"])
        for key in ("paths", "version_files"):
            values = row.get(key, [])
            if not isinstance(values, list) or len(values) > 256 or (key == "paths" and not values):
                raise QualityError("POLICY_INVALID", "Expected bounded path list", kind="error")
            for path in values:
                safe_path(path)
                if any(c in path for c in "*?[]{}!"):
                    raise QualityError("POLICY_INVALID", "Target paths do not accept glob syntax", kind="error")
        ids.add(row["id"])
        targets.append(Target(**row))
    return raw["mode"], sorted(targets, key=lambda t: t.id)


def load_exemptions(data, today):
    if data is None:
        return set(), []
    raw = toml(data, policy=True)
    if set(raw) != {"allow"} or not isinstance(raw["allow"], list):
        raise QualityError("POLICY_INVALID", "Expected quality allow entries", kind="error")
    required = {"fingerprint", "rule", "target_id", "reason", "author", "created", "expires"}
    eligible, entries = set(), []
    for row in raw["allow"]:
        if not isinstance(row, dict) or set(row) != required or not all(isinstance(v, str) and v.strip() for v in row.values()):
            raise QualityError("POLICY_INVALID", "Malformed quality exemption", kind="error")
        if row["rule"] not in STRONG_RULES or not TARGET_ID.fullmatch(row["target_id"]):
            raise QualityError("POLICY_INVALID", "Only concrete weakening events can be exempted", kind="error")
        pattern = re.escape(row["rule"] + "/" + row["target_id"] + "/q1:") + r"[0-9a-f]{64}\Z"
        if not re.fullmatch(pattern, row["fingerprint"]):
            raise QualityError("POLICY_INVALID", "Exemption requires a complete content fingerprint", kind="error")
        try:
            created, expires = (datetime.date.fromisoformat(row[k]) for k in ("created", "expires"))
        except ValueError as exc:
            raise QualityError("POLICY_INVALID", "Invalid exemption date", kind="error") from exc
        if not 0 <= (expires - created).days <= 180 or created > today:
            raise QualityError("POLICY_INVALID", "Invalid exemption validity window", kind="error")
        if expires >= today:
            eligible.add(row["fingerprint"])
        entries.append(row)
    return eligible, entries
