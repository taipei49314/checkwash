"""A UTF-8 BOM on config.toml or allow.toml is a Windows fact, not a parse error (issue #71).

PowerShell 5.1 `Set-Content -Encoding utf8` writes the BOM. tomllib rejects it
at line 1 column 1, and `load_config` decoded with plain `utf-8`, so a
hardened `fail_on` silently reverted to the default — the diagnostic was
printed, but the user's configuration was gone. Every other reader in
checkwash (deps, doctor, engine, roles, both frontends) already decodes with
`utf-8-sig`; these two were the holdouts. The diagnostics also name the file
that was actually read (#69), not a hardcoded `.greenwash/` path.
"""

from checkwash.allowlist import load_allowlist
from checkwash.config import load_config

BOM = b"\xef\xbb\xbf"
CONFIG = b'[gate]\nfail_on = "critical"\n'
ALLOW = (
    b"[[allow]]\n"
    b'fingerprint = "ASSERT_WEAKENED/tests/x.py/t/deadbeefdead"\n'
    b'rule = "ASSERT_WEAKENED"\nreason = "reviewed"\nauthor = "audit"\n'
    b'created = "2026-01-01"\nexpires = "2026-03-01"\n'
)


def test_bom_config_parses_like_its_bare_twin():
    bare, bare_err, _ = load_config(CONFIG)
    bommed, bom_err, _ = load_config(BOM + CONFIG)
    assert bare_err is None and bom_err is None
    assert bommed.fail_on == bare.fail_on == "critical"


def test_bom_allowlist_parses_like_its_bare_twin():
    bare, bare_err = load_allowlist(ALLOW)
    bommed, bom_err = load_allowlist(BOM + ALLOW)
    assert bare_err is None and bom_err is None
    assert [e.fingerprint for e in bommed] == [e.fingerprint for e in bare]


def test_parse_errors_name_the_file_that_was_read():
    _, err, _ = load_config(b"not = = toml", path=".checkwash/config.toml")
    assert err is not None and err.startswith(".checkwash/config.toml could not be parsed")
    _, aerr = load_allowlist(b"not = = toml", path=".checkwash/allow.toml")
    assert aerr is not None and aerr.startswith(".checkwash/allow.toml could not be parsed")


def test_default_diagnostic_path_is_the_documented_one():
    _, err, _ = load_config(b"not = = toml")
    assert err is not None and err.startswith(".greenwash/config.toml could not be parsed")
