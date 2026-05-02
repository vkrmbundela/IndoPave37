"""
Centralized Material Property Database for IRC:37 Pavement Design
=================================================================
Provides material properties (modulus, Poisson's ratio, density, etc.)
for all standard pavement layer types used in Indian highway design.
"""

from dataclasses import dataclass
from typing import Optional
from enum import Enum

from .irc37 import BitumenGrade, get_bituminous_modulus


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MaterialProperty:
    """Properties for a single pavement material type."""
    name: str
    category: str              # "bituminous", "granular", "cement_treated"
    default_modulus: float     # MPa (at reference temperature for bituminous)
    poisson: float             # Poisson's ratio
    density: float             # kg/m3
    bitumen_grade: Optional[BitumenGrade] = None  # only for bituminous


# ---------------------------------------------------------------------------
# Material Database  (IRC:37-2018, Table 9.1 & standard practice)
# ---------------------------------------------------------------------------
# Default moduli for bituminous materials are at VG30 @ 35 deg C unless noted.

MATERIAL_DB: dict[str, MaterialProperty] = {
    # --- Bituminous layers ---
    "BC": MaterialProperty(
        name="Bituminous Concrete (BC)",
        category="bituminous",
        default_modulus=1250.0,   # VG30 @ 35 C
        poisson=0.35,
        density=2400.0,
        bitumen_grade=BitumenGrade.VG30,
    ),
    "DBM": MaterialProperty(
        name="Dense Bituminous Macadam (DBM)",
        category="bituminous",
        default_modulus=1250.0,
        poisson=0.35,
        density=2350.0,
        bitumen_grade=BitumenGrade.VG30,
    ),
    "SMA": MaterialProperty(
        name="Stone Matrix Asphalt (SMA)",
        category="bituminous",
        default_modulus=2000.0,   # PMB-40 @ 35 C
        poisson=0.35,
        density=2450.0,
        bitumen_grade=BitumenGrade.PMB,
    ),
    "SDBC": MaterialProperty(
        name="Semi-Dense Bituminous Concrete (SDBC)",
        category="bituminous",
        default_modulus=1250.0,
        poisson=0.35,
        density=2350.0,
        bitumen_grade=BitumenGrade.VG30,
    ),
    "BM": MaterialProperty(
        name="Bituminous Macadam (BM)",
        category="bituminous",
        default_modulus=1250.0,
        poisson=0.35,
        density=2300.0,
        bitumen_grade=BitumenGrade.VG30,
    ),

    # --- Granular layers ---
    "WMM": MaterialProperty(
        name="Wet Mix Macadam (WMM)",
        category="granular",
        default_modulus=300.0,    # typical, depends on support
        poisson=0.35,
        density=2200.0,
    ),
    "WBM": MaterialProperty(
        name="Water Bound Macadam (WBM)",
        category="granular",
        default_modulus=250.0,
        poisson=0.35,
        density=2100.0,
    ),
    "GSB": MaterialProperty(
        name="Granular Sub-Base (GSB)",
        category="granular",
        default_modulus=200.0,
        poisson=0.35,
        density=2000.0,
    ),

    # --- Cement-treated layers ---
    "CTB": MaterialProperty(
        name="Cement Treated Base (CTB)",
        category="cement_treated",
        default_modulus=5000.0,
        poisson=0.25,
        density=2200.0,
    ),

    # --- Recycled / RAP ---
    "RAP": MaterialProperty(
        name="Reclaimed Asphalt Pavement (RAP)",
        category="bituminous",
        default_modulus=800.0,    # conservative, depends on RAP %
        poisson=0.35,
        density=2250.0,
        bitumen_grade=BitumenGrade.VG30,
    ),
}


# ---------------------------------------------------------------------------
# Lookup Helpers
# ---------------------------------------------------------------------------

def get_material(type_code: str) -> MaterialProperty:
    """
    Look up a material by its type code (e.g. "BC", "DBM", "WMM").

    Args:
        type_code: Material type code (case-insensitive).

    Returns:
        MaterialProperty for the requested material.

    Raises:
        KeyError: If the type code is not found.
    """
    key = type_code.upper().strip()
    if key not in MATERIAL_DB:
        available = ", ".join(sorted(MATERIAL_DB.keys()))
        raise KeyError(
            f"Unknown material type '{type_code}'. "
            f"Available: {available}"
        )
    return MATERIAL_DB[key]


def get_modulus(type_code: str,
                grade: Optional[BitumenGrade] = None,
                temperature: float = 35.0) -> float:
    """
    Get elastic modulus for a material, with temperature interpolation
    for bituminous types.

    Args:
        type_code: Material type code (e.g. "BC", "WMM").
        grade: Override bitumen grade (uses material default if None).
        temperature: Pavement temperature in deg C (only for bituminous).

    Returns:
        Elastic modulus in MPa.
    """
    mat = get_material(type_code)

    if mat.category == "bituminous":
        effective_grade = grade if grade is not None else mat.bitumen_grade
        if effective_grade is not None:
            return get_bituminous_modulus(effective_grade, temperature)

    # Granular / cement-treated / default
    return mat.default_modulus


def get_poisson(type_code: str) -> float:
    """Get Poisson's ratio for a material type."""
    return get_material(type_code).poisson


def get_density(type_code: str) -> float:
    """Get density (kg/m3) for a material type."""
    return get_material(type_code).density


def list_materials() -> list[str]:
    """Return sorted list of available material type codes."""
    return sorted(MATERIAL_DB.keys())
