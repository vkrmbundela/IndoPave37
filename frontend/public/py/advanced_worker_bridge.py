"""
Advanced-modules Web Worker Bridge
==================================
Bridges JSON requests from the Pyodide Web Worker to the mep_opt.advanced
compute functions, so the Sensitivity, Monte-Carlo, Reserve and Strain-Field
panels run fully in-browser (no FastAPI backend needed). The request and
response shapes mirror the FastAPI /api/v2/* endpoints so the frontend code is
identical whether it talks to the backend or to this bridge.
"""

import json
import math

import numpy as np

from mep_opt.advanced.sensitivity import compute_sensitivity
from mep_opt.advanced.montecarlo import run_monte_carlo
from mep_opt.advanced.reserve import compute_reserve
from mep_opt.advanced.strain_field import compute_strain_field


def _to_native(value):
    """NumPy -> native Python, with NaN/Inf -> None for valid JSON."""
    if isinstance(value, dict):
        return {k: _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_to_native(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        v = value.item()
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return None
        return v
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def run_advanced(req_json):
    """Dispatch one advanced-module request. req = {"op": str, "request": {...}}."""
    try:
        data = json.loads(req_json)
        op = (data.get("op") or "").strip().lower()
        r = data.get("request") or {}

        if op == "sensitivity":
            res = compute_sensitivity(
                r["layers"], r["load"], r["eval_points"],
                float(r["cumulative_msa"]), float(r["mix_modulus"]),
                int(r.get("reliability", 80)),
                r.get("point_roles"),  # None -> 4-point dashboard convention
                float(r.get("air_voids", 3.0)), float(r.get("bitumen_volume", 11.5)),
            )
            return json.dumps(_to_native({"status": "ok", "layers": res}))

        if op == "montecarlo":
            res = run_monte_carlo(
                r["layers"], r["load"], r["eval_points"],
                float(r["cumulative_msa"]), float(r["mix_modulus"]),
                r.get("sigmas"), int(r.get("n_simulations", 100)),
                int(r.get("reliability", 80)),
                r.get("point_roles"),  # None -> 4-point dashboard convention
                float(r.get("air_voids", 3.0)), float(r.get("bitumen_volume", 11.5)),
            )
            return json.dumps(_to_native({"status": "ok", **res}))

        if op == "reserve":
            res = compute_reserve(
                float(r["eps_t"]), float(r["eps_v"]), float(r["mix_modulus"]),
                float(r["design_msa"]), int(r.get("reliability", 80)),
                float(r.get("air_voids", 3.0)), float(r.get("bitumen_volume", 11.5)),
            )
            return json.dumps(_to_native({"status": "ok", **res}))

        if op in ("strain-field", "strain_field"):
            res = compute_strain_field(
                r["layers"], r["load"],
                int(r.get("r_steps", 12)), int(r.get("z_steps", 25)),
                float(r.get("r_max", 500.0)),
            )
            return json.dumps(_to_native({"status": "ok", **res}))

        return json.dumps({"status": "error", "message": f"Unknown advanced op: {op!r}"})
    except Exception as e:  # surface a structured error to the worker
        import traceback
        return json.dumps({"status": "error", "message": str(e),
                           "traceback": traceback.format_exc()})
