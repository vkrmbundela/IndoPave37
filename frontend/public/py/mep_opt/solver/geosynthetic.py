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

Source:
  Saride, S., Baadiga, R., Balunaini, U., Madhira, R.M. (2021).
  "Modulus Improvement Factor-based Design Coefficients for Geogrid and
  Geocell-reinforced Bases." J. Transp. Eng. Part B: Pavements.
  (Table: MIF of geogrid-reinforced bases.)
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


def list_geogrid_types() -> List[Dict[str, str]]:
    """Return geogrid options (including a 'none' sentinel) for UI menus."""
    out = [{"id": NONE_OPTION, "name": "None (unreinforced)",
            "description": "No geosynthetic reinforcement."}]
    for gid, meta in GEOGRID_TYPES.items():
        out.append({"id": gid, "name": meta["name"], "description": meta["description"]})
    return out


def get_mif(subgrade_modulus: float, geogrid_type: Optional[str]) -> float:
    """
    Modulus Improvement Factor for a geogrid-reinforced granular base.

    Args:
        subgrade_modulus: subgrade resilient modulus Mrs (MPa).
        geogrid_type: one of MIF_TABLE keys ("PP30", "PET30", "PET60"),
                      or None/"none" for no reinforcement.

    Returns:
        MIF (>= 1.0). Returns 1.0 (no uplift) for None/"none"/unknown type.

    Interpolation:
        Linear between the tabulated Mrs points for the chosen geogrid;
        clamped flat below the smallest and above the largest tabulated Mrs.
    """
    if not geogrid_type or geogrid_type == NONE_OPTION:
        return 1.0

    table = MIF_TABLE.get(geogrid_type)
    if not table:
        return 1.0

    points = sorted(table.items())  # [(Mrs, MIF), ...] ascending Mrs
    mrs = float(subgrade_modulus)

    # Clamp outside the tabulated range — extrapolating MIF is not supported
    # by the source data, so hold the nearest measured value.
    if mrs <= points[0][0]:
        return points[0][1]
    if mrs >= points[-1][0]:
        return points[-1][1]

    # Linear interpolation between the bracketing Mrs points.
    for (m0, v0), (m1, v1) in zip(points, points[1:]):
        if m0 <= mrs <= m1:
            frac = (mrs - m0) / (m1 - m0)
            return v0 + frac * (v1 - v0)

    return points[-1][1]  # unreachable, defensive
