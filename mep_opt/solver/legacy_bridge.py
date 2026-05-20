"""
Legacy Reference Bridge Public API
=================================
Preferred neutral import surface for structural analysis.

``run_bridge_from_stack`` now routes through the solver facade (AUTO mode):
native Python Burmister solver first, legacy .EXE bridge as fallback.
"""

from mep_opt.solver.iitpave_bridge import (
    LEGACY_DIR,
    LEGACY_EXE,
    DEFAULT_BRIDGE_TIMEOUT_S,
    BridgeTimeoutError,
    BridgeWorkerPool,
    is_bridge_available as is_bridge_available,
    run_legacy_bridge,
    run_bridge_from_stack as _run_bridge_only,
    set_bridge_cache_size,
    get_bridge_cache_stats,
    clear_bridge_cache,
)

from mep_opt.solver.solver_facade import (
    run_solver,
    SolverBackend,
    set_solver_backend,
    get_solver_backend,
    get_solver_stats,
    reset_solver_stats,
)


def run_bridge_from_stack(solver_stack, load_cfg, eval_points, timeout=DEFAULT_BRIDGE_TIMEOUT_S):
    """Structural analysis via AUTO mode: native solver with bridge fallback."""
    return run_solver(solver_stack, load_cfg, eval_points, timeout=timeout)


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
    "run_solver",
    "SolverBackend",
    "set_solver_backend",
    "get_solver_backend",
    "get_solver_stats",
    "reset_solver_stats",
]
