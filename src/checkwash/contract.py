"""Task scope contract (SPEC §5 E2, v1: file globs + oracle_freeze only).

Parses a restricted YAML front-matter subset from TASK.md — deliberately not
a YAML parser: only the `checkwash:` block with `scope.allow` lists and
scalar flags is understood. Intent NLP is out of scope by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Contract:
    present: bool = False
    scope_allow: list[str] = field(default_factory=list)
    oracle_freeze: bool = False
    intent: str = ""


def parse_contract(text: str | None) -> Contract:
    if not text:
        return Contract()
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return Contract()
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return Contract()

    contract = Contract(present=True)
    in_checkwash = False
    in_scope = False
    in_allow = False
    for raw in lines[1:end]:
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        if not stripped or stripped.startswith("#"):
            continue
        if indent == 0:
            in_checkwash = stripped in ("checkwash:", "greenwash:")
            in_scope = in_allow = False
            continue
        if not in_checkwash:
            continue
        if stripped == "scope:":
            in_scope, in_allow = True, False
        elif stripped.startswith("oracle_freeze:"):
            contract.oracle_freeze = stripped.split(":", 1)[1].strip().lower() == "true"
            in_scope = in_allow = False
        elif stripped.startswith("intent:"):
            contract.intent = stripped.split(":", 1)[1].strip().strip("\"'")
            in_scope = in_allow = False
        elif in_scope and stripped == "allow:":
            in_allow = True
        elif in_allow and stripped.startswith("- "):
            contract.scope_allow.append(stripped[2:].strip().strip("\"'"))
        elif in_scope and not stripped.startswith("- "):
            in_scope = in_allow = False
    return contract


def contract_diagnostics(text: str | None) -> list[str]:
    """Advisory syntax notes; never normalize or activate ignored policy."""
    if not text:
        return []
    if text.startswith("\ufeff"):
        return ["TASK syntax: a leading BOM prevents front-matter recognition; "
                "review the contract and the canonical format in docs/task-input.md."]
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return []
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return ["TASK syntax: opening front matter has no closing --- line; no contract is parsed. "
                "Review docs/task-input.md before changing the task."]
    messages = []
    in_block = in_scope = False
    for number, raw in enumerate(lines[1:end], start=2):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        reason = None
        if raw.startswith("\t") and in_block:
            reason = "tab indentation is not supported; contract fields may be ignored"
        if indent == 0:
            in_block = value in ("checkwash:", "greenwash:")
            in_scope = False
            if not in_block and value.startswith(("checkwash:", "greenwash:")):
                reason = "the contract block header must appear alone; this block is ignored"
        elif in_block:
            if value.startswith("oracle_freeze:"):
                if value.split(":", 1)[1].strip().lower() not in {"true", "false"}:
                    reason = "oracle_freeze requires an unquoted true/false scalar with no trailing comment; this value is parsed as false"
                in_scope = False
            elif value.startswith("scope:"):
                in_scope = value == "scope:"
                if not in_scope:
                    reason = "scope requires a block mapping; this inline form is ignored"
            elif in_scope and value.startswith("allow:"):
                if value != "allow:":
                    reason = "scope.allow requires a block list; this inline form is ignored"
                    in_scope = False
            elif in_scope and not value.startswith("- "):
                in_scope = False
        if reason:
            messages.append(f"TASK syntax: line {number}: {reason}. See docs/task-input.md; "
                            "this note does not change the parsed contract.")
    return messages
