"""
IRC:37-2018 §10 long-life pavements and §8.3 SAMI crack relief
================================================================
* Long-life (perpetual) pavement, §10 / §4.3.1 / Annex II.6: the bituminous
  tensile strain must stay within the 80 µε endurance limit (35 °C) and the
  subgrade vertical strain within 200 µε. The three Annex II.6 sections are
  reproduced with the strains IRC prints.
* SAMI (§8.3): a stress-absorbing membrane over the CTB is a crack-relief
  treatment that is not a structural layer, so the bituminous bundle sits
  directly on the CTB in the analysis. The API and the browser bridge accept
  `has_sami`; without it a bituminous layer on a CTB is rejected.
"""

import json

import pytest

from mep_opt.solver.irc37 import SubgradeInput, TrafficInput, ReliabilityLevel
from mep_opt.optimizer.problem import OptimizationProblem
from mep_opt.optimizer.smart_search import (
    SmartPavementSearch, LONG_LIFE_EPS_T, LONG_LIFE_EPS_V,
)
from mep_opt.tests.test_audit_fixes import _browser_request, _load_browser_bridge
from mep_opt.tests.test_audit_round2 import _api

# Design traffic well above 300 msa (the Annex II.6 example gives none).
_T_LONG = dict(initial_aadt=0, commercial_vehicles_per_day=20000, traffic_growth_rate=0.05,
               design_life_years=20, lane_distribution_factor=0.75, vehicle_damage_factor=5.0)
_VG40 = {"E": 3000, "nu": 0.35}

# Effective CBR 7 %. IRC's example uses MRS = 62 MPa; Eq. 6.2 gives 61.15 MPa
# at CBR 7 and 62.0 MPa at CBR 7.15.
_CBR_IRC_62 = (62.0 / 17.6) ** (1 / 0.64)


def _evaluate(types, thicknesses, props, cbr=_CBR_IRC_62, long_life=True, traffic=None, **kw):
    problem = OptimizationProblem(
        traffic=TrafficInput(**(traffic or _T_LONG)), subgrade=SubgradeInput(cbr=cbr),
        reliability=ReliabilityLevel.R90, road_category="expressway",
        layer_types=types, layer_props=props,
        thickness_bounds={t: (h, h) for t, h in zip(types, thicknesses)},
        ignore_minimum_thickness=True, long_life=long_life, **kw,
    )
    return SmartPavementSearch(problem)._evaluate(list(thicknesses))


def test_subgrade_modulus_matches_irc_example():
    assert SubgradeInput(cbr=_CBR_IRC_62).modulus == pytest.approx(62.0, abs=1e-6)


@pytest.mark.parametrize("types, h, props, eps_t_irc, eps_v_irc", [
    # Solution 1: 310 mm VG40 bituminous, 250 WMM, 200 GSB -> 80 / 153 µε
    (["BC", "DBM", "WMM", "GSB"], [40, 270, 250, 200], {"BC": _VG40, "DBM": _VG40}, 80, 153),
    # Solution 2: 250 mm VG40, 150 WMM (350 MPa over CTSB), 300 CTSB -> 80 / 157 µε
    (["BC", "DBM", "WMM", "CTSB"], [40, 210, 150, 300],
     {"BC": _VG40, "DBM": _VG40, "CTSB": {"E": 600, "nu": 0.25}}, 80, 157),
    # Solution 3: 190 mm high-modulus mix (5500 MPa) -> 78 / 172 µε
    (["BC", "DBM", "WMM", "CTSB"], [40, 150, 150, 300],
     {"BC": {"E": 5500, "nu": 0.35}, "DBM": {"E": 5500, "nu": 0.35},
      "CTSB": {"E": 600, "nu": 0.25}}, 78, 172),
])
def test_annex_ii6_long_life_sections(types, h, props, eps_t_irc, eps_v_irc):
    d = _evaluate(types, h, props)
    assert d["eps_t"] * 1e6 == pytest.approx(eps_t_irc, abs=1.5)
    assert d["eps_v"] * 1e6 == pytest.approx(eps_v_irc, rel=0.02)
    ll = d["long_life"]
    assert ll["eps_t_limit"] == LONG_LIFE_EPS_T == 80e-6
    assert ll["eps_v_limit"] == LONG_LIFE_EPS_V == 200e-6
    assert ll["ratio_t"] == pytest.approx(d["eps_t"] / 80e-6)
    assert ll["ratio_v"] == pytest.approx(d["eps_v"] / 200e-6)
    # IRC accepts all three ("80 µε = 80 µε" for Solutions 1 and 2).
    assert ll["ok"] and d["overall_adequate"], (d["eps_t"], d["eps_v"])
    assert ll["governing"] == "fatigue"


def test_irc_rounded_subgrade_modulus_decides_solution_1():
    """At CBR 7 exactly (MRS 61.15 MPa) Solution 1 is 80.01 µε: just over the limit."""
    d = _evaluate(["BC", "DBM", "WMM", "GSB"], [40, 270, 250, 200],
                  {"BC": _VG40, "DBM": _VG40}, cbr=7.0)
    assert 80.0 < d["eps_t"] * 1e6 < 80.1
    assert not d["long_life"]["ok"] and not d["overall_adequate"]


def test_conventional_150msa_section_fails_long_life_but_not_irc_cdfs():
    """Annex II.6 comparison: 200 mm VG40 / 250 WMM / 250 GSB at 150 msa,
    136 µε < 145 µε and 224 µε < 292 µε allowable."""
    t150 = dict(_T_LONG, commercial_vehicles_per_day=20000 * 150 / 905.0)
    d = _evaluate(["BC", "DBM", "WMM", "GSB"], [40, 160, 250, 250],
                  {"BC": _VG40, "DBM": _VG40}, traffic=t150)
    assert d["msa"] == pytest.approx(150, rel=0.01)
    assert d["CDF_fatigue"] < 1 and d["CDF_rutting"] < 1
    assert d["eps_t"] * 1e6 == pytest.approx(136, abs=2)
    assert d["eps_v"] * 1e6 == pytest.approx(224, rel=0.02)
    assert d["long_life"]["ratio_t"] > 1.6 and not d["long_life"]["ok"]
    assert d["governing_mode"] == "long_life"
    off = _evaluate(["BC", "DBM", "WMM", "GSB"], [40, 160, 250, 250],
                    {"BC": _VG40, "DBM": _VG40}, long_life=False, traffic=t150)
    assert off["long_life"] is None and off["governing_mode"] != "long_life"
    assert off["overall_adequate"]


def test_long_life_compressive_fatigue_is_not_checked():
    """Annex III: an all-compressive bituminous strain is not a fatigue check."""
    # Thin surfacing on a very stiff CTB: every horizontal strain compressive.
    d = _evaluate(["BC", "CTB"], [40, 300], {"BC": {"E": 3000, "nu": 0.35},
                                            "CTB": {"E": 5000, "nu": 0.25}},
                  has_sami=True)
    assert d["fatigue_compressive"]
    assert d["long_life"]["ratio_t"] == 0.0
    assert d["long_life"]["ratio_v"] == pytest.approx(d["eps_v"] / 200e-6)


def test_long_life_optimizer_returns_only_endurance_designs():
    problem = OptimizationProblem(
        traffic=TrafficInput(**_T_LONG), subgrade=SubgradeInput(cbr=_CBR_IRC_62),
        reliability=ReliabilityLevel.R90, road_category="expressway",
        layer_types=["BC", "DBM", "WMM", "GSB"],
        layer_props={"BC": _VG40, "DBM": _VG40},
        # BC 50 mm: the traffic-tier practice minimum above 50 msa.
        thickness_bounds={"BC": (50, 50), "DBM": (200, 300), "WMM": (250, 250), "GSB": (200, 200)},
        long_life=True,
    )
    search = SmartPavementSearch(problem)
    result = search.run()
    perf = [s.performance for s in result.pareto_front if s.performance.get("overall_adequate")]
    assert perf, result.warnings
    for p in perf:
        assert p["eps_t"] <= 80e-6 and p["eps_v"] <= 200e-6
    # The thinnest long-life bituminous bundle is close to IRC's 310 mm
    # (Solution 1), and the next thinner DBM fails the endurance limit.
    dbm = min(p["thicknesses"][1] for p in perf)
    assert 300 <= 50 + dbm <= 320
    thinner = search._evaluate([50, dbm - 5, 250, 200])
    assert not thinner["long_life"]["ok"] and thinner["eps_t"] > 80e-6
    assert any("§10" in w for w in result.warnings)


def test_long_life_recommended_warning_at_300msa():
    problem = OptimizationProblem(
        traffic=TrafficInput(**_T_LONG), subgrade=SubgradeInput(cbr=8),
        road_category="nh", layer_types=["BC", "DBM", "WMM", "GSB"],
        layer_props={"BC": _VG40, "DBM": _VG40},
        thickness_bounds={"BC": (40, 40), "DBM": (150, 150), "WMM": (250, 250), "GSB": (200, 200)},
    )
    warnings = SmartPavementSearch(problem)._build_warnings()
    assert any("§4.3.1" in w and "long-life" in w and "30 years" in w for w in warnings)


# --------------------------------------------------------------------------
# SAMI crack relief (§8.3)
# --------------------------------------------------------------------------

def _sami_layers():
    return [
        {"layer_type": "BC", "E": 3000, "nu": .35, "is_fixed": True, "fixed_thickness": 40,
         "min_thickness": 40, "max_thickness": 40},
        {"layer_type": "DBM", "E": 3000, "nu": .35, "is_fixed": True, "fixed_thickness": 90,
         "min_thickness": 90, "max_thickness": 90},
        {"layer_type": "CTB", "E": 5000, "nu": .25, "is_fixed": False, "fixed_thickness": 0,
         "min_thickness": 150, "max_thickness": 250},
        {"layer_type": "CTSB", "E": 600, "nu": .25, "is_fixed": True, "fixed_thickness": 250,
         "min_thickness": 250, "max_thickness": 250},
        {"layer_type": "Subgrade", "E": 66, "nu": .35, "is_fixed": True, "fixed_thickness": 0,
         "min_thickness": 0, "max_thickness": 0},
    ]


def _both(req):
    api = _api().post("/api/optimize", json=req)
    bridge = json.loads(_load_browser_bridge().run_optimize(json.dumps(req)))
    return api, bridge


def test_bituminous_on_ctb_needs_sami_flag():
    api, bridge = _both(_browser_request(layers=_sami_layers()))
    assert api.status_code in (400, 422) and "crack relief" in api.text
    assert bridge["status"] == "error" and "crack relief" in bridge["message"]


def test_sami_section_is_designed_by_api_and_bridge_alike():
    api, bridge = _both(_browser_request(layers=_sami_layers(), has_sami=True))
    assert api.status_code == 200, api.text
    a = api.json()["adequate_designs"]
    b = bridge["adequate_designs"]
    assert a and [d["total_thickness"] for d in a] == [d["total_thickness"] for d in b]
    # SAMI is not structural: the analysed stack is BC, DBM, CTB, CTSB, subgrade.
    names = [l["name"] for l in a[0]["details"]["layers"]]
    assert names[:4] == ["BC", "DBM", "CTB", "CTSB"]


def test_long_life_flag_reaches_api_and_bridge():
    api, bridge = _both(_browser_request(long_life=True))
    assert api.status_code == 200, api.text
    for designs in (api.json()["adequate_designs"], bridge["adequate_designs"]):
        for d in designs:
            assert d["details"]["long_life"]["ok"] is True


@pytest.mark.parametrize("over", [{"long_life": "yes"}, {"has_sami": 1}])
def test_bridge_rejects_non_boolean_flags(over):
    bridge = json.loads(_load_browser_bridge().run_optimize(json.dumps(_browser_request(**over))))
    assert bridge["status"] == "error" and "true or false" in bridge["message"]


def test_backend_pdf_prints_the_long_life_check():
    from mep_opt.tests.test_audit_round2 import _pdf_text, _pdf_has
    d = _evaluate(["BC", "DBM", "WMM", "CTSB"], [40, 210, 150, 300],
                  {"BC": _VG40, "DBM": _VG40, "CTSB": {"E": 600, "nu": 0.25}})
    _, txt = _pdf_text(d)
    assert _pdf_has(txt, "Long-Life Pavement (Endurance Limits)")
    assert _pdf_has(txt, f"{d['long_life']['ratio_t']:.3f}")
    plain = _evaluate(["BC", "DBM", "WMM", "CTSB"], [40, 210, 150, 300],
                      {"BC": _VG40, "DBM": _VG40, "CTSB": {"E": 600, "nu": 0.25}}, long_life=False)
    assert not _pdf_has(_pdf_text(plain)[1], "Long-Life Pavement")
