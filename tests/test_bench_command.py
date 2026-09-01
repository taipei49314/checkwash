"""`greenwash bench` documents reproduce steps and fails closed on missing clones."""

import io
import pathlib

from checkwash.bench import collect, find_checkout, run
from checkwash.cli import build_parser

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_bench_is_a_registered_subcommand():
    args = build_parser().parse_args(["bench", "--repo", ".", "--local"])
    assert args.command == "bench"
    assert args.local is True

    import checkwash.cli as cli_module

    source = pathlib.Path(cli_module.__file__).read_text(encoding="utf-8")
    fallback = source.split("elif argv[0] not in (", 1)[1].split("):", 1)[0]
    assert '"bench"' in fallback, "bench missing from main()'s bare-word passthrough list"


def test_find_checkout_walks_up_to_benchmarks_readme(tmp_path):
    nested = tmp_path / "src" / "checkwash"
    nested.mkdir(parents=True)
    assert find_checkout(nested) is None
    (tmp_path / "benchmarks").mkdir()
    (tmp_path / "benchmarks" / "README.md").write_text("pins\n", encoding="utf-8")
    (tmp_path / "benchmarks" / "sweeps").mkdir()
    assert find_checkout(nested) == tmp_path.resolve()


def test_not_a_checkout_fails_clearly(tmp_path):
    buf = io.StringIO()
    code = run(start=str(tmp_path), local_only=True, stream=buf)
    out = buf.getvalue()
    assert code == 2
    assert "not a checkwash checkout" in out
    assert "benchmarks/README.md" in out or "clone https://github.com/taipei49314/greenwash" in out


def test_local_from_this_checkout_passes():
    buf = io.StringIO()
    code = run(start=str(ROOT), local_only=True, stream=buf)
    out = buf.getvalue()
    assert code == 0, out
    assert "benchmarks" in out.replace("\\", "/")
    assert "README.md" in out
    assert "local reproduce ok" in out


def test_missing_clones_fail_clearly(tmp_path):
    buf = io.StringIO()
    code = run(start=str(ROOT), corpus=str(tmp_path), local_only=False, stream=buf)
    out = buf.getvalue()
    assert code == 2, out
    assert "flask" in out
    assert "httpx" in out
    assert "git clone https://github.com/pallets/flask" in out
    assert "GREENWASH_CORPUS" in out
    assert "published 1800-commit numbers not reproduced" in out
    assert "benchmarks/README.md" in out.replace("\\", "/")


def test_collect_marks_complete_clone(tmp_path):
    """A directory named flask that is a git repo with the pin is 'present'."""
    import json
    import subprocess

    flask_pin = json.loads((ROOT / "benchmarks" / "sweeps" / "flask.json").read_text(encoding="utf-8"))
    newest = flask_pin["corpus"]["newest_commit"]
    clone = tmp_path / "flask"
    clone.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "bench"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "bench@example.invalid"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=clone, check=True, capture_output=True)
    (clone / "README").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=clone, check=True, capture_output=True)
    # The pin is not in this toy clone — present but pin missing.
    report = collect(ROOT, corpus=str(tmp_path), local_only=False)
    flask = next(c for c in report.clones if c.name == "flask")
    assert flask.present
    assert not flask.pin_present
    assert "flask" in report.missing_clones
    # And newest is the published pin, not invented.
    assert flask.newest == newest
