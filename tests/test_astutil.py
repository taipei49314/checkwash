"""Shared AST helpers live in one module (E1 / review 2026-08-11)."""

import ast

from greenwash import gating
from greenwash.frontends.python import frontend
from greenwash.ir.astutil import dotted_name, expr_wraps, same_expr


def _expr(src: str) -> ast.AST:
    return ast.parse(src, mode="eval").body


def test_dotted_name_is_the_single_implementation():
    assert frontend._dotted is dotted_name
    assert gating._dotted_name is dotted_name


def test_dotted_name_name_and_attribute_chain():
    assert dotted_name(_expr("sys")) == "sys"
    assert dotted_name(_expr("sys.platform")) == "sys.platform"
    assert dotted_name(_expr("sys.version_info.major")) == "sys.version_info.major"


def test_dotted_name_refuses_calls_and_subscripts():
    assert dotted_name(_expr("platform.system()")) is None
    assert dotted_name(_expr("sys.modules[0]")) is None
    assert dotted_name(_expr("f(x).name")) is None


def test_same_expr_and_expr_wraps_unchanged():
    assert same_expr("f(x)", "f( x )")
    assert expr_wraps("f(x)", "sorted(f(x))")
    assert not expr_wraps("f(x)", "g(x)")
