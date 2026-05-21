"""
IRC:SP:72-2015 — Low-Volume Rural Road Design Branch
====================================================
For design traffic up to 2 million cumulative ESAL (~2 MSA), IRC:37 hands
off to IRC:SP:72, a catalogue-based method for low-volume rural roads.

This module provides the SP:72 *classification and rule* layer:
  - cumulative ESAL computation (same growth-series as IRC:37 traffic),
  - traffic categorisation T1..T9,
  - subgrade strength classification S1..S5 (from CBR),
  - regime detection (is this an SP:72 job?),
  - the SP:72 composition rules the optimizer must honour below 2 MSA.

The mechanistic IITPAVE engine still verifies the design; SP:72 changes the
*framing and constraints* (thin bituminous surfacing, coarser thickness
increments, blacktop-only above 100k ESAL, minimum base thickness).

Source: IRC:SP:72-2015, "Guidelines for the Design of Flexible Pavements
for Low Volume Rural Roads (First Revision)", §3 (Traffic), §8 (Recommended
Designs), Figs. 4 & 6.
"""

from dataclasses import dataclass
from typing import List, Optional


# SP:72 upper bound: 2,000,000 cumulative ESAL = 2 MSA. Above this → IRC:37.
SP72_MAX_ESAL = 2_000_000.0
SP72_MAX_MSA = 2.0

# Blacktopped (bituminous-surfaced) flexible pavement is warranted only at or
# above 100,000 ESAL (§8(iv)); below that a gravel/granular surface is used.
BLACKTOP_MIN_ESAL = 100_000.0

# Minimum granular base thickness for 100,000–1,000,000 ESAL (§8(v)).
MIN_BASE_THICKNESS_MM = 150.0

# SP:72 recommended thicknesses are multiples of 75 or 100 mm (§8(vii)).
SP72_THICKNESS_INCREMENT_MM = 75.0


# Traffic categories T1..T9 by cumulative ESAL (IRC:SP:72-2015 §3.5, Table).
# (label, lower_exclusive, upper_inclusive, surfacing_hint)
TRAFFIC_CATEGORIES = [
    ("T1", 10_000,    30_000,    "surface dressing / gravel"),
    ("T2", 30_000,    60_000,    "surface dressing / gravel"),
    ("T3", 60_000,    100_000,   "surface dressing / gravel"),
    ("T4", 100_000,   200_000,   "surface dressing"),
    ("T5", 200_000,   300_000,   "20 mm premix carpet"),
    ("T6", 300_000,   600_000,   "20 mm premix carpet"),
    ("T7", 600_000,   1_000_000, "20 mm premix carpet"),
    ("T8", 1_000_000, 1_500_000, "20 mm premix carpet"),
    ("T9", 1_500_000, 2_000_000, "20 mm premix carpet"),
]

# Subgrade strength classes S1..S5 by CBR (IRC:SP:72-2015 Fig. 4 legend).
# (label, name, cbr_low, cbr_high)
SUBGRADE_CLASSES = [
    ("S1", "Very Poor", 2.0, 2.0),
    ("S2", "Poor",      3.0, 4.0),
    ("S3", "Fair",      5.0, 6.0),
    ("S4", "Good",      7.0, 9.0),
    ("S5", "Very Good", 10.0, 15.0),
]


@dataclass
class SP72Classification:
    """Result of classifying a low-volume design under IRC:SP:72."""
    is_low_volume: bool          # True if design ESAL <= 2,000,000 (SP:72 regime)
    esal: float                  # cumulative ESAL applications
    msa: float                   # cumulative MSA (esal / 1e6)
    traffic_category: Optional[str]   # "T1".."T9" or None if out of SP:72 range
    surfacing_hint: Optional[str]     # recommended surfacing for the category
    subgrade_class: Optional[str]     # "S1".."S5"
    subgrade_class_name: Optional[str]
    blacktop_required: bool      # ESAL >= 100,000 → bituminous surfacing
    min_base_thickness_mm: float # minimum granular base for this regime
    thickness_increment_mm: float
    advisory: List[str]          # human-readable design notes


def compute_esal(cvpd: float, vdf: float, growth_rate: float,
                 design_life_years: int, lane_factor: float) -> float:
    """
    Cumulative ESAL applications over the design life (IRC:SP:72 §3.4.4).

        N = T0 × 365 × [((1+r)^n − 1) / r] × L,   T0 = CVPD × VDF

    This is the same growth-series IRC:37 uses; SP:72 just reports it in
    ESAL rather than MSA.
    """
    T0 = cvpd * vdf
    r = growth_rate
    n = design_life_years
    if abs(r) < 1e-10:
        series = float(n)
    else:
        series = ((1.0 + r) ** n - 1.0) / r
    return T0 * 365.0 * series * lane_factor


def classify_traffic(esal: float):
    """Return (label, surfacing_hint) for the SP:72 traffic category, or (None, None)."""
    for label, lo, hi, hint in TRAFFIC_CATEGORIES:
        # Ranges are lower-exclusive / upper-inclusive; T1's lower bound is
        # inclusive at 10,000 (the practical minimum).
        if (esal > lo or (label == "T1" and esal >= lo)) and esal <= hi:
            return label, hint
    return None, None


def classify_subgrade(cbr: float):
    """Return (label, name) for the SP:72 subgrade strength class."""
    for label, name, lo, hi in SUBGRADE_CLASSES:
        if lo <= cbr <= hi:
            return label, name
    # Clamp outside the tabulated 2–15 CBR span.
    if cbr < SUBGRADE_CLASSES[0][2]:
        return SUBGRADE_CLASSES[0][0], SUBGRADE_CLASSES[0][1]
    return SUBGRADE_CLASSES[-1][0], SUBGRADE_CLASSES[-1][1]


def is_low_volume(msa: float) -> bool:
    """True if the design traffic falls in the IRC:SP:72 regime (≤ 2 MSA)."""
    return msa <= SP72_MAX_MSA


def classify(cvpd: float, vdf: float, growth_rate: float,
             design_life_years: int, lane_factor: float,
             cbr: float) -> SP72Classification:
    """Full SP:72 classification + advisory for a candidate low-volume design."""
    esal = compute_esal(cvpd, vdf, growth_rate, design_life_years, lane_factor)
    msa = esal / 1e6
    low = is_low_volume(msa)
    cat, hint = classify_traffic(esal)
    s_label, s_name = classify_subgrade(cbr)
    blacktop = esal >= BLACKTOP_MIN_ESAL

    advisory: List[str] = []
    if low:
        advisory.append(
            f"Design traffic {esal:,.0f} ESAL (~{msa:.2f} MSA) is in the IRC:SP:72 "
            f"low-volume regime (≤ 2 MSA); IRC:37 catalogue rules apply."
        )
        if cat:
            advisory.append(f"Traffic category {cat}; recommended surfacing: {hint}.")
        else:
            advisory.append(
                f"Traffic {esal:,.0f} ESAL is below the SP:72 practical minimum "
                f"(10,000 ESAL); treat as a gravel road."
            )
        advisory.append(f"Subgrade class {s_label} ({s_name}), CBR {cbr:g}%.")
        if blacktop:
            advisory.append(
                "Bituminous surfacing warranted (≥ 100,000 ESAL): thin surfacing "
                "(surface dressing or 20 mm premix carpet), NOT structural BC/DBM. "
                f"Provide ≥ {MIN_BASE_THICKNESS_MM:.0f} mm granular base."
            )
        else:
            advisory.append(
                "Below 100,000 ESAL: a gravel/granular surface is acceptable; "
                "bituminous surfacing is optional (rainfall/subgrade dependent)."
            )
        advisory.append(
            f"SP:72 thicknesses are multiples of {SP72_THICKNESS_INCREMENT_MM:.0f}/100 mm."
        )
    else:
        advisory.append(
            f"Design traffic ~{msa:.2f} MSA exceeds 2 MSA; IRC:SP:72 does not apply — "
            f"use the standard IRC:37 mechanistic design."
        )

    return SP72Classification(
        is_low_volume=low,
        esal=esal,
        msa=msa,
        traffic_category=cat,
        surfacing_hint=hint,
        subgrade_class=s_label,
        subgrade_class_name=s_name,
        blacktop_required=blacktop,
        min_base_thickness_mm=MIN_BASE_THICKNESS_MM,
        thickness_increment_mm=SP72_THICKNESS_INCREMENT_MM,
        advisory=advisory,
    )
