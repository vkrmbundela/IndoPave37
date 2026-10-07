"""
Regression tests for the second (independent-verification) audit round
=======================================================================
Each test pins a defect that an adversarial reviewer reproduced on the first
round of audit fixes, against an exact solution, an IRC:37-2018 / IRC:SP:59
clause, or the engine's own reference path:

  * solver: input bounds (non-finite / far / sub-millimetre), radius sign,
    bond of a dropped zero-thickness layer, far-field quadrature, batched
    kernel == scalar kernel;
  * bituminous fatigue strain = largest TENSILE strain, compressive -> not
    checked (Annex III Tables III.2 / III.3 / III.4);
  * CTB spectrum always on the dual set; CTB >= 100 mm (§8.2.1); GSB 100 mm
    (§7.2.2) vs unbound base 150 mm (§8.1);
  * infeasibility diagnostics (skipped spectrum, traffic-tier reasons,
    preliminary design);
  * geogrid placement validated up front; reinforcement never worse than the
    conventional section (IRC:SP:59 §3.1.3); composite Poisson's ratio;
  * road-category wiring below the 20 / 10 msa thresholds, construction years,
    API / browser-bridge validation parity, PDF content, corridor envelope.
"""

import asyncio
import importlib.util
import json
import math
import re
from pathlib import Path

import numpy as np
import pytest

import mep_opt.solver.burmister as B
from mep_opt.solver.burmister import analyze_pavement
from mep_opt.solver.irc37 import (
    ReliabilityLevel, SubgradeInput, TrafficInput, bituminous_fatigue_strain,
    build_layer_stack, ctb_fatigue_life_strain, fatigue_life,
)
from mep_opt.optimizer.problem import OptimizationProblem
from mep_opt.optimizer.smart_search import SmartPavementSearch

from mep_opt.tests.test_audit_fixes import (
    DUAL, II4_SPECTRUM, T131, _browser_request, _ii4_problem, _load_browser_bridge,
)

_ROOT = Path(__file__).resolve().parents[2]


def _api():
    from fastapi.testclient import TestClient
    from mep_opt.web import main as web_main
    return TestClient(web_main.app)


# --------------------------------------------------------------------------
# Solver
# --------------------------------------------------------------------------

_STACK = [{"modulus": 3000, "poisson": .35, "thickness": 100},
          {"modulus": 300, "poisson": .35, "thickness": 250},
          {"modulus": 60, "poisson": .35, "thickness": 0}]
_SINGLE = {"load": 20000, "pressure": 0.56, "is_dual": False}


@pytest.mark.parametrize("pt", [
    {"z": 1.0, "r": math.inf}, {"z": 1.0, "r": math.nan}, {"z": -1.0, "r": 0.0},
    {"z": math.inf, "r": 0.0}, {"z": 1.0, "r": 2.5e4},
])
def test_solver_rejects_unbounded_points(pt):
    """r = inf used to loop forever in the refined-panel builder (server hang)."""
    with pytest.raises(ValueError):
        analyze_pavement(_STACK, _SINGLE, [pt])


def test_solver_rejects_submillimetre_layers():
    """A 0.01 mm top layer made the near-surface integral cost minutes per point."""
    st = [dict(_STACK[0], thickness=0.2)] + _STACK
    with pytest.raises(ValueError, match="thinner than 1 mm"):
        analyze_pavement(st, DUAL, [{"z": 0.0, "r": 0.0}])


def test_api_rejects_unbounded_points_and_thin_layers():
    client = _api()
    body = {"layers": [{"E": 3000, "nu": .35, "h": 100}, {"E": 300, "nu": .35, "h": 250},
                       {"E": 60, "nu": .35, "h": 0}],
            "wheel_type": "Single", "points": [{"z": 1.0, "r": 1e9}]}
    assert client.post("/api/solve", json=body).status_code == 422
    body["points"] = [{"z": 1.0, "r": 0.0}]
    body["layers"][0]["h"] = 0.5
    assert client.post("/api/solve", json=body).status_code == 422


def test_far_point_is_bounded_and_accurate():
    """r = 1e4 mm at a shallow depth now completes; panels are capped, not unbounded."""
    s = B.BurmisterSolver([B.LayerProperty(3000, .35, 1.0), B.LayerProperty(3000, .35, 100),
                           B.LayerProperty(300, .35, 250), B.LayerProperty(60, .35, 0)],
                          B.LoadConfig(20000, 0.56, False))
    m, w = s._refined_nodes(1e4, 2.0, max_panels=B._MAX_REFINED_PANELS)
    assert m.size <= 8 * (B._MAX_REFINED_PANELS + 200)
    x = s.solve([B.EvalPoint(0.0, 1e4)])[0]
    old = B._MAX_REFINED_PANELS
    try:
        B._MAX_REFINED_PANELS = 10 ** 7
        y = s.solve([B.EvalPoint(0.0, 1e4)])[0]
    finally:
        B._MAX_REFINED_PANELS = old
    assert x.eps_r == pytest.approx(y.eps_r, rel=1e-4)
    assert x.disp_z == pytest.approx(y.disp_z, rel=1e-6)


@pytest.mark.parametrize("z", [1.0, 100.0])
def test_negative_radius_is_a_radius(z):
    """Axisymmetric: r = -155 must equal r = +155 (eps_t was +79% at z = 100)."""
    a, b = analyze_pavement(_STACK, _SINGLE, [{"z": z, "r": -155.0}, {"z": z, "r": 155.0}])
    for k in ("eps_t", "eps_r", "eps_z", "sigma_t", "sigma_r", "sigma_z", "disp_z"):
        assert a[k] == pytest.approx(b[k], rel=1e-12, abs=1e-15), k
    assert a["r"] == -155.0


def test_dropped_zero_layer_keeps_its_frictionless_interface():
    """A 0 mm interlayer with f = 0 used to vanish together with its unbonded interface."""
    top = {"modulus": 3000, "poisson": .35, "thickness": 100}
    rest = [{"modulus": 300, "poisson": .35, "thickness": 250}, {"modulus": 60, "poisson": .35, "thickness": 0}]
    via_zero = [top, {"modulus": 500, "poisson": .35, "thickness": 0.0, "friction_factor": 0.0}] + rest
    direct = [dict(top, friction_factor=0.0)] + rest
    bonded = [top] + rest
    pts = [{"z": 99.9, "r": 0.0}, {"z": 350.1, "r": 0.0}]
    a = analyze_pavement(via_zero, DUAL, pts)
    b = analyze_pavement(direct, DUAL, pts)
    c = analyze_pavement(bonded, DUAL, pts)
    for i in range(2):
        assert a[i]["eps_t"] == pytest.approx(b[i]["eps_t"], rel=1e-12)
        assert a[i]["eps_z"] == pytest.approx(b[i]["eps_z"], rel=1e-12)
    assert abs(a[0]["eps_t"] - c[0]["eps_t"]) > 0.2 * abs(c[0]["eps_t"])


def test_far_field_is_continuous_across_near_surface_switch():
    """At r = 2000 mm the deep IITPAVE intervals aliased (eps_z +417% just below 0.75a)."""
    st = [{"modulus": 3000, "poisson": .35, "thickness": 40}, {"modulus": 3000, "poisson": .35, "thickness": 100},
          {"modulus": 300, "poisson": .35, "thickness": 250}, {"modulus": 150, "poisson": .35, "thickness": 200},
          {"modulus": 60, "poisson": .35, "thickness": 0}]
    a = math.sqrt(20000 / (math.pi * 0.56))
    lo, hi = analyze_pavement(st, _SINGLE, [{"z": 0.75 * a - 0.001, "r": 2000.0},
                                            {"z": 0.75 * a + 0.001, "r": 2000.0}])
    assert hi["eps_z"] == pytest.approx(lo["eps_z"], rel=1e-3)
    assert hi["eps_r"] == pytest.approx(lo["eps_r"], rel=1e-3)


def test_halfspace_far_field_matches_closed_form_kernel():
    """N = 1 half-space at r = 2000, z = 80 mm: deep path vs dense closed-form quadrature."""
    E, nu, q = 60.0, 0.35, 0.56
    s = B.BurmisterSolver([B.LayerProperty(E, nu, 0)], B.LoadConfig(20000, q, False))
    G = E / (2 * (1 + nu)); lam = 2 * G * nu / (1 - 2 * nu)
    m, w = s._refined_nodes(2000.0, 80.0)
    ref = s._hankel_sums(m, w, *B._halfspace_kernel_vec(m, 80.0, q, s.a, E, nu), 2000.0, lam, G, lam + 2 * G)
    got = s.solve([B.EvalPoint(80.0, 2000.0)])[0]
    assert got.sigma_z == pytest.approx(ref[2], abs=1e-9 * q)
    assert got.disp_z == pytest.approx(ref[0], rel=1e-9)


def test_batched_kernel_equals_scalar_kernel():
    """The vectorised linear solve is the same system as the per-m scalar one."""
    rng = np.random.default_rng(7)
    layers = [B.LayerProperty(3000, .35, 40), B.LayerProperty(450, .35, 100, 0.0),
              B.LayerProperty(5000, .25, 150), B.LayerProperty(600, .25, 200), B.LayerProperty(70, .35, 0)]
    s = B.BurmisterSolver(layers, B.LoadConfig(20000, 0.8, True, 310))
    ms = np.sort(rng.uniform(1e-4, 0.5, 300))
    for li, zl in [(0, 10.0), (2, 149.9), (4, 3.0)]:
        st, ok = s._kernel_batch(ms, li, zl)
        assert ok.all()
        for k in range(0, ms.size, 37):
            ref = s._kernel_at_m(ms[k], li, zl)
            np.testing.assert_allclose(st[k], ref, rtol=1e-10, atol=1e-25)


# --------------------------------------------------------------------------
# Bituminous fatigue strain (IRC:37-2018 Annex II / III)
# --------------------------------------------------------------------------

def _annex3(types, thk, **kw):
    p = OptimizationProblem(
        traffic=TrafficInput(0, 300, .05, 20, .75, 2.5), subgrade=SubgradeInput(8),
        reliability=ReliabilityLevel.R80, road_category="other",
        layer_types=types, thickness_bounds={t: (h, h) for t, h in zip(types, thk)},
        layer_props={types[0]: {"E": 2000, "nu": .35}, "Subgrade": {"E": 77}},
        air_voids=3.5, bitumen_volume=11.5, **kw,
    )
    return SmartPavementSearch(p)._evaluate(list(thk))


def test_annex_iii2_fatigue_uses_tensile_strain():
    """
    Table III.2 (5 msa): BC 40 / CRL 100 / CTB 100 / CTSB 200 -> 1.18E-04 and a
    fatigue life of 1096 msa. The radial strain between the duals is about
    -297 µε; taking |compressive| gave 296 µε and a 31 msa life.
    """
    out = _annex3(["BC", "CRL", "CTB", "CTSB"], [40, 100, 100, 200])
    assert [round(l["modulus"]) for l in out["layers"]] == [2000, 450, 5000, 600, 77]
    assert out["fatigue_compressive"] is False
    assert out["eps_t"] == pytest.approx(118e-6, rel=0.01)
    assert out["Nf"] / 1e6 == pytest.approx(1096, rel=0.03)


def test_annex_iii4_rap_section_fatigue_strain():
    """Table III.4 (5 msa): BC 40 / RAP 100 / CTSB 200 -> 3.48E-05 (was 209.7 µε, 6x)."""
    out = _annex3(["BC", "RAP", "CTSB"], [40, 100, 200])
    assert out["eps_t"] == pytest.approx(34.8e-6, rel=0.02)


def test_annex_iii3_compressive_strain_fatigue_not_checked():
    """Table III.3 (SAMI): 6.59E-05 (Comp) and '***' — fatigue need not be checked."""
    out = _annex3(["BC", "CTB", "CTSB"], [40, 160, 200], has_sami=True)
    assert out["fatigue_compressive"] is True
    assert out["eps_t"] == pytest.approx(-65.9e-6, rel=0.01)
    assert out["CDF_fatigue"] == 0.0


def test_fatigue_strain_helper_and_advanced_modules_agree():
    from mep_opt.advanced._strain_utils import extract_design_strains
    rows = [{"eps_t": 112e-6, "eps_r": 117e-6, "eps_z": -1e-4},
            {"eps_t": 59e-6, "eps_r": -296e-6, "eps_z": -1e-4},
            {"eps_t": 0.0, "eps_r": 0.0, "eps_z": -300e-6}]
    assert bituminous_fatigue_strain(rows[:2]) == (117e-6, 117e-6, False)
    eq, rep, comp = bituminous_fatigue_strain([{"eps_t": -6e-5, "eps_r": -6.6e-5}])
    assert (eq, rep, comp) == (0.0, -6.6e-5, True)
    eps_t, eps_v = extract_design_strains(rows, {"bit_bottom": [0, 1], "sub_top": [2]})
    assert eps_t == 117e-6 and eps_v == 300e-6
    assert fatigue_life(0.0, 3000) == math.inf


# --------------------------------------------------------------------------
# CTB checks
# --------------------------------------------------------------------------

def test_ctb_spectrum_uses_dual_set_whatever_the_wheel_type():
    """With wheel_type='Single' each axle was analysed at 1/4 of its load (CFD 0.038)."""
    p = _ii4_problem()
    p.wheel_type = "Single"
    out = SmartPavementSearch(p)._evaluate([100, 100, 120, 250])
    assert out["ctb_details"]["CDF_ctb"] == pytest.approx(4.88, rel=0.02)
    assert out["ctb_adequate"] is False


def test_ctb_spectrum_runs_on_the_default_path():
    """ctb_per_class_bridge_recompute=False (API/bridge default) must still run Eq. 3.6/3.7."""
    p = _ii4_problem()
    p.ctb_per_class_bridge_recompute = False
    out = SmartPavementSearch(p)._evaluate([100, 100, 120, 250])
    assert out["CDF_fatigue"] < 1 and out["CDF_rutting"] < 1 and out["CDF_ctb_strain"] < 1
    assert out["CDF_ctb"] == pytest.approx(4.88, rel=0.02)
    assert out["ctb_adequate"] is False and out["overall_adequate"] is False


def test_ctb_rf_value_used_in_the_strain_criterion():
    """RF = 1 must reach Eq. 3.5 itself (the old RF = 2 gave 1.12 and still passed > 1)."""
    p = OptimizationProblem(
        traffic=TrafficInput(0, 700, .05, 20, .75, 2.5), subgrade=SubgradeInput(8),
        reliability=ReliabilityLevel.R80, road_category="other",
        layer_types=["BC", "DBM", "CRL", "CTB", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (50, 50), "CRL": (100, 100), "CTB": (150, 150), "GSB": (200, 200)},
    )
    out = SmartPavementSearch(p)._evaluate([40, 50, 100, 150, 200])
    assert out["CDF_ctb_strain"] == pytest.approx(2.2375, rel=2e-3)
    assert out["Nf_ctb_strain"] == pytest.approx(ctb_fatigue_life_strain(out["eps_t_ctb"], 5000, ReliabilityLevel.R80, rf=1.0))


@pytest.mark.parametrize("cat, rel, rf, cdf", [("nh", "R90", 1.0, 0.959), ("other", "R80", 2.0, 0.479)])
def test_road_category_wiring_below_thresholds(cat, rel, rf, cdf):
    """6.79 msa: below both 20 msa (§3.7) and 10 msa (Eq. 3.5 RF) — only the category decides."""
    p = OptimizationProblem(
        traffic=TrafficInput(0, 300, .05, 20, .75, 2.5), subgrade=SubgradeInput(8),
        reliability=ReliabilityLevel.R80, road_category=cat,
        layer_types=["BC", "DBM", "CRL", "CTB", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (50, 50), "CRL": (100, 100), "CTB": (150, 150), "GSB": (200, 200)},
    )
    out = SmartPavementSearch(p)._evaluate([40, 50, 100, 150, 200])
    assert out["msa"] == pytest.approx(6.79, rel=1e-3)
    assert out["reliability"] == rel and out["ctb_rf"] == rf
    assert out["CDF_ctb_strain"] == pytest.approx(cdf, rel=2e-3)


# --------------------------------------------------------------------------
# Minimum thicknesses and infeasibility diagnostics
# --------------------------------------------------------------------------

def test_ctsb_demo_with_100mm_gsb_is_feasible():
    """The shipped CTSB preset (GSB 100 mm) was rejected by a misapplied §8.1 rule."""
    p = OptimizationProblem(
        traffic=TrafficInput(0, 1100, .05, 20, .75, 2.5), subgrade=SubgradeInput(6), road_category="nh",
        layer_types=["BC", "DBM", "WMM", "CTSB", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (80, 80), "WMM": (150, 150), "CTSB": (150, 150), "GSB": (100, 100)},
    )
    s = SmartPavementSearch(p)
    assert s._enumerate_combinations() == [(40, 80, 150, 150, 100)]


def test_infeasibility_diagnostic_completes_skipped_spectrum():
    """A design skipped by the spectrum gate carries only Eq. 3.5; the diagnostic completes it."""
    def run(recompute):
        p = OptimizationProblem(
            traffic=TrafficInput(**T131), subgrade=SubgradeInput(7), road_category="nh",
            layer_types=["DBM", "CRL", "CTB", "CTSB"],
            thickness_bounds={"DBM": (100, 130), "CRL": (100, 100), "CTB": (100, 100), "CTSB": (250, 250)},
            layer_props={"DBM": {"E": 3000, "nu": .35}, "Subgrade": {"E": 30}},
            ctb_axle_spectrum=II4_SPECTRUM, ctb_per_class_bridge_recompute=recompute,
        )
        s = SmartPavementSearch(p)
        res = s.run()
        return s._closest_to_passing_diagnostic(), res
    fast, res = run(False)
    full, _ = run(True)
    assert fast["governing_mode"] == "ctb" == full["governing_mode"]
    assert fast["max_cdf"] == pytest.approx(full["max_cdf"], rel=1e-9)
    assert "governed by ctb" in res.warnings[0]


def test_prefilter_message_names_tier_minimums_and_preliminary_is_compliant():
    p = OptimizationProblem(
        traffic=TrafficInput(0, 520, .05, 20, .75, 2.5), subgrade=SubgradeInput(8), road_category="other",
        layer_types=["BC", "DBM", "WBM", "GSB"],
        thickness_bounds={"BC": (30, 30), "DBM": (40, 45), "WBM": (75, 200), "GSB": (150, 200)},
    )
    s = SmartPavementSearch(p)
    res = s.run()
    msg = res.warnings[0]
    assert not res.is_feasible
    assert "traffic-tier practice minimum" in msg and "ignore_minimum_thickness" in msg
    assert s._irc_mandatory_violation(tuple(res.optimal_thicknesses)) is None


# --------------------------------------------------------------------------
# Geogrid and granular modelling
# --------------------------------------------------------------------------

def _gran_problem(cbr, props, geogrid=None, where="GSB", thk=(100, 150, 150)):
    props = {k: dict(v) for k, v in props.items()}
    if geogrid:
        props.setdefault(where, {})["geogrid"] = geogrid
    return OptimizationProblem(
        traffic=TrafficInput(0, 800, .05, 20, .75, 2.5), subgrade=SubgradeInput(cbr), road_category="other",
        layer_types=["DBM", "WMM", "GSB"],
        thickness_bounds={"DBM": (thk[0], thk[0]), "WMM": (thk[1], thk[1]), "GSB": (thk[2], thk[2])},
        layer_props=props,
    )


def test_geogrid_never_worse_than_conventional_section():
    """
    CBR 15, DBM 100 / WMM 150 / GSB 150 with PET30 on the GSB (MIF ~1.16): the
    separately estimated reinforced moduli are softer than the §7.2.3
    composite, so the reinforced section gave HIGHER eps_t / eps_v. IRC:SP:59
    §3.1.3 measures reinforcement against the conventional section.
    """
    props = {"DBM": {"E": 2000, "nu": .35}}
    conv = SmartPavementSearch(_gran_problem(15, props))._evaluate([100, 150, 150])
    reinf = SmartPavementSearch(_gran_problem(15, props, "PET30"))._evaluate([100, 150, 150])
    assert reinf["eps_t"] <= conv["eps_t"] * (1 + 1e-12)
    assert reinf["eps_v"] <= conv["eps_v"] * (1 + 1e-12)
    assert reinf["geogrid_credit"].startswith("not taken")
    strong = SmartPavementSearch(_gran_problem(4, props, "PET60", "WMM"))._evaluate([100, 150, 150])
    weak = SmartPavementSearch(_gran_problem(4, props))._evaluate([100, 150, 150])
    assert strong["geogrid_credit"] == "applied" and strong["eps_t"] < weak["eps_t"]


@pytest.mark.parametrize("types, props, msg", [
    (["BC", "DBM", "WMM", "GSB"], {"BC": {"geogrid": "PET60"}}, "only defined for unbound"),
    (["BC", "DBM", "WMM", "CTB", "GSB"], {"CTB": {"geogrid": "PP30"}}, "only defined for unbound"),
    (["BC", "DBM", "WMM", "CTB", "GSB"], {"WMM": {"geogrid": "PP30"}}, "directly above CTB"),
    (["BC", "DBM", "WMM", "CTSB", "GSB"], {"WMM": {"geogrid": "PP30"}}, "directly above CTSB"),
])
def test_geogrid_placement_rejected_up_front(types, props, msg):
    with pytest.raises(ValueError, match=msg):
        OptimizationProblem(
            traffic=TrafficInput(0, 800, .05, 20, .75, 2.5), subgrade=SubgradeInput(8),
            layer_types=types, thickness_bounds={t: (100, 200) for t in types}, layer_props=props,
        )


def test_geogrid_placement_api_and_bridge():
    layers = _browser_request()["layers"]
    layers[0] = dict(layers[0], geogrid="PET60")                       # on BC
    r = _api().post("/api/optimize", json=_browser_request(layers=layers))
    assert r.status_code == 422 and "only defined for unbound" in r.text
    bridge = _load_browser_bridge()
    out = json.loads(bridge.run_optimize(json.dumps(_browser_request(layers=layers))))
    assert out["status"] == "error" and "only defined for unbound" in out["message"]
    layers = _browser_request()["layers"]
    layers[2] = dict(layers[2], geogrid="none")                        # 'none' = no geogrid
    out = json.loads(bridge.run_optimize(json.dumps(_browser_request(layers=layers))))
    assert out["status"] == "success" and out["reinforcement"] == []


def test_composite_layer_keeps_the_user_poisson_ratio():
    """§7.2.3 composite row: thickness-weighted nu (was always 0.35; the cockpit used the user's)."""
    stack = build_layer_stack(
        SubgradeInput(8),
        [{"thickness": 250, "layer_type": "WMM", "E": None, "nu": 0.45},
         {"thickness": 200, "layer_type": "GSB", "E": None, "nu": 0.40}],
        [], {},
    )
    assert stack[0]["thickness"] == 450
    assert stack[0]["poisson"] == pytest.approx((0.45 * 250 + 0.40 * 200) / 450)
    default = build_layer_stack(SubgradeInput(8), [{"thickness": 250, "layer_type": "WMM"},
                                                   {"thickness": 200, "layer_type": "GSB"}], [], {})
    assert default[0]["poisson"] == 0.35


# --------------------------------------------------------------------------
# API / bridge / PDF / corridor
# --------------------------------------------------------------------------

def test_bridge_and_api_road_category_and_construction_years():
    """Below 20 msa only the category decides R90; x scales the MSA by (1+r)^x (Eq. 4.6)."""
    bridge = _load_browser_bridge()
    client = _api()
    for cat, rel in (("nh", "R90"), ("other", "R80")):
        req = _browser_request(cvpd=300, road_category=cat, construction_years=0)
        b = json.loads(bridge.run_optimize(json.dumps(req)))
        a = client.post("/api/optimize", json=req).json()
        for out in (a, b):
            assert out["adequate_designs"], out
            d = out["adequate_designs"][0]["details"]
            assert d["reliability"] == rel and d["road_category"] == cat
    msa = {}
    for x in (0, 2):
        req = _browser_request(cvpd=300, construction_years=x)
        msa[("bridge", x)] = json.loads(bridge.run_optimize(json.dumps(req)))["adequate_designs"][0]["details"]["msa"]
        msa[("api", x)] = client.post("/api/optimize", json=req).json()["adequate_designs"][0]["details"]["msa"]
    for side in ("bridge", "api"):
        assert msa[(side, 2)] / msa[(side, 0)] == pytest.approx(1.05 ** 2)


@pytest.mark.parametrize("over, field", [
    ({"design_life": 20.5}, "design_life"),
    ({"road_category": None}, "road_category"),
    ({"material_rates": {"BC": -100}}, "material_rates"),
    ({"material_rates": {"BC": {"density": 0}}}, "density"),
    ({"material_rates": {"BC": {"transport_co2_factor": -1}}}, "transport_co2_factor"),
])
def test_bridge_and_api_reject_the_same_inputs(over, field):
    r = _api().post("/api/optimize", json=_browser_request(**over))
    assert r.status_code == 422, (field, r.status_code, r.text)
    out = json.loads(_load_browser_bridge().run_optimize(json.dumps(_browser_request(**over))))
    assert out["status"] == "error", (field, out)


def test_bridge_requires_thickness_bounds():
    layers = _browser_request()["layers"]
    layers[1] = {k: v for k, v in layers[1].items() if k != "min_thickness"}
    assert _api().post("/api/optimize", json=_browser_request(layers=layers)).status_code == 422
    out = json.loads(_load_browser_bridge().run_optimize(json.dumps(_browser_request(layers=layers))))
    assert out["status"] == "error"


def _pdf_text(details):
    import reportlab.rl_config as rc
    from mep_opt.web.pdf_report import generate_report
    old = rc.pageCompression
    rc.pageCompression = 0
    try:
        pdf = generate_report(
            project_name="audit",
            traffic_params={"cvpd": 600, "growth_rate": .05, "design_life": 20, "vdf": 2.5, "ldf": .75},
            subgrade_cbr=8, selected_solution={"optimal_layers": [], "total_thickness": 0, "details": details},
            adequate_designs=[],
        )
    finally:
        rc.pageCompression = old
    raw = pdf.decode("latin-1")
    txt = "".join(re.findall(r"\((.*?)(?<!\\)\)\s*Tj", raw))
    return pdf, txt.replace("\\(", "(").replace("\\)", ")")


def _pdf_has(txt, phrase):
    """reportlab may split a line into several Tj runs; compare without spaces."""
    return phrase.replace(" ", "") in txt.replace(" ", "")


def test_backend_pdf_prints_the_reliability_actually_used():
    nh = SmartPavementSearch(OptimizationProblem(
        traffic=TrafficInput(0, 600, .05, 20, .75, 2.5), subgrade=SubgradeInput(8),
        reliability=ReliabilityLevel.R80, road_category="nh",
        layer_types=["BC", "DBM", "WMM", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (100, 100), "WMM": (250, 250), "GSB": (200, 200)},
    ))._evaluate([40, 100, 250, 200])
    assert nh["msa"] < 20 and nh["reliability"] == "R90"
    pdf, txt = _pdf_text(nh)
    assert pdf[:4] == b"%PDF"
    assert _pdf_has(txt, "90% (NH: any traffic)") and not _pdf_has(txt, "low-volume")
    assert _pdf_has(txt, "0.5161") and not _pdf_has(txt, "1.6064")
    other = dict(nh, reliability="R80", road_category="other")
    _, txt80 = _pdf_text(other)
    assert _pdf_has(txt80, "1.6064") and _pdf_has(txt80, "4.1656")


def test_backend_pdf_renders_ctb_strain_criterion_and_rf():
    p = OptimizationProblem(
        traffic=TrafficInput(0, 1100, .05, 20, .75, 2.5), subgrade=SubgradeInput(6),
        layer_types=["BC", "DBM", "WMM", "CTB", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (60, 60), "WMM": (100, 100), "CTB": (150, 150), "GSB": (200, 200)},
    )
    out = SmartPavementSearch(p)._evaluate([40, 60, 100, 150, 200])
    _, txt = _pdf_text(out)
    assert _pdf_has(txt, "Eq. 3.5") and _pdf_has(txt, "RF =")


def test_backend_pdf_compressive_fatigue_not_checked():
    out = _annex3(["BC", "CTB", "CTSB"], [40, 160, 200], has_sami=True)
    _, txt = _pdf_text(out)
    assert _pdf_has(txt, "not checked") and _pdf_has(txt, "Annex III")


def test_corridor_envelope_is_verified_against_every_section():
    from mep_opt.advanced.corridor import start_corridor_job, get_job_status
    lc = [{"layer_type": "BC", "min_thickness": 40, "max_thickness": 40, "is_fixed": True,
           "fixed_thickness": 40, "E": 2000, "nu": .35},
          {"layer_type": "DBM", "min_thickness": 50, "max_thickness": 90, "E": 2000, "nu": .35},
          {"layer_type": "WMM", "min_thickness": 150, "max_thickness": 250, "E": None, "nu": .35},
          {"layer_type": "GSB", "min_thickness": 150, "max_thickness": 200, "E": None, "nu": .35}]
    sections = [{"chainage": "0+000", "cbr": 8.0, "cvpd": 1000, "vdf": 2.5, "ldf": .75},
                {"chainage": "1+000", "cbr": 2.0, "cvpd": 20000, "vdf": 5.0, "ldf": .75}]

    async def go():
        job = await start_corridor_job(sections, lc, .05, 20, 80, "other")
        for _ in range(2400):
            st = get_job_status(job)
            if st["status"] == "complete":
                return st
            await asyncio.sleep(0.05)
        raise AssertionError("corridor job did not finish")

    st = asyncio.run(go())
    cs = st["corridor_strategy"]
    assert [s["status"] for s in st["sections"]] == ["ok", "no_adequate_design"]
    assert cs["unified_adequate_all_sections"] is False
    assert "1+000" in cs["unified_failing_sections"] and "0+000" not in cs["unified_failing_sections"]


def test_rap_listed_under_the_recycled_tab():
    from mep_opt.advanced.materials_library import get_full_library, get_material_by_code
    tabs = {"bituminous", "granular", "cement_treated", "recycled", "stabilized"}
    lib = get_full_library()
    assert all(m["category"] in tabs for m in lib), {m["code"]: m["category"] for m in lib}
    assert get_material_by_code("RAP")["category"] == "recycled"
