"""Coverage configuration adapter."""
from __future__ import annotations
import posixpath
import re
from .model import QualityError, inside
from .resolver import attach, boolean, check_dynamic, declarations, integer, resolved_sources, strings
from .snapshot import source
from .scope import scope

def coverage(snapshot, target, side, profile):
    result, raw, path, text = resolved_sources(snapshot, target, side)
    result.declarations = declarations(raw)
    check_dynamic(raw)
    run, report = raw.get("run", {}), raw.get("report", {})
    if not isinstance(run, dict) or not isinstance(report, dict):
        raise QualityError("SOURCE_INVALID", "Coverage run/report must be tables", kind="error")
    threshold = "coverage.report.fail_under"
    number = integer(report.get("fail_under", 0))
    if not 0 <= number <= 100:
        raise QualityError("SOURCE_INVALID", "Coverage threshold must be between 0 and 100", kind="error")
    attach(result, threshold, str(number), path, side, text, "fail_under")
    attach(result, "coverage.context", [str(integer(report.get("precision", 0))),
                                        str(boolean(run.get("branch", False)))], path, side, text, "precision")
    harmless_run = {"branch", "omit", "data_file", "parallel"}
    harmless_report = {"fail_under", "precision", "omit", "show_missing", "skip_covered", "skip_empty", "sort", "format"}
    unknown = (set(run) - harmless_run) | (set(report) - harmless_report) | (set(raw) - {"run", "report", "html", "xml", "json", "lcov"})
    if unknown:
        result.problem("UNSUPPORTED_KEY", "Coverage context includes unsupported settings: " + ", ".join(sorted(unknown)), [threshold, "coverage.context"])
    for stage, table in (("run", run), ("report", report)):
        dimension = "coverage." + stage + ".scope"
        try:
            if unknown:
                raise QualityError("CONTEXT_UNRESOLVED", "Coverage source/include or exclusion context is not qualified")
            value = scope(snapshot, target, table.get("omit", []), profile, result, side, stage)
            attach(result, dimension, value, path, side, text, "omit")
        except QualityError as exc:
            if exc.kind == "error":
                raise
            result.problem(exc.code, str(exc), [dimension])
    return result


