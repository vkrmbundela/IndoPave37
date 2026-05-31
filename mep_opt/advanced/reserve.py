"""
Module B: Structural Reserve Meter
===================================
Computes the exact MSA level where CDF reaches 1.0 (structural capacity),
giving engineers a clear picture of the safety buffer in their design.
"""

import math

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

# When either intercept_msa or reserve_percent is mathematically infinite
# (vanishingly small strain → infinite allowable repetitions) we cap the
# reported value before sending it to the UI. Plain infinities are not
# valid JSON and the dashboard renders "+NaN%" or "Low Reserve" badges
# off them. The cap is generous (10⁹ MSA / 10⁶ %) — well above any real
# pavement design — so it cannot be confused with a real intercept.
_FINITE_MSA_CAP = 1.0e9
_FINITE_RESERVE_PCT_CAP = 1.0e6


def _finite(value: float, cap: float) -> float:
    """Clamp infinities/NaN to a large finite number for JSON-safe output."""
    if value is None:
        return 0.0
    if math.isnan(value):
        return 0.0
    if math.isinf(value):
        return cap if value > 0 else -cap
    return value


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
        governing_mode, and individual Nf/NR capacities. All numeric
        fields are guaranteed finite so the response serialises cleanly
        to JSON and the UI's gauge math (comparisons, multiplications)
        never sees Infinity / NaN.
    """
    rel = _RELIABILITY_MAP.get(reliability, ReliabilityLevel.R80)
    if design_msa >= 20.0 and rel == ReliabilityLevel.R80:
        rel = ReliabilityLevel.R90

    result = find_intercept_msa(
        eps_t=eps_t,
        eps_v=eps_v,
        mix_modulus=mix_modulus,
        reliability=rel,
        air_voids=air_voids,
        bitumen_volume=bitumen_volume,
    )

    intercept_msa = result["intercept_msa"]

    if design_msa > 0 and not math.isinf(intercept_msa):
        reserve_percent = ((intercept_msa - design_msa) / design_msa) * 100.0
    elif design_msa > 0 and math.isinf(intercept_msa):
        reserve_percent = float("inf")  # infinite capacity, finite design
    else:
        reserve_percent = float("inf")  # design_msa == 0

    intercept_safe = _finite(intercept_msa, _FINITE_MSA_CAP)
    reserve_safe = _finite(reserve_percent, _FINITE_RESERVE_PCT_CAP)
    nf_safe = _finite(result["Nf_msa"], _FINITE_MSA_CAP)
    nr_safe = _finite(result["NR_msa"], _FINITE_MSA_CAP)

    return {
        "design_msa": round(design_msa, 2),
        "intercept_msa": round(intercept_safe, 2),
        "reserve_percent": round(reserve_safe, 1),
        "governing_mode": result["governing_mode"],
        "Nf_msa": round(nf_safe, 2),
        "NR_msa": round(nr_safe, 2),
        # Surface the unbounded flag explicitly so the UI can render
        # "Excellent (capacity ≫ design)" instead of a giant number.
        "is_unbounded": math.isinf(intercept_msa) or math.isinf(reserve_percent),
    }
