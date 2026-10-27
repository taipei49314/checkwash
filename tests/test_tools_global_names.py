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


def undefined(source, name="<owned>"):
    top = symtable.symtable(source, name, "exec")
    defined = {sym.get_name() for sym in top.get_symbols() if sym.is_assigned() or sym.is_imported() or sym.is_namespace()}

    def scopes(table):
        for child in table.get_children():
            yield child
            yield from scopes(child)

    # A function may assign a module global it declares `global`.
    defined |= {sym.get_name() for child in scopes(top) for sym in child.get_symbols()
                if sym.is_declared_global() and sym.is_assigned()}
    known = defined | BUILTINS
    # Module-level reads include default arguments and decorators, which the
    # module evaluates when it defines the function.
    found = [f"module:{sym.get_name()}" for sym in top.get_symbols() if sym.is_referenced() and sym.get_name() not in known]
    found += [f"{child.get_name()}:{child.get_lineno()}:{sym.get_name()}" for child in scopes(top) for sym in child.get_symbols()
              if sym.is_referenced() and sym.is_global() and sym.get_name() not in known]
    return found


def test_tools_exist():
    assert TOOLS


@pytest.mark.parametrize("path", TOOLS, ids=lambda path: path.name)
def test_every_global_read_is_defined(path):
    assert undefined(path.read_text(encoding="utf-8"), str(path)) == []


@pytest.mark.parametrize("source, name", [
    ("def verify(stage):\n    if stage == 'tag':\n        return exits['gate']\n    return None\n", "verify:1:exits"),
    ("exits\n", "module:exits"),
    ("def verify(stage=exits):\n    return stage\n", "module:exits"),
    ("@exits\ndef verify():\n    pass\n", "module:exits"),
])
def test_the_check_sees_reads_in_branches_module_scope_and_defaults(source, name):
    assert undefined(source) == [name]


def test_defined_imported_global_and_builtin_names_pass():
    source = ("import os\nfrom pathlib import Path\nLIMIT = 1\n"
              "def set_mode():\n    global MODE\n    MODE = 'x'\n"
              "def read(path=Path('.')):\n    return os.sep, LIMIT, MODE, len(str(path))\n"
              "class Packet:\n    size = LIMIT\n")
    assert undefined(source) == []
