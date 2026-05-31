"""
Module F: Monte Carlo Risk Analysis
=====================================
Run N simulations with Gaussian noise on layer thicknesses
to quantify the probability of design adequacy.
"""

import numpy as np
from typing import Optional, List, Dict
from mep_opt.solver.legacy_bridge import run_bridge_from_stack
from mep_opt.solver.irc37 import check_design_adequacy, ReliabilityLevel
from mep_opt.advanced._strain_utils import extract_design_strains

_RELIABILITY_MAP = {
    80: ReliabilityLevel.R80, 90: ReliabilityLevel.R90,
    95: ReliabilityLevel.R95, 98: ReliabilityLevel.R98,
    99: ReliabilityLevel.R99,
}


def run_monte_carlo(
    layers: list[dict],
    load_data: dict,
    eval_points: list[dict],
    cumulative_msa: float,
    mix_modulus: float,
    sigmas: Optional[List[float]] = None,
    n_simulations: int = 100,
    reliability: int = 80,
    point_roles: Optional[Dict[str, List[int]]] = None,
    air_voids: float = 3.0,
    bitumen_volume: float = 11.5,
) -> dict:
    """
    Run Monte Carlo simulation with Gaussian noise on layer thicknesses.

    Args:
        layers: [{modulus, poisson, thickness}, ...] (last = subgrade)
        load_data: {load, pressure, is_dual, spacing}
        eval_points: [{z, r}, ...]
        cumulative_msa: design traffic in MSA
        mix_modulus: bituminous modulus for fatigue
        sigmas: std deviation (mm) per layer (default 5mm for non-subgrade)
        n_simulations: number of runs (default 100)
        point_roles: optional mapping of role name → result indices, e.g.
            ``{"bit_bottom": [0, 1], "sub_top": [2, 3]}``. When omitted,
            the dashboard convention is assumed (first two points at the
            bituminous bottom, next two at subgrade top).

    Returns:
        Statistics and distribution data for visualization.
    """
    if n_simulations < 1:
        raise ValueError("n_simulations must be >= 1")

    rel = _RELIABILITY_MAP.get(reliability, ReliabilityLevel.R80)
    if cumulative_msa >= 20.0 and rel == ReliabilityLevel.R80:
        rel = ReliabilityLevel.R90
    n_layers = len(layers)

    # Default sigmas: 5mm for each non-subgrade layer, 0 for subgrade
    if sigmas is None:
        sigmas = [5.0] * (n_layers - 1) + [0.0]
    elif len(sigmas) < n_layers:
        sigmas = list(sigmas) + [0.0] * (n_layers - len(sigmas))

    base_thicknesses = [ld.get("thickness", 0) for ld in layers]

    cdf_f_values = []
    cdf_r_values = []
    adequate_count = 0

    rng = np.random.default_rng(seed=42)

    for _ in range(n_simulations):
        # Perturb thicknesses
        perturbed = []
        for i, lyr in enumerate(layers):
            entry = dict(lyr)
            if sigmas[i] > 0 and base_thicknesses[i] > 0:
                noisy_h = max(5.0, rng.normal(base_thicknesses[i], sigmas[i]))
                entry["thickness"] = round(noisy_h, 1)
            perturbed.append(entry)

        try:
            res = run_bridge_from_stack(perturbed, load_data, eval_points)
            # Role-aware extraction: each iteration is independent so a
            # short or oddly ordered result list cannot corrupt the
            # statistics by selecting the wrong row.
            eps_t, eps_v = extract_design_strains(res, point_roles)

            adequacy = check_design_adequacy(
                eps_t, eps_v, cumulative_msa, mix_modulus, rel,
                air_voids=air_voids, bitumen_volume=bitumen_volume,
            )
            cdf_f = adequacy["CDF_fatigue"]
            cdf_r = adequacy["CDF_rutting"]
            cdf_f_values.append(cdf_f)
            cdf_r_values.append(cdf_r)

            if adequacy["overall_adequate"]:
                adequate_count += 1
        except Exception:
            # Solver failure counts as inadequate
            cdf_f_values.append(float("inf"))
            cdf_r_values.append(float("inf"))

    # Compute statistics
    cdf_f_arr = np.array([v for v in cdf_f_values if np.isfinite(v)])
    cdf_r_arr = np.array([v for v in cdf_r_values if np.isfinite(v)])

    # Build histogram bins for the governing CDF
    max_cdf_values = [max(f, r) for f, r in zip(cdf_f_values, cdf_r_values) if np.isfinite(f) and np.isfinite(r)]
    if max_cdf_values:
        hist_max = min(max(max_cdf_values) * 1.1, 3.0)
        bin_edges = np.linspace(0, hist_max, 21)
        counts, _ = np.histogram(max_cdf_values, bins=bin_edges)
        histogram = [
            {"bin_start": round(bin_edges[i], 3), "bin_end": round(bin_edges[i+1], 3), "count": int(counts[i])}
            for i in range(len(counts))
        ]
    else:
        histogram = []

    return {
        "n_simulations": n_simulations,
        "n_adequate": adequate_count,
        "probability_adequate": round(adequate_count / n_simulations * 100, 1),
        "cdf_f_stats": {
            "mean": round(float(np.mean(cdf_f_arr)), 4) if len(cdf_f_arr) else None,
            "std": round(float(np.std(cdf_f_arr)), 4) if len(cdf_f_arr) else None,
            "p5": round(float(np.percentile(cdf_f_arr, 5)), 4) if len(cdf_f_arr) else None,
            "p95": round(float(np.percentile(cdf_f_arr, 95)), 4) if len(cdf_f_arr) else None,
        },
        "cdf_r_stats": {
            "mean": round(float(np.mean(cdf_r_arr)), 4) if len(cdf_r_arr) else None,
            "std": round(float(np.std(cdf_r_arr)), 4) if len(cdf_r_arr) else None,
            "p5": round(float(np.percentile(cdf_r_arr, 5)), 4) if len(cdf_r_arr) else None,
            "p95": round(float(np.percentile(cdf_r_arr, 95)), 4) if len(cdf_r_arr) else None,
        },
        "histogram": histogram,
        "sigmas_used": sigmas[:-1],  # exclude subgrade
    }
