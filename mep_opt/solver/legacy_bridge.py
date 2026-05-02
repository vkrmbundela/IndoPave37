"""
Legacy Reference Bridge Public API
=================================
Preferred neutral import surface for legacy executable integration.
"""

from mep_opt.solver.iitpave_bridge import (
    LEGACY_DIR,
    LEGACY_EXE,
    is_bridge_available,
    run_legacy_bridge,
    run_bridge_from_stack,
)

__all__ = [
    "LEGACY_DIR",
    "LEGACY_EXE",
    "is_bridge_available",
    "run_legacy_bridge",
    "run_bridge_from_stack",
]
