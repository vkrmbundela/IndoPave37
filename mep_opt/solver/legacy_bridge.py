"""
Legacy Reference Bridge Public API
=================================
Preferred neutral import surface for legacy executable integration.
"""

from mep_opt.solver.iitpave_bridge import (
    LEGACY_DIR,
    LEGACY_EXE,
    DEFAULT_BRIDGE_TIMEOUT_S,
    BridgeTimeoutError,
    BridgeWorkerPool,
    is_bridge_available,
    run_legacy_bridge,
    run_bridge_from_stack,
    set_bridge_cache_size,
    get_bridge_cache_stats,
    clear_bridge_cache,
)

__all__ = [
    "LEGACY_DIR",
    "LEGACY_EXE",
    "DEFAULT_BRIDGE_TIMEOUT_S",
    "BridgeTimeoutError",
    "BridgeWorkerPool",
    "is_bridge_available",
    "run_legacy_bridge",
    "run_bridge_from_stack",
    "set_bridge_cache_size",
    "get_bridge_cache_stats",
    "clear_bridge_cache",
]
