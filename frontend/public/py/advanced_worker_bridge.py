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
from mep_opt.advanced._strain_utils import ADVANCED_SCOPE_NOTE


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


def _validate_advanced(r: dict) -> None:
    """
    Mirror of the /api/v2/* Pydantic rules (mep_opt.advanced.router) for the
    in-browser path, so the same request is rejected with the same message
    instead of giving an all-null result.
    """
    from mep_opt.solver.burmister import MAX_RADIAL_OFFSET

    def finite(v, name):
        v = float(v)
        if not math.isfinite(v):
            raise ValueError(f"{name} must be a finite number")
        return v

    for lay in r.get("layers") or []:
        if not finite(lay.get("modulus"), "modulus") > 0:
            raise ValueError("modulus must be positive")
        if not (0.0 <= finite(lay.get("poisson"), "poisson") < 0.5):
            raise ValueError("poisson must be in [0, 0.5)")
        h = finite(lay.get("thickness"), "thickness")
        if h < 0:
            raise ValueError("thickness must be non-negative")
        if 0 < h < 1.0:
            raise ValueError("layers thinner than 1 mm are not modelled; enter 0 to omit the layer")
        if float(lay.get("friction_factor", 1.0)) not in (0.0, 1.0):
            raise ValueError("friction_factor must be 1 (fully bonded) or 0 (frictionless); "
                             "partial bond is not modelled")
    for p in r.get("eval_points") or []:
        if finite(p.get("z"), "z") < 0:
            raise ValueError("z must be non-negative and finite")
        rr = finite(p.get("r"), "r")
        if rr < 0 or rr > MAX_RADIAL_OFFSET:
            raise ValueError(f"r must be non-negative, finite and <= {MAX_RADIAL_OFFSET:.0f} mm")
    if "reliability" in r and int(r["reliability"]) not in (80, 90):
        raise ValueError(f"reliability must be one of (80, 90); got {r['reliability']}")
    for key in ("cumulative_msa", "design_msa", "mix_modulus", "eps_t", "eps_v", "r_max"):
        if key in r and r[key] is not None:
            finite(r[key], key)


def run_advanced(req_json):
    """Dispatch one advanced-module request. req = {"op": str, "request": {...}}."""
    try:
        data = json.loads(req_json)
        op = (data.get("op") or "").strip().lower()
        r = data.get("request") or {}
        _validate_advanced(r)

        if op == "sensitivity":
            res = compute_sensitivity(
                r["layers"], r["load"], r["eval_points"],
                float(r["cumulative_msa"]), float(r["mix_modulus"]),
                int(r.get("reliability", 80)),
                r.get("point_roles"),  # None -> 4-point dashboard convention
                float(r.get("air_voids", 3.0)), float(r.get("bitumen_volume", 11.5)),
            )
            return json.dumps(_to_native({"status": "ok", "layers": res, "scope": ADVANCED_SCOPE_NOTE}))

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
