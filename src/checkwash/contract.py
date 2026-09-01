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
