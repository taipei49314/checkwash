"""Declared-dependency resolution for IMPORT_UNRESOLVED (base side only).

Import names are guessed from distribution names, so the mapping is
deliberately generous: a false "resolved" costs one missed finding, a false
"unresolved" costs trust. IMPORT_UNRESOLVED stays OFF entirely when no
manifest is found — with nothing to resolve against, every third-party
import would look hallucinated.
"""

from __future__ import annotations

import re
import tomllib

MANIFESTS = (
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "poetry.lock",
    "uv.lock",
)

_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_NAME_FIELD = re.compile(r'^\s*name\s*=\s*"([^"]+)"', re.MULTILINE)

# Distributions whose import name is not derivable from the project name.
_KNOWN_ALIASES = {
    "beautifulsoup4": {"bs4"},
    "pillow": {"PIL"},
    "pyyaml": {"yaml"},
    "python-dateutil": {"dateutil"},
    "attrs": {"attr", "attrs"},
    "protobuf": {"google"},
    "scikit-learn": {"sklearn"},
    "opencv-python": {"cv2"},
    "msgpack-python": {"msgpack"},
    "typing-extensions": {"typing_extensions"},
    "setuptools": {"setuptools", "pkg_resources"},
}


def _module_forms(dist: str) -> set[str]:
    name = dist.strip().lower()
    forms = set(_KNOWN_ALIASES.get(name, ()))
    forms.add(name.replace("-", "_"))
    forms.add(name.replace("-", ""))
    forms.add(name.replace("_", ""))
    return {f for f in forms if f}


def project_names(path: str, data: bytes) -> set[str]:
    """Import names of the project *itself*, separate from its dependencies.

    `parse_manifest` folds the project's own name in with everything it
    depends on, and for IMPORT_UNRESOLVED that is right: both resolve. Any
    rule asking "is this someone else's code?" needs the two apart, because
    "declared" alone answers yes for `flask` inside flask — a first-party
    check that denies the first party, silent in exactly the repos it is
    measured on.

    Only manifests that name a project have one. Lockfiles and
    requirements.txt list dependencies and nothing else.
    """
    if not path.endswith(".toml") or path == "uv.lock":
        return set()
    try:
        raw = tomllib.loads(data.decode("utf-8-sig", errors="replace"))
    except tomllib.TOMLDecodeError:
        return set()
    names: set[str] = set()
    tool = raw.get("tool") if isinstance(raw.get("tool"), dict) else {}
    for table in (raw.get("project"), tool.get("poetry")):
        if isinstance(table, dict) and isinstance(table.get("name"), str):
            names |= _module_forms(table["name"])
    names.discard("python")
    return names


def parse_manifest(path: str, data: bytes) -> set[str]:
    text = data.decode("utf-8-sig", errors="replace")
    names: set[str] = set()
    if path.endswith(".toml") and path != "uv.lock":
        try:
            raw = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return names
        project = raw.get("project", {})
        if isinstance(project, dict):
            if isinstance(project.get("name"), str):
                names |= _module_forms(project["name"])
            for spec in project.get("dependencies", []) or []:
                if isinstance(spec, str):
                    m = _REQ_LINE.match(spec)
                    if m:
                        names |= _module_forms(m.group(1))
            optional = project.get("optional-dependencies", {})
            if isinstance(optional, dict):
                for specs in optional.values():
                    for spec in specs or []:
                        if isinstance(spec, str):
                            m = _REQ_LINE.match(spec)
                            if m:
                                names |= _module_forms(m.group(1))
        poetry = raw.get("tool", {}).get("poetry", {}) if isinstance(raw.get("tool"), dict) else {}
        if isinstance(poetry, dict):
            if isinstance(poetry.get("name"), str):
                names |= _module_forms(poetry["name"])
            for group in ("dependencies", "dev-dependencies"):
                deps = poetry.get(group, {})
                if isinstance(deps, dict):
                    for dist in deps:
                        names |= _module_forms(str(dist))
    elif path.endswith(".lock"):
        # poetry.lock / uv.lock: every `name = "..."` is a locked package.
        for match in _NAME_FIELD.finditer(text):
            names |= _module_forms(match.group(1))
    else:  # requirements-style
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "-")):
                continue
            m = _REQ_LINE.match(stripped)
            if m:
                names |= _module_forms(m.group(1))
    names.discard("python")
    return names
