"""One resolver for the directory checkwash owns (issue #69).

`check` reads `.checkwash/<file>` first and falls back to `.greenwash/<file>`.
`allow` used to write `.greenwash/allow.toml` unconditionally and `doctor`
looked only there, so in a repository carrying `.checkwash/allow.toml` the
documented exemption flow wrote a ledger the engine never opened (reproduced
on v0.2.10). Every surface now asks the same function.
"""

from checkwash.config import CONFIG_DIRS, resolve_config_file


def test_neither_directory_means_the_documented_default(tmp_path):
    assert resolve_config_file(str(tmp_path), "allow.toml") == ".greenwash/allow.toml"
    assert resolve_config_file(str(tmp_path), "config.toml") == ".greenwash/config.toml"


def test_a_bare_checkwash_directory_is_where_new_files_go(tmp_path):
    (tmp_path / ".checkwash").mkdir()
    assert resolve_config_file(str(tmp_path), "allow.toml") == ".checkwash/allow.toml"
    assert resolve_config_file(str(tmp_path), "config.toml") == ".checkwash/config.toml"


def test_an_existing_file_beats_a_bare_directory(tmp_path):
    (tmp_path / ".checkwash").mkdir()
    (tmp_path / ".greenwash").mkdir()
    (tmp_path / ".greenwash" / "allow.toml").write_text("", encoding="utf-8")
    assert resolve_config_file(str(tmp_path), "allow.toml") == ".greenwash/allow.toml"
    assert resolve_config_file(str(tmp_path), "config.toml") == ".checkwash/config.toml"


def test_checkwash_file_beats_greenwash_file_like_the_engine_does(tmp_path):
    for d in CONFIG_DIRS:
        (tmp_path / d).mkdir()
        (tmp_path / d / "allow.toml").write_text("", encoding="utf-8")
    assert resolve_config_file(str(tmp_path), "allow.toml") == ".checkwash/allow.toml"
