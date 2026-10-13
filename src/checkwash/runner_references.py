"""Finite source-visible runner references, not ambient process completeness.

An opaque source withholds omission proof. Returned calls preserve targetless
pytest declarations; an empty target tuple never means an empty collection.
"""
from __future__ import annotations

import configparser
import hashlib
import posixpath
import re
import shlex
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from checkwash.change import EngineError
from checkwash.ci_control_flow import _read_document, _step_command, is_github_workflow
from checkwash.gitio.snapshot import MAX_BATCH_BYTES, MAX_SOURCE_BYTES
from checkwash.roles import _is_runner_script, _runs_test_command


@dataclass(frozen=True)
class RunnerCall:
    source: str
    site: str
    cwd: str
    argv: tuple[str, ...]
    targets: tuple[str, ...]
    config_path: str | None
    positional_binding: tuple[str, ...] | None
    effective_config: str | None = None
    collection_modifiers: tuple[str, ...] = ()
    source_sha256: str = ""
    effective_config_sha256: str | None = None


@dataclass(frozen=True)
class Reference:
    source: str
    site: str
    kind: str
    path: str


@dataclass(frozen=True)
class ConfigOptions:
    source: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class ReferenceClosure:
    calls: tuple[RunnerCall, ...]
    references: tuple[Reference, ...]
    opaque: tuple[tuple[str, str, str], ...]
    config_options: tuple[ConfigOptions, ...]

    @property
    def complete(self) -> bool:
        return not self.opaque


_CONFIGS = frozenset({"pytest.toml", ".pytest.toml", "pytest.ini", ".pytest.ini",
                      "pyproject.toml", "tox.ini", "setup.cfg"})
_SHELLS = frozenset({"sh", "bash", "dash", "zsh", "ksh", "ash"})
_SIMPLE = re.compile(r"[A-Za-z0-9_./:=,+{}@%$-]+")
_TARGET = re.compile(r"[A-Za-z0-9_.-]+")
_Context = tuple[str, str, str, tuple[str, ...] | None]
_Entrypoint = tuple[str, str, str]


def _selected_command(text: str, *, python_entry: bool = True) -> bool:
    stripped = text.strip()
    if not stripped or stripped.startswith("#"):
        return False
    first = stripped.split(maxsplit=1)[0]
    return (_runs_test_command(stripped.encode("utf-8"))
            or posixpath.basename(first) in {"make", "gmake", "tox"}
            or "/" in first
            or python_entry and posixpath.basename(first) in {"python", "python3", "py", "pypy", "pypy3"}
            or first.startswith(("./", "../", "/", "$", "%", "{", "'", '"'))
            or posixpath.basename(first) in _SHELLS)


def _literal_path(value: str, cwd: str) -> str | None:
    if not value or any(char in value for char in "$%{}*?[]\\\r\n\0"):
        return None
    if value.startswith("/") or ":" in value:
        return None
    path = posixpath.normpath(posixpath.join(cwd, value))
    return None if path == ".." or path.startswith("../") else "" if path == "." else path


class _Closure:
    def __init__(self, sources: Mapping[str, bytes], paths: frozenset[str],
                 reserve_work: Callable[[int], None], ci_paths: frozenset[str]):
        self.sources = sources
        self.paths = paths
        self.reserve_work = reserve_work
        self.ci_paths = ci_paths
        self.identities = {path: hashlib.sha256(data).hexdigest() for path, data in sources.items()}
        self.calls: list[RunnerCall] = []
        self.references: list[Reference] = []
        self.opaque: list[tuple[str, str, str]] = []
        self.config_options: list[ConfigOptions] = []
        self.makefiles: dict[str, dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {}
        self.tox: dict[str, dict[str, str]] = {}
        self.pending: list[_Context] = []
        self.visited: set[_Context] = set()
        self.active: _Entrypoint | None = None
        self.edges: dict[_Entrypoint, set[_Entrypoint]] = {}
        self.settings: dict[str, dict] = {}

    def decline(self, source: str, site: str, reason: str) -> None:
        self.opaque.append((source, site, reason))

    def schedule(self, context: _Context) -> None:
        self.reserve_work(1)
        entry = context[:3]
        if self.active is not None:
            children = self.edges.setdefault(self.active, set())
            if entry not in children:
                # Binding is deliberately not part of this graph: a recursive
                # tox declaration can grow posargs forever without repeating
                # its full context. Supported bodies have no conditional exit.
                pending = [entry]
                reached = set()
                while pending:
                    self.reserve_work(1)
                    current = pending.pop()
                    if current == self.active:
                        self.decline(context[0], context[1], "cyclic runner entrypoint")
                        return
                    if current not in reached:
                        reached.add(current)
                        pending.extend(self.edges.get(current, ()))
                children.add(entry)
        self.pending.append(context)

    def reference(self, source: str, site: str, kind: str, value: str, cwd: str) -> None:
        path = _literal_path(value, cwd)
        if path is None:
            self.decline(source, site, "nonliteral " + kind + " reference")
        else:
            self.references.append(Reference(source, site, kind, path))

    def pytest_references(self, source: str, site: str, cwd: str,
                          args: list[str], *,
                          unbound_tox: bool = False) -> tuple[tuple[str, ...], str | None]:
        from checkwash.shadow import _pytest_cli

        # Keep the existing option/target contract. Explicit config slots are
        # checked separately: their variables must not become no-config.
        for index, word in enumerate(args):
            if word in {"-c", "--config-file"}:
                if index + 1 == len(args):
                    self.decline(source, site, "missing explicit config value")
                else:
                    self.reference(source, site, "config", args[index + 1], cwd)
            elif word.startswith("--config-file="):
                self.reference(source, site, "config", word.split("=", 1)[1], cwd)
            elif word.startswith("-c") and word != "-c":
                self.reference(source, site, "config", word[2:], cwd)
            elif word in {"-o", "--override-ini"} or word.startswith("--override-ini="):
                self.decline(source, site, "pytest option overrides require a separate context")
        targets, _, config_path = _pytest_cli(args)
        normalized = []
        for target in targets:
            if unbound_tox and target == "{posargs}":
                # A source-visible tox declaration has no actual positional
                # binding. Preserve its argv/None binding and targetless scope.
                continue
            value = _literal_path(target, cwd)
            if value is None:
                self.decline(source, site, "unsupported collection target")
            else:
                normalized.append(value)
                self.references.append(Reference(source, site, "collection", value))
        resolved_config = _literal_path(config_path, cwd) if config_path is not None else None
        return tuple(normalized), resolved_config

    def pytest(self, source: str, site: str, cwd: str, args: list[str],
               binding: tuple[str, ...] | None) -> None:
        normalized, resolved_config = self.pytest_references(
            source, site, cwd, args, unbound_tox=source in self.tox and binding is None)
        self.calls.append(RunnerCall(source, site, cwd, tuple(args), normalized,
                                     resolved_config, binding))

    def command(self, source: str, site: str, text: str, cwd: str = "",
                binding: tuple[str, ...] | None = None, neutral: bool = False) -> None:
        stripped = text.strip()
        if not stripped or stripped.startswith("#"):
            return
        # The existing content gate selects test obligations, not every tool
        # that a multi-purpose Makefile/workflow can execute. Literal make/tox
        # edges are also relevant. A dynamic executable remains opaque.
        literal_pip = re.match(r"(?:python(?:3)?|py|pypy3?)\s+-m\s+pip(?:\s|$)", stripped) is not None
        if "`" in stripped or "\0" in stripped:
            self.decline(source, site, "unsupported shell substitution or NUL")
            return
        if neutral and not literal_pip and any(_SIMPLE.fullmatch(word) is None for word in stripped.split()):
            self.decline(source, site, "shell dialect is unknown for non-neutral words")
            return
        try:
            lexer = shlex.shlex(stripped, posix=True, punctuation_chars=";&|()<>")
            lexer.whitespace_split = True
            lexer.commenters = "#"
            words = list(lexer)
        except ValueError:
            self.decline(source, site, "shell words could not be parsed")
            return
        if not words:
            return
        if any(word and all(char in ";&|()<>" for char in word) for word in words):
            self.decline(source, site, "shell control flow or redirection")
            return
        executable = words[0]
        base = posixpath.basename(executable)
        args = words[1:]
        if base in {"pytest", "pytest.exe", "py.test", "py.test.exe"}:
            self.pytest(source, site, cwd, args, binding)
        elif base in {"python", "python3", "py", "pypy", "pypy3"} and args[:2] == ["-m", "pytest"]:
            self.pytest(source, site, cwd, args[2:], binding)
        elif base in {"make", "gmake"}:
            if any(not _TARGET.fullmatch(word) for word in args):
                self.decline(source, site, "make options, expansion or nonliteral target")
                return
            path = posixpath.join(cwd, "Makefile")
            self.references.append(Reference(source, site, "makefile", path))
            rules = self.makefiles.get(path)
            if not rules:
                self.decline(source, site, "make source missing or outside rule grammar")
                return
            for target in args or [next(iter(rules))]:
                self.schedule((path, target, cwd, None))
        elif base == "tox":
            try:
                separator = args.index("--")
            except ValueError:
                separator = len(args)
            options, posargs = args[:separator], tuple(args[separator + 1:])
            if options not in ([], ["-p"], ["--parallel"]):
                self.decline(source, site, "tox options outside the finite environment union")
                return
            if any(any(char in word for char in "$%{}") for word in posargs):
                self.decline(source, site, "source-visible tox positional expansion")
                return
            path = posixpath.join(cwd, "tox.ini")
            self.references.append(Reference(source, site, "tox-config", path))
            if path not in self.tox:
                self.decline(source, site, "tox command source missing or unsupported")
                return
            for environment in self.tox[path]:
                self.schedule((path, environment, cwd, posargs))
        elif base in _SHELLS:
            if len(args) != 1:
                self.decline(source, site, "shell invocation outside literal one-script grammar")
            else:
                self.reference(source, site, "script", args[0], cwd)
                self.decline(source, site, "referenced script requires transitive source proof")
        elif executable.startswith(("./", "../", "/")) or "/" in executable:
            self.reference(source, site, "script", executable, cwd)
            self.decline(source, site, "direct script requires transitive source proof")
        elif any(char in executable for char in "$%{}"):
            self.decline(source, site, "nonliteral executable")
        elif base in {"python", "python3", "py", "pypy", "pypy3"}:
            if args[:2] == ["-m", "pip"]:
                return  # Literal installation command is not a pytest call.
            self.decline(source, site, "Python invocation outside pytest/pip grammar")
        elif base in {"echo", "printf", "git", "rm", "ln", "openssl", "twine"}:
            return  # Data/tool operations, not a recognized pytest entrypoint.
        else:
            self.decline(source, site, "unclassified executable")

    def make(self, path: str, text: str) -> None:
        rules: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
        active = None
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.startswith("\t"):
                if active is None:
                    self.decline(path, str(number), "recipe without a supported rule")
                    continue
                dependencies, commands = rules[active]
                rules[active] = dependencies, (*commands, line[1:].removeprefix("@"))
                continue
            active = None
            if line.startswith(".PHONY:"):
                continue
            match = re.fullmatch(r"([A-Za-z0-9_.-]+):\s*([A-Za-z0-9_. -]*)", line)
            if match is None or match.group(1) in rules:
                self.decline(path, str(number), "Make declaration/expansion outside literal rules")
                continue
            active = match.group(1)
            rules[active] = tuple(match.group(2).split()), ()
        self.makefiles[path] = rules

    def config(self, path: str, text: str) -> None:
        name = posixpath.basename(path)
        if name in {"pytest.toml", ".pytest.toml"}:
            self.decline(path, "config", "pytest TOML schema outside the admitted grammar")
            return
        try:
            if name.endswith(".toml"):
                parsed = tomllib.loads(text)
                settings = (parsed.get("tool", {}).get("pytest", {}).get("ini_options", {})
                            if name == "pyproject.toml" else parsed.get("pytest", {}).get("ini_options", {}))
                if not isinstance(settings, dict):
                    raise ValueError("pytest settings are not a mapping")
            else:
                parser = configparser.RawConfigParser(interpolation=None, strict=True)
                parser.read_string(text)
                sections = [section for section in ("pytest", "tool:pytest") if parser.has_section(section)]
                settings = dict(parser.items(sections[0])) if sections else {}
                if len(sections) > 1:
                    raise ValueError("multiple pytest sections")
                if name == "tox.ini":
                    base = dict(parser.items("testenv")) if parser.has_section("testenv") else {}
                    commands = {}
                    for section in parser.sections():
                        if section != "testenv" and not section.startswith("testenv:"):
                            continue
                        values = {**base, **dict(parser.items(section))}
                        if set(values) - {"commands", "deps", "extras", "description"}:
                            self.decline(path, section, "unsupported tox environment setting")
                        if any(key in values for key in ("commands_pre", "commands_post", "changedir", "base",
                                                         "setenv", "passenv")):
                            self.decline(path, section, "tox command inheritance/cwd outside grammar")
                        commands[section] = values.get("commands", "")
                    self.tox[path] = commands
            for key in ("testpaths", "pythonpath"):
                value = settings.get(key, ())
                values = shlex.split(value) if isinstance(value, str) else value
                if not isinstance(values, (tuple, list)) or any(not isinstance(item, str) for item in values):
                    raise ValueError("path settings are not literal strings")
                for item in values:
                    self.reference(path, key, "config-" + key, item, posixpath.dirname(path))
            addopts = settings.get("addopts", "")
            if isinstance(addopts, str):
                options = shlex.split(addopts)
            elif isinstance(addopts, list) and all(isinstance(item, str) for item in addopts):
                options = addopts
            else:
                raise ValueError("addopts outside literal word grammar")
            if options:
                self.config_options.append(ConfigOptions(path, tuple(options)))
            self.settings[path] = settings
        except (configparser.Error, ValueError, TypeError, AttributeError):
            self.decline(path, "config", "configuration parse or shape failure")
        except RecursionError as exc:
            raise EngineError("runner reference configuration parser exceeded recursion") from exc

    def workflow(self, path: str, data: bytes) -> None:
        try:
            tree, reason = _read_document(data)
        except RecursionError as exc:
            raise EngineError("runner reference workflow parser exceeded recursion") from exc
        if reason is not None or not isinstance(tree, dict) or not isinstance(tree.get("jobs"), dict):
            self.decline(path, "workflow", "unsupported workflow document")
            return
        for job_name, job in tree["jobs"].items():
            if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
                self.decline(path, str(job_name), "unsupported workflow job")
                continue
            for index, step in enumerate(job["steps"]):
                site = str(job_name) + ":" + str(index)
                if not isinstance(step, dict):
                    self.decline(path, site, "unsupported workflow step")
                    continue
                if "run" in step and "uses" in step:
                    self.decline(path, site, "workflow step combines run and uses")
                    continue
                if "run" not in step:
                    uses = step.get("uses")
                    if not isinstance(uses, str) or not uses.strip():
                        self.decline(path, site, "missing or nonliteral workflow action")
                    elif uses.startswith("./"):
                        self.reference(path, site, "local-action", uses, "")
                        self.decline(path, site, "local action requires transitive source proof")
                    elif _step_command(step) is not None or isinstance(uses, str) and "${{" in uses:
                        self.decline(path, site, "runner action or dynamic action")
                    continue
                run = step["run"]
                if not isinstance(run, str):
                    self.decline(path, site, "nonliteral workflow run")
                    continue
                if not any(_selected_command(line) for line in run.splitlines()):
                    continue  # No selected test/runner edge in this run block.
                if any("working-directory" in mapping or "env" in mapping or "defaults" in mapping
                       for mapping in (tree, job, step)):
                    self.decline(path, site, "workflow cwd/environment/default context")
                    continue
                shell = step.get("shell")
                if "shell" in step and (not isinstance(shell, str) or shell not in {"bash", "sh"}):
                    self.decline(path, site, "unsupported explicit workflow shell")
                    continue
                for line in run.splitlines():
                    self.command(path, site, line, neutral=shell is None)

    def precommit(self, path: str, data: bytes) -> None:
        # Existing ci_control_flow._precommit_sites models source-visible
        # entry, not packages/args of a remote hook with no entry override.
        try:
            tree, reason = _read_document(data)
        except RecursionError as exc:
            raise EngineError("runner reference pre-commit parser exceeded recursion") from exc
        if reason is not None or not isinstance(tree, dict) or not isinstance(tree.get("repos"), list):
            self.decline(path, "pre-commit", "unsupported pre-commit document")
            return
        for index, repo in enumerate(tree["repos"]):
            self.reserve_work(1)
            site = str(index)
            if (not isinstance(repo, dict) or not isinstance(repo.get("repo"), str)
                    or not repo["repo"] or "${" in repo["repo"]
                    or not isinstance(repo.get("hooks"), list)):
                self.decline(path, site, "unsupported pre-commit repository")
                continue
            for number, hook in enumerate(repo["hooks"]):
                self.reserve_work(1)
                label = site + ":" + str(number)
                if not isinstance(hook, dict) or not isinstance(hook.get("id"), str):
                    self.decline(path, label, "unsupported pre-commit hook")
                    continue
                if "entry" not in hook:
                    if repo["repo"] == "local":
                        self.decline(path, label, "local hook lacks required entry")
                    continue
                entry, args = hook["entry"], hook.get("args", [])
                if (not isinstance(entry, str) or not entry.strip()
                        or not isinstance(args, list) or any(not isinstance(arg, str) for arg in args)):
                    self.decline(path, label, "unsupported pre-commit entry/args")
                    continue
                if _selected_command(entry):
                    self.command(path, label, entry + " " + shlex.join(args))

    def bind_configs(self) -> None:
        from checkwash.shadow import _pytest_config_path

        options = {record.source: record.argv for record in self.config_options}
        bound = []
        for call in self.calls:
            self.reserve_work(1)
            selected = _pytest_config_path(self.paths, "", call.targets,
                                           call.config_path, self.sources, call.cwd)
            if call.config_path is not None and selected is None:
                self.decline(call.source, call.site, "explicit config is absent")
            if selected is not None and selected not in self.settings:
                self.decline(call.source, call.site, "selected config lacks parsed source")
                continue
            settings = self.settings.get(selected, {})
            if set(settings) - {"addopts", "testpaths", "pythonpath", "minversion",
                                "doctest_optionflags"}:
                self.decline(call.source, call.site, "unsupported collection/config setting")
            config_args = options.get(selected, ())
            effective = (*config_args, *call.argv)
            unbound_tox = call.source in self.tox and call.positional_binding is None
            modifiers = []
            index = 0
            while index < len(effective):
                self.reserve_work(1)
                word = effective[index]
                index += 1
                if word in {"--doctest-modules"}:
                    modifiers.append(word)
                elif word in {"-q", "-v", "-vv", "--quiet", "--verbose", "-s", "-x"}:
                    pass
                elif word == "{posargs}" and unbound_tox and index > len(config_args):
                    pass  # D-123 declaration remains targetless, not empty proof.
                elif word.startswith("--doctest-glob"):
                    self.decline(call.source, call.site, "explicit non-Python doctest discovery")
                elif word.startswith(("--junitxml=", "--junit-xml=")):
                    pass  # Output destination, not an input/collection selector.
                elif word.startswith("--cov-report="):
                    if word.split("=", 1)[1] not in {"term", "xml"}:
                        self.decline(call.source, call.site, "unsupported coverage report option")
                elif word.startswith("--cov="):
                    self.reference(call.source, call.site, "coverage-source", word.split("=", 1)[1], call.cwd)
                elif word.startswith("--config-file="):
                    self.reference(call.source, call.site, "config", word.split("=", 1)[1], call.cwd)
                elif word.startswith("--cov-config="):
                    self.reference(call.source, call.site, "coverage-config", word.split("=", 1)[1], call.cwd)
                elif word in {"-c", "--config-file", "--cov-config", "--cov-report",
                              "--junitxml", "--junit-xml"}:
                    if index == len(effective):
                        self.decline(call.source, call.site, "missing option value")
                        continue
                    value = effective[index]
                    index += 1
                    if word in {"-c", "--config-file", "--cov-config"}:
                        self.reference(call.source, call.site,
                                       "coverage-config" if word == "--cov-config" else "config",
                                       value, call.cwd)
                    elif word == "--cov-report" and value not in {"term", "xml"}:
                        self.decline(call.source, call.site, "unsupported coverage report option")
                elif word.startswith("-"):
                    self.decline(call.source, call.site, "unsupported pytest option")
                else:
                    self.reference(call.source, call.site, "collection", word.split("::", 1)[0], call.cwd)
            # Config addopts cannot silently change the explicit config used to
            # discover those same options. Such recursive selection is opaque.
            if any(word in {"-c", "--config-file"} or word.startswith("--config-file=")
                   for word in options.get(selected, ())):
                self.decline(call.source, call.site, "addopts changes config selection")
            targets, config_path = self.pytest_references(call.source, call.site, call.cwd,
                                                          list(effective), unbound_tox=unbound_tox)
            bound.append(replace(call, argv=tuple(effective), targets=targets,
                                 config_path=config_path, effective_config=selected,
                                 collection_modifiers=tuple(modifiers),
                                 source_sha256=self.identities[call.source],
                                 effective_config_sha256=self.identities.get(selected)))
        self.calls = bound

    def close(self) -> ReferenceClosure:
        for path, data in sorted(self.sources.items()):
            if not isinstance(data, bytes):
                raise EngineError("runner reference closure lacks required source bytes")
            try:
                text = data.decode("utf-8-sig", errors="strict")
            except UnicodeError:
                self.decline(path, "source", "undecodable source")
                continue
            if posixpath.basename(path) in _CONFIGS:
                self.config(path, text)
            elif (_is_runner_script(path, data, data)
                  and posixpath.basename(path).startswith(("Makefile", "makefile", "GNUmakefile"))):
                self.make(path, text)
        # Every declared pytest/runner recipe is a root, not just CI's chosen
        # target. Unrelated publishing/docs recipes are not arbitrary-process
        # completeness obligations. Invoked dependencies still parse strictly.
        for path, rules in self.makefiles.items():
            for target, (_dependencies, commands) in rules.items():
                # Python-only publication/docs recipes are not added to the
                # existing declared pytest root model. Once any test/make/tox
                # edge selects a recipe, every command uses strict parsing.
                if any(_selected_command(command, python_entry=False) for command in commands):
                    self.schedule((path, target, "", None))
        for path, environments in self.tox.items():
            for environment in environments:
                self.schedule((path, environment, "", None))
        for path, data in sorted(self.sources.items()):
            if path in self.makefiles or posixpath.basename(path) in _CONFIGS:
                continue
            if (not _is_runner_script(path, data, data) and not is_github_workflow(path)
                    and path not in self.ci_paths):
                continue  # Strictly acquired control with no live content gate.
            if is_github_workflow(path):
                self.workflow(path, data)
            elif path == ".pre-commit-config.yaml":
                self.precommit(path, data)
            elif path.endswith((".sh", ".bash")) or data.startswith(b"#!"):
                try:
                    text = data.decode("utf-8-sig", errors="strict")
                except UnicodeError:
                    continue  # Recorded above; never a COMPLETE result.
                for number, line in enumerate(text.splitlines(), 1):
                    self.command(path, str(number), line)
            else:
                self.decline(path, "carrier", "unsupported carrier grammar")
        while self.pending:
            context = self.pending.pop()
            if context in self.visited:
                continue
            self.visited.add(context)
            path, target, cwd, binding = context
            self.active = context[:3]
            if path in self.makefiles:
                rule = self.makefiles[path].get(target)
                if rule is None:
                    self.decline(path, target, "unknown Make dependency/target")
                    continue
                dependencies, commands = rule
                for dependency in dependencies:
                    self.schedule((path, dependency, cwd, None))
            else:
                text = self.tox[path][target]
                commands = tuple(text.splitlines())
            for index, command in enumerate(commands):
                if path in self.tox:
                    match = re.fullmatch(r"(.*?)(\{posargs(?::([^{}]*))?\})(.*?)", command)
                    if match:
                        if binding is None:
                            replacement = "{posargs}"
                        else:
                            replacement = shlex.join(binding) if binding else (match.group(3) or "")
                        command = match.group(1) + replacement + match.group(4)
                    if "{" in command.replace("{posargs}", "") or "}" in command.replace("{posargs}", ""):
                        self.decline(path, target, "unsupported tox substitution")
                        continue
                self.command(path, target + ":" + str(index), command, cwd, binding)
        self.bind_configs()
        return ReferenceClosure(tuple(self.calls), tuple(self.references), tuple(self.opaque),
                                tuple(self.config_options))


def reference_closure(sources: Mapping[str, bytes], *, paths: frozenset[str],
                      reserve_work: Callable[[int], None],
                      ci_paths: frozenset[str] = frozenset()) -> ReferenceClosure:
    """The caller supplies the complete required carrier selection for one side."""
    if not isinstance(sources, Mapping) or any(not isinstance(path, str) or not path for path in sources):
        raise EngineError("runner reference closure requires named source inputs")
    if any(not isinstance(data, bytes) for data in sources.values()):
        raise EngineError("runner reference closure requires complete source bytes")
    if any(len(data) > MAX_SOURCE_BYTES for data in sources.values()) or sum(map(len, sources.values())) > MAX_BATCH_BYTES:
        raise EngineError("runner reference closure exceeds the existing source byte limit")
    return _Closure(sources, paths, reserve_work, ci_paths).close()
