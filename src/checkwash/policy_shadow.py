"""Effective BASE policy for newly winning priority-file creations.

This is policy provenance, never a replacement for the BASE configuration
or exemptions used to judge the diff. No HEAD file is loaded as authority.
"""
from dataclasses import dataclass
import hashlib

from checkwash.change import EngineError
from checkwash.config import CONFIG_DIRS, DEFAULT_CONFIG_DIR, SEVERITY_ORDER, load_config


def _policy_mapping(snapshot):
    """Use engine's lexical slash spelling; aliased filenames stay unknown."""
    own_paths = {f"{directory}/{name}" for directory in CONFIG_DIRS
                 for name in ("config.toml", "allow.toml")}
    selected, ambiguous = {}, set()
    for path, data in snapshot.items():
        path = path.replace("\\", "/")
        if path not in own_paths:
            continue
        if path in selected:
            ambiguous.add(path.rsplit("/", 1)[1])
        else:
            selected[path] = data
    return selected, ambiguous


@dataclass(frozen=True)
class PolicyBase:
    config_path: str = ".greenwash/config.toml"
    config_data: bytes | None = None
    allow_path: str = ".greenwash/allow.toml"
    allow_data: bytes | None = None
    known_names: frozenset[str] = frozenset({"config.toml", "allow.toml"})

    @classmethod
    def from_mapping(cls, snapshot, *, known_names=frozenset({"config.toml", "allow.toml"})):
        """Select proven BASE filenames; an unknown filename is never absence."""
        snapshot, ambiguous = _policy_mapping(snapshot)
        known_names = frozenset(known_names) - ambiguous
        def pick(name):
            for directory in CONFIG_DIRS:
                path = f"{directory}/{name}"
                data = snapshot.get(path)
                if data is not None:
                    return path, data
            return f"{DEFAULT_CONFIG_DIR}/{name}", None
        return cls(*pick("config.toml"), *pick("allow.toml"), known_names=known_names)


def shadow_baseline(change, policy_base):
    """A new winning priority file's selected BASE predecessor, or None.

    Inactive lower-priority creations, ordinary edits, deletes and renames
    keep their old treatment. Empty bytes are an existing policy file, except
    an empty file renamed into place: Git pairs empty blobs as renames by
    default, and the engine already counts that arrival as a creation.
    """
    if change.after is None:
        return None
    path = change.path.replace("\\", "/")
    renamed_empty = change.before == b"" and (change.old_path or path).replace("\\", "/") != path
    if change.before is not None and not renamed_empty:
        return None
    if path not in (".checkwash/config.toml", ".checkwash/allow.toml"):
        return None
    name = path.rsplit("/", 1)[1]
    if policy_base is None or name not in policy_base.known_names:
        raise EngineError("priority policy creation needs selected BASE policy provenance")
    config = path.endswith("/config.toml")
    selected_path = (policy_base.config_path if config else policy_base.allow_path).replace("\\", "/")
    data = policy_base.config_data if config else policy_base.allow_data
    expected = ".greenwash/config.toml" if config else ".greenwash/allow.toml"
    if selected_path != expected or data is None:
        return None
    return data, {"base_path": selected_path, "base_sha256": hashlib.sha256(data).hexdigest()}


def config_transition(before, after):
    """A bounded partial order; incomparable role changes remain guarded."""
    old, old_error, old_warnings = load_config(before)
    new, new_error, new_warnings = load_config(after)
    if old_error or new_error or old_warnings or new_warnings or old.roles != new.roles:
        return "config_uncomparable"
    if (not set(new.disabled_detectors).issubset(old.disabled_detectors)
            or SEVERITY_ORDER[new.fail_on] > SEVERITY_ORDER[old.fail_on]
            or (old.on_engine_error == "block" and new.on_engine_error != "block")):
        return "config_relaxation"
    return "config_nonweakening"
