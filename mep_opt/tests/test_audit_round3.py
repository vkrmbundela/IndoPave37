"""
Regression tests for the third (independent-verification) audit round
======================================================================
Defects an adversarial reviewer found in the round-2 fixes, each pinned here:

  * infeasibility diagnostic: no completion cap; a deadline-limited result is
    reported as a lower bound, never as an exact CDF with a governing mode;
  * the far wheel of a dual set at the edge of the input domain is accepted;
  * points shallower than 0.5 mm are reported at the depth evaluated (0);
  * API / browser-bridge parity: evaluation points, sub-millimetre layers,
    a geogrid on the subgrade row, NaN / Infinity, temperature range,
    advanced-module requests;
  * backend PDF reliability label for a requested R90 below 20 msa;
  * corridor tool can design sections of 50 msa or more.
"""

import json
import math
import time
from pathlib import Path

import pytest

import mep_opt.solver.burmister as B
from mep_opt.solver.burmister import analyze_pavement
from mep_opt.solver.irc37 import SubgradeInput, TrafficInput
from mep_opt.optimizer.problem import OptimizationProblem
from mep_opt.optimizer.smart_search import SmartPavementSearch

from mep_opt.tests.test_audit_fixes import (
    II4_SPECTRUM, T131, _browser_request, _load_browser_bridge,
)
from mep_opt.tests.test_audit_round2 import _api, _annex3, _pdf_text, _pdf_has

_ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# Infeasibility diagnostic
# --------------------------------------------------------------------------

def _many_skips_problem(recompute):
    """IRC II.4 spectrum (x3) on CBR 3: dozens of designs skip the spectrum check."""
    from mep_opt.solver.irc37 import AxleLoadGroup
    spectrum = [AxleLoadGroup(g.axle_type, g.load_kn, 3 * g.expected_repetitions) for g in II4_SPECTRUM]
    return OptimizationProblem(
        traffic=TrafficInput(**T131), subgrade=SubgradeInput(3), road_category="nh",
        layer_types=["BC", "DBM", "CRL", "CTB", "CTSB"],
        thickness_bounds={"BC": (30, 50), "DBM": (50, 90), "CRL": (100, 100),
                          "CTB": (100, 150), "CTSB": (100, 250)},
        ignore_minimum_thickness=True,
        ctb_axle_spectrum=spectrum, ctb_per_class_bridge_recompute=recompute,
    )


def test_diagnostic_is_exact_beyond_25_skipped_designs():
    """The old 25-completion cap reported 1.86 (rutting) where the exact answer is 3.68 (ctb)."""
    fast = SmartPavementSearch(_many_skips_problem(False))
    fast.run()
    skipped = sum(1 for d in fast._all_evaluated if (d.get("ctb_details") or {}).get("skipped"))
    assert skipped > 25
    full = SmartPavementSearch(_many_skips_problem(True))
    full.run()
    a, b = fast._closest_to_passing_diagnostic(), full._closest_to_passing_diagnostic()
    assert a["lower_bound"] is False
    assert a["governing_mode"] == b["governing_mode"] == "ctb"
    assert a["max_cdf"] == pytest.approx(b["max_cdf"], rel=1e-9)


def test_diagnostic_after_the_deadline_is_a_lower_bound():
    s = SmartPavementSearch(_many_skips_problem(False))
    s.run()
    s._deadline = time.monotonic() - 1.0          # budget already spent
    diag = s._closest_to_passing_diagnostic()
    assert diag["lower_bound"] is True and diag["governing_mode"] is None


# --------------------------------------------------------------------------
# Solver domain
# --------------------------------------------------------------------------

def test_far_wheel_of_a_dual_set_is_accepted():
    """r = -20000 is in the domain; its second wheel sits at |S - r| = 20310 mm."""
    st = [{"modulus": 3000, "poisson": .35, "thickness": 1}, {"modulus": 3000, "poisson": .35, "thickness": 100},
          {"modulus": 300, "poisson": .35, "thickness": 250}, {"modulus": 60, "poisson": .35, "thickness": 0}]
    load = {"load": 20000, "pressure": .56, "is_dual": True, "spacing": 310}
    a = analyze_pavement(st, load, [{"z": 1.0, "r": -20000.0}])[0]
    assert math.isfinite(a["eps_r"]) and math.isfinite(a["disp_z"])


def test_subsurface_snap_is_reported():
    """Points shallower than 0.5 mm are evaluated at the surface and say so."""
    st = [{"modulus": 3000, "poisson": .35, "thickness": 40}, {"modulus": 60, "poisson": .35, "thickness": 0}]
    load = {"load": 20000, "pressure": .56, "is_dual": False}
    shallow, surface, deeper = analyze_pavement(st, load, [{"z": 0.3, "r": 50}, {"z": 0.0, "r": 50},
                                                          {"z": 0.6, "r": 50}])
    assert shallow["z"] == 0.0 and shallow["eps_r"] == surface["eps_r"]
    assert deeper["z"] == 0.6
    body = {"layers": [{"E": 3000, "nu": .35, "h": 40}, {"E": 60, "nu": .35, "h": 0}],
            "wheel_type": "Single", "points": [{"z": 0.3, "r": 50}, {"z": 0.6, "r": 50}]}
    out = _api().post("/api/solve", json=body).json()["results"]
    assert [p["z"] for p in out] == [0.0, 0.6]


def test_refined_panel_cap_reaches_the_solve_path(monkeypatch):
    """The cap must be applied by _integrate itself, not only when called by hand."""
    seen = []
    orig = B.BurmisterSolver._refined_nodes

    def spy(self, r, z_decay, max_panels=None):
        m, w = orig(self, r, z_decay, max_panels=max_panels)
        seen.append((max_panels, m.size))
        return m, w

    monkeypatch.setattr(B.BurmisterSolver, "_refined_nodes", spy)
    s = B.BurmisterSolver([B.LayerProperty(3000, .35, 1.0), B.LayerProperty(3000, .35, 100),
                           B.LayerProperty(300, .35, 250), B.LayerProperty(60, .35, 0)],
                          B.LoadConfig(20000, 0.56, False))
    s.solve([B.EvalPoint(0.0, 1e4)])
    assert seen and all(mp is not None for mp, _ in seen)
    assert all(n <= 8 * (mp + 200) for mp, n in seen)


# --------------------------------------------------------------------------
# API / browser-bridge parity
# --------------------------------------------------------------------------

def _both(req):
    api = _api().post("/api/optimize", content=json.dumps(req), headers={"content-type": "application/json"})
    bridge = json.loads(_load_browser_bridge().run_optimize(json.dumps(req)))
    return api, bridge


@pytest.mark.parametrize("over", [
    {"points": [{"z": 10, "r": 20001}]},
    {"points": [{"z": -1, "r": 0}]},
    {"temperature": float("nan")},
    {"temperature": 45.0},
    {"cvpd": float("inf")},
    {"subgrade_cbr": float("nan")},
])
def test_api_and_bridge_reject_out_of_domain_scalars_and_points(over):
    api, bridge = _both(_browser_request(**over))
    assert api.status_code == 422, (over, api.status_code)
    assert bridge["status"] == "error", (over, bridge.get("status"))


def test_sub_millimetre_layer_rejected_by_optimize():
    layers = _browser_request()["layers"]
    layers[0] = dict(layers[0], fixed_thickness=0.5, min_thickness=0.5, max_thickness=0.5)
    api, bridge = _both(_browser_request(layers=layers))
    assert api.status_code == 422 and "thinner than 1 mm" in api.text
    assert bridge["status"] == "error" and "thinner than 1 mm" in bridge["message"]


def test_geogrid_on_subgrade_row_rejected():
    layers = _browser_request()["layers"]
    layers[-1] = dict(layers[-1], geogrid="PET60")
    api, bridge = _both(_browser_request(layers=layers))
    assert api.status_code == 422 and "Subgrade" in api.text
    assert bridge["status"] == "error" and "Subgrade" in bridge["message"]


def test_bridge_reports_missing_bounds_by_name():
    layers = _browser_request()["layers"]
    layers[1] = {k: v for k, v in layers[1].items() if k != "max_thickness"}
    out = json.loads(_load_browser_bridge().run_optimize(json.dumps(_browser_request(layers=layers))))
    assert out["status"] == "error" and "min_thickness and max_thickness" in out["message"]


def _load_advanced_bridge():
    import importlib.util
    path = _ROOT / "frontend" / "public" / "py" / "advanced_worker_bridge.py"
    spec = importlib.util.spec_from_file_location("advanced_worker_bridge_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _sensitivity(**over):
    req = {
        "layers": [{"modulus": 3000, "poisson": .35, "thickness": 100},
                   {"modulus": 300, "poisson": .35, "thickness": 250},
                   {"modulus": 60, "poisson": .35, "thickness": 0}],
        "load": {"load": 20000, "pressure": .56, "is_dual": True, "spacing": 310},
        "eval_points": [{"z": 99.9, "r": 0}, {"z": 99.9, "r": 155}, {"z": 350.1, "r": 0}, {"z": 350.1, "r": 155}],
        "cumulative_msa": 20.0, "mix_modulus": 3000, "reliability": 90,
    }
    req.update(over)
    return req


@pytest.mark.parametrize("over", [
    {"eval_points": [{"z": 99.9, "r": 25000}, {"z": 99.9, "r": 155}, {"z": 350.1, "r": 0}, {"z": 350.1, "r": 155}]},
    {"layers": [{"modulus": 3000, "poisson": .35, "thickness": 100, "friction_factor": 0.5},
                {"modulus": 300, "poisson": .35, "thickness": 250}, {"modulus": 60, "poisson": .35, "thickness": 0}]},
    {"layers": [{"modulus": 3000, "poisson": .35, "thickness": 0.5},
                {"modulus": 300, "poisson": .35, "thickness": 250}, {"modulus": 60, "poisson": .35, "thickness": 0}]},
    {"reliability": 95},
])
def test_advanced_bridge_rejects_what_the_router_rejects(over):
    req = _sensitivity(**over)
    assert _api().post("/api/v2/sensitivity", json=req).status_code == 422
    out = json.loads(_load_advanced_bridge().run_advanced(json.dumps({"op": "sensitivity", "request": req})))
    assert out["status"] == "error", out


def test_advanced_endpoints_reject_thin_layers_and_far_points_with_422():
    client = _api()
    body = {"layers": [{"modulus": 3000, "poisson": .35, "thickness": 0.5},
                       {"modulus": 60, "poisson": .35, "thickness": 0}],
            "load": {"load": 20000, "pressure": .56, "is_dual": True, "spacing": 310}}
    assert client.post("/api/v2/strain-field", json=body).status_code == 422
    assert client.post("/api/v2/sensitivity", json=_sensitivity(
        eval_points=[{"z": 1, "r": 2.5e4}] * 4)).status_code == 422
    solve = {"layers": [{"E": 3000, "nu": .35, "h": 100}, {"E": 60, "nu": .35, "h": 0}],
             "wheel_type": "Single", "points": [{"z": -1, "r": 0}]}
    assert client.post("/api/solve", json=solve).status_code == 422


# --------------------------------------------------------------------------
# Reports and corridor
# --------------------------------------------------------------------------

def test_backend_pdf_requested_r90_below_20msa_is_not_labelled_as_traffic():
    out = SmartPavementSearch(OptimizationProblem(
        traffic=TrafficInput(0, 150, .05, 15, .75, 2.5), subgrade=SubgradeInput(8), road_category="other",
        layer_types=["BC", "DBM", "WMM", "GSB"],
        thickness_bounds={"BC": (40, 40), "DBM": (60, 60), "WMM": (250, 250), "GSB": (200, 200)},
    ))._evaluate([40, 60, 250, 200])
    assert out["msa"] < 20 and out["reliability"] == "R90"
    _, txt = _pdf_text(out)
    assert _pdf_has(txt, "90% (as requested)") and not _pdf_has(txt, "90% (≥ 20 MSA)")


def test_backend_pdf_compressive_case_has_no_fatigue_criterion_block():
    """The checklist always mentions Annex III; the compliance section must too, without Eq. 3.3/3.4."""
    out = _annex3(["BC", "CTB", "CTSB"], [40, 160, 200], has_sami=True)
    _, txt = _pdf_text(out)
    assert _pdf_has(txt, "fatigue performance need not be checked")
    assert not _pdf_has(txt, "Eq. 3.3/3.4")
    ok = _annex3(["BC", "CRL", "CTB", "CTSB"], [40, 100, 100, 200])
    _, txt_ok = _pdf_text(ok)
    assert _pdf_has(txt_ok, "Eq. 3.3/3.4")


def test_corridor_designs_a_section_above_50_msa():
    """BC was fixed at 40 mm while the >= 50 msa practice minimum is 50 mm."""
    from fastapi.testclient import TestClient
    from mep_opt.web import main as web_main
    csv = "Chainage,Subgrade_CBR,CVPD,VDF,LDF\n0+000,8,3000,4.5,0.75\n"
    with TestClient(web_main.app) as client:      # keeps the loop running the job
        r = client.post("/api/v2/corridor?road_category=nh", files={"file": ("c.csv", csv, "text/csv")})
        assert r.status_code == 200, r.text
        job = r.json()["job_id"]
        for _ in range(1200):
            st = client.get(f"/api/v2/corridor/{job}/status").json()
            if st.get("status") == "complete":
                break
            time.sleep(0.1)
    sec = st["sections"][0]
    assert sec["msa"] > 50
    assert sec["status"] == "ok", sec
    assert sec["thicknesses"][0] == 50
