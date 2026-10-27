"""Replay admitted composite blocks on an authorized local Windows host.

Run with an audited Python outside the subject checkout, using -I -B -X utf8.
Only the frozen, reviewed Action definition below is supported. The comment
step is disabled. A new Action definition needs a new source review, not a
permissive expression evaluator. Installation retains the Action's actual
PEP 517 behavior (including its network-resolved build dependencies).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

_ROUTE_SPEC = importlib.util.spec_from_file_location("_trusted_receipt_route", Path(__file__).with_name("receipt_execution_route.py"))
_ROUTE = importlib.util.module_from_spec(_ROUTE_SPEC)
_ROUTE_SPEC.loader.exec_module(_ROUTE)
HOST = _ROUTE.HOST
execution_route = _ROUTE.current_route
ACTION_SHA = "d6eda4f695fabb8e7d138f7a87b099d2028f0294"
ACTION_YAML_SHA256 = "94abd7b990e5611e9d091678247cece7fe51f28c19faad6b0d954efa45408e83"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")


def regular(path, directory=False):
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
            "symlink/reparse point: " + str(path))
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
            "nonregular path: " + str(path))


def absolute_path(value, *, directory=False, exists=True):
    path = Path(value)
    require(path.is_absolute() and not any(c in str(path) for c in "\r\n\0"), "absolute single-line path required")
    path = Path(os.path.abspath(path))
    for ancestor in reversed(path.parents):
        if ancestor.exists():
            regular(ancestor, directory=True)
    if exists:
        regular(path, directory=directory)
    else:
        require(not path.exists(), "output already exists: " + str(path))
    return path


def outside(path, root):
    require(path != root and not path.is_relative_to(root), "path must be outside subject checkout: " + str(path))


def clean_environment(python, git, bash, temporary):
    """Construct an allowlist; do not copy caller credentials or configuration."""
    system = absolute_path(os.environ.get("SystemRoot", r"C:\Windows"), directory=True)
    program = absolute_path(os.environ.get("ProgramFiles", r"C:\Program Files"), directory=True)
    paths = [python.parent, git.parent, bash.parent, program / "Git" / "usr" / "bin",
             system / "System32", system]
    home = temporary / "home"
    home.mkdir(parents=True, exist_ok=True)
    return {
        "SystemRoot": str(system), "WINDIR": str(system), "ProgramFiles": str(program),
        "COMSPEC": str(system / "System32" / "cmd.exe"),
        "PATH": os.pathsep.join(str(p) for p in dict.fromkeys(paths) if p.is_dir()),
        "PATHEXT": ".COM;.EXE;.BAT;.CMD", "HOME": str(home), "USERPROFILE": str(home),
        "APPDATA": str(home), "LOCALAPPDATA": str(home), "XDG_CONFIG_HOME": str(home),
        "XDG_CACHE_HOME": str(home), "TEMP": str(temporary), "TMP": str(temporary),
        "TMPDIR": str(temporary), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0", "PIP_CONFIG_FILE": os.devnull,
        "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "NO_COLOR": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    }


def run_record(name, argv, *, cwd, env, output, timeout, ledger):
    require(re.fullmatch(r"[a-z0-9-]+", name), "invalid command name")
    require(not any(row["name"] == name for row in ledger), "duplicate command name")
    logs = output / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stdout, stderr = logs / (name + ".stdout"), logs / (name + ".stderr")
    started = datetime.now(timezone.utc).isoformat()
    tick = time.monotonic()
    timed_out = False
    exit_code = 125
    with stdout.open("xb") as out, stderr.open("xb") as err:
        try:
            proc = subprocess.Popen([str(a) for a in argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=err, shell=False)
            try:
                exit_code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                # Kill the tree, not just Bash/Python, before any final source check.
                killer = Path(env["SystemRoot"]) / "System32" / "taskkill.exe"
                killed = subprocess.run([str(killer), "/PID", str(proc.pid), "/T", "/F"],
                                        env=env, stdin=subprocess.DEVNULL, stdout=err, stderr=err, timeout=60)
                if killed.returncode and proc.poll() is None:
                    proc.kill()
                proc.wait(timeout=60)
                exit_code = 124
        except OSError as exc:
            err.write((type(exc).__name__ + ": " + str(exc)).encode("utf-8", errors="replace"))
    row = dict(name=name, argv=[str(a) for a in argv], cwd=str(cwd), started_at=started,
               finished_at=datetime.now(timezone.utc).isoformat(), duration_seconds=time.monotonic() - tick,
               exit_code=exit_code, timed_out=timed_out,
               stdout=stdout.relative_to(output).as_posix(), stderr=stderr.relative_to(output).as_posix())
    ledger.append(row)
    save_json(output / "command-ledger.json", ledger)
    return row


class GitReader:
    def __init__(self, git, env, output):
        self.git, self.env, self.output = git, env, output
        self.ledger = []

    def read(self, root, *args):
        name = "git-" + str(len(self.ledger)).zfill(5)
        row = run_record(name, [self.git, "-c", "core.hooksPath=" + os.devnull,
                               "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
                               "-C", root, *args], cwd=self.output, env=self.env,
                         output=self.output, timeout=120, ledger=self.ledger)
        require(row["exit_code"] == 0, "Git read failed: " + " ".join(args))
        return (self.output / row["stdout"]).read_bytes()

    def text(self, root, *args):
        return self.read(root, *args).decode("utf-8").strip()


def snapshot(reader, root, commit):
    require(re.fullmatch(r"[0-9a-f]{40}", commit), "full Git commit required")
    require(reader.text(root, "rev-parse", "HEAD") == commit, "checkout HEAD mismatch")
    require(reader.text(root, "rev-parse", "--show-toplevel").replace("\\", "/").casefold()
            == root.as_posix().casefold(), "checkout root mismatch")
    require(not reader.read(root, "status", "--porcelain=v1", "--untracked-files=all"), "dirty source checkout")
    members = {}
    for row in reader.read(root, "ls-tree", "-r", "-z", commit).split(b"\0"):
        if not row:
            continue
        header, name = row.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        relative = name.decode("utf-8")
        require(mode in ("100644", "100755") and kind == "blob", "nonregular Git member")
        require(relative and "\\" not in relative and ":" not in relative
                and all(p not in ("", ".", "..") for p in relative.split("/")), "unsafe Git member")
        path = absolute_path(root / relative)
        raw = path.read_bytes()
        require(hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == oid,
                "checkout bytes differ from Git blob: " + relative)
        members[relative] = dict(git_blob=oid, sha256=digest(raw), bytes=len(raw))
    require(members, "empty checkout")
    return members


def load_action(raw):
    require(digest(raw) == ACTION_YAML_SHA256, "unsupported Action YAML; source review required")
    import yaml

    class UniqueLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            require(key not in result, "duplicate YAML field")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    value = yaml.load(raw.decode("utf-8"), Loader=UniqueLoader)
    require(set(value) == {"name", "description", "branding", "inputs", "outputs", "runs"}, "Action schema differs")
    require(set(value["inputs"]) == {"fail-on", "base", "comment-pr", "python-path"}, "Action inputs differ")
    require(value["inputs"]["comment-pr"]["default"] == "false", "comment default differs")
    expected_outputs = {"exit-code": "${{ steps.check.outputs.exit_code }}",
                        "receipt-path": "${{ steps.check.outputs.receipt_path }}",
                        "identity-path": "${{ steps.install.outputs.identity_path }}"}
    require({k: v["value"] for k, v in value["outputs"].items()} == expected_outputs, "Action outputs differ")
    require(set(value["runs"]) == {"using", "steps"} and value["runs"]["using"] == "composite", "not admitted composite")
    steps = value["runs"]["steps"]
    require([step["id"] for step in steps] == ["install", "check", "comment"], "Action step order differs")
    maps = [
        {"CW_ACTION_PATH": "${{ github.action_path }}", "CW_REQUESTED_PYTHON": "${{ inputs.python-path }}",
         "CW_PYTHON_LOCATION": "${{ env.pythonLocation }}"},
        {"CW_ACTION_PATH": "${{ github.action_path }}", "CW_PYTHON": "${{ steps.install.outputs.python }}",
         "CHECKWASH_RUNTIME_DIRECTORY": "${{ steps.install.outputs.directory }}",
         "CHECKWASH_BASE": "${{ inputs.base }}", "CHECKWASH_FAIL_ON": "${{ inputs.fail-on }}",
         "CHECKWASH_PR_BASE": "${{ github.event.pull_request.base.sha }}"},
        {"CW_ACTION_PATH": "${{ github.action_path }}", "CW_PYTHON": "${{ steps.install.outputs.python }}",
         "CHECKWASH_RUNTIME_DIRECTORY": "${{ steps.install.outputs.directory }}", "GH_TOKEN": "${{ github.token }}",
         "GH_REPO": "${{ github.repository }}", "PR_NUMBER": "${{ github.event.pull_request.number }}"},
    ]
    for step, expected in zip(steps, maps):
        keys = {"id", "shell", "env", "run"} | ({"if"} if step["id"] == "comment" else set())
        require(set(step) == keys and step["shell"] == "bash" and step["env"] == expected
                and type(step["run"]) is str and step["run"], "unsupported Action step")
    require(steps[2]["if"] == "${{ inputs.comment-pr == 'true' }}", "unsupported comment condition")
    return value


def parse_outputs(raw, expected):
    result = {}
    for line in raw.decode("utf-8").splitlines():
        require("=" in line and "\0" not in line, "invalid Action output syntax")
        key, value = line.split("=", 1)
        require(key in expected and key not in result and value, "unexpected/duplicate/empty Action output")
        result[key] = value
    require(set(result) == set(expected), "missing Action outputs")
    return result


def replay(*, source, action, action_sha, base, head, python, git, bash, output, scratch):
    route = execution_route()
    require(sys.flags.isolated and sys.dont_write_bytecode and sys.flags.utf8_mode,
            "replayer requires -I -B -X utf8")
    require(re.fullmatch(r"[0-9a-f]{40}", base) and re.fullmatch(r"[0-9a-f]{40}", head), "full base/head required")
    for path in (Path(__file__).resolve(), action, python, git, bash, output, scratch):
        outside(path, source)
    require(action != source and not source.is_relative_to(action), "separate Action checkout required")
    output.mkdir(parents=True, exist_ok=False)
    scratch.mkdir(parents=True, exist_ok=False)
    env = clean_environment(python, git, bash, scratch)
    # secure.py deliberately selects this Git-for-Windows installation itself.
    require(git == Path(env["ProgramFiles"]) / "Git" / "cmd" / "git.exe"
            and bash == Path(env["ProgramFiles"]) / "Git" / "bin" / "bash.exe", "unexpected Git/Bash installation")
    reader = GitReader(git, env, output / "git-evidence")
    reader.output.mkdir()
    receipt = dict(schema_version=1, kind="checkwash.pju-action-replay.v1", provenance=route["action_provenance"],
                   status="failed", host=route["host"], action_sha=action_sha, action_tree=None, action_yaml_sha256=None,
                   base_sha=base, head_sha=head, fail_on="high", comment_pr=False,
                   steps=[], resolved_outputs={}, files={}, errors=[])
    ledger = []
    try:
        before = snapshot(reader, source, head)
        action_before = snapshot(reader, action, action_sha)
        require(reader.text(source, "rev-parse", base + "^{commit}") == base, "base unavailable")
        receipt["action_tree"] = reader.text(action, "rev-parse", "HEAD^{tree}")
        raw = (action / "action/action.yml").read_bytes()
        definition = load_action(raw)
        (output / "action.yml").write_bytes(raw)
        receipt["files"]["action_yaml"] = "action.yml"
        receipt["action_yaml_sha256"] = digest(raw)
        env.update(RUNNER_OS="Windows", GITHUB_WORKSPACE=str(source), RUNNER_TEMP=str(scratch),
                   GITHUB_STEP_SUMMARY=str(output / "step-summary.md"))
        expressions = {"${{ github.action_path }}": str(action / "action"), "${{ inputs.python-path }}": str(python),
                       "${{ env.pythonLocation }}": str(python.parent), "${{ inputs.base }}": base,
                       "${{ inputs.fail-on }}": "high", "${{ github.event.pull_request.base.sha }}": base}
        outputs = {}
        for step in definition["runs"]["steps"][:2]:
            sid = step["id"]
            script = output / (sid + ".bash")
            script.write_bytes(step["run"].encode("utf-8"))
            receipt["files"][sid + "_run"] = script.name
            outpath = output / (sid + ".outputs")
            outpath.write_bytes(b"")
            step_env = {**env, "GITHUB_OUTPUT": str(outpath)}
            for key, expression in step["env"].items():
                require(expression in expressions, "unresolved Action expression")
                step_env[key] = expressions[expression]
            row = run_record(sid, [bash, "--noprofile", "--norc", "-e", "-o", "pipefail", script.as_posix()],
                             cwd=scratch, env=step_env, output=output, timeout=1500, ledger=ledger)
            result = dict(id=sid, exit_code=row["exit_code"], run_sha256=digest(script.read_bytes()),
                          stdout=row["stdout"], stderr=row["stderr"], outputs={})
            receipt["steps"].append(result)
            receipt["files"][sid + "_stdout"] = row["stdout"]
            receipt["files"][sid + "_stderr"] = row["stderr"]
            expected = {"python", "directory", "identity_path"} if sid == "install" else {
                "exit_code", "analysis_exit_code", "receipt_path", "base", "head", "fail_on"}
            if outpath.stat().st_size:
                outputs[sid] = parse_outputs(outpath.read_bytes(), expected)
                result["outputs"] = outputs[sid]
            require(row["exit_code"] == 0 and not row["timed_out"], "Action " + sid + " failed")
            require(sid in outputs, "Action outputs missing")
            if sid == "install":
                directory = absolute_path(outputs[sid]["directory"], directory=True)
                require(directory.is_relative_to(scratch) and directory != scratch, "Action directory escaped scratch")
                require(absolute_path(outputs[sid]["python"]) == directory / "environment/Scripts/python.exe",
                        "Action interpreter escaped its venv")
                require(absolute_path(outputs[sid]["identity_path"]) == directory / "identity.json", "identity path differs")
                for key, value in outputs[sid].items():
                    expressions["${{ steps.install.outputs." + key + " }}"] = value
            else:
                require(outputs[sid]["base"] == base and outputs[sid]["head"] == head
                        and outputs[sid]["fail_on"] == "high" and outputs[sid]["exit_code"] == "0"
                        and outputs[sid]["analysis_exit_code"] == "0", "Action checked the wrong range or failed")
                require(absolute_path(outputs[sid]["receipt_path"]) == directory / "check-receipt.json", "receipt path differs")
        receipt["resolved_outputs"] = {"exit-code": outputs["check"]["exit_code"],
                                       "receipt-path": outputs["check"]["receipt_path"],
                                       "identity-path": outputs["install"]["identity_path"]}
        require(snapshot(reader, source, head) == before, "subject source changed during Action")
        require(snapshot(reader, action, action_sha) == action_before, "Action source changed during replay")
        receipt["status"] = "completed"
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        receipt["errors"].append(type(exc).__name__ + ": " + str(exc))
    finally:
        # Include raw installation/identity/check artifacts even when a step failed.
        candidates = list(scratch.glob("checkwash-action-*"))
        if len(candidates) == 1 and candidates[0].is_dir():
            absolute_path(candidates[0], directory=True)
            saved = output / "runtime-receipts"
            saved.mkdir(exist_ok=True)
            names = {"identity.json": "identity", "check-receipt.json": "check_receipt",
                     "install-report.json": "install_report", "install-stdout.txt": "pip_stdout",
                     "install-stderr.txt": "pip_stderr", "stdout.txt": "engine_stdout", "stderr.txt": "engine_stderr"}
            for name, key in names.items():
                path = candidates[0] / name
                if path.exists():
                    absolute_path(path)
                    shutil.copyfile(path, saved / name)
                    receipt["files"][key] = (saved / name).relative_to(output).as_posix()
        save_json(output / "replay.json", receipt)
    return 0 if receipt["status"] == "completed" else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "action-root", "python", "git", "bash", "output", "scratch"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--action-sha", default=ACTION_SHA)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args(argv)
    return replay(source=absolute_path(args.source_root, directory=True), action=absolute_path(args.action_root, directory=True),
                  action_sha=args.action_sha, base=args.base_sha, head=args.head_sha,
                  python=absolute_path(args.python), git=absolute_path(args.git), bash=absolute_path(args.bash),
                  output=absolute_path(args.output, exists=False), scratch=absolute_path(args.scratch, exists=False))


if __name__ == "__main__":
    raise SystemExit(main())
