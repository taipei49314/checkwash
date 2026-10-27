"""Release tools read no global name their module never defines; symtable only, nothing imported or run.

The v0.10.0 tag-stage verification stopped on a NameError in a branch that only
tag and later stages reach (validate_verdict read `exits` without receiving it).
"""
import builtins
from pathlib import Path
import symtable

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = sorted((ROOT / "tools").glob("*.py"))
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__builtins__"}


def undefined(path):
    top = symtable.symtable(path.read_text(encoding="utf-8"), str(path), "exec")
    defined = {sym.get_name() for sym in top.get_symbols() if sym.is_assigned() or sym.is_imported() or sym.is_namespace()}
    found = []

    def walk(table):
        for child in table.get_children():
            for sym in child.get_symbols():
                if sym.is_referenced() and sym.is_global() and sym.get_name() not in defined | BUILTINS:
                    found.append(f"{child.get_name()}:{child.get_lineno()}:{sym.get_name()}")
            walk(child)

    walk(top)
    return found


def test_tools_exist():
    assert TOOLS


@pytest.mark.parametrize("path", TOOLS, ids=lambda path: path.name)
def test_every_global_read_is_defined(path):
    assert undefined(path) == []


def test_the_check_sees_a_branch_only_name():
    source = "def verify(stage):\n    if stage == 'tag':\n        return exits['gate']\n    return None\n"
    table = symtable.symtable(source, "<owned>", "exec")
    sym = table.get_children()[0].lookup("exits")
    assert sym.is_referenced() and sym.is_global()
