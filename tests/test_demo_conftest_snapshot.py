"""The declarative demo adapter supplies the same strict snapshot as check."""

import io
from pathlib import Path

from checkwash import demo


def test_demo_resolves_unchanged_firstparty_conftest_target(monkeypatch):
    fixture = Path(__file__).parent / "cases/conftest_unchanged_firstparty_pos.gwcase"
    source = fixture.read_text(encoding="utf-8")
    monkeypatch.setattr(demo, "_load_cases", lambda: [(fixture.name, source)])
    stream = io.StringIO()
    assert demo.run(stream) == 0
    assert "CONFTEST_PATCHES_PROD" in stream.getvalue()
    assert "1/1 tampering cases blocked" in stream.getvalue()
