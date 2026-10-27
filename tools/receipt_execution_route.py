"""Exact trusted local receipt routes; the owner still admits each source packet.

Protocol names containing ``pju`` are retained for existing evidence/check links.
They never override the actual host or provenance recorded by a new collection.
This table is not permission to execute arbitrary sources, and is not hardware
attestation. No environment variable can choose the execution host.
"""
from __future__ import annotations

import os
import platform
from types import MappingProxyType


HOST = "LAPTOP-01AGNPJU"  # Historical route, retained for legacy callers/fixtures.
PROVENANCE = "HUMAN_AUTHORIZED_LOCAL_PJU_NOT_EC_POOL"
ROUTES = MappingProxyType({
    HOST: (PROVENANCE, "PJU_LOCAL_COMPOSITE_REPLAY"),
    "LAPTOP-16NUA5I8": ("HUMAN_AUTHORIZED_LOCAL_16NU_NOT_EC_POOL", "16NU_LOCAL_COMPOSITE_REPLAY"),
})


def route_for(host):
    if type(host) is not str or host not in ROUTES:
        raise ValueError("unsupported local receipt host")
    provenance, action_provenance = ROUTES[host]
    return {"host": host, "provenance": provenance, "action_provenance": action_provenance}


def current_route():
    if os.name != "nt":
        raise ValueError("authorized local Windows host required")
    return route_for(platform.node().upper())


def receipt_route(record):
    if type(record) is not dict:
        raise ValueError("local receipt route record required")
    route = route_for(record.get("host"))
    if record.get("provenance") != route["provenance"]:
        raise ValueError("local receipt host/provenance mismatch")
    return route
