"""#502: the rebinding spellings #306's fix left out.

Since #306 (D-145 Sub-Q3), `self._check(...)` stays unresolved when the module
rebinds the helper's name. These spellings were not read, so the call stayed
resolved and the helper's assertions stayed the unit's although another
function answered the call: a namespace write (`vars(self)[...]`,
`self.__dict__.update(...)`, `vars()` or `locals()` in a class body), a
`__setattr__` or `__delattr__` by its last name, and a computed-name
`setattr` through an alias of the class (ruling 502, items 1 to 4). The pins
of the spellings caught before stay in `tests/test_issue306_self_methods.py`.
"""

import datetime

import pytest

from checkwash.change import FileChange
from checkwash.config import Config
from checkwash.contract import Contract
from checkwash.engine import analyze
from checkwash.frontends.python import parse_python

HEAD = "import unittest\n\nfrom app.billing import total\n\n\n"
CHECK = "    def _check(self, value):\n        self.assertEqual(value, 78.75)\n\n"
TEST = "    def test_total(self):\n        self._check(total([50.0, 28.75]))\n"
SOURCE = HEAD + "class TotalTest(unittest.TestCase):\n" + CHECK + TEST
RESOLVED = [("self.assertEqual(value, 78.75)", "TotalTest._check")]


def unit(source, qualname="TotalTest.test_total"):
    parsed = parse_python(source.encode(), collect_tests=True)
    assert parsed.parse_ok
    [found] = [u for u in parsed.units if u.qualname == qualname]
    return found


def via(source, qualname="TotalTest.test_total"):
    return [(a.text, a.via) for a in unit(source, qualname).side.assertions if a.via is not None]


def run(before, after):
    _ir, findings, verdict = analyze(
        [FileChange("tests/test_billing.py", "modified", before.encode(), after.encode())],
        Config(), Contract(), [], datetime.date(2026, 10, 19),
        root_reader={}.get, root_searcher=lambda _needles: [],
    )
    return verdict, [(f.rule, f.severity) for f in findings]


def set_up(*lines):
    """SOURCE with a `setUp` that runs these lines."""
    body = "".join(f"        {line}\n" for line in lines)
    return SOURCE.replace("    def test_total(self):\n", "    def setUp(self):\n" + body + "\n    def test_total(self):\n")


def class_body(*lines):
    """SOURCE with these lines in the class body, after the helper's def."""
    return HEAD + "class TotalTest(unittest.TestCase):\n" + CHECK + "".join(f"    {line}\n" for line in lines) + "\n" + TEST


def module(*lines):
    """SOURCE with these lines at module level, after the class."""
    return SOURCE + "\n\n" + "".join(f"{line}\n" for line in lines)


def test_the_unchanged_helper_method_resolves():
    assert via(SOURCE) == RESOLVED


# -- item 1: `vars(x)[...]` is read as `x.__dict__[...]` is --------------------------


@pytest.mark.parametrize("statement", [
    "vars(self)['_check'] = lambda value: None",
    # any key: the channel is module-wide, as for `x.__dict__[...]`
    "vars(self)['data'] = 1",
    "vars(self)[NAME] = print",
    "del vars(self)['_check']",
])
def test_a_store_into_vars_of_the_instance_leaves_every_name_unresolved(statement):
    assert via(set_up(statement)) == []


@pytest.mark.parametrize("later", [
    "vars(TotalTest)['_check'] = print",
    "del vars(TotalTest)['_check']",
])
def test_a_store_into_vars_of_the_class_is_read_as_its_dict_store_is(later):
    # A class's `vars()` is a read-only mappingproxy, so this raises TypeError
    # at run time. The pinned `TotalTest.__dict__['_check'] = print` raises the
    # same way and is read as a rebinding too.
    assert via(module(later)) == []


# -- item 2: a class body's `vars()` and `locals()` ----------------------------------


@pytest.mark.parametrize("line", [
    "vars()['_check'] = print",
    "locals()['_check'] = print",
    "del vars()['_check']",
    "del locals()['_check']",
    "locals().update(_check=print)",
    "vars().__setitem__('_check', print)",
])
def test_a_class_body_namespace_write_of_the_name_leaves_it_unresolved(line):
    assert via(class_body(line)) == []


@pytest.mark.parametrize("line", [
    "vars()['other'] = print",
    "locals().update(other=print)",
])
def test_a_class_body_namespace_write_of_another_name_leaves_it_resolved(line):
    assert via(class_body(line)) == RESOLVED


@pytest.mark.parametrize("source", [
    class_body("vars()[NAME] = print"),
    # names generated in a class-body loop
    class_body("for name in NAMES:", "    locals()['test_' + name] = print"),
    # in another class's body: every name in the module
    module("class Other:", "    vars()[NAME] = 1"),
])
def test_a_computed_key_in_a_class_body_namespace_leaves_every_name_unresolved(source):
    assert via(source) == []


@pytest.mark.parametrize("source", [
    module("vars()['_check'] = print"),
    module("vars()[NAME] = print"),
    set_up("locals()['_check'] = print"),
])
def test_a_namespace_write_outside_a_class_body_rebinds_no_method(source):
    # At module scope `vars()` is the module's namespace, and in a function
    # `locals()` is its locals: neither holds the class's methods.
    assert via(source) == RESOLVED


# -- item 2: `x.__dict__` and `vars(x)` methods, and the dunder setters --------------


@pytest.mark.parametrize("statement", [
    # the issue's spelling: the instance attribute shadows the method at run time
    "self.__dict__.update({'_check': lambda value: None})",
    "self.__dict__.update(_check=print)",
    "vars(self).update({'data': 1, '_check': print})",
    "vars(self).update(_check=print)",
    "self.__dict__.setdefault('_check', print)",
    "vars(self).setdefault('_check', print)",
])
def test_a_literal_namespace_write_of_the_name_leaves_it_unresolved(statement):
    assert via(set_up(statement)) == []


@pytest.mark.parametrize("source", [
    # bound: the name is the first argument
    set_up("self.__setattr__('_check', print)"),
    set_up("super().__setattr__('_check', print)"),
    set_up("self.__delattr__('_check')"),
    # unbound: the name is the second
    module("type.__setattr__(TotalTest, '_check', print)"),
    module("type.__delattr__(TotalTest, '_check')"),
])
def test_a_dunder_setter_naming_the_method_leaves_it_unresolved(source):
    assert via(source) == []


@pytest.mark.parametrize("source", [
    set_up("self.__dict__.update(data=1)"),
    set_up("vars(self).update({'data': 1})"),
    set_up("self.__dict__.setdefault('data', 1)"),
    set_up("self.__setattr__('data', 1)"),
    set_up("object.__setattr__(self, 'data', 1)"),
    module("type.__setattr__(TotalTest, 'data', 1)"),
    # unbound `__delattr__` takes two arguments, so the name is the second
    set_up("object.__delattr__(self, 'data')"),
])
def test_a_literal_write_of_another_name_leaves_it_resolved(source):
    assert via(source) == RESOLVED


# -- item 3: the other forms leave every name unresolved -----------------------------


@pytest.mark.parametrize("statement", [
    # a mapping that is not a literal, or a `**`
    "self.__dict__.update(attrs)",
    "self.__dict__.update(**attrs)",
    "self.__dict__.update({**attrs})",
    "self.__dict__.update(attrs, data=1)",
    # a computed key
    "vars(self).update({NAME: print})",
    "self.__dict__.setdefault(NAME, print)",
    # a dunder setter with no literal name, bound or unbound, or with a starred one
    "self.__setattr__(NAME, print)",
    "type.__setattr__(type(self), NAME, print)",
    "super().__delattr__(NAME)",
    "self.__setattr__(*pair)",
    # a literal value is not the name: bound, the name is the first argument
    # (the draft took the bound call's 'x'); unbound, the second
    "self.__setattr__(NAME, 'x')",
    "object.__setattr__(config, NAME, 'x')",
    # the namespace itself replaced
    "self.__dict__ = {'data': 1}",
    "self.__dict__ |= {'data': 1}",
    "setattr(self, '__dict__', {'data': 1})",
    # the item store spelled as a call, and a starred setattr
    "self.__dict__.__setitem__('data', 1)",
    "setattr(*(self, NAME, print))",
])
def test_an_unreadable_namespace_or_reflective_write_leaves_every_name_unresolved(statement):
    assert via(set_up(statement)) == []


# -- item 4: a computed-name setattr, one alias away ---------------------------------


@pytest.mark.parametrize("source", [
    # a module-level alias of the running class
    module("Alias = TotalTest", "setattr(Alias, NAME, print)"),
    module("Alias = TotalTest", "delattr(Alias, NAME)"),
    # a function-local alias of the class, of the receiver's type, or of its `__class__`
    set_up("cls = TotalTest", "setattr(cls, NAME, print)"),
    set_up("klass = type(self)", "setattr(klass, NAME, print)"),
    set_up("klass = self.__class__", "setattr(klass, NAME, print)"),
    # a module-level alias read in a function, and an alias read in a def nested under its own
    module("Alias = TotalTest", "", "", "def install():", "    setattr(Alias, NAME, print)"),
    set_up("klass = type(self)", "def install():", "    setattr(klass, NAME, print)", "install()"),
    # an alias of the base that binds the name
    HEAD + "class Base(unittest.TestCase):\n" + CHECK + "class TotalTest(Base):\n" + TEST
    + "\n\nAlias = Base\nsetattr(Alias, NAME, print)\n",
])
def test_a_computed_setattr_through_one_alias_leaves_the_call_unresolved(source):
    assert via(source) == []


@pytest.mark.parametrize("source", [
    module("setattr(globals()['TotalTest'], NAME, print)"),
    "import sys\n" + module("setattr(sys.modules[__name__].TotalTest, NAME, print)"),
    module("setattr(make_class(), NAME, print)"),
])
def test_a_computed_setattr_on_a_target_that_is_no_name_leaves_every_class_unresolved(source):
    assert via(source) == []


@pytest.mark.parametrize("source", [
    module("setattr(config, NAME, 1)"),
    module("setattr(config, 'data', 1)"),
    # an alias of a call's value is not followed, and one of a class outside the order is not it
    module("obj = Fake()", "setattr(obj, NAME, 1)"),
    module("class Other:", "    pass", "", "", "Alias = Other", "setattr(Alias, NAME, 1)"),
    # an alias is followed only from a name, `type(x)` or `x.__class__`, the
    # values the ruling names: an attribute of the receiver is another object
    set_up("cfg = self.settings", "setattr(cfg, NAME, 1)"),
])
def test_a_setattr_on_an_unrelated_object_leaves_the_call_resolved(source):
    assert via(source) == RESOLVED


# -- item 5: the stated cost ---------------------------------------------------------


@pytest.mark.parametrize("statement", [
    # the issue's evasion
    "self.__dict__.update({'_check': lambda value: None})",
    # an innocent write of another name, read as every name (item 1)
    "vars(self)['data'] = 1",
])
def test_stated_cost_a_rebinding_spelling_added_reads_as_the_helpers_assertions_removed(statement):
    # The call resolves at the parent only, so its assertion reads as removed,
    # as for the spellings caught before.
    assert run(SOURCE, set_up(statement)) == ("block", [("ASSERT_REMOVED", "high")])


def test_a_rebinding_spelling_removed_reads_nothing_as_removed():
    _verdict, findings = run(set_up("self.__dict__.update({'_check': lambda value: None})"), SOURCE)
    assert "ASSERT_REMOVED" not in [rule for rule, _ in findings]
