"""Run a pinned Action without importing or installing from its subject tree."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
import uuid


ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 600


def path_value(value: str) -> Path:
    """Accept native paths, including Windows drive paths passed from Bash."""
    if not value or any(c in value for c in "\r\n\0"):
        raise ValueError("missing or invalid path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("path must be absolute")
    return path.resolve(strict=True)


def trusted_path(env: dict[str, str]) -> str:
    """Do not inherit executable search paths from the subject or caller PATH."""
    paths = [str(Path(sys.executable).resolve().parent)]
    if os.name == "nt":
        system = path_value(env.get("SYSTEMROOT") or env["SystemRoot"])
        program = path_value(env.get("PROGRAMFILES") or env["ProgramFiles"])
        paths += [str(system / "System32"), str(system),
                  str(program / "Git" / "cmd"), str(program / "Git" / "bin"),
                  str(program / "Git" / "usr" / "bin")]
    else:
        paths += ["/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    return os.pathsep.join(path for path in paths if Path(path).is_dir())


def child_environment(env: dict[str, str], temporary: Path) -> dict[str, str]:
    """Isolation flags do not sanitize PEP 517 children; sanitize before spawn."""
    blocked = {"BASH_ENV", "ENV", "CDPATH", "VIRTUAL_ENV", "CONDA_PREFIX",
               "__PYVENV_LAUNCHER__", "LD_PRELOAD", "LD_LIBRARY_PATH",
               "DYLD_INSERT_LIBRARIES", "DYLD_LIBRARY_PATH", "GH_TOKEN",
               "GITHUB_TOKEN", "SSH_ASKPASS", "GIT_ASKPASS", "REQUESTS_CA_BUNDLE",
               "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR", "HTTP_PROXY",
               "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "NETRC"}
    clean = {key: value for key, value in env.items()
             if key.upper() not in blocked
             and not key.upper().endswith("_TOKEN")
             and not key.upper().startswith(("PYTHON", "PIP_", "GIT_", "PYENV_"))}
    home = temporary / "home"
    home.mkdir(exist_ok=True)
    clean.update(PATH=trusted_path(env), PIP_CONFIG_FILE=os.devnull, HOME=str(home),
                 USERPROFILE=str(home), APPDATA=str(home), LOCALAPPDATA=str(home),
                 XDG_CONFIG_HOME=str(home), XDG_CACHE_HOME=str(home),
                 TMPDIR=str(temporary), TEMP=str(temporary), TMP=str(temporary),
                 GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                 GIT_TERMINAL_PROMPT="0")
    return clean


def output_values(path: str, values: dict[str, object]) -> None:
    rows = []
    for key, value in values.items():
        text = str(value)
        if any(c in key + text for c in "\r\n\0") or "=" in key:
            raise ValueError("invalid Action output")
        rows.append(f"{key}={text}\n")
    with open(path, "a", encoding="utf-8", newline="\n") as stream:
        stream.writelines(rows)


def save_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def raise_walk_error(error: OSError) -> None:
    raise error


def source_manifest(root: Path, *, reject_cache: bool = False) -> dict[str, str]:
    """Read bytes only; importing an unverified package would be too late."""
    manifest = {}
    if not root.is_dir() or root.is_symlink():
        raise ValueError("runtime package directory is missing or linked")
    for directory, names, files in os.walk(root, followlinks=False, onerror=raise_walk_error):
        base = Path(directory)
        for name in names:
            if (base / name).is_symlink():
                raise ValueError("linked directory in runtime package")
            if reject_cache and name == "__pycache__":
                raise ValueError("bytecode cache in installed runtime package")
        names[:] = sorted(name for name in names if name != "__pycache__")
        for name in sorted(files):
            path = base / name
            if path.is_symlink():
                raise ValueError("linked file in runtime package")
            if name.endswith((".pyc", ".pyo")):
                if reject_cache:
                    raise ValueError("bytecode in installed runtime package")
                continue
            if not path.is_file():
                raise ValueError("nonregular runtime package file")
            manifest[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    if "__init__.py" not in manifest or "__main__.py" not in manifest:
        raise ValueError("runtime entry points missing")
    return manifest


def manifest_digest(manifest: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def identity() -> dict[str, object]:
    if not sys.flags.isolated or not sys.flags.utf8_mode or not sys.dont_write_bytecode or sys.version_info < (3, 11):
        raise ValueError("requires Python 3.11+ with -I -B -X utf8")
    if sys.prefix == sys.base_prefix:
        raise ValueError("runtime must be a private virtual environment")
    expected = source_manifest(ROOT / "src" / "checkwash")
    installed_root = Path(sysconfig.get_path("purelib")) / "checkwash"
    installed = source_manifest(installed_root, reject_cache=True)
    if installed != expected:
        raise ValueError("installed Checkwash content differs from pinned Action source")
    distribution = importlib.metadata.distribution("checkwash")
    if Path(distribution.locate_file("checkwash")).resolve() != installed_root.resolve():
        raise ValueError("distribution metadata points outside the verified package")
    expected_version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    if distribution.version != expected_version:
        raise ValueError("installed Checkwash version differs from pinned Action source")
    return {"python": sys.executable, "python_version": sys.version.split()[0],
            "base_python": str(Path(sys._base_executable).resolve()),
            "isolated": bool(sys.flags.isolated), "utf8": bool(sys.flags.utf8_mode),
            "bytecode_writes_disabled": sys.dont_write_bytecode,
            "source_root": str(ROOT), "package_root": str(installed_root.resolve()),
            "version": distribution.version, "runtime_files": len(installed),
            "source_digest": manifest_digest(expected)}


def private_directory(env: dict[str, str]) -> Path:
    temporary = path_value(env["RUNNER_TEMP"])
    workspace = path_value(env["GITHUB_WORKSPACE"])
    if temporary.is_relative_to(workspace):
        raise ValueError("RUNNER_TEMP must be outside the subject checkout")
    return Path(tempfile.mkdtemp(prefix="checkwash-action-", dir=temporary)).resolve()


def install(env: dict[str, str]) -> int:
    if not sys.flags.isolated or not sys.flags.utf8_mode or sys.version_info < (3, 11):
        raise ValueError("requires Python 3.11+ with -I -X utf8")
    workspace = path_value(env["GITHUB_WORKSPACE"])
    if Path(sys.executable).resolve().is_relative_to(workspace):
        raise ValueError("bootstrap Python cannot be inside the subject checkout")
    directory = private_directory(env)
    clean = child_environment(env, directory)
    venv = directory / "environment"
    subprocess.run([sys.executable, "-I", "-X", "utf8", "-m", "venv", str(venv)],
                   cwd=directory, env=clean, check=True, timeout=TIMEOUT)
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    installed = subprocess.run([str(python), "-I", "-X", "utf8", "-m", "pip", "--isolated",
                    "--disable-pip-version-check", "--no-input",
                    "--verbose", "install", "--no-deps", "--no-compile", "--no-cache-dir",
                    "--index-url", "https://pypi.org/simple", "--report", str(directory / "install-report.json"),
                    str(ROOT)], cwd=directory, env=clean, capture_output=True, timeout=TIMEOUT)
    (directory / "install-stdout.txt").write_bytes(installed.stdout)
    (directory / "install-stderr.txt").write_bytes(installed.stderr)
    safe_log(installed.stdout + installed.stderr)
    installed.check_returncode()
    verified = subprocess.run([str(python), "-I", "-B", "-X", "utf8", str(Path(__file__).resolve()), "identity"],
                              cwd=directory, env=clean, capture_output=True, check=True, timeout=60)
    receipt = json.loads(verified.stdout)
    save_json(directory / "identity.json", receipt)
    output_values(env["GITHUB_OUTPUT"], {"python": str(python), "directory": str(directory),
                                         "identity_path": str(directory / "identity.json")})
    print("Checkwash Action verified", receipt["version"], receipt["source_digest"])
    return 0


def runtime_directory(env: dict[str, str]) -> Path:
    directory = path_value(env["CHECKWASH_RUNTIME_DIRECTORY"])
    temporary = path_value(env["RUNNER_TEMP"])
    workspace = path_value(env["GITHUB_WORKSPACE"])
    if directory == temporary or not directory.is_relative_to(temporary) or directory.is_relative_to(workspace):
        raise ValueError("runtime directory must be private runner temporary storage")
    # Resolve the venv directory, not its Unix interpreter symlink target.
    if Path(sys.prefix).resolve() != directory / "environment":
        raise ValueError("runtime interpreter does not match the installation receipt")
    return directory


def git_commit(git: str, repo: Path, value: str, clean: dict[str, str]) -> str:
    if not value or any(c in value for c in "\r\n\0"):
        raise ValueError("invalid Git ref")
    result = subprocess.run([git, "-C", str(repo), "rev-parse", "--verify", "--end-of-options",
                             value + "^{commit}"], env=clean, capture_output=True, check=True, timeout=60)
    commit = result.stdout.decode("ascii").strip()
    if len(commit) not in {40, 64} or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("Git returned invalid commit identity")
    return commit


def safe_log(data: bytes) -> None:
    # A finding contains subject-controlled evidence; do not execute its workflow commands.
    token = "checkwash-" + uuid.uuid4().hex
    print("::stop-commands::" + token, flush=True)
    try:
        sys.stdout.buffer.write(data)
        if data and not data.endswith(b"\n"):
            sys.stdout.buffer.write(b"\n")
        sys.stdout.buffer.flush()
    finally:
        print("::" + token + "::", flush=True)


def check(env: dict[str, str]) -> int:
    directory = runtime_directory(env)
    clean = child_environment(env, directory)
    receipt: dict[str, object] = {"action_receipt_version": 1, "exit_code": 2,
                                 "analysis_exit_code": "unavailable", "error": None}
    try:
        receipt["identity"] = identity()
        repo = path_value(env["GITHUB_WORKSPACE"])
        git = shutil.which("git", path=clean["PATH"])
        if not git:
            raise ValueError("trusted runner Git is unavailable")
        fail_on = env.get("CHECKWASH_FAIL_ON", "high")
        if fail_on not in {"info", "warn", "high", "critical"}:
            raise ValueError("invalid fail-on input")
        requested = env.get("CHECKWASH_BASE") or env.get("CHECKWASH_PR_BASE") or "HEAD~1"
        base = git_commit(git, repo, requested, clean)
        head = git_commit(git, repo, "HEAD", clean)
        receipt.update(base=base, head=head, fail_on=fail_on)
        result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-m", "checkwash", "check",
                                 base + "..." + head, "--repo", str(repo), "--fail-on", fail_on,
                                 "--format", "term"], cwd=directory, env=clean,
                                capture_output=True, timeout=TIMEOUT)
        receipt["analysis_exit_code"] = result.returncode
        receipt["exit_code"] = result.returncode if result.returncode in {0, 1, 2} else 2
        if result.returncode not in {0, 1, 2}:
            receipt["error"] = "engine returned an unexpected exit code"
        (directory / "stdout.txt").write_bytes(result.stdout)
        (directory / "stderr.txt").write_bytes(result.stderr)
        safe_log(result.stdout + result.stderr)
        with open(env["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8", newline="\n") as stream:
            stream.write(result.stdout.decode("utf-8", errors="replace"))
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError) as exc:
        receipt["exit_code"] = 2
        receipt["error"] = "Action integration failed: " + type(exc).__name__
        print(receipt["error"], file=sys.stderr)
    save_json(directory / "check-receipt.json", receipt)
    output_values(env["GITHUB_OUTPUT"], {"exit_code": receipt["exit_code"],
                                         "analysis_exit_code": receipt["analysis_exit_code"],
                                         "receipt_path": str(directory / "check-receipt.json"),
                                         "base": receipt.get("base", ""), "head": receipt.get("head", ""),
                                         "fail_on": receipt.get("fail_on", "")})
    return int(receipt["exit_code"])


def comment(env: dict[str, str]) -> int:
    if not env.get("PR_NUMBER") or not env.get("GH_TOKEN"):
        print("comment-pr skipped: not a pull_request or no token")
        return 0
    directory = runtime_directory(env)
    identity()
    clean = child_environment(env, directory)
    receipt = json.loads((directory / "check-receipt.json").read_text(encoding="utf-8"))
    if receipt["analysis_exit_code"] not in {0, 1} or receipt["error"]:
        print("comment-pr skipped: no completed analysis")
        return 0
    repo = path_value(env["GITHUB_WORKSPACE"])
    result = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", "-m", "checkwash", "check",
                             receipt["base"] + "..." + receipt["head"], "--repo", str(repo),
                             "--fail-on", receipt["fail_on"], "--format", "json"],
                            cwd=directory, env=clean, capture_output=True, timeout=TIMEOUT)
    if result.returncode != receipt["analysis_exit_code"]:
        print("comment-pr skipped: analysis result changed")
        return 0
    report = directory / "findings.json"
    # Reject invalid output before the helper is allowed to use its network token.
    json.loads(result.stdout)
    report.write_bytes(result.stdout)
    clean.update(GH_TOKEN=env["GH_TOKEN"], GH_REPO=env.get("GH_REPO", ""), PR_NUMBER=env["PR_NUMBER"])
    posted = subprocess.run([sys.executable, "-I", "-B", "-X", "utf8", str(ROOT / "action" / "post_review.py"), str(report)],
                            cwd=directory, env=clean, capture_output=True, timeout=60)
    safe_log(posted.stdout + posted.stderr)
    if posted.returncode:
        print("comment-pr soft-failed; the check verdict still stands")
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    try:
        if mode == "identity":
            print(json.dumps(identity(), sort_keys=True))
            return 0
        if mode == "install":
            return install(dict(os.environ))
        if mode == "check":
            return check(dict(os.environ))
        if mode == "comment":
            return comment(dict(os.environ))
        raise ValueError("unknown Action mode")
    except (OSError, ValueError, KeyError, subprocess.SubprocessError, importlib.metadata.PackageNotFoundError) as exc:
        # Avoid echoing untrusted subprocess output into the Actions command channel.
        print("Checkwash Action integration failed:", type(exc).__name__, file=sys.stderr)
        return 0 if mode == "comment" else 2


if __name__ == "__main__":
    raise SystemExit(main())
