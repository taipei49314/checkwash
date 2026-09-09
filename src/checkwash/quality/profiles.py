"""Package-owned, content-addressed models. Never load a model from a target."""
from __future__ import annotations

import json
from importlib import resources

from .model import QualityError, digest


def available():
    result = {}
    directory = resources.files("checkwash.quality").joinpath("profile_data")
    if not directory.is_dir():
        return result
    for path in sorted((p for p in directory.iterdir() if p.name.endswith(".json")), key=lambda p: p.name):
        row = json.loads(path.read_text(encoding="utf-8"))
        expected = row.pop("digest")
        if expected != digest(row):
            raise QualityError("SOURCE_INVALID", "Packaged profile digest mismatch", kind="error")
        row["digest"] = expected
        if row["id"] in result:
            raise QualityError("SOURCE_INVALID", "Duplicate packaged profile", kind="error")
        result[row["id"]] = row
    return result


def load(profile_id, tool):
    row = available().get(profile_id)
    if row is None or row["tool"] != tool:
        raise QualityError("UNKNOWN_PROFILE", "No matching package-owned quality profile")
    return row
