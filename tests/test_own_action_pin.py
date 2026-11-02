"""tools/own_action_pin.py on owned Git chains; nothing from checkwash runs here."""
import importlib.util
import json
from pathlib import Path

import pytest

from own_action_pin_fixtures import (ACTION, DOCTOR, PREVIOUS, chain, commit, content, doctor, git, repository, set_own,
                                     write)

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("own_action_pin_tool", ROOT / "tools/own_action_pin.py")
T = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(T)


def release_head(root, **kwargs):
    b = repository(root, **kwargs)
    return b, content(root)


def diff_lines(root, old, new):
    return [line for line in git(root, "diff", "--no-ext-diff", "--no-color", "-U0", old, new).splitlines()
            if line.startswith(("-", "+")) and not line.startswith(("---", "+++"))]


def refused(root, capsys, message):
    before = ((root / DOCTOR).read_bytes(), git(root, "status", "--porcelain=v1", "--untracked-files=all"),
              git(root, "rev-parse", "HEAD"))
    assert T.main(["write", "--repo", str(root)]) == 2
    assert message in capsys.readouterr().err
    assert ((root / DOCTOR).read_bytes(), git(root, "status", "--porcelain=v1", "--untracked-files=all"),
            git(root, "rev-parse", "HEAD")) == before


def test_write_stages_exactly_the_own_pin_line(tmp_path, capsys):
    root = tmp_path / "repo"
    b, a = release_head(root)
    assert T.main(["write", "--repo", str(root / "src")]) == 0
    assert capsys.readouterr().out == f'git commit -m "release: doctor accepts its own Action pin {a}"\n'
    assert git(root, "diff", "--cached", "--name-only") == DOCTOR
    assert git(root, "status", "--porcelain=v1", "--untracked-files=all") == "M  " + DOCTOR
    r = commit(root, "R")
    assert git(root, "rev-list", "--parents", "-n", "1", r).split() == [r, a]
    assert diff_lines(root, a, r) == [f'-_OWN_ACTION_PIN = "{PREVIOUS}"', f'+_OWN_ACTION_PIN = "{a}"']
    expected = {"applies": True, "action_commit": a, "release_pr_head": r, "previous_action_pin": PREVIOUS}
    assert T.main(["check", "--repo", str(root), "--stage", "pr", "--head", r, "--base", b, "--announced", PREVIOUS]) == 0
    assert json.loads(capsys.readouterr().out) == expected

    # A merge commit, then an annotated tag on it: the user's `vX.Y.Z^2^1` is A.
    m = git(root, "commit-tree", r + "^{tree}", "-p", b, "-p", r, "-m", "merge")
    git(root, "tag", "-a", "v0.11.0", "-m", "release", m)
    assert git(root, "rev-parse", "v0.11.0^2^1") == a
    assert diff_lines(root, "v0.11.0^2^1", "v0.11.0") == diff_lines(root, a, r)
    for stage, head, extra in (("main", m, ["--pr-head", r]), ("tag", "v0.11.0", [])):
        assert T.main(["check", "--repo", str(root), "--stage", stage, "--head", head, "--base", b,
                       "--announced", PREVIOUS, *extra]) == 0
        assert json.loads(capsys.readouterr().out) == expected
    # The default announced pin is the receipt tool's ACTION_SHA, which this chain does not use.
    assert T.main(["check", "--repo", str(root), "--stage", "pr", "--head", r, "--base", b]) == 2
    assert "previous Action pin is not the announced pin" in capsys.readouterr().err
    # --pr-head reaches the rule: at main, the merge must name the verified PR head.
    assert T.main(["check", "--repo", str(root), "--stage", "main", "--head", m, "--base", b, "--announced", PREVIOUS,
                   "--pr-head", a]) == 2
    assert "merge commit's second parent is not the verified release PR head" in capsys.readouterr().err


def test_check_refuses_a_release_head_without_r(tmp_path, capsys):
    root = tmp_path / "repo"
    b, a = release_head(root)
    assert T.main(["check", "--repo", str(root), "--stage", "pr", "--head", a, "--base", b, "--announced", PREVIOUS]) == 2
    assert "own Action pin is not the one parent" in capsys.readouterr().err
    assert T.main(["check", "--repo", str(root), "--stage", "pr", "--head=--all", "--base", b]) == 2
    assert "cannot start with '-'" in capsys.readouterr().err


def test_check_warns_when_the_rule_does_not_apply(tmp_path, capsys):
    root = tmp_path / "repo"
    b = repository(root)
    write(root, {"NEWS": "no version change\n"})
    head = commit(root, "H")
    for stage in ("pr", "main"):
        assert T.main(["check", "--repo", str(root), "--stage", stage, "--head", head, "--base", b, "--announced", PREVIOUS]) == 0
        captured = capsys.readouterr()
        assert json.loads(captured.out) == {"applies": False}
        assert captured.err.startswith(f"warning: the rule does not apply at the {stage} stage") and captured.err.count("\n") == 1
    assert T.main(["check", "--repo", str(root), "--stage", "tag", "--head", head, "--base", b, "--announced", PREVIOUS]) == 2
    assert "not a two-parent merge commit" in capsys.readouterr().err


def test_write_refuses_untracked_and_modified_files(tmp_path, capsys):
    root = tmp_path / "repo"
    release_head(root)
    write(root, {"scratch.txt": "untracked\n"})
    refused(root, capsys, "the checkout is not clean")
    (root / "scratch.txt").unlink()
    write(root, {"README.md": f"      - uses: {ACTION}@{PREVIOUS} # v0.10.0\nedited\n"})
    refused(root, capsys, "the checkout is not clean")


def test_write_refuses_a_head_that_is_already_r(tmp_path, capsys):
    root = tmp_path / "repo"
    release_head(root)
    assert T.main(["write", "--repo", str(root)]) == 0
    capsys.readouterr()
    commit(root, "R")
    refused(root, capsys, "it is R")


def test_write_refuses_a_bad_line_shape(tmp_path, capsys):
    root = tmp_path / "repo"
    twice = doctor() + f'_OWN_ACTION_PIN = "{PREVIOUS}"\n'
    release_head(root, doctor_text=twice)
    refused(root, capsys, "exactly one previous and one own Action pin line")
    other = tmp_path / "comment"
    release_head(other, doctor_text=doctor().replace(f'_OWN_ACTION_PIN = "{PREVIOUS}"', f'_OWN_ACTION_PIN = "{PREVIOUS}"  # note'))
    refused(other, capsys, "differ from the exact shape")


def test_write_refuses_a_head_that_is_not_a_release(tmp_path, capsys):
    root = tmp_path / "repo"
    repository(root)
    write(root, {"NEWS": "no version change\n"})
    commit(root, "H")
    refused(root, capsys, "is the advertised release's")


def test_write_refuses_a_crlf_worktree(tmp_path, capsys):
    # With *.py eol=lf, as in this repository, Git reports the rewrite.
    root = tmp_path / "repo"
    release_head(root)
    path = root / DOCTOR
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    refused(root, capsys, "the checkout is not clean")
    # Without it, core.autocrlf checks out CRLF that Git calls clean; the blob check refuses.
    trap = tmp_path / "autocrlf"
    repository(trap)
    write(trap, {".gitattributes": "", "pyproject.toml": '[project]\nname = "checkwash"\nversion = "0.11.0"\n'})
    commit(trap, "A")
    git(trap, "config", "core.autocrlf", "true")
    (trap / DOCTOR).unlink()
    git(trap, "checkout", "--", DOCTOR)
    assert b"\r\n" in (trap / DOCTOR).read_bytes()
    assert git(trap, "status", "--porcelain=v1", "--untracked-files=all") == ""
    refused(trap, capsys, "differs from HEAD's blob (line endings included)")


def test_write_refuses_a_content_commit_whose_pins_differ(tmp_path, capsys):
    root = tmp_path / "repo"
    release_head(root, doctor_text=doctor(own="c" * 40))
    refused(root, capsys, "R is written only on a content commit whose two pin lines are equal")


def test_write_restores_doctor_when_staging_fails(tmp_path, capsys):
    root = tmp_path / "repo"
    release_head(root)

    def state():
        return ((root / DOCTOR).read_bytes(), git(root, "ls-files", "--stage"), git(root, "diff", "--cached", "--name-only"),
                git(root, "status", "--porcelain=v1", "--untracked-files=all"), git(root, "rev-parse", "HEAD"))

    before = state()
    lock = root / ".git" / "index.lock"
    lock.write_bytes(b"")
    assert T.main(["write", "--repo", str(root)]) == 2
    error = capsys.readouterr().err
    assert "git add -- src/checkwash/doctor.py failed" in error and error.rstrip().endswith("doctor.py was restored")
    lock.unlink()
    assert state() == before


def verify(root, stage, head, base, pr_head=None):
    return T.R.validate_own_action_pin(root, {"stage": stage, "head_sha": head, "base_sha": base},
                                       announced=PREVIOUS, pr_head=pr_head)


def write_r_again(root, capsys):
    assert T.main(["write", "--repo", str(root)]) == 0
    capsys.readouterr()
    return commit(root, "R again")


def test_a_squash_is_recovered_by_a_reset_commit_and_a_new_r(tmp_path, capsys):
    # RELEASING's recovery: a squash S leaves A off main and keeps R's own line.
    # A follow-up content commit resets that line to the previous pin; R
    # written on it, merged with a merge commit, verifies with it as A.
    c = chain(tmp_path / "repo")
    root, s = c["root"], c["S"]
    with pytest.raises(ValueError, match="two-parent merge commit"):
        verify(root, "main", s, c["B"], c["R"])
    git(root, "checkout", "-q", "--detach", s)
    refused(root, capsys, "R is written only on a content commit whose two pin lines are equal")
    set_own(root, PREVIOUS)
    reset = commit(root, "doctor: reset the own Action pin")
    r = write_r_again(root, capsys)
    assert T.R.commit_parents(root, r) == [reset]
    expected = {"applies": True, "action_commit": reset, "release_pr_head": r, "previous_action_pin": PREVIOUS}
    assert verify(root, "pr", r, s) == expected
    m = git(root, "commit-tree", r + "^{tree}", "-p", s, "-p", r, "-m", "merge")
    assert verify(root, "main", m, s, r) == expected
    assert verify(root, "tag", m, s) == expected


@pytest.mark.parametrize("case", ["commit", "update-branch"])
def test_a_commit_after_r_is_refused_until_r_is_dropped(tmp_path, capsys, case):
    # Nothing may follow R: a commit after it, or GitHub's "Update branch" merge
    # of a newer main, keeps R's own line, and write refuses that head. R is
    # dropped, the change made again on A, and R written on the result verifies.
    c = chain(tmp_path / "repo")
    root, base = c["root"], c["B"]
    if case == "update-branch":
        base = git(root, "commit-tree", c["B"] + "^{tree}", "-p", c["B"], "-m", "newer main")

    def change():
        if case == "commit":
            write(root, {"NEWS": "release notes, corrected\n"})
            return commit(root, "the change")
        git(root, "merge", "-q", "--no-ff", "-m", "Update branch", base)
        return git(root, "rev-parse", "HEAD")

    head = change()
    with pytest.raises(ValueError, match="one parent of the release PR's last commit"):
        verify(root, "pr", head, base)
    refused(root, capsys, "after a commit that followed R, R must be dropped first")
    git(root, "reset", "-q", "--hard", c["R"] + "^1")
    action = change()
    r = write_r_again(root, capsys)
    assert T.R.commit_parents(root, r) == [action]
    expected = {"applies": True, "action_commit": action, "release_pr_head": r, "previous_action_pin": PREVIOUS}
    assert verify(root, "pr", r, base) == expected
    m = git(root, "commit-tree", r + "^{tree}", "-p", base, "-p", r, "-m", "merge")
    assert verify(root, "main", m, base, r) == expected
    assert verify(root, "tag", m, base) == expected
