"""
IRC 37:2018 — Design Criteria Module
=====================================
Implements the fatigue cracking and rutting criteria, modulus calculations,
traffic computation, and CDF check per IRC 37:2018.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union
from enum import Enum

logger = logging.getLogger(__name__)


class ReliabilityLevel(Enum):
    """
    Design reliability level.

    IRC 37:2018 only specifies two levels:
      - R80: 80% reliability (low-volume traffic, < 30 MSA)
      - R90: 90% reliability (high-volume traffic, ≥ 30 MSA)

    R95/R98/R99 are NOT defined in IRC 37:2018. They are retained here for
    legacy callers but the calculation falls back to R90 with a warning,
    since fabricating shift factors would produce non-compliant results.
    """
    R80 = 80   # IRC 37:2018 — low-volume traffic
    R90 = 90   # IRC 37:2018 — high-volume traffic
    R95 = 95   # NON-STANDARD — falls back to R90
    R98 = 98   # NON-STANDARD — falls back to R90
    R99 = 99   # NON-STANDARD — falls back to R90


def _resolve_irc_reliability(reliability: "ReliabilityLevel") -> "ReliabilityLevel":
    """Map non-IRC reliability levels to R90 (the strictest IRC-compliant level)."""
    if reliability in (ReliabilityLevel.R80, ReliabilityLevel.R90):
        return reliability
    logger.warning(
        "Reliability %s is not defined in IRC 37:2018; falling back to R90 "
        "(the strictest IRC-compliant level). Use R80 or R90 for compliant designs.",
        getattr(reliability, "name", reliability),
    )
    return ReliabilityLevel.R90


class BitumenGrade(Enum):
    """
    Bitumen grade options.

    The three "VG*" grades are unmodified bitumens covered by the
    BC/DBM modulus row of IRC 37:2018 Table 9.2.

    CRMB / PMB / NRMB are *modified* binders covered collectively by the
    "BC with Modified Bitumen (IRC:SP:53)" row of Table 9.2. IRC 37 page 40
    explicitly states "modified binders are not recommended for the DBM
    layers due to the concern about the recyclability" — the optimizer
    rejects DBM + modified-binder combinations on this basis.
    """
    VG10 = "VG10"
    VG30 = "VG30"
    VG40 = "VG40"
    CRMB = "CRMB-55"
    PMB = "PMB-40"
    NRMB = "NRMB-70"   # Natural Rubber Modified Bitumen — same modulus row as PMB/CRMB

# Modified-binder grades that share the same Table 9.2 row.
MODIFIED_BITUMEN_GRADES = frozenset({BitumenGrade.CRMB, BitumenGrade.PMB, BitumenGrade.NRMB})


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

        Per IRC 37:2018 Eqs. 6.1 and 6.2:
        - MR = 10 × CBR             for CBR ≤ 5%
        - MR = 17.6 × CBR^0.64      for CBR > 5%

        Per IRC 37:2018 Annex-II worked example (page 78):
        "the effective modulus value will be limited to 100 MPa for design
        purpose." The cap corresponds to a design CBR of about 15.8%.
        """
        if self.cbr <= 5.0:
            mr = 10.0 * self.cbr
        else:
            mr = 17.6 * (self.cbr ** 0.64)
        # IRC 37:2018 design ceiling
        return min(mr, 100.0)


@dataclass
class GranularLayerInput:
    """Granular sub-base / base layer."""
    thickness: float          # mm
    material_type: str = "WMM"  # WMM, WBM, etc.

    def modulus(self, support_modulus: float) -> float:
        MR_gran = 0.2 * (self.thickness ** 0.45) * support_modulus
        return min(MR_gran, 3.0 * support_modulus)


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
# IRC 37:2018 — Bituminous Modulus Lookup Table (Table 9.2, page 30)
# ===========================================================================
# Indicative resilient modulus (MPa) of bituminous mixes (BC/DBM) versus the
# average annual pavement temperature. These are the *2018* values; earlier
# pre-2018 tables ran 25-30% lower for VG30 and ~30% lower for VG40, which
# the optimizer used previously and which produced systematically over-thick
# Economy designs. Modified-binder rows (BC + IRC:SP:53) were also wrong in
# the old table. Now matches IRC 37:2018 page 40.
#
# Format: {grade: {temp_C: modulus_MPa}}
BITUMINOUS_MODULUS_TABLE = {
    # Plain VG (IRC 37:2018 Table 9.2 row 1–3)
    BitumenGrade.VG10: {20: 2300, 25: 2000, 30: 1450, 35: 1000, 40: 800},
    BitumenGrade.VG30: {20: 3500, 25: 3000, 30: 2500, 35: 2000, 40: 1250},
    BitumenGrade.VG40: {20: 6000, 25: 5000, 30: 4000, 35: 3000, 40: 2000},
    # Modified binders — Table 9.2 row "BC with Modified Bitumen (IRC:SP:53)".
    # Per IRC:SP:53 the row applies collectively to PMB, CRMB and NRMB.
    BitumenGrade.CRMB: {20: 5700, 25: 3800, 30: 2400, 35: 1600, 40: 1300},
    BitumenGrade.PMB:  {20: 5700, 25: 3800, 30: 2400, 35: 1600, 40: 1300},
    BitumenGrade.NRMB: {20: 5700, 25: 3800, 30: 2400, 35: 1600, 40: 1300},
}

# IRC 37:2018 Table 9.2 — BM (Bituminous Macadam) is given as a single
# value at 35°C only, NOT as a temperature curve. The optimizer uses these
# fixed values regardless of the input temperature; that's how IRC 37
# specifies it and treating BM with the BC/DBM curve over-stiffens it
# by ~3× (its mix grade has lower binder content and coarser aggregates).
BM_MODULUS_AT_35C: Dict["BitumenGrade", float] = {
    BitumenGrade.VG10: 500.0,
    BitumenGrade.VG30: 700.0,
}


def get_bm_modulus(grade: "BitumenGrade" = BitumenGrade.VG30,
                   temperature: float = 35.0) -> float:
    """
    Resilient modulus for Bituminous Macadam (BM) per IRC 37:2018 Table 9.2.

    BM only has fixed values at 35°C in the table (500 MPa for VG10,
    700 MPa for VG30). Modified binders are not specified for BM. We
    use the fixed value regardless of `temperature` — this matches IRC's
    deliberate choice to specify BM independently of the BC/DBM curve.
    """
    return BM_MODULUS_AT_35C.get(grade, 700.0)


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
    # The IRC equation divides by mix_modulus; a zero or negative value
    # would produce a meaningless result (or a ZeroDivisionError on the
    # power calculation). Reject early.
    if mix_modulus is None or mix_modulus <= 0:
        raise ValueError(
            f"mix_modulus must be > 0 MPa (got {mix_modulus!r})"
        )

    # Volume correction factor C = 10^M, where M = 4.84·(Vb/(Vb+Va) − 0.69).
    # Guard the (Vb + Va) denominator: if both volumes are zero (or
    # negative — physically meaningless inputs) the formula collapses.
    Vb = bitumen_volume
    Va = air_voids
    vol_total = Vb + Va
    if vol_total <= 0:
        raise ValueError(
            f"bitumen_volume + air_voids must be > 0% "
            f"(got Vb={Vb}, Va={Va})"
        )
    M = 4.84 * (Vb / vol_total - 0.69)
    C = 10.0 ** M

    # IRC 37:2018 page 16, Equations for bottom-up cracking:
    #   Nf = 1.6064 · C · 10⁻⁴ · (1/εt)^3.89 · (1/MR)^0.854   (80% reliability)
    #   Nf = 0.5161 · C · 10⁻⁴ · (1/εt)^3.89 · (1/MR)^0.854   (90% reliability)
    # The R90 coefficient is intentionally smaller — higher reliability ⇒
    # fewer allowable cycles ⇒ more conservative design. Earlier code used
    # 0.5161e-4 as the R80 base and applied a 0.5 shift for R90, which
    # produced an R80 result roughly 3× too conservative and an R90 result
    # roughly 2× too conservative. This is the inversion fix.
    FATIGUE_COEFFICIENT = {
        ReliabilityLevel.R80: 1.6064e-4,
        ReliabilityLevel.R90: 0.5161e-4,
    }
    coeff = FATIGUE_COEFFICIENT[_resolve_irc_reliability(reliability)]
    Nf = coeff * C * (1.0 / abs(eps_t)) ** 3.89 * (1.0 / mix_modulus) ** 0.854

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

    # IRC 37:2018 Table 12.4 — only R80 and R90 are defined.
    # NR = coeff × (1/εv)^4.5337
    RUTTING_COEFF = {
        ReliabilityLevel.R80: 4.1656e-8,
        ReliabilityLevel.R90: 1.41e-8,
    }
    coeff = RUTTING_COEFF[_resolve_irc_reliability(reliability)]
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
    # MOR is the denominator in the stress-ratio calculation; a zero
    # or negative value is not physically meaningful and would crash
    # the divide. Surface a clear error so the caller can fix the input.
    if modulus_of_rupture is None or modulus_of_rupture <= 0:
        raise ValueError(
            f"modulus_of_rupture must be > 0 MPa (got {modulus_of_rupture!r})"
        )

    sr = abs(sigma_t) / modulus_of_rupture
    # Apply the IRC stress-ratio relation continuously for all finite SR.
    # Only the zero-stress limit is treated as unbounded life.
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
                      granular_layers: List[Union[dict, GranularLayerInput]],
                      bituminous_layers: List[BituminousLayerInput],
                      layer_props: dict = None
                      ) -> List[dict]:
    """
    Build the complete layer stack for Burmister analysis.
    Returns list of {modulus, poisson, thickness} dicts (top to bottom).

    Per IRC 37:2018 §7.2.3 (page 33):
      - When the only granular layers in the stack are *unbound* (e.g. WMM
        + GSB only, no cement-treated layer between them), the granular
        base and granular sub-base must be analysed as a SINGLE composite
        layer of total thickness ``h_total``. Modulus is then computed
        once via Eq. 7.1 with the subgrade as the support.
      - When a cement-treated/bitumen-treated base sits over the granular
        sub-base, each layer is analysed separately bottom-up.

    The previous implementation treated every granular layer separately
    in all cases, which produced a different effective stiffness than
    IRC mandates for the common WMM+GSB (no CTB) stack-up.
    """
    if layer_props is None:
        layer_props = {}

    stack = []

    # Subgrade modulus can be overridden by user
    sub_custom = layer_props.get('Subgrade', {})
    support_modulus = sub_custom.get('E', subgrade.modulus)
    sub_nu = sub_custom.get('nu', 0.40)

    def _gran_get(gran: Union[dict, GranularLayerInput], key: str, default: Any = None) -> Any:
        if isinstance(gran, dict):
            return gran.get(key, default)
        return getattr(gran, key, default)

    # IRC 37 distinguishes "all-unbound" vs "treated-base-over-GSB" — the
    # collapse rule only applies when *every* granular entry is an unbound
    # type (WMM/WBM/GSB). CTB/CTSB or any other bound material breaks the
    # collapse and forces per-layer analysis.
    UNBOUND_GRANULAR = {"WMM", "WBM", "GSB"}

    def _is_unbound(gran) -> bool:
        l_type = _gran_get(gran, 'layer_type') or _gran_get(gran, 'material_type') or ''
        return str(l_type).upper() in UNBOUND_GRANULAR

    all_granular_unbound = bool(granular_layers) and all(_is_unbound(g) for g in granular_layers)
    # Custom-E overrides on any granular entry should be respected even in
    # the collapse case — if the user explicitly assigned moduli, we cannot
    # quietly replace them.
    any_user_E = any(
        (_gran_get(g, 'E') is not None) or
        ((layer_props.get(_gran_get(g, 'layer_type') or _gran_get(g, 'material_type') or '', {}) or {}).get('E') is not None)
        for g in granular_layers
    )

    def _geogrid_of(gran) -> Optional[str]:
        """Geogrid type on a granular entry (granular-level or layer_props), else None."""
        g = _gran_get(gran, 'geogrid')
        if g is None:
            l_type = _gran_get(gran, 'layer_type') or _gran_get(gran, 'material_type') or ''
            g = (layer_props.get(l_type, {}) or {}).get('geogrid')
        if g in (None, "", "none"):
            return None
        return g

    # A geogrid-reinforced layer must stay distinct so its uplifted modulus is
    # traceable — it breaks the IRC §7.2.3 composite collapse, like a user-E.
    any_geogrid = any(_geogrid_of(g) is not None for g in granular_layers)

    gran_moduli = []
    gran_nu_values = []
    gran_thicknesses = []

    if all_granular_unbound and not any_user_E and not any_geogrid and len(granular_layers) > 1:
        # IRC 37:2018 §7.2.3 page 33 — collapse to a single composite layer
        # for the IIT Pave call. We still report each layer's geometry for
        # the cost report, but the IIT Pave stack receives one combined row.
        h_total = sum(float(_gran_get(g, 'thickness') or 0.0) for g in granular_layers)
        if h_total <= 0:
            raise ValueError("Composite granular layer must have positive total thickness")
        composite_mod = 0.2 * (h_total ** 0.45) * support_modulus
        # IRC 37:2018 §7.4.2 page 35 — cap modulus ratio at 3.0
        composite_mod = min(composite_mod, 3.0 * support_modulus)
        gran_moduli.append(composite_mod)
        gran_nu_values.append(0.35)
        gran_thicknesses.append(h_total)
    else:
        # Treated/mixed stack-ups: per-layer bottom-up analysis (unchanged)
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
                # Fallback to empirical (per-layer formula)
                mod = 0.2 * (h ** 0.45) * current_support
                # IRC 37:2018 §7.4.2 page 35 — cap modulus ratio at 3.0
                mod = min(mod, 3.0 * current_support)

            # Geosynthetic reinforcement: uplift the (unreinforced) modulus by
            # the MIF, keyed on the SUBGRADE modulus Mrs — not the immediate
            # support. Mr_reinforced = MIF × Mr_unreinforced (Saride 2021).
            geogrid = _geogrid_of(gran)
            if geogrid is not None:
                from mep_opt.solver.geosynthetic import get_mif
                mod = mod * get_mif(support_modulus, geogrid)

            gran_moduli.insert(0, mod)
            gran_nu_values.insert(0, custom_nu if custom_nu is not None else 0.35)
            gran_thicknesses.insert(0, h)
            current_support = mod

    # Build stack: bituminous (top) → granular → subgrade (bottom).
    # Note: gran_* lists have one entry per row that should appear in the
    # IIT Pave stack — that's len(granular_layers) for the per-layer
    # branch, but exactly 1 for the IRC §7.2.3 composite-collapse branch.
    for bl in bituminous_layers:
        stack.append({
            "modulus": bl.modulus,
            "poisson": bl.poisson,
            "thickness": bl.thickness,
        })

    for i in range(len(gran_moduli)):
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
