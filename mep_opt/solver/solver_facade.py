"""
Unified Solver Facade
=====================
Routes structural analysis through the pure-Python Burmister solver
with automatic fallback to the legacy bridge (.EXE) when the native
solver is unavailable or produces a computation error.

Every consumer (optimizer, web API, advanced modules) should import
from here instead of directly from iitpave_bridge or burmister.
"""

import logging
import threading
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_STATS_LOCK = threading.Lock()
_STATS = {
    "native_calls": 0,
    "native_ok": 0,
    "native_errors": 0,
    "bridge_calls": 0,
    "bridge_fallbacks": 0,
}


class SolverBackend(Enum):
    AUTO = "auto"
    NATIVE = "native"
    BRIDGE = "bridge"


_active_backend: SolverBackend = SolverBackend.AUTO


def set_solver_backend(backend: SolverBackend) -> None:
    global _active_backend
    _active_backend = backend
    logger.info("Solver backend set to %s", backend.value)


def get_solver_backend() -> SolverBackend:
    return _active_backend


def get_solver_stats() -> Dict[str, int]:
    with _STATS_LOCK:
        return dict(_STATS)


def reset_solver_stats() -> None:
    with _STATS_LOCK:
        for k in _STATS:
            _STATS[k] = 0


def _run_native(
    solver_stack: List[Dict[str, float]],
    load_cfg: Dict[str, float],
    eval_points: List[Dict[str, float]],
) -> List[Dict[str, Any]]:
    """Run the pure-Python Burmister solver."""
    from mep_opt.solver.burmister import analyze_pavement
    return analyze_pavement(solver_stack, load_cfg, eval_points)


def _run_bridge(
    solver_stack: List[Dict[str, float]],
    load_cfg: Dict[str, float],
    eval_points: List[Dict[str, float]],
    timeout: float = 30.0,
) -> List[Dict[str, Any]]:
    """Run the legacy .EXE bridge."""
    from mep_opt.solver.iitpave_bridge import run_iitpave_bridge
    return run_iitpave_bridge(solver_stack, load_cfg, eval_points, timeout=timeout)


def run_solver(
    solver_stack: List[Dict[str, float]],
    load_cfg: Dict[str, float],
    eval_points: List[Dict[str, float]],
    timeout: float = 30.0,
    backend: Optional[SolverBackend] = None,
) -> List[Dict[str, Any]]:
    """
    Unified solver entry point.

    Args:
        solver_stack: layered system [{modulus, poisson, thickness}, ...]
        load_cfg: {load, pressure, is_dual, spacing}
        eval_points: [{z, r}, ...]
        timeout: bridge subprocess timeout (ignored for native)
        backend: override the global backend for this call

    Returns:
        List of result dicts with keys:
            z, r, sigma_z, sigma_r, sigma_t, tau_rz, disp_z,
            eps_z, eps_t, eps_r

    Raises:
        RuntimeError: if both native and bridge fail (AUTO mode)
        Any solver-specific exception in forced mode
    """
    mode = backend or _active_backend

    if mode == SolverBackend.BRIDGE:
        with _STATS_LOCK:
            _STATS["bridge_calls"] += 1
        return _run_bridge(solver_stack, load_cfg, eval_points, timeout)

    if mode == SolverBackend.NATIVE:
        with _STATS_LOCK:
            _STATS["native_calls"] += 1
        try:
            result = _run_native(solver_stack, load_cfg, eval_points)
            with _STATS_LOCK:
                _STATS["native_ok"] += 1
            return result
        except Exception:
            with _STATS_LOCK:
                _STATS["native_errors"] += 1
            raise

    # AUTO mode: try native first, fall back to bridge
    with _STATS_LOCK:
        _STATS["native_calls"] += 1
    try:
        result = _run_native(solver_stack, load_cfg, eval_points)
        with _STATS_LOCK:
            _STATS["native_ok"] += 1
        return result
    except Exception as exc:
        logger.warning(
            "Native Burmister solver failed (%s); falling back to bridge",
            exc,
        )
        with _STATS_LOCK:
            _STATS["native_errors"] += 1
            _STATS["bridge_fallbacks"] += 1
            _STATS["bridge_calls"] += 1
        return _run_bridge(solver_stack, load_cfg, eval_points, timeout)
