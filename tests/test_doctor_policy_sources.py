"""Doctor describes per-file worktree precedence without claiming base authority."""
import pytest

from checkwash.doctor import collect


def _put(root, name):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# controlled policy file\n", encoding="utf-8")


@pytest.mark.parametrize("name", ("config.toml", "allow.toml"))
def test_doctor_explains_shadowed_policy_file(tmp_path, name):
    for directory in (".checkwash", ".greenwash"):
        _put(tmp_path, directory + "/" + name)
    notes = collect(tmp_path)
    note = next(note for note in notes if "precedence" in note.title)
    assert note.level == "info"
    assert ".checkwash/" + name in note.detail
    assert ".greenwash/" + name in note.detail
    assert "working tree" in note.detail and "BASE" in note.detail
    assert "review" in note.detail.lower()


@pytest.mark.parametrize("directory", (".checkwash", ".greenwash"))
def test_one_policy_directory_has_no_shadow_diagnostic(tmp_path, directory):
    _put(tmp_path, directory + "/config.toml")
    _put(tmp_path, directory + "/allow.toml")
    assert not any("precedence" in note.title for note in collect(tmp_path))


def test_config_and_allow_precedence_are_independent(tmp_path):
    _put(tmp_path, ".checkwash/config.toml")
    _put(tmp_path, ".greenwash/config.toml")
    _put(tmp_path, ".greenwash/allow.toml")
    notes = collect(tmp_path)
    precedence = [note for note in notes if "precedence" in note.title]
    assert len(precedence) == 1 and "config.toml" in precedence[0].detail
    assert "allow.toml" not in precedence[0].detail
    existing = next(note for note in notes if "read from the BASE side" in note.title)
    assert ".greenwash/allow.toml" in existing.detail
