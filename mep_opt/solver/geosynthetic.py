"""
Geosynthetic Reinforcement — Modulus Improvement Factor (MIF)
============================================================
Implements the MIF design approach for geogrid-reinforced granular bases,
the mechanistic-compatible counterpart to the IRC:SP:59 layer-coefficient-
ratio (LCR) method.

A geogrid placed in/under a granular base raises its effective resilient
modulus by a factor MIF that depends on:
  - the subgrade resilient modulus Mrs (weaker subgrade → larger benefit), and
  - the geogrid type/stiffness.

The reinforced base modulus is:
    Mr_reinforced = MIF × Mr_unreinforced

Because our solver is mechanistic (IRC:37 Burmister), the modulus uplift
flows straight through: lower strains for the same thickness → the optimizer
can trim the granular layer while staying IRC:37-adequate.

Sources:
  Saride, S., Baadiga, R., Balunaini, U., Madhira, R.M. (2022).
  "Modulus Improvement Factor-Based Design Coefficients for Geogrid- and
  Geocell-Reinforced Bases." J. Transp. Eng. Part B: Pavements 148(3).
  (Large-scale model tests; MIF of geogrid-reinforced bases 1.5-3.5.)
  IRC:SP:59-2019 §3.1.3: "The indicative range of MIF values for geogrid to be
  used in the design shall be 1.2 to 2" and "Only third party validated MIF
  values must be used for the design."
  IRC:37-2018 §7.2.3 / §8.1: un-reinforced base and sub-base moduli are
  estimated separately (Eq. 7.1, the base resting on the EFFECTIVE modulus of
  the GSB + subgrade system) and then multiplied by the MIF.

Design rule implemented here (get_mif):
  * the research table (research_mif) is interpolated linearly in Mrs;
  * below the smallest tabulated Mrs the first value is held (MIF rises as
    the subgrade weakens, so holding it is conservative);
  * above the largest tabulated Mrs the last segment is extrapolated
    (MIF falls with stiffer subgrade; holding it flat over-states the
    benefit), never below 1.0;
  * the result is capped at the IRC:SP:59 design maximum of 2.0.
The research values above 2.0 (very weak subgrades) are therefore not used
for design; a project needs third-party-certified MIF to justify more.
"""

from typing import Dict, List, Optional


# MIF tabulated against subgrade resilient modulus Mrs (MPa) per geogrid type.
# Blanks in the source table are simply omitted; interpolation/clamping uses
# whatever Mrs points are available for the chosen geogrid.
MIF_TABLE: Dict[str, Dict[float, float]] = {
    "PP30":  {10.0: 3.13, 30.0: 1.88, 50.0: 1.60, 70.0: 1.50},
    "PET30": {10.0: 3.50, 30.0: 2.06, 50.0: 1.80},
    "PET60": {30.0: 2.25, 50.0: 2.00},
}

# Human-readable metadata for the UI / reports.
GEOGRID_TYPES: Dict[str, Dict[str, str]] = {
    "PP30":  {"name": "Polypropylene Geogrid (PP30)",
              "description": "Biaxial polypropylene geogrid, ~30 kN/m. Economical, moderate uplift."},
    "PET30": {"name": "Polyester Geogrid (PET30)",
              "description": "Polyester geogrid, ~30 kN/m. Higher stiffness than PP30."},
    "PET60": {"name": "Polyester Geogrid (PET60)",
              "description": "High-strength polyester geogrid, ~60 kN/m. Largest uplift."},
}

NONE_OPTION = "none"

# IRC:SP:59-2019 §3.1.3 — design range of MIF for geogrids is 1.2 to 2.0.
SP59_GEOGRID_MIF_MAX = 2.0


def list_geogrid_types() -> List[Dict[str, str]]:
    """Return geogrid options (including a 'none' sentinel) for UI menus."""
    out = [{"id": NONE_OPTION, "name": "None (unreinforced)",
            "description": "No geosynthetic reinforcement."}]
    for gid, meta in GEOGRID_TYPES.items():
        out.append({"id": gid, "name": meta["name"], "description": meta["description"]})
    return out


def research_mif(subgrade_modulus: float, geogrid_type: Optional[str]) -> float:
    """
    Raw MIF from the research table (no IRC:SP:59 cap): linear interpolation
    in Mrs, first value held below the table, last segment extrapolated above
    it (floored at 1.0). Returns 1.0 for None/"none"/unknown geogrid types.
    """
    if not geogrid_type or geogrid_type == NONE_OPTION:
        return 1.0

    table = MIF_TABLE.get(geogrid_type)
    if not table:
        return 1.0

    points = sorted(table.items())  # [(Mrs, MIF), ...] ascending Mrs
    mrs = float(subgrade_modulus)

    if mrs <= points[0][0]:
        return points[0][1]
    if mrs >= points[-1][0]:
        if len(points) < 2:
            return points[-1][1]
        (m0, v0), (m1, v1) = points[-2], points[-1]
        slope = (v1 - v0) / (m1 - m0)
        return max(1.0, v1 + slope * (mrs - m1))

    # Linear interpolation between the bracketing Mrs points.
    for (m0, v0), (m1, v1) in zip(points, points[1:]):
        if m0 <= mrs <= m1:
            frac = (mrs - m0) / (m1 - m0)
            return v0 + frac * (v1 - v0)

    return points[-1][1]  # unreachable, defensive


def get_mif(subgrade_modulus: float, geogrid_type: Optional[str]) -> float:
    """
    DESIGN Modulus Improvement Factor for a geogrid-reinforced granular layer:
    the research MIF capped at the IRC:SP:59-2019 §3.1.3 maximum of 2.0.

    Args:
        subgrade_modulus: subgrade resilient modulus Mrs (MPa).
        geogrid_type: one of MIF_TABLE keys ("PP30", "PET30", "PET60"),
                      or None/"none" for no reinforcement.

    Returns:
        MIF in [1.0, 2.0]. 1.0 (no uplift) for None/"none"/unknown type.
    """
    return min(SP59_GEOGRID_MIF_MAX, research_mif(subgrade_modulus, geogrid_type))
