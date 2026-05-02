"""
Legacy Reference Bridge
=======================
Extracts strain values from the legacy reference executable to ensure
regulatory reporting compliance by sidestepping pure-python integration drift.
"""

import os
import sys
import subprocess
import threading
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

# Global lock to prevent race conditions on the legacy IN file
_BRIDGE_LOCK = threading.Lock()

# Define the original directory for legacy executable files
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _discover_legacy_executable_path(project_root: str) -> str:
    """Locate the legacy executable by scanning for a *PFILE.exe binary."""
    for root, _, files in os.walk(project_root):
        for name in files:
            if name.upper().endswith("PFILE.EXE"):
                return os.path.join(root, name)
    return ""


LEGACY_EXE = _discover_legacy_executable_path(PROJECT_ROOT)
LEGACY_DIR = os.path.dirname(LEGACY_EXE) if LEGACY_EXE else ""


def _discover_legacy_io_file(directory: str, suffix: str) -> str:
    if not directory or not os.path.isdir(directory):
        return ""
    candidates = [name for name in os.listdir(directory) if name.lower().endswith(suffix)]
    if not candidates:
        return ""
    candidates.sort()
    return os.path.join(directory, candidates[0])


LEGACY_IN_FILE = _discover_legacy_io_file(LEGACY_DIR, ".in")
LEGACY_OUT_FILE = _discover_legacy_io_file(LEGACY_DIR, ".out")

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



def run_iitpave_bridge(solver_stack: List[Dict[str, float]], 
                       load_cfg: Dict[str, float], 
                       eval_points: List[Dict[str, float]]) -> List[Dict[str, Any]]:
    """
    Runs the legacy reference executable by formatting an IN file
    and reading the OUT file.

    Returns a list-of-dicts structure:
    [ { "z": float, "r": float, "eps_z": float, "eps_t": float }, ... ]
    """
    
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
        subprocess.run(
            cmd,
            cwd=LEGACY_DIR,
            capture_output=True,
            text=True,
            check=True,
            startupinfo=startupinfo,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )

        # Parse results
        out_path = LEGACY_OUT_FILE
        if not out_path:
            raise FileNotFoundError("Legacy output file template was not found in executable folder.")
        if not os.path.exists(out_path):
            raise FileNotFoundError("Legacy output file was not generated!")

        with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        return _parse_out_file(lines, eval_points)


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
            
        # Unfortunately the numbers can touch if there's a negative sign!
        # e.g. 0.00-0.4108E+00 instead of 0.00 -0.4108E+00
        # Replace occurrences of "-" that are likely connected to numbers (not scientific E- )
        # A simple hack: replace " -" with " -", and "E-" with "E_minus_" temporarily
        text = text.replace("E-", "EMINUS")
        text = text.replace("E+", "EPLUS")
        text = text.replace("-", " -")
        text = text.replace("EMINUS", "E-")
        text = text.replace("EPLUS", "E+")
        
        parts = text.split()
        
        if parts and parts[0].endswith('L'):
            parts[0] = parts[0][:-1]
        
        if len(parts) >= 10:
            # We want epZ (index 8) and epT (index 9) typically, or -2 and -1 if 10 columns
            try:
                epz_str = parts[-3]
                ept_str = parts[-2]
                
                # Convert back to float
                epz = float(epz_str)
                ept = float(ept_str)
                
                pt = expected_evals[i]
                
                # NOTE: Keep legacy sign conventions to preserve compliance checks.
                # Alternatively, we could flip them back to Burmister standards.
                # Legacy standard: positive epZ is compressive.
                # Since MEP-Opt uses Burmister: negative eps_z is compressive. 
                # Let's map it safely. If legacy output is positive for compression,
                # and MEP-Opt needs negative, we multiply by -1 if we want to drop it in.
                # We keep exact legacy compliance, so we return raw legacy values.
                
                results.append({
                    "z": pt['z'],
                    "r": pt['r'],
                    "sigma_z": float(parts[-8]) if len(parts) >= 10 else 0.0,
                    "sigma_r": float(parts[-6]) if len(parts) >= 10 else 0.0,
                    "sigma_t": float(parts[-7]) if len(parts) >= 10 else 0.0,
                    "tau_rz": float(parts[-5]) if len(parts) >= 10 else 0.0,
                    "disp_z": float(parts[-4]) if len(parts) >= 10 else 0.0,
                    "eps_z": epz, # Raw from legacy output
                    "eps_t": ept, # Raw from legacy output
                    "eps_r": float(parts[-1]) if len(parts) >= 10 else 0.0
                })
            except Exception as e:
                parse_errors.append(f"line {line_idx + 1}: {e}")

    if parse_errors:
        logger.error("Legacy output parse errors detected: %s", parse_errors)
        raise ValueError(f"Failed to parse legacy output rows ({len(parse_errors)} errors)")

    if len(results) != len(expected_evals):
        raise ValueError(
            f"Parsed {len(results)} legacy rows but expected {len(expected_evals)}"
        )
                
    return results

def run_iitpave_from_stack(solver_stack: List[Dict], load_cfg: Dict, eval_points: List[Dict]) -> List[Dict]:
    """
    High-level API for running the legacy bridge based on an established layer stack.
    Handles fallbacks and formats.
    """
    return run_iitpave_bridge(solver_stack, load_cfg, eval_points)


def is_bridge_available() -> bool:
    """Preferred neutral alias for bridge availability checks."""
    return is_iitpave_available()


def run_legacy_bridge(solver_stack: List[Dict], load_cfg: Dict, eval_points: List[Dict]) -> List[Dict]:
    """Preferred neutral alias for bridge execution."""
    return run_iitpave_bridge(solver_stack, load_cfg, eval_points)


def run_bridge_from_stack(solver_stack: List[Dict], load_cfg: Dict, eval_points: List[Dict]) -> List[Dict]:
    """Preferred neutral alias for stack-based bridge execution."""
    return run_iitpave_from_stack(solver_stack, load_cfg, eval_points)

