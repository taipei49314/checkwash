"""Qualify the wheel and zipapp in isolated processes on hosted CI only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipapp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="quality-package-") as temporary:
        temp = Path(temporary)
        wheels, installed, repo = temp / "wheels", temp / "installed", temp / "repo"
        repo.mkdir()
        subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", str(root), "--wheel-dir", str(wheels)], check=True)
        wheel, = wheels.glob("*.whl")
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(installed), str(wheel)], check=True)
        archive = temp / "checkwash.pyz"
        zipapp.create_archive(root / "src", archive, main="checkwash.zipapp_entry:run", compressed=True)
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        git("init")
        git("config", "user.name", "quality-package-fixture")
        git("config", "user.email", "fixture@example.invalid")
        (repo / ".checkwash").mkdir()
        (repo / "src").mkdir()
        (repo / "src/code.py").write_text("x = 1\n", encoding="utf-8")
        policy = 'schema_version=1\nmode="enforce"\n'
        for tool, version in [("coverage", "7.16.0"), ("ruff", "0.16.6"), ("mypy", "2.3.1")]:
            policy += f'[[targets]]\nid="{tool}"\ntool="{tool}"\nroot="."\nconfig="pyproject.toml"\nprofile="{tool}-{version}-q1"\npaths=["src/"]\n'
        (repo / ".checkwash/quality.toml").write_text(policy, encoding="utf-8")
        config = '[tool.coverage.report]\nfail_under=85\n[tool.ruff.lint]\nselect=["F401"]\n[tool.mypy]\ndisallow_untyped_defs=true\n'
        (repo / "pyproject.toml").write_text(config, encoding="utf-8")
        git("add", ".")
        git("commit", "-m", "trusted fixture base")
        (repo / "pyproject.toml").write_text(config.replace("85", "50").replace('["F401"]', "[]").replace("true", "false"), encoding="utf-8")
        git("add", ".")
        git("commit", "-m", "trusted fixture weaker head")
        draft_repo = temp / "draft-repo"
        draft_repo.mkdir()
        subprocess.run(["git", "-C", str(draft_repo), "init"], check=True, capture_output=True)
        (draft_repo / "pyproject.toml").write_text(config, encoding="utf-8")
        (draft_repo / "code.py").write_text("x = 1\n", encoding="utf-8")
        reports, receipts = {}, []
        for name, command, pythonpath in [("wheel", [sys.executable, "-S", "-m", "checkwash"], str(installed)),
                                         ("zipapp", [sys.executable, "-S", str(archive)], "")]:
            env = {**os.environ, "PYTHONPATH": pythonpath, "CHECKWASH_TODAY": "2026-09-09", "PYTHONUTF8": "1"}
            def run(*args, expected=0):
                result = subprocess.run([*command, "quality", *args], cwd=repo, env=env, capture_output=True)
                assert result.returncode == expected, (name, args, result.stdout, result.stderr)
                return result.stdout
            inventory = json.loads(run("profiles"))
            assert len(inventory["profiles"]) == 3, inventory
            details = json.loads(run("profiles", "--details"))
            assert all(row["qualification_receipt"] for row in details["profiles"])
            setup = json.loads(run("doctor", "--format", "json"))
            assert setup["state"] == "configured" and setup["authority"] == "advisory_only", setup
            refused = json.loads(run("init", "--format", "json", expected=2))
            assert refused["state"] == "error" and (repo / ".checkwash/quality.toml").read_text(encoding="utf-8") == policy
            draft = json.loads(run("init", "--repo", str(draft_repo), "--format", "json"))
            assert draft["state"] == "draft" and len(draft["targets"]) == 3
            assert not (draft_repo / ".checkwash/quality.toml").exists()
            reports[name] = run("HEAD~1..HEAD", "--format", "json", expected=1)
            assert reports[name] == run("HEAD~1..HEAD", "--format", "json", expected=1)
            payload = json.loads(reports[name])
            assert payload["analysis_status"] == "complete" and payload["summary"]["high"] == 3, payload
            assert json.loads(run("HEAD..HEAD", "--format", "json"))["verdict"] == "no_blocking_finding"
            assert json.loads(run("MISSING..HEAD", "--format", "json", expected=2))["verdict"] == "error"
            assert json.loads(run("HEAD~1..HEAD", "--format", "sarif", expected=1))["runs"][0]["tool"]["driver"]["name"] == "checkwash-quality"
            assert b"QW_THRESHOLD_LOWERED" in run("HEAD~1..HEAD", expected=1)
            (output / (name + "-quality.json")).write_bytes(reports[name])
            receipts.append({"distribution": name, "profiles": len(inventory["profiles"]), "process_exits": [0, 1, 2], "json_repeat_identical": True,
                             "setup_doctor_advisory": True, "setup_init_draft_only": True,
                             "setup_init_existing_policy_refused": True, "profile_details": True})
        assert reports["wheel"] == reports["zipapp"]
        receipt = {"status": "passed", "receipts": receipts, "wheel_zipapp_identical": True,
                   "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                   "zipapp_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
        (output / "package-qualification.json").write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
