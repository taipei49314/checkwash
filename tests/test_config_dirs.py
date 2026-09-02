"""`.checkwash/` and `.greenwash/` are one directory under two names.

`check` and `sweep` read `.checkwash/config.toml` and `.checkwash/allow.toml`
first and fall back to `.greenwash/`, so both must carry the guardrail role:
a config edit that is critical under one name and a production change under
the other is a bypass (issue #68 — reproduced on v0.2.10: a comment edit in
`.checkwash/config.toml` granted repair evidence to a weakened assertion in
the same diff, and a committed `[detectors] disable` produced zero findings).
"""

import pytest

from checkwash.config import DEFAULT_ROLES, Config


@pytest.mark.parametrize("rel", ["config.toml", "allow.toml", "nested/anything.txt"])
def test_both_config_directories_share_the_guardrail_role(rel):
    cfg = Config()
    assert cfg.role_of(f".greenwash/{rel}") == "guardrail"
    assert cfg.role_of(f".checkwash/{rel}") == cfg.role_of(f".greenwash/{rel}")


def test_default_roles_list_both_directories_as_guardrail():
    assert ".greenwash/**" in DEFAULT_ROLES["guardrail"]
    assert ".checkwash/**" in DEFAULT_ROLES["guardrail"]


# --- issue #79: creation of checkwash's own config is a modification when its
# --- content relaxes the defaults that were in force without it.

from checkwash.engine import _created_config_loosens  # noqa: E402


def test_created_config_loosens_when_it_disables_a_detector():
    assert _created_config_loosens(b'[detectors]\ndisable = ["ASSERT_WEAKENED"]\n')


def test_created_config_loosens_when_fail_on_rises_above_the_default():
    assert _created_config_loosens(b'[gate]\nfail_on = "critical"\n')


def test_created_config_that_tightens_does_not_loosen():
    assert not _created_config_loosens(b'[gate]\nfail_on = "warn"\n')
    assert not _created_config_loosens(b'[gate]\non_engine_error = "block"\n')


def test_created_config_with_only_comments_or_nothing_does_not_loosen():
    assert not _created_config_loosens(b"# checkwash config\n")
    assert not _created_config_loosens(b"")
    assert not _created_config_loosens(None)


def test_unparseable_created_config_does_not_loosen():
    # Defaults stay in force; the parse error is surfaced on the next diff.
    assert not _created_config_loosens(b"not = = toml\n")
