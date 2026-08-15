"""T3.5: execution stays a satellite note, never the check path."""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "greenwash"
NOTE = ROOT / "docs" / "satellite-execution.md"

# Names that would mean execution leaked into the core package.
_FORBIDDEN = re.compile(
    r"^(mutate|mutation|rerun|sandbox_exec|exec_companion)(\.py)?$"
)


def test_satellite_note_is_non_default():
    text = NOTE.read_text(encoding="utf-8")
    assert "not a product" in text.lower() or "design note" in text.lower()
    assert "must not import" in text.lower()
    assert "zero execution" in text.lower()
    assert "src/greenwash/" in text


def test_core_package_has_no_execution_satellite_module():
    leaked = [
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*")
        if path.is_file() and _FORBIDDEN.match(path.name)
    ]
    assert not leaked, f"execution satellite leaked into core: {leaked}"
