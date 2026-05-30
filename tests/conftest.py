"""Test helpers: load the pure modules without importing the HA package __init__."""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType

_BASE = (
    pathlib.Path(__file__).resolve().parents[1]
    / "custom_components"
    / "miele_move"
)

_PKG = "miele_move_test_pkg"


def _ensure_pkg() -> None:
    """Register an empty package so relative imports between modules resolve.

    Modules loaded via load_module are registered as <pkg>.<name>; Python then
    resolves `from .other import ...` by looking up <pkg>.other in sys.modules
    or auto-loading it from __path__.
    """
    if _PKG in sys.modules:
        return
    pkg = ModuleType(_PKG)
    pkg.__path__ = [str(_BASE)]
    sys.modules[_PKG] = pkg


def load_module(name: str) -> ModuleType:
    """Load custom_components/miele_move/<name>.py as a standalone module.

    This avoids triggering the package __init__, which imports Home Assistant
    (not installed in the unit-test environment).
    """
    _ensure_pkg()
    full_name = f"{_PKG}.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    spec = importlib.util.spec_from_file_location(full_name, _BASE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module
