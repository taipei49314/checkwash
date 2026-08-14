"""E5: roles / ci / evidence / compat are real modules; public API unchanged."""

from greenwash.ci import _scan_ci_weakening
from greenwash.compat import unit_is_live as compat_live
from greenwash.engine import FileChange, analyze, collectable, is_artifact
from greenwash.evidence import _module_of
from greenwash.gating import apply_gates, unit_is_live
from greenwash.roles import collectable as roles_collectable
from greenwash.roles import is_artifact as roles_artifact


def test_e5_modules_are_the_implementations():
    assert is_artifact is roles_artifact
    assert collectable is roles_collectable
    assert unit_is_live is compat_live
    assert _module_of("src/pkg/mod.py") == "pkg.mod"
    assert callable(_scan_ci_weakening)
    assert callable(analyze)
    assert callable(apply_gates)
    assert FileChange.__module__ == "greenwash.change"
