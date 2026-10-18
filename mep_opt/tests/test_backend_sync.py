"""
Backend / Pyodide copy synchronization guard
=============================================
The deployed GitHub-Pages app runs the optimizer in the browser via Pyodide
using a SECOND copy of the engine under ``frontend/public/py/mep_opt``. That
copy must stay byte-identical to the authoritative ``mep_opt`` package — if it
drifts, the dashboard silently runs different (often stale) physics than the
backend and the test suite.

This test fails the moment the two diverge, forcing every engine fix to be
mirrored. Keep it green by running ``python tools/sync_pyodide_copy.py`` (or
copying the changed file) after editing any mirrored module.
"""

import hashlib
from pathlib import Path

import pytest

# Modules that are duplicated into the Pyodide bundle. (Web-only modules such
# as web/main.py, advanced/router.py and advanced/corridor.py are intentionally
# NOT mirrored — they need FastAPI / async job state.)
MIRRORED = [
    "cost/__init__.py",
    "solver/irc37.py",
    "solver/materials.py",
    "solver/burmister.py",
    "solver/geosynthetic.py",
    "solver/sp72.py",
    "solver/iitpave_bridge.py",
    "solver/legacy_bridge.py",
    "advanced/__init__.py",
    "advanced/_strain_utils.py",
    "advanced/sensitivity.py",
    "advanced/montecarlo.py",
    "advanced/reserve.py",
    "advanced/strain_field.py",
    "solver/solver_facade.py",
    "optimizer/smart_search.py",
    "optimizer/problem.py",
]

_REPO = Path(__file__).resolve().parents[2]
_BACKEND = _REPO / "mep_opt"
_BROWSER = _REPO / "frontend" / "public" / "py" / "mep_opt"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_pyodide_top_level_solver_in_sync():
    """
    The browser Evaluate path imports a top-level ``py/burmister.py`` (the
    worker's ``import burmister``), separate from the mirrored package. It must
    carry the same solver as the backend.
    """
    backend = _BACKEND / "solver" / "burmister.py"
    browser = _REPO / "frontend" / "public" / "py" / "burmister.py"
    assert browser.exists(), f"missing browser solver copy: {browser}"
    assert _sha(backend) == _sha(browser), (
        "ENGINE DRIFT: frontend/public/py/burmister.py differs from "
        "mep_opt/solver/burmister.py — the browser Evaluate path would run a "
        "different solver than the backend."
    )


@pytest.mark.parametrize("rel", MIRRORED)
def test_pyodide_copy_in_sync(rel):
    backend = _BACKEND / rel
    browser = _BROWSER / rel
    if not browser.exists():
        pytest.skip(f"browser copy not present: {browser}")
    assert _sha(backend) == _sha(browser), (
        f"ENGINE DRIFT: '{rel}' differs between mep_opt and "
        f"frontend/public/py/mep_opt. Mirror the change so the deployed "
        f"browser app runs the same physics as the backend."
    )
