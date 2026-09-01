"""Test-wide guards.

The no-network fixture makes "zero network" a tested claim, not a README
adjective (SPEC §8): any in-process socket creation fails the test.
"""

import socket

import pytest


class _NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def _blocked(*args, **kwargs):
        raise _NetworkBlocked("network access is forbidden in checkwash core paths")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    yield
