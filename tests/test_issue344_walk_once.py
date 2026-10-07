"""Issue #344: the Python frontend walks each subtree once per parse.

The perf gate's 500-file case ran at its 2.5 s budget on the ubuntu runners.
Each test function was walked by six passes and each module by two more, so
`parse_python` now remembers a subtree's walk for the rest of the parse, after
its last change to the tree, and stripping docstrings walks statements only.
Nothing a parse returns may change.
"""
import ast
import datetime

import pytest

from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import FileChange, analyze
import checkwash.frontends.python.frontend as frontend
from checkwash.frontends.python.frontend import _strip_docstrings, _walk, parse_python

NESTED = '''"""module."""
def top():
    """top."""
    def inner():
        """inner."""
        return 1
    return inner
class Box:
    """box."""
    def method(self):
        """method."""
        async def coro():
            """coro."""
if True:
    def in_if():
        """if."""
for _ in ():
    def in_for():
        """for."""
while False:
    def in_while():
        """while."""
with open(__file__):
    def in_with():
        """with."""
try:
    def in_try():
        """try."""
except Exception:
    def in_except():
        """except."""
else:
    def in_else():
        """else."""
finally:
    def in_finally():
        """finally."""
match 1:
    case 1:
        def in_case():
            """case."""
x = lambda: """not a docstring"""
'''


def _old_strip(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree


def test_stripping_reaches_a_def_under_every_statement():
    assert ast.dump(_strip_docstrings(ast.parse(NESTED))) == ast.dump(_old_strip(ast.parse(NESTED)))
    docstrings = [node for node in ast.walk(_strip_docstrings(ast.parse(NESTED)))
                  if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert [node.value for node in docstrings] == ["not a docstring"]


def test_a_walk_outside_a_parse_is_not_remembered():
    tree = ast.parse("def test_x():\n    assert f(1) == 2\n")
    assert frontend._walks is None
    assert list(_walk(tree)) == list(ast.walk(tree))
    assert frontend._walks is None


def test_the_memo_lives_for_one_parse(monkeypatch):
    seen = []
    real = frontend._walk

    def watch(node):
        seen.append(frontend._walks is not None)
        return real(node)

    monkeypatch.setattr(frontend, "_walk", watch)
    parsed = parse_python(b"def test_x():\n    value = f(1)\n    assert value == 2\n", collect_tests=True)
    assert parsed.parse_ok and [unit.qualname for unit in parsed.units] == ["test_x"]
    assert seen and all(seen)
    assert frontend._walks is None


@pytest.mark.parametrize("weaken", [False, True])
def test_a_parse_reads_the_same_with_or_without_the_memo(monkeypatch, weaken):
    lines = ["from app.calc import compute", ""]
    for i in range(6):
        lines += ["", f"def test_case_{i}():", f"    value = compute({i})"]
        lines.append("    assert value is not None" if weaken and i % 3 == 0 else f"    assert value == {i * 2}")
    after = ("\n".join(lines) + "\n").encode()
    before = after.replace(b"is not None", b"== 0")
    changes = [FileChange("tests/test_mod.py", "modified", before, after)]

    def judge():
        _ir, findings, verdict = analyze(changes, Config(), Contract(), [], datetime.date(2026, 10, 7))
        return verdict, [(f.rule, f.severity, f.message, f.fingerprint) for f in findings]

    remembered = judge()
    monkeypatch.setattr(frontend, "_walk", ast.walk)
    assert judge() == remembered
