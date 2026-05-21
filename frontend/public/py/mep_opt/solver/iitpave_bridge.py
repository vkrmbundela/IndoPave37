"""
Legacy Reference Bridge — Compatibility Shim
=============================================
The Fortran-based IIT Pave executable has been fully replaced by the
native Python Burmister solver.  This module preserves backward-
compatible public symbols and the thread-safe LRU result cache so that
existing tests (test_severity4 cache tests, test_optimizer, etc.) keep
passing without modification.

All structural analysis is now routed through the native solver via
``mep_opt.solver.solver_facade.run_solver``.
"""

import copy
import threading
from collections import OrderedDict
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backward-compatible constants (previously pointed at the Fortran .EXE)
# ---------------------------------------------------------------------------
LEGACY_DIR = ""
LEGACY_EXE = ""
DEFAULT_BRIDGE_TIMEOUT_S = 30.0


class BridgeTimeoutError(RuntimeError):
    """Kept for backward compatibility; the native solver never times out."""


# ---------------------------------------------------------------------------
# Thread-safe LRU result cache
# ---------------------------------------------------------------------------
_BRIDGE_CACHE_LOCK = threading.Lock()
_BRIDGE_CACHE_MAX = 0       # 0 = disabled
_BRIDGE_CACHE: "OrderedDict[Tuple, List[Dict]]" = OrderedDict()
_BRIDGE_CACHE_HITS = 0
_BRIDGE_CACHE_MISSES = 0


def set_bridge_cache_size(max_entries: int) -> None:
    """Enable (max_entries > 0) or disable (0) the bridge result cache."""
    global _BRIDGE_CACHE_MAX
    with _BRIDGE_CACHE_LOCK:
        _BRIDGE_CACHE_MAX = max(0, int(max_entries))
        while _BRIDGE_CACHE_MAX and len(_BRIDGE_CACHE) > _BRIDGE_CACHE_MAX:
            _BRIDGE_CACHE.popitem(last=False)
        if _BRIDGE_CACHE_MAX == 0:
            _BRIDGE_CACHE.clear()


def get_bridge_cache_stats() -> Dict[str, int]:
    """Return current hit/miss counters and cache size — useful for tests."""
    with _BRIDGE_CACHE_LOCK:
        return {
            "hits": _BRIDGE_CACHE_HITS,
            "misses": _BRIDGE_CACHE_MISSES,
            "size": len(_BRIDGE_CACHE),
            "max": _BRIDGE_CACHE_MAX,
        }


def clear_bridge_cache() -> None:
    """Drop all cached results (does not change the configured max size)."""
    global _BRIDGE_CACHE_HITS, _BRIDGE_CACHE_MISSES
    with _BRIDGE_CACHE_LOCK:
        _BRIDGE_CACHE.clear()
        _BRIDGE_CACHE_HITS = 0
        _BRIDGE_CACHE_MISSES = 0


def _cache_key(solver_stack, load_cfg, eval_points, timeout=None) -> Tuple:
    """Build a hashable signature for a solver call."""
    stack_key = tuple(
        (
            round(float(l.get("modulus", 0.0)), 4),
            round(float(l.get("poisson", 0.0)), 4),
            round(float(l.get("thickness", 0.0)), 4),
        )
        for l in solver_stack
    )
    load_key = (
        round(float(load_cfg.get("load", 0.0)), 4),
        round(float(load_cfg.get("pressure", 0.0)), 4),
        bool(load_cfg.get("is_dual", False)),
        round(float(load_cfg.get("spacing", 0.0)), 4),
    )
    points_key = tuple(
        (round(float(p.get("z", 0.0)), 4), round(float(p.get("r", 0.0)), 4))
        for p in eval_points
    )
    return (stack_key, load_key, points_key)


def _cache_get(key) -> Optional[List[Dict]]:
    global _BRIDGE_CACHE_HITS, _BRIDGE_CACHE_MISSES
    with _BRIDGE_CACHE_LOCK:
        if _BRIDGE_CACHE_MAX == 0:
            _BRIDGE_CACHE_MISSES += 1
            return None
        if key not in _BRIDGE_CACHE:
            _BRIDGE_CACHE_MISSES += 1
            return None
        # LRU touch
        _BRIDGE_CACHE.move_to_end(key)
        _BRIDGE_CACHE_HITS += 1
        return copy.deepcopy(_BRIDGE_CACHE[key])


def _cache_put(key, value) -> None:
    with _BRIDGE_CACHE_LOCK:
        if _BRIDGE_CACHE_MAX == 0:
            return
        _BRIDGE_CACHE[key] = copy.deepcopy(value)
        _BRIDGE_CACHE.move_to_end(key)
        while len(_BRIDGE_CACHE) > _BRIDGE_CACHE_MAX:
            _BRIDGE_CACHE.popitem(last=False)


# ---------------------------------------------------------------------------
# Solver routing — all calls go through the native Python Burmister solver
# ---------------------------------------------------------------------------

def _run_native(solver_stack, load_cfg, eval_points) -> List[Dict[str, Any]]:
    """Run the pure-Python Burmister solver."""
    from mep_opt.solver.burmister import analyze_pavement
    return analyze_pavement(solver_stack, load_cfg, eval_points)


def run_iitpave_bridge(solver_stack, load_cfg, eval_points,
                       timeout=DEFAULT_BRIDGE_TIMEOUT_S) -> List[Dict[str, Any]]:
    """Cached native solver call (backward-compatible entry point)."""
    cache_key = _cache_key(solver_stack, load_cfg, eval_points)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    results = _run_native(solver_stack, load_cfg, eval_points)
    _cache_put(cache_key, results)
    return results


def is_iitpave_available() -> bool:
    """Native solver is always available."""
    return True


def is_bridge_available() -> bool:
    """Native solver is always available."""
    return True


def run_legacy_bridge(solver_stack, load_cfg, eval_points,
                      timeout=DEFAULT_BRIDGE_TIMEOUT_S) -> List[Dict]:
    """Preferred neutral alias — routes through native solver."""
    return run_iitpave_bridge(solver_stack, load_cfg, eval_points, timeout=timeout)


def run_bridge_from_stack(solver_stack, load_cfg, eval_points,
                          timeout=DEFAULT_BRIDGE_TIMEOUT_S) -> List[Dict]:
    """Preferred neutral alias — routes through native solver."""
    return run_iitpave_bridge(solver_stack, load_cfg, eval_points, timeout=timeout)


# ---------------------------------------------------------------------------
# BridgeWorkerPool stub — parallel mode now uses ThreadPoolExecutor directly
# with the in-memory native solver (no scratch dirs needed).
# ---------------------------------------------------------------------------

class BridgeWorkerPool:
    """
    Stub for backward compatibility.  The native solver is thread-safe
    and doesn't need scratch directories, so this simply wraps
    ThreadPoolExecutor around run_iitpave_bridge.
    """

    def __init__(self, n_workers: int = 4, timeout: float = DEFAULT_BRIDGE_TIMEOUT_S):
        self.n_workers = max(1, int(n_workers))
        self.timeout = float(timeout)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        pass  # nothing to tear down

    def _run_one(self, spec):
        stack, load, points = spec
        return run_iitpave_bridge(stack, load, points, self.timeout)

    def run_many(self, specs):
        if not specs:
            return []
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self.n_workers) as ex:
            futures = [ex.submit(self._run_one, s) for s in specs]
            out = []
            for f in futures:
                try:
                    out.append((f.result(), None))
                except Exception as e:
                    out.append((None, e))
            return out


# Backward-compatible helper — previously used by _brute_force_parallel in
# smart_search.py; now a no-op.
def _make_worker_scratch_dir(prefix: str = "iitpave_worker_") -> str:
    """No longer needed — returns empty string for backward compat."""
    return ""


def _run_bridge_in_dir(solver_stack, load_cfg, eval_points,
                       work_dir, timeout) -> List[Dict[str, Any]]:
    """No longer uses work_dir — routes through native solver."""
    return run_iitpave_bridge(solver_stack, load_cfg, eval_points, timeout=timeout)
