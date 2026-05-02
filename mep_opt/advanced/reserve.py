"""
Module B: Structural Reserve Meter
===================================
Computes the exact MSA level where CDF reaches 1.0 (structural capacity),
giving engineers a clear picture of the safety buffer in their design.
"""

from mep_opt.solver.irc37 import (
    find_intercept_msa, ReliabilityLevel,
)


# Map integer reliability values to enum
_RELIABILITY_MAP = {
    80: ReliabilityLevel.R80,
    90: ReliabilityLevel.R90,
    95: ReliabilityLevel.R95,
    98: ReliabilityLevel.R98,
    99: ReliabilityLevel.R99,
}


def compute_reserve(
    eps_t: float,
    eps_v: float,
    mix_modulus: float,
    design_msa: float,
    reliability: int = 80,
    air_voids: float = 4.0,
    bitumen_volume: float = 11.5,
) -> dict:
    """
    Compute structural reserve — how much traffic capacity remains
    beyond the design traffic.

    Returns:
        Dictionary with design_msa, intercept_msa, reserve_percent,
        governing_mode, and individual Nf/NR capacities.
    """
    rel = _RELIABILITY_MAP.get(reliability, ReliabilityLevel.R80)

    result = find_intercept_msa(
        eps_t=eps_t,
        eps_v=eps_v,
        mix_modulus=mix_modulus,
        reliability=rel,
        air_voids=air_voids,
        bitumen_volume=bitumen_volume,
    )

    intercept_msa = result["intercept_msa"]

    if design_msa > 0:
        reserve_percent = ((intercept_msa - design_msa) / design_msa) * 100.0
    else:
        reserve_percent = float("inf")

    return {
        "design_msa": round(design_msa, 2),
        "intercept_msa": round(intercept_msa, 2),
        "reserve_percent": round(reserve_percent, 1),
        "governing_mode": result["governing_mode"],
        "Nf_msa": round(result["Nf_msa"], 2),
        "NR_msa": round(result["NR_msa"], 2),
    }
