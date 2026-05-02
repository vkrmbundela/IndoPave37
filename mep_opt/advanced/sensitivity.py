"""
Module A: Structural Sensitivity Heatmaps
==========================================
For each layer, perturb thickness by small deltas and compute
how CDF_fatigue and CDF_rutting change — revealing which layer
is most sensitive to construction error.
"""

from mep_opt.solver.legacy_bridge import run_bridge_from_stack
from mep_opt.solver.irc37 import check_design_adequacy, ReliabilityLevel

DELTAS = [-10, -5, 5, 10]  # mm perturbations

_RELIABILITY_MAP = {
    80: ReliabilityLevel.R80, 90: ReliabilityLevel.R90,
    95: ReliabilityLevel.R95, 98: ReliabilityLevel.R98,
    99: ReliabilityLevel.R99,
}


def compute_sensitivity(
    layers: list[dict],
    load_data: dict,
    eval_points: list[dict],
    cumulative_msa: float,
    mix_modulus: float,
    reliability: int = 80,
) -> list[dict]:
    """
    Compute CDF sensitivity for each non-subgrade layer.

    Args:
        layers: list of {modulus, poisson, thickness} dicts (last = subgrade)
        load_data: {load, pressure, is_dual, spacing}
        eval_points: [{z, r}, ...]
        cumulative_msa: design traffic in MSA
        mix_modulus: bituminous mix modulus for fatigue calc

    Returns:
        List of {layer_index, layer_name, deltas: [{delta_mm, CDF_f, CDF_r, eps_t, eps_v}]}
    """
    rel = _RELIABILITY_MAP.get(reliability, ReliabilityLevel.R80)
    results = []

    # Skip last layer (subgrade — infinite, no thickness to perturb)
    for layer_idx in range(len(layers) - 1):
        base_h = layers[layer_idx].get("thickness", 0)
        if base_h <= 0:
            continue

        delta_results = []
        for delta in DELTAS:
            new_h = base_h + delta
            if new_h <= 0:
                continue

            # Build perturbed stack
            perturbed = []
            for i, lyr in enumerate(layers):
                entry = dict(lyr)
                if i == layer_idx:
                    entry["thickness"] = new_h
                perturbed.append(entry)

            try:
                res = run_bridge_from_stack(perturbed, load_data, eval_points)
                eps_t = max(abs(r["eps_t"]) for r in res)
                eps_v = max(abs(r["eps_z"]) for r in res)

                adequacy = check_design_adequacy(
                    eps_t, eps_v, cumulative_msa, mix_modulus, rel,
                )

                delta_results.append({
                    "delta_mm": delta,
                    "thickness_mm": new_h,
                    "CDF_f": round(adequacy["CDF_fatigue"], 4),
                    "CDF_r": round(adequacy["CDF_rutting"], 4),
                    "eps_t": eps_t,
                    "eps_v": eps_v,
                })
            except Exception:
                delta_results.append({
                    "delta_mm": delta,
                    "thickness_mm": new_h,
                    "CDF_f": None,
                    "CDF_r": None,
                    "eps_t": None,
                    "eps_v": None,
                })

        results.append({
            "layer_index": layer_idx,
            "base_thickness": base_h,
            "deltas": delta_results,
        })

    return results
