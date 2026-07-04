"""
Module C: Extended Material Library
=====================================
India-market materials extending the base MATERIAL_DB.
Includes commercial materials like PMB-40, CRMB-55, Geogrids,
specialized CTB variants, and recycled material blends.
"""

from typing import Optional
from mep_opt.solver.materials import MATERIAL_DB, MaterialProperty
from mep_opt.solver.irc37 import BitumenGrade
from mep_opt.cost import DEFAULT_MATERIAL_RATES, MaterialRate


# Extended materials not in the base DB
ADVANCED_MATERIALS: dict[str, dict] = {
    # Modified binders: IRC:37-2018 Table 9.2 has a SINGLE row for "BC with
    # Modified Bitumen (IRC:SP:53)" that covers PMB, CRMB and NRMB
    # collectively — 5700/3800/2400/1600/1300 MPa at 20/25/30/35/40 °C.
    # (Earlier entries carried vendor-style values ~2x the IRC row at 35 °C
    # while citing IRC — corrected in the July-2026 audit.)
    "PMB40": {
        "name": "Polymer Modified Bitumen (PMB-40)",
        "category": "bituminous",
        "E_default": 1600.0,      # IRC:37-2018 Table 9.2 modified row @ 35 °C
        "nu": 0.35,
        "density": 2400.0,
        "cost_multiplier": 1.25,
        "cost_per_cum": 15625,    # 12500 * 1.25
        "co2_per_cum": 210.0,
        "description": "Modified binder for heavy traffic corridors. Modulus per IRC:37-2018 Table 9.2 'BC with Modified Bitumen (IRC:SP:53)' row.",
        "temperature_table": {20: 5700, 25: 3800, 30: 2400, 35: 1600, 40: 1300},
    },
    "CRMB55": {
        "name": "Crumb Rubber Modified Bitumen (CRMB-55)",
        "category": "bituminous",
        "E_default": 1600.0,      # IRC:37-2018 Table 9.2 modified row @ 35 °C
        "nu": 0.35,
        "density": 2380.0,
        "cost_multiplier": 1.15,
        "cost_per_cum": 14375,    # 12500 * 1.15
        "co2_per_cum": 155.0,
        "description": "Recycled rubber-modified binder. Modulus per IRC:37-2018 Table 9.2 'BC with Modified Bitumen (IRC:SP:53)' row.",
        "temperature_table": {20: 5700, 25: 3800, 30: 2400, 35: 1600, 40: 1300},
    },
    "GEO_GSB": {
        "name": "Geogrid-Reinforced GSB",
        "category": "granular",
        "E_default": 350.0,
        "nu": 0.30,
        "density": 2050.0,
        "cost_multiplier": 1.40,
        "cost_per_cum": 2520,     # 1800 * 1.40
        "co2_per_cum": 45.0,
        "description": "GSB with biaxial geogrid interlock (indicative, non-IRC value — for IRC-consistent design use the geogrid MIF option on a plain granular layer instead).",
    },
    "CTB5": {
        "name": "Cement Treated Base (5% cement)",
        "category": "cement_treated",
        "E_default": 5000.0,      # IRC:37-2018 §8.4 design modulus for CTB
        "nu": 0.25,
        "density": 2200.0,
        "cost_multiplier": 1.10,
        "cost_per_cum": 3850,     # 3500 * 1.10
        "co2_per_cum": 140.0,
        "description": "Standard CTB with 5% OPC content. 5000 MPa is the IRC:37-2018 design modulus for cement-treated bases.",
    },
    "CTB3": {
        "name": "Cement Treated Base (3% cement)",
        "category": "cement_treated",
        "E_default": 3000.0,
        "nu": 0.25,
        "density": 2150.0,
        "cost_multiplier": 1.00,
        "cost_per_cum": 3500,
        "co2_per_cum": 100.0,
        "description": "Lean CTB for moderate traffic (indicative modulus, non-IRC value — IRC:37-2018 tabulates 5000 MPa for CTB).",
    },
    "RAP40": {
        "name": "RAP 40% Blend",
        "category": "recycled",
        "E_default": 1000.0,
        "nu": 0.35,
        "density": 2250.0,
        "cost_multiplier": 0.70,
        "cost_per_cum": 7560,     # 10800 * 0.70
        "co2_per_cum": 95.0,
        "description": "40% reclaimed asphalt pavement blend (indicative modulus, non-IRC value — verify with project mix testing).",
    },
    "FBS": {
        "name": "Foam Bitumen Stabilized Base",
        "category": "stabilized",
        "E_default": 800.0,
        "nu": 0.35,
        "density": 2100.0,
        "cost_multiplier": 0.85,
        "cost_per_cum": 4250,
        "co2_per_cum": 75.0,
        "description": "Cold-recycled base using foamed bitumen (indicative modulus in the 600-800 MPa range IRC:37-2018 cites for bitumen-stabilised RAP bases).",
    },
}


def get_full_library() -> list[dict]:
    """
    Return the complete material library: base MATERIAL_DB + advanced materials.
    Each entry is a flat dict suitable for JSON serialization.
    """
    library = []

    # Base materials from MATERIAL_DB
    for code, mat in sorted(MATERIAL_DB.items()):
        rate = DEFAULT_MATERIAL_RATES.get(code)
        entry = {
            "code": code,
            "name": mat.name,
            "category": mat.category,
            "E_default": mat.default_modulus,
            "nu": mat.poisson,
            "density": mat.density,
            "cost_multiplier": 1.0,
            "cost_per_cum": rate.cost_per_cum if rate else 0,
            "co2_per_cum": rate.co2_per_cum if rate else 0,
            "description": f"Standard {mat.name} per IRC:37-2018.",
            "source": "base",
        }
        library.append(entry)

    # Advanced materials
    for code, data in sorted(ADVANCED_MATERIALS.items()):
        entry = {
            "code": code,
            "name": data["name"],
            "category": data["category"],
            "E_default": data["E_default"],
            "nu": data["nu"],
            "density": data["density"],
            "cost_multiplier": data["cost_multiplier"],
            "cost_per_cum": data["cost_per_cum"],
            "co2_per_cum": data["co2_per_cum"],
            "description": data["description"],
            "source": "advanced",
        }
        if "temperature_table" in data:
            entry["temperature_table"] = data["temperature_table"]
        library.append(entry)

    return library


def get_material_by_code(code: str) -> Optional[dict]:
    """Look up a single material by code from the combined library."""
    code_upper = code.upper().strip()

    # Check base DB
    if code_upper in MATERIAL_DB:
        mat = MATERIAL_DB[code_upper]
        rate = DEFAULT_MATERIAL_RATES.get(code_upper)
        return {
            "code": code_upper,
            "name": mat.name,
            "category": mat.category,
            "E_default": mat.default_modulus,
            "nu": mat.poisson,
            "density": mat.density,
            "cost_multiplier": 1.0,
            "cost_per_cum": rate.cost_per_cum if rate else 0,
            "co2_per_cum": rate.co2_per_cum if rate else 0,
            "description": f"Standard {mat.name} per IRC:37-2018.",
            "source": "base",
        }

    # Check advanced DB
    if code_upper in ADVANCED_MATERIALS:
        data = ADVANCED_MATERIALS[code_upper]
        entry = {
            "code": code_upper,
            "name": data["name"],
            "category": data["category"],
            "E_default": data["E_default"],
            "nu": data["nu"],
            "density": data["density"],
            "cost_multiplier": data["cost_multiplier"],
            "cost_per_cum": data["cost_per_cum"],
            "co2_per_cum": data["co2_per_cum"],
            "description": data["description"],
            "source": "advanced",
        }
        if "temperature_table" in data:
            entry["temperature_table"] = data["temperature_table"]
        return entry

    return None
