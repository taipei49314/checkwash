"""Adapter registry, independent from test-oracle detectors."""
from .coverage_adapter import coverage
from .ruff_adapter import ruff, selected_rules
from .mypy_adapter import mypy

ADAPTERS = {"coverage": coverage, "ruff": ruff, "mypy": mypy}
