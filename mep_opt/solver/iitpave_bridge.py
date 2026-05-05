"""
Legacy Reference Bridge
=======================
Extracts strain values from the legacy reference executable to ensure
regulatory reporting compliance by sidestepping pure-python integration drift.
"""

import os
import sys
import copy
import shutil
import tempfile
import subprocess
import threading
import queue as _queue
from collections import OrderedDict
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Global lock to prevent race conditions on the legacy IN file
_BRIDGE_LOCK = threading.Lock()

# Default per-call timeout for the legacy IIT Pave executable. A typical
# evaluation finishes well under 1 s; 30 s leaves generous headroom for
# slow disks or cold caches while still catching a hung process before
# it pins the backend thread indefinitely. Override per call if needed.
DEFAULT_BRIDGE_TIMEOUT_S = 30.0


class BridgeTimeoutError(RuntimeError):
    """Raised when the legacy IIT Pave executable exceeds its time budget."""


# ---------------------------------------------------------------------------
# Severity-4 #4.4 — Result cache
#
# IIT Pave is deterministic: the same (solver_stack, load_cfg, eval_points)
# always returns the same strains. Repeat queries — sensitivity sweeps,
# corridor optimisation across similar sections, the optimizer's own
# Premium-vs-Balanced re-evaluations — therefore have a high natural hit
# rate. We use a small thread-safe LRU keyed on the call signature; on a
# hit we clone the cached result so callers can mutate it freely.
# Disabled by default for callers that want bit-exact reproducibility of
# the .OUT file on disk; enable by calling `set_bridge_cache_size(N)`.
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
        # If shrinking, evict the oldest entries
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


def _cache_key(solver_stack, load_cfg, eval_points, timeout) -> Tuple:
    """Build a hashable signature for a bridge call."""
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
    # Timeout doesn't affect the answer when the call succeeds, so it's
    # intentionally NOT part of the key.
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

# Define the project root relative to this file
# mep_opt/solver/iitpave_bridge.py -> mep_opt/solver -> mep_opt -> root
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _discover_legacy_executable_path(project_root: str) -> str:
    """Locate the legacy executable by scanning for a *PFILE.exe binary."""
    # Priority 1: Check standard location directly (fast)
    standard_loc = os.path.join(project_root, "IIT Pave - Original", "IIT P", "IITPAVE", "IITPFILE.exe")
    if os.path.exists(standard_loc):
        logger.info(f"Legacy solver found at standard location: {standard_loc}")
        return standard_loc

    # Priority 2: Deep scan fallback
    logger.info(f"Scanning {project_root} for legacy solver...")
    for root, _, files in os.walk(project_root):
        # Skip heavy folders to speed up
        if any(skip in root for skip in (".venv", "node_modules", ".git", "__pycache__")):
            continue
        for name in files:
            if name.upper() == "IITPFILE.EXE":
                found_path = os.path.join(root, name)
                logger.info(f"Legacy solver found during scan: {found_path}")
                return found_path
    
    logger.error(f"Legacy solver binary (IITPFILE.exe) not found in {project_root}")
    return ""


LEGACY_EXE = _discover_legacy_executable_path(PROJECT_ROOT)
LEGACY_DIR = os.path.dirname(LEGACY_EXE) if LEGACY_EXE else ""


def _resolve_legacy_io_path(directory: str, filename: str) -> str:
    """Return the expected path for a legacy IO file, whether it exists yet or not."""
    if not directory:
        return ""
    return os.path.join(directory, filename)


LEGACY_IN_FILE = _resolve_legacy_io_path(LEGACY_DIR, "IITPAVE.IN")
LEGACY_OUT_FILE = _resolve_legacy_io_path(LEGACY_DIR, "IITPAVE.out")

# Backward-compatible aliases
IITPAVE_DIR = LEGACY_DIR
IITP_EXE = LEGACY_EXE

def is_iitpave_available() -> bool:
    """Check if the legacy executable is present."""
    if not os.path.exists(LEGACY_EXE):
        return False
    # If not on Windows, we need wine to be installed
    if sys.platform != "win32":
        try:
            subprocess.run(["wine", "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return False
    return True


# ---------------------------------------------------------------------------
# Severity-4 #4.5 — Parallel bridge workers
#
# The legacy IIT Pave executable reads `IITPAVE.IN` and writes
# `IITPAVE.OUT` from its current working directory. The default behaviour
# uses a single shared LEGACY_DIR with `_BRIDGE_LOCK` serialising calls.
#
# To run N workers in parallel we hand each one its own scratch directory
# containing a copy (or symlink) of the .EXE plus any sibling DLLs, so
# they don't fight over the same .IN/.OUT files. A WorkerPool issues
# tasks over a shared queue and threads consume them, each binding to one
# scratch directory for its lifetime. We use threads (not processes)
# because the bottleneck is the .EXE subprocess — Python's GIL is
# released across `subprocess.run`.
# ---------------------------------------------------------------------------

_LEGACY_DIR_FILES_TO_COPY = ("IITPFILE.exe",)  # Files needed in each worker dir


def _make_worker_scratch_dir(prefix: str = "iitpave_worker_") -> str:
    """Create a scratch dir containing the bridge executable and return path."""
    if not LEGACY_EXE or not LEGACY_DIR:
        raise FileNotFoundError("Legacy bridge not configured; cannot spawn worker")
    scratch = tempfile.mkdtemp(prefix=prefix)
    # Copy any companion files the .EXE expects in its CWD. The legacy
    # dir typically contains the .EXE plus IITPAVE.IN/.OUT (which are
    # transient — we re-create them per call). We mirror only files that
    # are present and look like persistent companions of the .EXE.
    for entry in os.listdir(LEGACY_DIR):
        src = os.path.join(LEGACY_DIR, entry)
        # Skip transient IO files
        if entry.upper() in ("IITPAVE.IN", "IITPAVE.OUT"):
            continue
        if os.path.isdir(src):
            continue
        try:
            shutil.copy2(src, os.path.join(scratch, entry))
        except Exception:
            logger.exception("Failed to copy %s into worker scratch %s", src, scratch)
    return scratch


def _run_bridge_in_dir(
    solver_stack: List[Dict[str, float]],
    load_cfg: Dict[str, float],
    eval_points: List[Dict[str, float]],
    work_dir: str,
    timeout: float,
) -> List[Dict[str, Any]]:
    """
    Bridge call rooted at an arbitrary working directory. Used by the
    parallel pool — each worker has its own ``work_dir`` so multiple
    bridge subprocesses can run simultaneously without colliding on
    `IITPAVE.IN`/`IITPAVE.OUT`.

    Falls back to FileNotFoundError if the .EXE isn't in the scratch dir.
    """
    exe_in_dir = os.path.join(work_dir, os.path.basename(LEGACY_EXE))
    if not os.path.exists(exe_in_dir):
        raise FileNotFoundError(f"Legacy executable missing in worker dir: {exe_in_dir}")

    in_path = os.path.join(work_dir, "IITPAVE.IN")
    out_path = os.path.join(work_dir, "IITPAVE.out")

    # Format the IN file directly into work_dir (this is what
    # _write_in_file does, but it writes to the global path).
    _write_in_file_at(solver_stack, load_cfg, eval_points, in_path)

    cmd = [exe_in_dir]
    if sys.platform != "win32":
        cmd = ["wine", exe_in_dir]

    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
    try:
        subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise BridgeTimeoutError(
            f"Legacy IIT Pave executable exceeded {timeout}s timeout"
        ) from exc

    if not os.path.exists(out_path):
        raise FileNotFoundError(f"Worker {work_dir} did not produce IITPAVE.out")

    with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    return _parse_out_file(lines, eval_points)


class BridgeWorkerPool:
    """
    Thread-per-scratch-dir worker pool for parallel bridge calls.

    Usage:
        pool = BridgeWorkerPool(n_workers=4)
        results = pool.run_many([
            (stack1, load1, points1),
            (stack2, load2, points2),
            ...
        ])
        pool.close()

    or as a context manager:
        with BridgeWorkerPool(4) as pool:
            results = pool.run_many(specs)
    """

    def __init__(self, n_workers: int = 4, timeout: float = DEFAULT_BRIDGE_TIMEOUT_S):
        if n_workers < 1:
            raise ValueError(f"n_workers must be >= 1, got {n_workers}")
        self.n_workers = int(n_workers)
        self.timeout = float(timeout)
        self._scratch_dirs: List[str] = []
        for i in range(self.n_workers):
            self._scratch_dirs.append(_make_worker_scratch_dir(prefix=f"iitpave_w{i}_"))
        # Free-list of scratch dirs; each worker grabs one and returns it
        self._available: "_queue.Queue[str]" = _queue.Queue()
        for d in self._scratch_dirs:
            self._available.put(d)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """Tear down scratch directories. Idempotent."""
        for d in list(self._scratch_dirs):
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                logger.exception("Failed to clean worker dir %s", d)
        self._scratch_dirs.clear()

    def _run_one(self, spec):
        stack, load, points = spec
        # Cache check at the parallel layer too — multiple identical
        # specs in the same batch should not all dispatch to a worker.
        key = _cache_key(stack, load, points, self.timeout)
        cached = _cache_get(key)
        if cached is not None:
            return cached
        d = self._available.get()
        try:
            result = _run_bridge_in_dir(stack, load, points, d, self.timeout)
            _cache_put(key, result)
            return result
        finally:
            self._available.put(d)

    def run_many(self, specs):
        """
        Run a list of (stack, load_cfg, eval_points) specs in parallel.
        Returns a list of (result, error) tuples, in the same order as
        ``specs``. ``error`` is None on success; on failure ``result`` is
        None and ``error`` is the exception instance.
        """
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


def _write_in_file_at(solver_stack, load_cfg, eval_points, in_path):
    """Write IITPAVE.IN at an explicit path (parallel-pool helper)."""
    n_layers = len(solver_stack)
    moduli, poissons, thicknesses = [], [], []
    for i, layer in enumerate(solver_stack):
        m = layer['modulus']; t = layer.get('thickness', 0)
        moduli.append(str(int(m)) if isinstance(m, float) and m == int(m)
                      else (f"{m:.6f}" if isinstance(m, float) else str(m)))
        poissons.append(f"{layer['poisson']:.2f}".lstrip('0'))
        if i < n_layers - 1:
            thicknesses.append(str(int(t)) if isinstance(t, float) and t == int(t)
                               else (f"{t:.2f}" if isinstance(t, float) else str(t)))

    load_val = load_cfg['load']
    load_str = (str(int(load_val)) if isinstance(load_val, float) and load_val == int(load_val)
                else str(load_val))
    press_str = f"{load_cfg['pressure']:.2f}"
    is_dual = load_cfg.get("is_dual", True)
    load_type_int = 2 if is_dual else 1
    n_eval = len(eval_points)

    lines = [str(n_layers), " ".join(moduli) + " ", " ".join(poissons) + " "]
    lines.append((" ".join(thicknesses) + " ") if thicknesses else "")
    lines.append(f"{load_str} {press_str}")
    lines.append(str(n_eval))
    for pt in eval_points:
        lines.append(f"{_format_num(pt['z'])} {_format_num(pt['r'])}")
    lines.append(str(load_type_int))
    lines.append("")
    with open(in_path, "w") as f:
        f.write("\n".join(lines))



def run_iitpave_bridge(solver_stack: List[Dict[str, float]],
                       load_cfg: Dict[str, float],
                       eval_points: List[Dict[str, float]],
                       timeout: float = DEFAULT_BRIDGE_TIMEOUT_S) -> List[Dict[str, Any]]:
    """
    Runs the legacy reference executable by formatting an IN file
    and reading the OUT file.

    Args:
        solver_stack: layered system, top to bottom
        load_cfg: {load, pressure, is_dual, spacing}
        eval_points: list of {z, r} where strains/stresses are reported
        timeout: per-call subprocess timeout in seconds. Pass a smaller value
            for tight loops or a larger value if running on slow hardware.
            ``None`` disables the timeout (NOT recommended in production —
            a hung executable will pin the backend thread indefinitely).

    Returns:
        List of result dicts {"z", "r", "sigma_*", "eps_z", "eps_t", "eps_r", ...}.

    Raises:
        BridgeTimeoutError: if the executable does not finish within ``timeout``.
        FileNotFoundError: if the executable or its output file is missing.
        subprocess.CalledProcessError: if the executable exits non-zero.
    """

    # Cache lookup BEFORE the lock — pure-Python LRU is fast and a hit
    # avoids the bridge entirely. The cache is disabled by default
    # (set_bridge_cache_size > 0 to enable).
    cache_key = _cache_key(solver_stack, load_cfg, eval_points, timeout)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    with _BRIDGE_LOCK:
        if not os.path.exists(LEGACY_EXE):
            raise FileNotFoundError(f"Legacy executable not found at {LEGACY_EXE}")

        _write_in_file(solver_stack, load_cfg, eval_points)

        # Determine execution command (Wine for Linux/Mac, direct for Windows)
        cmd = [LEGACY_EXE]
        if sys.platform != "win32":
            cmd = ["wine", LEGACY_EXE]

        # Execute silently (CREATE_NO_WINDOW prevents console flash on Windows)
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
        try:
            subprocess.run(
                cmd,
                cwd=LEGACY_DIR,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            # Surface a typed error so the optimizer can record it and move on
            # without confusing it with normal solver-failure CalledProcessError.
            logger.error(
                "Legacy IIT Pave bridge timed out after %.1fs (cmd=%s)",
                timeout if timeout is not None else -1, cmd,
            )
            raise BridgeTimeoutError(
                f"Legacy IIT Pave executable exceeded {timeout}s timeout"
            ) from exc

        # Parse results
        out_path = LEGACY_OUT_FILE
        if not out_path:
            raise FileNotFoundError("Legacy output file template was not found in executable folder.")
        if not os.path.exists(out_path):
            raise FileNotFoundError("Legacy output file was not generated!")

        with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        results = _parse_out_file(lines, eval_points)
        _cache_put(cache_key, results)
        return results


def _format_num(val):
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val)

def _write_in_file(solver_stack: List[Dict], load_cfg: Dict, eval_points: List[Dict]):
    """Format the legacy IN text blob."""
    n_layers = len(solver_stack)
    
    # Layer properties
    moduli = []
    poissons = []
    thicknesses = []
    for i, layer in enumerate(solver_stack):
        m = layer['modulus']
        t = layer.get('thickness', 0)
        
        if isinstance(m, float) and m == int(m):
            moduli.append(str(int(m)))
        else:
            moduli.append(f"{m:.6f}" if isinstance(m, float) else str(m))
            
        poissons.append(f"{layer['poisson']:.2f}".lstrip('0'))
        
        if i < n_layers - 1:
            if isinstance(t, float) and t == int(t):
                thicknesses.append(str(int(t)))
            else:
                thicknesses.append(f"{t:.2f}" if isinstance(t, float) else str(t))

    # Load properties
    load_val = load_cfg['load']
    if isinstance(load_val, float) and load_val == int(load_val):
        load_str = str(int(load_val))
    else:
        load_str = str(load_val)
        
    press_val = f"{load_cfg['pressure']:.2f}"
    
    is_dual = load_cfg.get("is_dual", True)
    load_type_int = 2 if is_dual else 1
    
    n_eval = len(eval_points)
    
    # Build text
    lines = []
    lines.append(str(n_layers))
    lines.append(" ".join(moduli) + " ")
    lines.append(" ".join(poissons) + " ")
    if thicknesses:
        lines.append(" ".join(thicknesses) + " ")
    else:
        lines.append("")
    lines.append(f"{load_str} {press_val}")
    lines.append(str(n_eval))
    
    for pt in eval_points:
        z_str = _format_num(pt['z'])
        r_str = _format_num(pt['r'])
        lines.append(f"{z_str} {r_str}")
        
    lines.append(str(load_type_int))
    lines.append("")  # Empty line at end

    in_path = LEGACY_IN_FILE
    if not in_path:
        raise FileNotFoundError("Legacy input file template was not found in executable folder.")
    with open(in_path, "w") as f:
        f.write("\n".join(lines))


def _parse_out_file(lines: List[str], expected_evals: List[Dict]) -> List[Dict]:
    """Parse the tabular output from the legacy OUT file."""
    results = []
    parse_errors = []
    
    # Example format:
    #     Z        R      SigmaZ      SigmaT     SigmaR     TaoRZ      DispZ      epZ        epT        epR
    #    55.00    0.00-0.4108E+00 0.6959E+00 0.6087E+00-0.1910E-01 0.4357E+00-0.2478E-03 0.1790E-03 0.1454E-03
    
    data_start_idx = -1
    for i, line in enumerate(lines):
        if "epZ" in line and "epT" in line and "Z" in line and "R" in line:
            data_start_idx = i + 1
            break
            
    if data_start_idx == -1:
        raise ValueError("Could not find data table header in legacy output")

    # The next len(expected_evals) lines should be the tabular data
    for i in range(len(expected_evals)):
        line_idx = data_start_idx + i
        if line_idx >= len(lines):
            break
            
        text = lines[line_idx].strip()
        if not text:
            continue

        # Robust float extraction: handle formats like 0.00, -0.4108E+00, -0.123D-02
        # and cases where numbers run together without spaces. Use a regex to
        # extract numeric tokens (supports E/e/D/d exponents and optional sign).
        # Examples matched: -1.234E-05, 0.123, 123, -0.12D+03
        float_re = r"[+-]?(?:\d*\.\d+|\d+)(?:[EeDd][+-]?\d+)?"
        import re

        nums = re.findall(float_re, text)

        # Some legacy rows include a trailing 'L' on the first token (index/id).
        # If present, strip an 'L' from the first numeric-like token.
        if nums and nums[0].endswith('L'):
            nums[0] = nums[0][:-1]

        def parse_legacy_float(token: str) -> float:
            return float(token.replace('D', 'E').replace('d', 'E'))

        if len(nums) >= 6:
            try:
                # Heuristic mapping: legacy table typically has many columns; we
                # conservatively map from the end to find epZ/epT and surface values.
                # Use -3 and -2 like before when available, otherwise best-effort.
                epz_str = nums[-3] if len(nums) >= 3 else nums[-2]
                ept_str = nums[-2] if len(nums) >= 2 else nums[-1]

                epz = parse_legacy_float(epz_str)
                ept = parse_legacy_float(ept_str)

                pt = expected_evals[i]

                def safe_get(idx_from_end, default=0.0):
                    if len(nums) >= abs(idx_from_end):
                        try:
                            return parse_legacy_float(nums[idx_from_end])
                        except Exception:
                            return default
                    return default

                results.append({
                    "z": pt['z'],
                    "r": pt['r'],
                    "sigma_z": safe_get(-8, 0.0),
                    "sigma_r": safe_get(-6, 0.0),
                    "sigma_t": safe_get(-7, 0.0),
                    "tau_rz": safe_get(-5, 0.0),
                    "disp_z": safe_get(-4, 0.0),
                    "eps_z": epz,
                    "eps_t": ept,
                    "eps_r": safe_get(-1, 0.0)
                })
            except Exception as e:
                parse_errors.append(f"line {line_idx + 1}: {e}")
        else:
            parse_errors.append(f"line {line_idx + 1}: insufficient numeric columns ({len(nums)})")

    if parse_errors:
        logger.error("Legacy output parse errors detected: %s", parse_errors)
        raise ValueError(f"Failed to parse legacy output rows ({len(parse_errors)} errors)")

    if len(results) != len(expected_evals):
        raise ValueError(
            f"Parsed {len(results)} legacy rows but expected {len(expected_evals)}"
        )
                
    return results

def run_iitpave_from_stack(solver_stack: List[Dict], load_cfg: Dict, eval_points: List[Dict],
                            timeout: float = DEFAULT_BRIDGE_TIMEOUT_S) -> List[Dict]:
    """
    High-level API for running the legacy bridge based on an established layer stack.
    Handles fallbacks and formats.
    """
    return run_iitpave_bridge(solver_stack, load_cfg, eval_points, timeout=timeout)


def is_bridge_available() -> bool:
    """Preferred neutral alias for bridge availability checks."""
    return is_iitpave_available()


def run_legacy_bridge(solver_stack: List[Dict], load_cfg: Dict, eval_points: List[Dict],
                      timeout: float = DEFAULT_BRIDGE_TIMEOUT_S) -> List[Dict]:
    """Preferred neutral alias for bridge execution."""
    return run_iitpave_bridge(solver_stack, load_cfg, eval_points, timeout=timeout)


def run_bridge_from_stack(solver_stack: List[Dict], load_cfg: Dict, eval_points: List[Dict],
                           timeout: float = DEFAULT_BRIDGE_TIMEOUT_S) -> List[Dict]:
    """Preferred neutral alias for stack-based bridge execution."""
    return run_iitpave_from_stack(solver_stack, load_cfg, eval_points, timeout=timeout)

