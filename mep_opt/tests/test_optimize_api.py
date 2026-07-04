from fastapi.testclient import TestClient

from mep_opt.optimizer.problem import OptimizationResult, ParetoSolution
from mep_opt.web import main as web_main


class DummyInfeasibleSearch:
    """Stub optimizer that returns a fallback non-adequate design."""

    def __init__(self, problem):
        self.problem = problem

    def run(self, *args, **kwargs):
        # Accept timeout/deadline kwargs the real optimizer now exposes,
        # so the stub stays drop-in across signature evolution.
        perf = {
            "overall_adequate": False,
            "CDF_fatigue": 12345.0,
            "CDF_rutting": 67890.0,
            "governing_mode": "fatigue",
            "msa": 100.0,
            "layers": [
                {"id": 1, "name": "BC", "thickness": 30.0, "modulus": 3000.0},
                {"id": 2, "name": "WMM", "thickness": 150.0, "modulus": 500.0},
                {"id": 3, "name": "Subgrade", "thickness": 0.0, "modulus": 80.0},
            ],
        }

        prelim = ParetoSolution(
            optimal_thicknesses=[30.0, 150.0],
            optimal_materials={},
            cost=123456.0,
            co2=987.0,
            performance=perf,
        )

        return OptimizationResult(
            optimal_thicknesses=prelim.optimal_thicknesses,
            optimal_materials={},
            layer_types=["BC", "WMM"],
            cost=prelim.cost,
            co2=prelim.co2,
            is_feasible=False,
            performance=perf,
            pareto_front=[prelim],
            warnings=["stub warning"],
        )


def test_optimize_endpoint_hides_infeasible_fallback_designs(monkeypatch):
    monkeypatch.setattr(web_main, "SmartPavementSearch", DummyInfeasibleSearch)
    client = TestClient(web_main.app)

    payload = {
        "cvpd": 3000,
        "growth_rate": 0.05,
        "design_life": 20,
        "vdf": 2.5,
        "lane_factor": 0.75,
        "subgrade_cbr": 8.0,
        "reliability": "90%",
        "temperature": 35.0,
        "layers": [
            {
                "layer_type": "BC",
                "min_thickness": 30,
                "max_thickness": 50,
                "is_fixed": False,
                "fixed_thickness": 0,
                "E": 3000,
                "nu": 0.35,
            },
            {
                "layer_type": "WMM",
                "min_thickness": 150,
                "max_thickness": 250,
                "is_fixed": False,
                "fixed_thickness": 0,
                "E": 500,
                "nu": 0.35,
            },
        ],
    }

    response = client.post("/api/optimize", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["is_adequate"] is False
    assert body["adequate_designs"] == []
    assert body["warnings"] == ["stub warning"]


# --- July-2026 audit fix: E is optional ("auto" = IRC:37-2018 Eq. 7.1) ---

def test_layer_constraint_accepts_null_E_for_auto_mode():
    """E: null must validate (auto mode); E <= 0 must still be rejected."""
    import pytest
    from mep_opt.web.main import LayerConstraint

    auto = LayerConstraint(
        layer_type="WMM", min_thickness=150, max_thickness=300,
        E=None, nu=0.35,
    )
    assert auto.E is None

    pinned = LayerConstraint(
        layer_type="WMM", min_thickness=150, max_thickness=300,
        E=300.0, nu=0.35,
    )
    assert pinned.E == 300.0

    with pytest.raises(Exception):
        LayerConstraint(
            layer_type="WMM", min_thickness=150, max_thickness=300,
            E=-5.0, nu=0.35,
        )
