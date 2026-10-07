"""
Regression tests for the October-2026 mathematics / IRC audit
============================================================
Every test pins a fix to an exact solution, an IRC:37-2018 Annex-II worked
example, or an explicit IRC clause:

  * Burmister solver near the surface (exact Boussinesq / converged layered
    reference) and the IRC Eq. 6.3 effective modulus (Annex-II II.1);
  * Annex-II II.2 (GSB construction strains), II.3 (entered with its SMA
    surface), II.4 (CTB stresses + cumulative damage), II.5 (RAP base);
  * reliability and the CTB RF factor by road category (§3.7, Eq. 3.5);
  * granular base over CTSB (§8.1 / Table 11.1), crack-relief only over a
    CTB, no CTB fatigue check for a CTSB;
  * RAP modelled as the 800 MPa base, unknown/misordered layers rejected;
  * IRC mandatory minimum thicknesses always enforced;
  * traffic growth to the opening year (Eq. 4.6);
  * corridor feasibility, interface bond, cache key, browser bridge.
"""

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest

from mep_opt.solver.burmister import analyze_pavement
from mep_opt.solver.irc37 import (
    AxleLoadGroup, ReliabilityLevel, SubgradeInput, TrafficInput,
    ctb_reliability_factor, effective_modulus, expand_axle_spectrum,
    required_reliability,
)
from mep_opt.optimizer.problem import OptimizationProblem
from mep_opt.optimizer.smart_search import SmartPavementSearch

DUAL = {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310}
T131 = dict(initial_aadt=0, commercial_vehicles_per_day=2500,
            traffic_growth_rate=0.06, design_life_years=20,
            lane_distribution_factor=0.75, vehicle_damage_factor=5.2)


def _boussinesq_axis(z, q, a, E, nu):
    R = math.sqrt(a * a + z * z)
    sz = -q * (1 - z ** 3 / R ** 3)
    sr = -q / 2 * ((1 + 2 * nu) - 2 * (1 + nu) * z / R + z ** 3 / R ** 3)
    w = (1 + nu) * q * a / E * (a / R + (1 - 2 * nu) / a * (R - z))
    return sz, sr, w


# --------------------------------------------------------------------------
# Solver: near-surface accuracy
# --------------------------------------------------------------------------

@pytest.mark.parametrize("z", [0.0, 1.0, 2.0, 5.0, 10.0, 20.0, 40.0, 79.0, 81.0])
def test_halfspace_matches_boussinesq_at_all_depths(z):
    """Previously sigma_z was +154% at z=0, +140% at 1 mm, +7% at 10 mm."""
    E, nu, P, q = 60.0, 0.35, 20000.0, 0.56
    a = math.sqrt(P / (math.pi * q))
    r = analyze_pavement([{"modulus": E, "poisson": nu, "thickness": 0}],
                         {"load": P, "pressure": q, "is_dual": False}, [{"z": z, "r": 0}])[0]
    sz, sr, w = _boussinesq_axis(z, q, a, E, nu)
    assert r["sigma_z"] == pytest.approx(sz, rel=1e-4, abs=1e-6)
    assert r["sigma_r"] == pytest.approx(sr, rel=1e-4, abs=1e-6)
    assert r["disp_z"] == pytest.approx(w, rel=1e-4)


def test_surface_outside_load_is_traction_free():
    r = analyze_pavement([{"modulus": 60, "poisson": 0.35, "thickness": 0}],
                         {"load": 20000, "pressure": 0.56, "is_dual": False},
                         [{"z": 0.0, "r": 155}])[0]
    assert abs(r["sigma_z"]) < 1e-9 and abs(r["tau_rz"]) < 1e-9


def test_thin_surfacing_matches_converged_reference():
    """
    25 mm surfacing: values of an independent high-precision propagator-matrix
    solver (mpmath, dense quadrature). The old fixed quadrature was ~0.8% off.
    """
    st = [{"modulus": 2000, "poisson": .35, "thickness": 25},
          {"modulus": 250, "poisson": .35, "thickness": 250},
          {"modulus": 120, "poisson": .35, "thickness": 200},
          {"modulus": 40, "poisson": .35, "thickness": 0}]
    r0, r1 = analyze_pavement(st, DUAL, [{"z": 24.9, "r": 0}, {"z": 24.9, "r": 155}])
    assert r0["eps_t"] == pytest.approx(1.1299e-4, rel=3e-3)
    assert r0["eps_r"] == pytest.approx(1.2102e-4, rel=3e-3)
    assert r0["eps_z"] == pytest.approx(-2.9703e-4, rel=3e-3)
    assert r1["eps_r"] == pytest.approx(-4.8727e-4, rel=3e-3)


def test_deep_points_unchanged_by_near_surface_treatment():
    """Design-depth results keep matching IRC Annex-II II.3 / the recorded run."""
    st = [{"modulus": 3000, "poisson": .35, "thickness": 190},
          {"modulus": 200, "poisson": .35, "thickness": 480},
          {"modulus": 62, "poisson": .35, "thickness": 0}]
    r = analyze_pavement(st, DUAL, [{"z": 189.9, "r": 155}, {"z": 670.1, "r": 155}])
    assert r[0]["eps_t"] == pytest.approx(145.79e-6, rel=1e-3)
    assert abs(r[1]["eps_z"]) == pytest.approx(244.54e-6, rel=1e-3)


def test_partial_bond_rejected_and_zero_thickness_layer_dropped():
    st = [{"modulus": 3000, "poisson": .35, "thickness": 190, "friction_factor": 0.5},
          {"modulus": 62, "poisson": .35, "thickness": 0}]
    with pytest.raises(ValueError, match="partial bond"):
        analyze_pavement(st, DUAL, [{"z": 100, "r": 0}])
    base = [{"modulus": 3000, "poisson": .35, "thickness": 190},
            {"modulus": 62, "poisson": .35, "thickness": 0}]
    with_zero = [base[0], {"modulus": 500, "poisson": .35, "thickness": 0.0}, base[1]]
    a = analyze_pavement(base, DUAL, [{"z": 190.1, "r": 0}])[0]
    b = analyze_pavement(with_zero, DUAL, [{"z": 190.1, "r": 0}])[0]
    assert a["eps_z"] == pytest.approx(b["eps_z"], rel=1e-9)


def test_solver_rejects_invalid_layers():
    with pytest.raises(ValueError):
        analyze_pavement([{"modulus": -1, "poisson": .35, "thickness": 0}], DUAL, [{"z": 1, "r": 0}])
    with pytest.raises(ValueError):
        analyze_pavement([{"modulus": 50, "poisson": .5, "thickness": 0}], DUAL, [{"z": 1, "r": 0}])


# --------------------------------------------------------------------------
# IRC Annex-II worked examples
# --------------------------------------------------------------------------

def test_annex_ii1_effective_modulus():
    """II.1: 500 mm @119.7 over 66.6 MPa -> delta 1.41 mm -> M_RS 105.10 MPa."""
    e = effective_modulus([{"modulus": 119.7, "poisson": .35, "thickness": 500},
                           {"modulus": 66.6, "poisson": .35, "thickness": 0}])
    assert e == pytest.approx(105.10, rel=5e-3)


@pytest.mark.parametrize("h, irc_strain", [(150, 4324e-6), (250, 2179e-6)])
def test_annex_ii2_gsb_construction_strain(h, irc_strain):
    E = 0.2 * h ** 0.45 * 50.0
    r = analyze_pavement([{"modulus": E, "poisson": .35, "thickness": h},
                          {"modulus": 50, "poisson": .35, "thickness": 0}],
                         DUAL, [{"z": h + 0.1, "r": 0}, {"z": h + 0.1, "r": 155}])
    assert max(abs(x["eps_z"]) for x in r) == pytest.approx(irc_strain, rel=0.01)


def test_annex_ii3_entered_with_its_sma_surface_is_adequate():
    """
    IRC II.3 specifies an SMA surface over DBM, analysed as ONE 3000 MPa
    bituminous layer (§5, §9.2). Previously the SMA got 1600 MPa and IRC's own
    design failed fatigue (CDF 1.096).
    """
    p = OptimizationProblem(
        traffic=TrafficInput(**T131), subgrade=SubgradeInput(7), road_category="nh",
        layer_types=["SMA", "DBM", "WMM", "GSB"],
        thickness_bounds={"SMA": (40, 40), "DBM": (150, 150), "WMM": (250, 250), "GSB": (230, 230)},
        layer_props={"DBM": {"E": 3000, "nu": .35}, "SMA": {"nu": .35}, "Subgrade": {"E": 62}},
    )
    s = SmartPavementSearch(p)
    out = s._evaluate([40, 150, 250, 230])
    assert [round(l["modulus"]) for l in out["layers"]][:2] == [3000, 3000]
    assert out["eps_t"] == pytest.approx(146e-6, rel=0.01)
    assert out["eps_v"] == pytest.approx(243e-6, rel=0.02)
    assert out["overall_adequate"] is True
    assert any("bottom mix" in w for w in s._build_warnings())


II4_SPECTRUM = (
    [AxleLoadGroup("single", kn, n) for kn, n in [
        (190, 70000), (180, 90000), (170, 92000), (160, 300000), (150, 280000), (140, 650000),
        (130, 600000), (120, 1340000), (110, 1300000), (100, 1500000), (90, 1350000), (85, 3700000)]]
    + [AxleLoadGroup("tandem", kn, n) for kn, n in [
        (400, 200000), (380, 230000), (360, 240000), (340, 235000), (320, 225000), (300, 475000),
        (280, 450000), (260, 1435000), (240, 1250000), (220, 1185000), (200, 1000000),
        (180, 800000), (170, 3200000)]]
    + [AxleLoadGroup("tridem", kn, n) for kn, n in [
        (600, 35000), (570, 40000), (540, 40000), (510, 45000), (480, 43000), (450, 110000),
        (420, 100000), (390, 330000), (360, 300000), (330, 275000), (300, 260000),
        (270, 180000), (255, 720000)]]
)


def _ii4_problem(h_ctb=120):
    return OptimizationProblem(
        traffic=TrafficInput(**T131), subgrade=SubgradeInput(7), road_category="nh",
        layer_types=["DBM", "CRL", "CTB", "CTSB"],
        thickness_bounds={"DBM": (100, 100), "CRL": (100, 100), "CTB": (h_ctb, h_ctb), "CTSB": (250, 250)},
        layer_props={"DBM": {"E": 3000, "nu": .35}, "Subgrade": {"E": 62}},
        ctb_axle_spectrum=II4_SPECTRUM, ctb_per_class_bridge_recompute=True,
    )


def test_annex_ii4_spectrum_stresses_and_damage():
    """
    IRC II.4 single-axle table: sigma_t 0.70 ... 0.33 MPa and damage 0.48.
    Previously the axle load was used as the WHEEL load (4x / 6x / 9x the
    stress) and tandem/tridem axles were not split, so every CTB failed.
    """
    out = SmartPavementSearch(_ii4_problem())._evaluate([100, 100, 120, 250])
    det = out["ctb_details"]["details"]
    singles = [d for d in det if d["axle_type"] == "single"]
    irc = [0.70, 0.67, 0.63, 0.60, 0.56, 0.53, 0.49, 0.46, 0.42, 0.39, 0.35, 0.33]
    assert [round(d["sigma_t"], 2) for d in singles] == irc
    assert singles[0]["sigma_t"] == pytest.approx(0.6995, abs=5e-4)
    assert sum(d["damage"] for d in singles) == pytest.approx(0.48, abs=0.01)
    # IRC prints 5.29 in total; its tandem/tridem rows use stress ratios
    # rounded UP (e.g. SR 0.53 for sigma 0.73) and its tandem 170 kN row
    # (0.31 MPa) contradicts its own single 85 kN row (0.33 MPa). The exact,
    # internally consistent total is 4.88.
    assert out["ctb_details"]["CDF_ctb"] == pytest.approx(4.88, rel=0.02)
    assert out["ctb_adequate"] is False
    tandem400 = next(d for d in det if d["axle_type"] == "tandem" and d["group_load_kn"] == 400)
    assert tandem400["single_axle_kn"] == 200 and tandem400["n_applied"] == 400000
    assert tandem400["sigma_t"] == pytest.approx(0.73, abs=0.005)


def test_annex_ii4_construction_traffic_stress():
    """CTB 160 / CTSB 250 / subgrade 62, 120 kN single axle at 0.80 MPa -> 0.767 MPa."""
    st = [{"modulus": 5000, "poisson": .25, "thickness": 160},
          {"modulus": 600, "poisson": .25, "thickness": 250},
          {"modulus": 62, "poisson": .35, "thickness": 0}]
    r = analyze_pavement(st, {"load": 30000, "pressure": 0.8, "is_dual": True, "spacing": 310},
                         [{"z": 159.9, "r": 0}, {"z": 159.9, "r": 155}])
    sigma = max(max(abs(x["sigma_t"]), abs(x["sigma_r"])) for x in r)
    assert sigma == pytest.approx(0.767, rel=0.005)


def test_annex_ii5_rap_base():
    """
    II.5: 100 mm bituminous / 180 mm foam-bitumen RAP (800 MPa) / 250 mm CTSB.
    Previously a RAP layer was silently dropped from the structure. IRC's
    eps_t 104.2 is reproduced; IRC's quoted eps_v 0.000148 is the vertical
    strain at the top of the CTSB (z = 280 mm) — at the top of the subgrade
    (§3.6.1) it is 0.000267, still within the 0.000301 allowable.
    """
    p = OptimizationProblem(
        traffic=TrafficInput(**T131), subgrade=SubgradeInput(7), road_category="nh",
        layer_types=["DBM", "RAP", "CTSB"],
        thickness_bounds={"DBM": (100, 100), "RAP": (180, 180), "CTSB": (250, 250)},
        layer_props={"DBM": {"E": 3000, "nu": .35}, "Subgrade": {"E": 62}},
    )
    out = SmartPavementSearch(p)._evaluate([100, 180, 250])
    assert [round(l["modulus"]) for l in out["layers"]] == [3000, 800, 600, 62]
    assert out["eps_t"] == pytest.approx(104.2e-6, rel=0.01)
    assert out["eps_v"] == pytest.approx(266.7e-6, rel=0.01)
    assert out["CDF_ctb"] is None            # a CTSB is not checked for fatigue
    assert out["overall_adequate"] is True
    st = [{"modulus": 3000, "poisson": .35, "thickness": 100},
          {"modulus": 800, "poisson": .35, "thickness": 180},
          {"modulus": 600, "poisson": .25, "thickness": 250},
          {"modulus": 62, "poisson": .35, "thickness": 0}]
    r = analyze_pavement(st, DUAL, [{"z": 280.1, "r": 0}, {"z": 280.1, "r": 155}])
    assert max(abs(x["eps_z"]) for x in r) == pytest.approx(148e-6, rel=0.01)


# --------------------------------------------------------------------------
# Reliability and RF (IRC:37-2018 §3.7, Eq. 3.5)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("msa, cat, expected", [
    (15, "nh", ReliabilityLevel.R90), (15, "sh", ReliabilityLevel.R90),
    (15, "expressway", ReliabilityLevel.R90), (15, "urban", ReliabilityLevel.R90),
    (15, "other", ReliabilityLevel.R80), (25, "other", ReliabilityLevel.R90),
])
def test_required_reliability_by_category(msa, cat, expected):
    assert required_reliability(msa, cat, ReliabilityLevel.R80) == expected


@pytest.mark.parametrize("msa, cat, rf", [
    (8, "other", 2.0), (10, "other", 1.0), (15.8, "other", 1.0), (5, "nh", 1.0), (5, "sh", 1.0),
])
def test_ctb_rf_by_category_and_traffic(msa, cat, rf):
    assert ctb_reliability_factor(msa, cat) == rf


def test_ctb_rf_not_tied_to_reliability():
    """15.8 msa CTB on an 'other' road: R80 but RF must be 1 (was 2 -> 2x life)."""
    p = OptimizationProblem(
        traffic=TrafficInput(0, 700, .05, 20, .75, 2.5), subgrade=SubgradeInput(8),
        reliability=ReliabilityLevel.R80, road_category="other",
        layer_types=["BC", "DBM", "CRL", "CTB", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (50, 50), "CRL": (100, 100), "CTB": (150, 150), "GSB": (200, 200)},
    )
    out = SmartPavementSearch(p)._evaluate([40, 50, 100, 150, 200])
    assert out["reliability"] == "R80" and out["ctb_rf"] == 1.0
    # RF = 1 gives 2.24; the old RF = 2 halved it to 1.12 (pinned, so RF = 2 fails).
    assert out["CDF_ctb_strain"] == pytest.approx(2.2375, rel=2e-3)


# --------------------------------------------------------------------------
# Layer modelling
# --------------------------------------------------------------------------

def _evaluate(layer_types, thk, cbr=6, **kw):
    p = OptimizationProblem(
        traffic=TrafficInput(0, 1100, .05, 20, .75, 2.5), subgrade=SubgradeInput(cbr),
        layer_types=layer_types, thickness_bounds={lt: (t, t) for lt, t in zip(layer_types, thk)}, **kw,
    )
    return SmartPavementSearch(p)._evaluate(list(thk))


def test_granular_base_over_ctsb_is_350_and_no_ctb_check():
    out = _evaluate(["BC", "DBM", "WMM", "CTSB", "GSB"], [40, 80, 150, 150, 150])
    mods = {l["name"]: round(l["modulus"]) for l in out["layers"]}
    assert mods["WMM"] == 350 and mods["CTSB"] == 600
    assert out["CDF_ctb"] is None and out["sigma_t_ctb"] is None


def test_gsb_over_ctsb_is_300():
    out = _evaluate(["BC", "DBM", "GSB", "CTSB"], [40, 80, 150, 200])
    assert {l["name"]: round(l["modulus"]) for l in out["layers"]}["GSB"] == 300


def test_crack_relief_450_only_over_ctb():
    out = _evaluate(["BC", "DBM", "WMM", "CTB", "GSB"], [40, 60, 100, 150, 200])
    assert {l["name"]: round(l["modulus"]) for l in out["layers"]}["WMM"] == 450


def test_unknown_and_misordered_layers_rejected():
    with pytest.raises(ValueError, match="Unknown layer type"):
        _evaluate(["Paved Surface", "WMM"], [20, 225])
    with pytest.raises(ValueError, match="must form the top"):
        _evaluate(["WMM", "BC"], [150, 40])


def test_geogrid_on_fixed_modulus_layer_rejected():
    with pytest.raises(ValueError, match="Geogrid"):
        _evaluate(["BC", "DBM", "WMM", "CTB", "GSB"], [40, 60, 100, 150, 200],
                  layer_props={"WMM": {"nu": .35, "geogrid": "PP30"}})


def test_irc_mandatory_minimums_always_enforced():
    """IRC thickness rules survive ignore_minimum_thickness: §9.2 CTB bundle >= 100 mm
    (> 20 msa), §8.2.1 CTB >= 100 mm, §7.2.2 GSB >= 100 mm, §8.1 CRL >= 100 mm."""
    p = OptimizationProblem(
        traffic=TrafficInput(0, 3000, .05, 20, .75, 2.5), subgrade=SubgradeInput(8),
        layer_types=["BC", "DBM", "CRL", "CTB", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (50, 50), "CRL": (100, 100), "CTB": (150, 150), "GSB": (100, 200)},
        ignore_minimum_thickness=True,
    )
    s = SmartPavementSearch(p)
    assert s._irc_mandatory_violation((40, 50, 100, 150, 200)).startswith("bituminous bundle")
    assert "§7.2.2" in (s._irc_mandatory_violation((40, 60, 100, 150, 90)) or "")
    assert "§8.2.1" in (s._irc_mandatory_violation((40, 60, 100, 90, 150)) or "")
    assert "§8.1" in (s._irc_mandatory_violation((40, 60, 90, 150, 150)) or "")
    # A 100 mm GSB filter / drainage layer is IRC-compliant (§7.2.2 (i)/(iii)).
    assert s._irc_mandatory_violation((40, 60, 100, 150, 100)) is None
    assert s._enumerate_combinations() == []


def test_unbound_base_minimum_is_150_but_gsb_is_100():
    """§8.1: an unbound BASE (WMM/WBM) >= 150 mm; a GSB sub-base only >= 100 mm (§7.2.2)."""
    p = OptimizationProblem(
        traffic=TrafficInput(0, 1000, .05, 20, .75, 2.5), subgrade=SubgradeInput(8),
        layer_types=["BC", "DBM", "WMM", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (60, 60), "WMM": (100, 250), "GSB": (100, 200)},
        ignore_minimum_thickness=True,
    )
    s = SmartPavementSearch(p)
    assert "§8.1" in (s._irc_mandatory_violation((40, 60, 125, 150)) or "")
    assert s._irc_mandatory_violation((40, 60, 150, 100)) is None


def test_traffic_growth_to_opening_year():
    base = TrafficInput(0, 1000, 0.05, 15, 0.75, 3.0)
    later = TrafficInput(0, 1000, 0.05, 15, 0.75, 3.0, years_to_completion=2)
    assert later.cumulative_msa() == pytest.approx(base.cumulative_msa() * 1.05 ** 2)


def test_axle_spectrum_expansion():
    out = expand_axle_spectrum([AxleLoadGroup("Tandem", 400, 10), AxleLoadGroup("tridem", 600, 5)])
    assert out[0]["single_axle_kn"] == 200 and out[0]["wheel_load_n"] == 50000
    assert out[0]["single_axle_repetitions"] == 20
    assert out[1]["single_axle_kn"] == 200 and out[1]["single_axle_repetitions"] == 15
    with pytest.raises(ValueError):
        expand_axle_spectrum([AxleLoadGroup("quad", 100, 1)])


# --------------------------------------------------------------------------
# Periphery
# --------------------------------------------------------------------------

def test_corridor_reports_infeasible_section():
    from mep_opt.advanced.corridor import _run_single_section
    sec = {"chainage": "0+000", "cbr": 2.0, "cvpd": 20000, "vdf": 5, "ldf": .75}
    lc = [{"layer_type": "BC", "min_thickness": 40, "max_thickness": 40, "is_fixed": True,
           "fixed_thickness": 40, "E": 2000, "nu": .35},
          {"layer_type": "DBM", "min_thickness": 50, "max_thickness": 60, "E": 2000, "nu": .35},
          {"layer_type": "WMM", "min_thickness": 150, "max_thickness": 150, "E": None, "nu": .35},
          {"layer_type": "GSB", "min_thickness": 150, "max_thickness": 150, "E": None, "nu": .35}]
    out = _run_single_section(sec, lc, .05, 20, 80)
    assert out["status"] == "no_adequate_design"
    assert out["cdf_f"] is None and out["thicknesses"] == []


def test_bridge_cache_key_includes_bond():
    from mep_opt.solver.iitpave_bridge import _cache_key
    a = [{"modulus": 3000, "poisson": .35, "thickness": 100}, {"modulus": 60, "poisson": .35, "thickness": 0}]
    b = [dict(a[0], friction_factor=0.0), a[1]]
    assert _cache_key(a, DUAL, [{"z": 1, "r": 0}]) != _cache_key(b, DUAL, [{"z": 1, "r": 0}])


def _load_browser_bridge():
    path = Path(__file__).resolve().parents[2] / "frontend" / "public" / "py" / "optimizer_worker_bridge.py"
    spec = importlib.util.spec_from_file_location("optimizer_worker_bridge_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _browser_request(**over):
    req = {
        "cvpd": 1500, "growth_rate": 0.05, "design_life": 20, "subgrade_cbr": 8,
        "reliability": "80%", "road_category": "nh", "construction_years": 1,
        "layers": [
            {"layer_type": "BC", "E": 2000, "nu": .35, "is_fixed": True, "fixed_thickness": 40,
             "min_thickness": 40, "max_thickness": 40},
            {"layer_type": "DBM", "E": 2000, "nu": .35, "is_fixed": False,
             "min_thickness": 100, "max_thickness": 150, "fixed_thickness": 0},
            {"layer_type": "WMM", "E": None, "nu": .35, "is_fixed": True, "fixed_thickness": 250,
             "min_thickness": 250, "max_thickness": 250},
            {"layer_type": "GSB", "E": None, "nu": .35, "is_fixed": True, "fixed_thickness": 200,
             "min_thickness": 200, "max_thickness": 200},
            {"layer_type": "Subgrade", "E": 66, "nu": .35, "is_fixed": True, "fixed_thickness": 0,
             "min_thickness": 0, "max_thickness": 0},
        ],
    }
    req.update(over)
    return req


def test_browser_bridge_matches_api_contract():
    bridge = _load_browser_bridge()
    ok = json.loads(bridge.run_optimize(json.dumps(_browser_request())))
    assert ok["status"] == "success" and ok["adequate_designs"]
    assert ok["adequate_designs"][0]["details"]["road_category"] == "nh"
    # (R90 by category below 20 msa: test_audit_round2.test_bridge_and_api_road_category...)
    bad = json.loads(bridge.run_optimize(json.dumps(_browser_request(road_category="motorway"))))
    assert bad["status"] == "error" and "road_category" in bad["message"]
    layers = _browser_request()["layers"]
    layers[0] = dict(layers[0], layer_type="Paved Surface")
    bad2 = json.loads(bridge.run_optimize(json.dumps(_browser_request(layers=layers))))
    assert bad2["status"] == "error" and "Unknown layer_type" in bad2["message"]


def test_api_accepts_road_category_and_rejects_unknown_types():
    from fastapi.testclient import TestClient
    from mep_opt.web import main as web_main
    client = TestClient(web_main.app)
    body = _browser_request()
    body["layers"][0] = dict(body["layers"][0], layer_type="Paved Surface")
    r = client.post("/api/optimize", json=body)
    assert r.status_code == 422 and "Unknown layer_type" in r.text
    r2 = client.post("/api/optimize", json=_browser_request(road_category="motorway"))
    assert r2.status_code == 422
    r3 = client.post("/api/optimize", json=_browser_request())
    assert r3.status_code == 200, r3.text
    designs = r3.json()["adequate_designs"]
    assert designs and designs[0]["details"]["reliability"] == "R90"      # NH at any traffic
    assert designs[0]["details"]["road_category"] == "nh"


def test_router_rejects_partial_bond():
    from fastapi.testclient import TestClient
    from mep_opt.web import main as web_main
    client = TestClient(web_main.app)
    body = {
        "layers": [{"modulus": 3000, "poisson": .35, "thickness": 100, "friction_factor": 0.5},
                   {"modulus": 60, "poisson": .35, "thickness": 0}],
        "load": {"load": 20000, "pressure": .56, "is_dual": True, "spacing": 310},
        "r_steps": 2, "z_steps": 2,
    }
    assert client.post("/api/v2/strain-field", json=body).status_code == 422


def test_backend_pdf_renders_ctb_criteria():
    from mep_opt.web.pdf_report import generate_report
    out = _evaluate(["BC", "DBM", "WMM", "CTB", "GSB"], [40, 60, 100, 150, 200])
    pdf = generate_report(
        project_name="audit", traffic_params={"cvpd": 1100, "growth_rate": .05, "design_life": 20,
                                              "vdf": 2.5, "ldf": .75},
        subgrade_cbr=6, selected_solution={"optimal_layers": [], "total_thickness": 0, "details": out},
        adequate_designs=[],
    )
    assert pdf[:4] == b"%PDF"
    # (PDF content: test_audit_round2.test_backend_pdf_*)


@pytest.mark.parametrize("r", [0.0, 50.0, 100.0, 150.0, 300.0])
def test_surface_closed_form_is_limit_of_dense_integral(r):
    """The exact z = 0 half-space values equal the z -> 0+ dense Hankel integral."""
    import mep_opt.solver.burmister as B
    E, nu, q = 60.0, 0.35, 0.56
    s = B.BurmisterSolver([B.LayerProperty(E, nu, 0)], B.LoadConfig(20000.0, q, False))
    G = E / (2 * (1 + nu))
    lam = 2 * G * nu / (1 - 2 * nu)
    uz, ur, sz, sr, st, _ = B._halfspace_surface_closed_form(r, q, s.a, E, nu)
    m, w = s._refined_nodes(r, 0.005)
    num = s._hankel_sums(m, w, *B._halfspace_kernel_vec(m, 0.005, q, s.a, E, nu), r, lam, G, lam + 2 * G)
    assert num[0] == pytest.approx(uz, rel=1e-4)
    assert num[1] == pytest.approx(ur, rel=1e-3, abs=1e-6)
    assert num[2] == pytest.approx(sz, abs=1e-4)
    assert num[4] == pytest.approx(sr, abs=1e-3)
    assert num[5] == pytest.approx(st, abs=1e-3)
