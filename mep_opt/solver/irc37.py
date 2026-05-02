"""
IRC 37:2018 — Design Criteria Module
=====================================
Implements the fatigue cracking and rutting criteria, modulus calculations,
traffic computation, and CDF check per IRC 37:2018.
"""

import math
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple
from enum import Enum


class ReliabilityLevel(Enum):
    """Design reliability level per IRC 37:2018."""
    R80 = 80   # 80% reliability
    R90 = 90   # 90% reliability
    R95 = 95   # 95% reliability
    R98 = 98   # 98% reliability
    R99 = 99   # 99% reliability


class BitumenGrade(Enum):
    """Bitumen grade options."""
    VG10 = "VG10"
    VG30 = "VG30"
    VG40 = "VG40"
    CRMB = "CRMB-55"
    PMB = "PMB-40"


@dataclass
class TrafficInput:
    """Traffic characterization input."""
    initial_aadt: float        # Initial AADT
    commercial_vehicles_per_day: float  # CVpd in one direction
    traffic_growth_rate: float  # Annual growth rate (fraction, e.g., 0.05)
    design_life_years: int = 20
    lane_distribution_factor: float = 0.75  # fraction of traffic in design lane
    vehicle_damage_factor: float = 2.5      # VDF (standard axle load factor)

    def cumulative_msa(self) -> float:
        """
        Calculate cumulative traffic in million standard axles (MSA).

        N = 365 × A × D × F × [(1+r)^n - 1] / r

        Where:
        - A = CVpd (commercial vehicles per day)
        - D = lane distribution factor
        - F = vehicle damage factor
        - r = growth rate
        - n = design life
        """
        A = self.commercial_vehicles_per_day
        D = self.lane_distribution_factor
        F = self.vehicle_damage_factor
        r = self.traffic_growth_rate
        n = self.design_life_years

        if abs(r) < 1e-10:
            N = 365 * A * D * F * n
        else:
            N = 365 * A * D * F * ((1 + r)**n - 1) / r

        return N / 1e6  # Convert to MSA


@dataclass
class AxleLoadGroup:
    """Axle load category for load spectrum analysis (e.g. for CTB)."""
    axle_type: str              # "single", "tandem", "tridem"
    load_kn: float              # Axle load in kN
    expected_repetitions: float # n_i: Number of expected repetitions over design life



@dataclass
class SubgradeInput:
    """Subgrade characterization."""
    cbr: float  # CBR value (%)

    @property
    def modulus(self) -> float:
        """
        Effective resilient modulus of subgrade (MPa).

        Per IRC 37:2018:
        - MR = 10 × CBR  for CBR ≤ 5%
        - MR = 17.6 × CBR^0.64  for CBR > 5%
        """
        if self.cbr <= 5.0:
            return 10.0 * self.cbr
        else:
            return 17.6 * (self.cbr ** 0.64)


@dataclass
class GranularLayerInput:
    """Granular sub-base / base layer."""
    thickness: float          # mm
    material_type: str = "WMM"  # WMM, WBM, etc.

    def modulus(self, support_modulus: float) -> float:
        """
        Resilient modulus of granular layer (MPa).

        Per IRC 37:2018:
        MR_gran = 0.2 × h^0.45 × MR_support

        Where h = thickness in mm, MR_support = modulus of underlying layer.
        """
        return 0.2 * (self.thickness ** 0.45) * support_modulus


@dataclass
class BituminousLayerInput:
    """Bituminous layer specification."""
    mix_type: str            # e.g., "BC", "DBM", "SMA", "SDBC"
    thickness: float         # mm
    modulus: float           # Elastic modulus (MPa)
    poisson: float = 0.35   # Poisson's ratio
    bitumen_grade: BitumenGrade = BitumenGrade.VG30
    air_voids: float = 4.0  # Air voids (%)
    bitumen_volume: float = 11.5  # Effective bitumen volume (%)


# ===========================================================================
# IRC 37:2018 — Bituminous Modulus Lookup Table
# ===========================================================================
# Table 9.1: Indicative modulus values (MPa) vs temperature
# Format: {grade: {temp_C: modulus_MPa}}
BITUMINOUS_MODULUS_TABLE = {
    BitumenGrade.VG10: {20: 1700, 25: 1250, 30: 900, 35: 650, 40: 500},
    BitumenGrade.VG30: {20: 3000, 25: 2500, 30: 1700, 35: 1250, 40: 900},
    BitumenGrade.VG40: {20: 5000, 25: 3800, 30: 3000, 35: 2500, 40: 1700},
    BitumenGrade.CRMB: {20: 3500, 25: 3000, 30: 2500, 35: 2000, 40: 1500},
    BitumenGrade.PMB:  {20: 5700, 25: 4500, 30: 3800, 35: 3000, 40: 2500},
}


def get_bituminous_modulus(grade: BitumenGrade, temperature: float) -> float:
    """
    Interpolate bituminous modulus from IRC 37 table.

    Args:
        grade: Bitumen grade
        temperature: Pavement temperature (°C)

    Returns:
        Elastic modulus (MPa)
    """
    table = BITUMINOUS_MODULUS_TABLE.get(grade, BITUMINOUS_MODULUS_TABLE[BitumenGrade.VG30])
    temps = sorted(table.keys())
    vals = [table[t] for t in temps]

    if temperature <= temps[0]:
        return vals[0]
    if temperature >= temps[-1]:
        return vals[-1]

    # Linear interpolation
    for i in range(len(temps) - 1):
        if temps[i] <= temperature <= temps[i + 1]:
            frac = (temperature - temps[i]) / (temps[i + 1] - temps[i])
            return vals[i] + frac * (vals[i + 1] - vals[i])

    return vals[-1]


# ===========================================================================
# IRC 37:2018 — Performance Models (Fatigue + Rutting)
# ===========================================================================

def fatigue_life(eps_t: float, mix_modulus: float,
                 reliability: ReliabilityLevel = ReliabilityLevel.R80,
                 air_voids: float = 4.0,
                 bitumen_volume: float = 11.5) -> float:
    """
    Allowable fatigue repetitions per IRC 37:2018.

    Nf = 0.5161 × C × 10⁻⁴ × (1/εt)^3.89 × (1/MR)^0.854

    Where:
    - εt = horizontal tensile strain at bottom of bituminous layer (microstrain)
    - MR = resilient modulus of bituminous mix (MPa)
    - C = 10^M
    - M = 4.84 × (Vb/(Vb + Va) - 0.69)
    - Vb = effective bitumen volume %
    - Va = air voids %

    Args:
        eps_t: Horizontal tensile strain (absolute value, not microstrain)
        mix_modulus: Bituminous mix modulus (MPa)
        reliability: ReliabilityLevel
        air_voids: Air voids percentage
        bitumen_volume: Effective bitumen volume percentage

    Returns:
        Allowable fatigue repetitions Nf
    """
    if abs(eps_t) < 1e-15:
        return float('inf')

    # Volume correction factor
    Vb = bitumen_volume
    Va = air_voids
    M = 4.84 * (Vb / (Vb + Va) - 0.69)
    C = 10.0 ** M

    # Base equation (80% reliability)
    Nf = 0.5161 * C * 1e-4 * (1.0 / abs(eps_t)) ** 3.89 * (1.0 / mix_modulus) ** 0.854

    # Reliability shift factors per IRC 37:2018 Table 12.3
    # Higher reliability => fewer allowable repetitions (more conservative)
    FATIGUE_SHIFT = {
        ReliabilityLevel.R80: 1.0,
        ReliabilityLevel.R90: 0.5,
        ReliabilityLevel.R95: 0.25,
        ReliabilityLevel.R98: 0.125,
        ReliabilityLevel.R99: 0.0625,
    }
    Nf *= FATIGUE_SHIFT.get(reliability, 1.0)

    return Nf


def rutting_life(eps_v: float,
                 reliability: ReliabilityLevel = ReliabilityLevel.R80) -> float:
    """
    Allowable rutting repetitions per IRC 37:2018.

    80% reliability: NR = 4.1656 × 10⁻⁸ × (1/εv)^4.5337
    90% reliability: NR = 1.41   × 10⁻⁸ × (1/εv)^4.5337

    Args:
        eps_v: Vertical compressive strain on subgrade (absolute value)
        reliability: ReliabilityLevel

    Returns:
        Allowable rutting repetitions NR
    """
    if abs(eps_v) < 1e-15:
        return float('inf')

    # Rutting coefficients per IRC 37:2018 Table 12.4
    # NR = coeff × (1/εv)^4.5337
    RUTTING_COEFF = {
        ReliabilityLevel.R80: 4.1656e-8,
        ReliabilityLevel.R90: 1.41e-8,
        ReliabilityLevel.R95: 0.50e-8,
        ReliabilityLevel.R98: 0.20e-8,
        ReliabilityLevel.R99: 0.085e-8,
    }
    coeff = RUTTING_COEFF.get(reliability, 4.1656e-8)
    NR = coeff * (1.0 / abs(eps_v)) ** 4.5337

    return NR


def ctb_fatigue_life(sigma_t: float, modulus_of_rupture: float = 1.4) -> float:
    """
    Allowable fatigue repetitions for Cement Treated Base (CTB) per IRC 37.

    N = 10 ^ ((0.972 - SR) / 0.0825)
    Where SR (Stress Ratio) = sigma_t / modulus_of_rupture

    Args:
        sigma_t: Maximum tensile stress at bottom of CTB layer (MPa)
        modulus_of_rupture: Modulus of rupture of the CTB (MPa, default 1.4)

    Returns:
        Allowable repetitions N
    """
    if abs(sigma_t) < 1e-15:
        return float('inf')
        
    sr = abs(sigma_t) / modulus_of_rupture
    
    # If stress ratio is very low, it has infinite fatigue life per general models
    if sr < 0.45:
        return float('inf')
        
    n_allowable = 10.0 ** ((0.972 - sr) / 0.0825)
    return n_allowable


def check_ctb_adequacy(expected_spectrum: List[AxleLoadGroup], 
                       computed_stresses_mpa: List[float], 
                       modulus_of_rupture: float = 1.4) -> dict:
    """
    Check if a CTB layer is adequate using Cumulative Fatigue Damage (CFD)
    across an axle load spectrum.

    Args:
        expected_spectrum: List of AxleLoadGroup representing traffic
        computed_stresses_mpa: Matching list of tensile stresses (sigma_t) at CTB bottom
        modulus_of_rupture: Modulus of Rupture of CTB (MPa)

    Returns:
        Dictionary with CFD and adequacy flag.
    """
    if len(expected_spectrum) != len(computed_stresses_mpa):
        raise ValueError("Mismatch between spectrum length and computed stresses length")
        
    cdf_total = 0.0
    details = []
    
    for load_group, sigma_t in zip(expected_spectrum, computed_stresses_mpa):
        n_allowable = ctb_fatigue_life(sigma_t, modulus_of_rupture)
        n_applied = load_group.expected_repetitions
        
        damage = n_applied / n_allowable if n_allowable > 0 else float('inf')
        cdf_total += damage
        
        details.append({
            "load_kn": load_group.load_kn,
            "sigma_t": sigma_t,
            "sr": abs(sigma_t) / modulus_of_rupture,
            "n_allowable": n_allowable,
            "n_applied": n_applied,
            "damage": damage
        })
        
    return {
        "CDF_ctb": cdf_total,
        "ctb_adequate": cdf_total <= 1.0,
        "details": details
    }


def check_design_adequacy(eps_t: float, eps_v: float,
                          cumulative_msa: float,
                          mix_modulus: float,
                          reliability: ReliabilityLevel = ReliabilityLevel.R80,
                          air_voids: float = 4.0,
                          bitumen_volume: float = 11.5) -> dict:
    """
    Check if a pavement section is adequate per IRC 37:2018.

    Computes:
    - CDF_fatigue = N_applied / Nf
    - CDF_rutting = N_applied / NR
    - Adequate if both CDF ≤ 1.0

    Args:
        eps_t: Tensile strain at bottom of bituminous layer
        eps_v: Vertical strain on top of subgrade
        cumulative_msa: Design traffic in MSA
        mix_modulus: Bituminous mix modulus (MPa)

    Returns:
        Dictionary with Nf, NR, CDF values, and adequacy flag.
    """
    N_applied = cumulative_msa * 1e6  # Convert MSA to repetitions

    Nf = fatigue_life(eps_t, mix_modulus, reliability, air_voids, bitumen_volume)
    NR = rutting_life(eps_v, reliability)

    cdf_fatigue = N_applied / Nf if Nf > 0 else float('inf')
    cdf_rutting = N_applied / NR if NR > 0 else float('inf')

    return {
        "Nf": Nf,
        "NR": NR,
        "CDF_fatigue": cdf_fatigue,
        "CDF_rutting": cdf_rutting,
        "fatigue_adequate": cdf_fatigue <= 1.0,
        "rutting_adequate": cdf_rutting <= 1.0,
        "overall_adequate": cdf_fatigue <= 1.0 and cdf_rutting <= 1.0,
        "governing_mode": "fatigue" if cdf_fatigue > cdf_rutting else "rutting",
        "N_applied_msa": cumulative_msa,
        "eps_t": eps_t,
        "eps_v": eps_v,
    }


def build_layer_stack(subgrade: SubgradeInput,
                      granular_layers: List[dict | GranularLayerInput],
                      bituminous_layers: List[BituminousLayerInput],
                      layer_props: dict = None
                      ) -> List[dict]:
    """
    Build the complete layer stack for Burmister analysis.
    Returns list of {modulus, poisson, thickness} dicts (top to bottom).

    Bottom-up modulus computation:
    1. Subgrade modulus from CBR (unless overridden)
    2. Granular layers: User defined OR MR = f(thickness, support_modulus)
    3. Bituminous layers: given directly
    """
    if layer_props is None:
        layer_props = {}

    stack = []
    
    # Subgrade modulus can be overridden by user
    sub_custom = layer_props.get('Subgrade', {})
    support_modulus = sub_custom.get('E', subgrade.modulus)
    sub_nu = sub_custom.get('nu', 0.40)

    def _gran_get(gran: dict | GranularLayerInput, key: str, default: Any = None) -> Any:
        if isinstance(gran, dict):
            return gran.get(key, default)
        return getattr(gran, key, default)

    # Compute granular moduli bottom-up
    gran_moduli = []
    gran_nu_values = []
    gran_thicknesses = []
    current_support = support_modulus
    for gran in reversed(granular_layers):
        l_type = _gran_get(gran, 'layer_type') or _gran_get(gran, 'material_type') or 'Granular'
        h = _gran_get(gran, 'thickness')
        if h is None:
            raise ValueError("Each granular layer must define thickness")
        
        # Exact override if provided
        custom_E = _gran_get(gran, 'E')
        custom_nu = _gran_get(gran, 'nu')

        # Layer-level properties override defaults when granular entry omits them.
        layer_custom = layer_props.get(l_type, {}) if isinstance(layer_props, dict) else {}
        if custom_E is None:
            custom_E = layer_custom.get('E')
        if custom_nu is None:
            custom_nu = layer_custom.get('nu')

        if custom_E is not None:
            mod = custom_E
        else:
            # Fallback to empirical
            mod = 0.2 * (h ** 0.45) * current_support
        
        gran_moduli.insert(0, mod)
        gran_nu_values.insert(0, custom_nu if custom_nu is not None else 0.35)
        gran_thicknesses.insert(0, h)
        current_support = mod

    # Build stack: bituminous (top) → granular → subgrade (bottom)
    for bl in bituminous_layers:
        stack.append({
            "modulus": bl.modulus,
            "poisson": bl.poisson,
            "thickness": bl.thickness,
        })

    for i, _gran in enumerate(granular_layers):
        stack.append({
            "modulus": gran_moduli[i],
            "poisson": gran_nu_values[i],
            "thickness": gran_thicknesses[i],
        })

    # Subgrade (infinite)
    stack.append({
        "modulus": support_modulus,
        "poisson": sub_nu,
        "thickness": 0,  # infinite
    })

    return stack


# ===========================================================================
# Value Engineering — Structural Capacity Intercept
# ===========================================================================

def find_intercept_msa(
    eps_t: float,
    eps_v: float,
    mix_modulus: float,
    reliability: ReliabilityLevel = ReliabilityLevel.R80,
    air_voids: float = 4.0,
    bitumen_volume: float = 11.5,
) -> dict:
    """
    Find the MSA level where CDF reaches 1.0 — the structural capacity.

    Since CDF = N_applied / N_allowed, the intercept is simply
    min(Nf, NR) converted to MSA.

    Returns:
        Dictionary with intercept_msa, governing_mode, Nf_msa, NR_msa.
    """
    Nf = fatigue_life(eps_t, mix_modulus, reliability, air_voids, bitumen_volume)
    NR = rutting_life(eps_v, reliability)
    intercept_msa = min(Nf, NR) / 1e6
    governing = "fatigue" if Nf < NR else "rutting"
    return {
        "intercept_msa": intercept_msa,
        "governing_mode": governing,
        "Nf_msa": Nf / 1e6,
        "NR_msa": NR / 1e6,
    }
