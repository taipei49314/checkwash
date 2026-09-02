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
