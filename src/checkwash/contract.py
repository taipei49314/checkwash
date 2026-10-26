"""Task scope contract (SPEC §5 E2, v1: file globs + oracle_freeze only).

Parses a restricted YAML front-matter subset from TASK.md — deliberately not
a YAML parser: only the `checkwash:` block with `scope.allow` lists and
scalar flags is understood. Intent NLP is out of scope by design.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from checkwash.change import EngineError


@dataclass
class Contract:
    present: bool = False
    scope_allow: list[str] = field(default_factory=list)
    oracle_freeze: bool = False
    intent: str = ""


def parse_contract(text: str | None) -> Contract:
    """Decode the historical subset; authority entrypoints use load_contract.

    Retained for reading historical case records without reinterpreting their
    recorded contracts. This best-effort decoder does not validate input.
    """
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


def load_contract(text: str | None, *, source: str = "TASK") -> Contract:
    """Validate the restricted policy language before using it as authority.

    A malformed recognized policy must not silently become an absent scope or
    false freeze. General task prose and unrelated front-matter metadata remain
    accepted; this does not introduce a YAML dependency or expand its language.
    """
    errors = (["TASK syntax: NUL text is unsupported; save TASK as UTF-8. See docs/task-input.md."]
              if text and "\x00" in text else contract_diagnostics(text))
    if not errors:
        errors = _contract_shape_errors(text)
    if errors:
        # Diagnostics are fixed descriptions with line numbers, never raw task
        # text. Multiple defects need one refusal, not a partially applied policy.
        raise EngineError(f"{source}: invalid TASK contract: {errors[0]} "
                          "No TASK policy was applied; use the canonical restricted syntax.")
    return parse_contract(text)


def _contract_shape_errors(text: str | None) -> list[str]:
    """Reject ambiguous or ignored structure inside a recognized policy block."""
    if not text:
        return []
    lines = text.replace("\r\n", "\n").split("\n")
    if lines[0].startswith("---\r"):
        return ["TASK syntax: lone-CR front-matter lines are unsupported. See docs/task-input.md."]
    if lines[0].strip() != "---":
        return []
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return []  # The public diagnostic already explains this refusal.
    in_block = False
    block_seen = False
    fields: set[str] = set()
    field_indent = None
    scope = False
    allow_indent = None
    allow_seen = False

    def invalid(number: int, reason: str) -> list[str]:
        return [f"TASK syntax: line {number}: {reason}. See docs/task-input.md."]

    for number, raw in enumerate(lines[1:end], 2):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        header = value.split(":", 1)[0].strip()
        if header.strip("\"'") in {"checkwash", "greenwash"}:
            if header not in {"checkwash", "greenwash"} or value not in {"checkwash:", "greenwash:"}:
                return invalid(number, "the contract header requires an unquoted bare name on its own line")
            if raw[:len(raw) - len(raw.lstrip())]:
                return invalid(number, "the contract block header must start at column 1")
        if indent == 0:
            if value in ("checkwash:", "greenwash:"):
                if block_seen:
                    return invalid(number, "duplicate contract blocks are ambiguous")
                in_block = block_seen = True
                continue
            if value.split(":", 1)[0] in {"scope", "oracle_freeze", "intent", "allow"}:
                return invalid(number, "contract fields must be nested beneath the contract block")
            in_block = False
            continue
        if not in_block:
            continue
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            return invalid(number, "tab indentation is not supported")
        key = value.split(":", 1)[0]
        if key in {"scope", "oracle_freeze", "intent"} and ":" in value:
            if field_indent is None:
                field_indent = indent
            if indent != field_indent:
                return invalid(number, "contract fields require a consistent indentation level")
            if key in fields:
                return invalid(number, "duplicate contract fields are ambiguous")
            fields.add(key)
            scope = key == "scope"
            allow_indent = None
            allow_seen = False
            continue
        if scope and value == "allow:":
            if allow_seen or indent <= field_indent:
                return invalid(number, "scope.allow must be a single nested block list")
            allow_seen = True
            allow_indent = indent
            continue
        if scope and allow_indent is not None and value.startswith("- "):
            if indent <= allow_indent:
                return invalid(number, "scope.allow items must be nested below allow")
            item = value[2:].strip()
            if not item or (item[0] in "\"'" and (len(item) < 2 or item[-1] != item[0])):
                return invalid(number, "scope.allow requires a complete literal glob")
            literal = item[1:-1] if item[0] in "\"'" else item
            # The historical decoder strips all edge quotes, not one balanced
            # layer. Refuse forms whose literal identity that operation loses.
            if not literal or literal != item.strip("\"'"):
                return invalid(number, "scope.allow must retain its exact literal glob after decoding")
            continue
        return invalid(number, "unsupported or misplaced contract field")
    return []


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
    in_block = in_scope = in_allow = False
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
            in_scope = in_allow = False
            if not in_block and value.startswith(("checkwash:", "greenwash:")):
                reason = "the contract block header must appear alone; this block is ignored"
        elif not in_block and value in ("checkwash:", "greenwash:"):
            reason = "leading spaces on the contract block header prevent recognition; place it at column 1"
        elif in_block:
            if value.startswith("oracle_freeze:"):
                if value.split(":", 1)[1].strip().lower() not in {"true", "false"}:
                    reason = "oracle_freeze requires an unquoted true/false scalar with no trailing comment; this value is parsed as false"
                in_scope = in_allow = False
            elif value.startswith("scope:"):
                in_scope = value == "scope:"
                in_allow = False
                if not in_scope:
                    reason = "scope requires a block mapping; this inline form is ignored"
            elif in_scope and value.startswith("allow:"):
                in_allow = value == "allow:"
                if value != "allow:":
                    reason = "scope.allow requires a block list; this inline form is ignored"
                    in_scope = False
            elif in_scope and in_allow and value.startswith("- "):
                item = value[2:].strip()
                fully_quoted = len(item) >= 2 and item[0] in "\"'" and item[-1] == item[0]
                if not fully_quoted and " #" in item:
                    reason = "scope.allow retains trailing # text in its literal glob; review whether a comment was intended"
            elif in_scope and not value.startswith("- "):
                in_scope = in_allow = False
        if reason:
            messages.append(f"TASK syntax: line {number}: {reason}. See docs/task-input.md; "
                            "this note does not change the parsed contract.")
    return messages
