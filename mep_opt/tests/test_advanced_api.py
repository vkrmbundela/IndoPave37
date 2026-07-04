"""
Tests for Advanced Engineering Endpoints (/api/v2/*)
=====================================================
Covers all 6 modules: Reserve, Materials, Sensitivity,
Strain-Field, Corridor, and Monte Carlo.

Bridge-dependent endpoints are tested with monkeypatched
solver returns so the test suite runs without the Fortran .EXE.
"""

import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from mep_opt.web import main as web_main
from mep_opt.advanced import sensitivity as sens_mod
from mep_opt.advanced import montecarlo as mc_mod
from mep_opt.advanced import strain_field as sf_mod
from mep_opt.advanced import corridor as corr_mod


client = TestClient(web_main.app)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def _fake_bridge_result(eps_t=-150e-6, eps_z=-300e-6):
    """Return a realistic-looking bridge result dict."""
    return {
        "sigma_z": -100.0,
        "sigma_r": 50.0,
        "sigma_t": 50.0,
        "tau_rz": 0.0,
        "disp_z": -0.5,
        "disp_r": 0.0,
        "eps_z": eps_z,
        "eps_r": 80e-6,
        "eps_t": eps_t,
    }


def _fake_bridge(stack, load, points):
    """Mock bridge that returns one result per eval point."""
    return [_fake_bridge_result() for _ in points]


SAMPLE_LAYERS = [
    {"modulus": 1250, "poisson": 0.35, "thickness": 50, "name": "BC"},
    {"modulus": 1250, "poisson": 0.35, "thickness": 100, "name": "DBM"},
    {"modulus": 300, "poisson": 0.35, "thickness": 200, "name": "WMM"},
    {"modulus": 200, "poisson": 0.35, "thickness": 200, "name": "GSB"},
    {"modulus": 80, "poisson": 0.40, "thickness": 0, "name": "Subgrade"},
]

SAMPLE_LOAD = {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310}

SAMPLE_POINTS = [
    {"z": 149.9, "r": 0},
    {"z": 549.9, "r": 0},
]


# ═══════════════════════════════════════════════════════════════════════════
# Module B: Structural Reserve Meter
# ═══════════════════════════════════════════════════════════════════════════

class TestReserveEndpoint:
    """POST /api/v2/reserve — pure math, no bridge needed."""

    def test_reserve_basic(self):
        """Typical design: eps_t and eps_v produce finite capacity."""
        payload = {
            "eps_t": 150e-6,
            "eps_v": 300e-6,
            "mix_modulus": 1250,
            "design_msa": 50.0,
            "reliability": 90,
        }
        resp = client.post("/api/v2/reserve", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "intercept_msa" in body
        assert "reserve_percent" in body
        assert "governing_mode" in body
        assert body["governing_mode"] in ("fatigue", "rutting")
        assert body["Nf_msa"] > 0
        assert body["NR_msa"] > 0

    def test_reserve_high_strain_low_capacity(self):
        """High strain values should give low intercept MSA."""
        payload = {
            "eps_t": 500e-6,
            "eps_v": 800e-6,
            "mix_modulus": 1250,
            "design_msa": 100.0,
            "reliability": 90,
        }
        resp = client.post("/api/v2/reserve", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        # High strains → capacity likely below design → negative reserve
        assert body["reserve_percent"] < 0

    def test_reserve_low_strain_high_capacity(self):
        """Low strain values should give high intercept MSA."""
        payload = {
            "eps_t": 50e-6,
            "eps_v": 100e-6,
            "mix_modulus": 3000,
            "design_msa": 10.0,
            "reliability": 80,
        }
        resp = client.post("/api/v2/reserve", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["reserve_percent"] > 0
        assert body["intercept_msa"] > body["design_msa"]

    def test_reserve_different_reliability_levels(self):
        """Higher reliability should reduce allowable repetitions.

        IRC 37:2018 only defines R80 (low-volume) and R90 (high-volume),
        so the advanced API rejects anything else. R90 is the more
        conservative of the two and must yield a lower intercept MSA.
        """
        base = {
            "eps_t": 150e-6,
            "eps_v": 300e-6,
            "mix_modulus": 1250,
            "design_msa": 50.0,
        }
        resp_80 = client.post("/api/v2/reserve", json={**base, "reliability": 80}).json()
        resp_90 = client.post("/api/v2/reserve", json={**base, "reliability": 90}).json()
        # R90 is more conservative → lower intercept
        assert resp_80["intercept_msa"] >= resp_90["intercept_msa"]

    def test_reserve_rejects_non_irc_reliability(self):
        """Non-IRC reliability (R95/R98/R99) must be rejected at the API."""
        payload = {
            "eps_t": 150e-6,
            "eps_v": 300e-6,
            "mix_modulus": 1250,
            "design_msa": 50.0,
            "reliability": 95,
        }
        resp = client.post("/api/v2/reserve", json=payload)
        assert resp.status_code == 422  # Pydantic validation error

    def test_reserve_custom_mix_params(self):
        """Custom air_voids and bitumen_volume should work."""
        payload = {
            "eps_t": 150e-6,
            "eps_v": 300e-6,
            "mix_modulus": 1250,
            "design_msa": 50.0,
            "reliability": 90,
            "air_voids": 3.5,
            "bitumen_volume": 12.0,
        }
        resp = client.post("/api/v2/reserve", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_reserve_auto_escalation(self):
        """Design traffic >= 20.0 msa should auto-escalate R80 -> R90, yielding lower capacity."""
        payload_base = {
            "eps_t": 150e-6,
            "eps_v": 300e-6,
            "mix_modulus": 1250,
            "reliability": 80,
        }
        resp_low = client.post("/api/v2/reserve", json={**payload_base, "design_msa": 10.0}).json()
        resp_high = client.post("/api/v2/reserve", json={**payload_base, "design_msa": 20.0}).json()
        
        # Under R80, low/high design_msa would have identical intercept_msa.
        # But because 20.0 msa escalates to R90 (more conservative), its intercept_msa is lower.
        assert resp_high["intercept_msa"] < resp_low["intercept_msa"]


# ═══════════════════════════════════════════════════════════════════════════
# Module C: Material Library
# ═══════════════════════════════════════════════════════════════════════════

class TestMaterialsEndpoint:
    """GET /api/v2/materials — static lookup, no bridge needed."""

    def test_list_all_materials(self):
        resp = client.get("/api/v2/materials")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        materials = body["materials"]
        assert isinstance(materials, list)
        assert len(materials) >= 10  # base (10+) + advanced (7)

        # Verify required fields on each material
        for mat in materials:
            assert "code" in mat
            assert "name" in mat
            assert "E_default" in mat
            assert "nu" in mat
            assert "category" in mat
            assert mat["E_default"] > 0

    def test_list_includes_base_and_advanced(self):
        resp = client.get("/api/v2/materials")
        materials = resp.json()["materials"]
        sources = {m["source"] for m in materials}
        assert "base" in sources
        assert "advanced" in sources

    def test_get_base_material_by_code(self):
        resp = client.get("/api/v2/materials/BC")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        mat = body["material"]
        assert mat["code"] == "BC"
        assert mat["category"] == "bituminous"
        # BC default modulus is VG30 @ 35°C = 2000 MPa per IRC 37:2018 Table 9.2.
        # The earlier 1250 MPa value came from a pre-2018 table.
        assert mat["E_default"] == 2000.0
        assert mat["source"] == "base"

    def test_get_advanced_material_by_code(self):
        resp = client.get("/api/v2/materials/PMB40")
        assert resp.status_code == 200
        mat = resp.json()["material"]
        assert mat["code"] == "PMB40"
        # Modified binders share ONE IRC:37-2018 Table 9.2 row — 1600 MPa at
        # the 35 °C design temperature. The earlier 3000 MPa was a vendor-style
        # value carrying an IRC citation (July-2026 audit fix).
        assert mat["E_default"] == 1600.0
        assert mat["source"] == "advanced"
        assert "temperature_table" in mat
        # JSON object keys arrive as strings.
        assert mat["temperature_table"].get("35", mat["temperature_table"].get(35)) == 1600

    def test_get_material_case_insensitive(self):
        resp = client.get("/api/v2/materials/gsb")
        assert resp.status_code == 200
        assert resp.json()["material"]["code"] == "GSB"

    def test_get_material_not_found(self):
        resp = client.get("/api/v2/materials/NONEXISTENT")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_material_has_cost_data(self):
        resp = client.get("/api/v2/materials/DBM")
        mat = resp.json()["material"]
        assert mat["cost_per_cum"] > 0
        assert mat["co2_per_cum"] > 0


# ═══════════════════════════════════════════════════════════════════════════
# Module A: Sensitivity Heatmaps
# ═══════════════════════════════════════════════════════════════════════════

class TestSensitivityEndpoint:
    """POST /api/v2/sensitivity — requires bridge mock."""

    @patch.object(sens_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_sensitivity_basic(self, mock_bridge):
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "eval_points": SAMPLE_POINTS,
            "cumulative_msa": 50.0,
            "mix_modulus": 1250,
            "reliability": 90,
        }
        resp = client.post("/api/v2/sensitivity", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "layers" in body
        # Should have results for 4 non-subgrade layers
        assert len(body["layers"]) == 4

    @patch.object(sens_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_sensitivity_delta_structure(self, mock_bridge):
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "eval_points": SAMPLE_POINTS,
            "cumulative_msa": 50.0,
            "mix_modulus": 1250,
        }
        resp = client.post("/api/v2/sensitivity", json=payload)
        body = resp.json()
        layer_result = body["layers"][0]
        assert "layer_index" in layer_result
        assert "base_thickness" in layer_result
        assert "deltas" in layer_result

        # Each delta entry should have CDF values
        for delta in layer_result["deltas"]:
            assert "delta_mm" in delta
            assert "thickness_mm" in delta
            assert "CDF_f" in delta
            assert "CDF_r" in delta

    @patch.object(sens_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_sensitivity_skips_subgrade(self, mock_bridge):
        """Subgrade (last layer) should not be perturbed."""
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "eval_points": SAMPLE_POINTS,
            "cumulative_msa": 50.0,
            "mix_modulus": 1250,
        }
        resp = client.post("/api/v2/sensitivity", json=payload)
        layer_indices = [l["layer_index"] for l in resp.json()["layers"]]
        # Should not include index 4 (subgrade)
        assert 4 not in layer_indices

    @patch.object(sens_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_sensitivity_auto_escalation(self, mock_bridge):
        """Traffic >= 20.0 msa should auto-escalate R80 -> R90, yielding same CDF as R90."""
        payload_base = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "eval_points": SAMPLE_POINTS,
            "mix_modulus": 1250,
        }
        resp_r80 = client.post("/api/v2/sensitivity", json={**payload_base, "cumulative_msa": 20.0, "reliability": 80}).json()
        resp_r90 = client.post("/api/v2/sensitivity", json={**payload_base, "cumulative_msa": 20.0, "reliability": 90}).json()
        
        # With auto-escalation, both resolve to R90 and yield identical CDFs.
        assert resp_r80["layers"][0]["deltas"][0]["CDF_f"] == resp_r90["layers"][0]["deltas"][0]["CDF_f"]


# ═══════════════════════════════════════════════════════════════════════════
# Module D: 3D Strain Field
# ═══════════════════════════════════════════════════════════════════════════

class TestStrainFieldEndpoint:
    """POST /api/v2/strain-field — requires bridge mock."""

    @patch.object(sf_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_strain_field_basic(self, mock_bridge):
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "r_steps": 4,
            "z_steps": 5,
            "r_max": 200.0,
        }
        resp = client.post("/api/v2/strain-field", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "r_values" in body
        assert "z_values" in body
        assert "eps_z_grid" in body
        assert "eps_t_grid" in body
        assert "disp_z_grid" in body
        assert "layer_interfaces" in body
        assert "layer_names" in body

    @patch.object(sf_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_strain_field_grid_dimensions(self, mock_bridge):
        r_steps, z_steps = 6, 8
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "r_steps": r_steps,
            "z_steps": z_steps,
            "r_max": 300.0,
        }
        resp = client.post("/api/v2/strain-field", json=payload)
        body = resp.json()

        assert len(body["r_values"]) == r_steps
        assert len(body["z_values"]) == z_steps
        # Grid should be [z_steps][r_steps]
        assert len(body["eps_z_grid"]) == z_steps
        assert len(body["eps_z_grid"][0]) == r_steps

    @patch.object(sf_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_strain_field_layer_interfaces(self, mock_bridge):
        """Layer interfaces should match cumulative thicknesses."""
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "r_steps": 3,
            "z_steps": 3,
        }
        resp = client.post("/api/v2/strain-field", json=payload)
        body = resp.json()
        # BC=50, DBM=100, WMM=200, GSB=200 → interfaces at 50, 150, 350, 550
        interfaces = body["layer_interfaces"]
        assert interfaces == [50.0, 150.0, 350.0, 550.0]

    @patch.object(sf_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_strain_field_defaults(self, mock_bridge):
        """Default r_steps=12, z_steps=25, r_max=500."""
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
        }
        resp = client.post("/api/v2/strain-field", json=payload)
        body = resp.json()
        assert len(body["r_values"]) == 12
        assert len(body["z_values"]) == 25


# ═══════════════════════════════════════════════════════════════════════════
# Module E: Corridor Optimization
# ═══════════════════════════════════════════════════════════════════════════

class TestCorridorEndpoint:
    """POST /api/v2/corridor + GET /api/v2/corridor/{job_id}/status."""

    def _make_csv(self, rows):
        """Build a CSV string from list of dicts."""
        header = "Chainage,Subgrade_CBR,CVPD,VDF,LDF\n"
        lines = [f"{r['ch']},{r['cbr']},{r['cvpd']},{r['vdf']},{r['ldf']}" for r in rows]
        return header + "\n".join(lines)

    def test_corridor_upload_parses_csv(self):
        """Upload CSV and get job_id back (actual optimization is mocked)."""
        csv_content = self._make_csv([
            {"ch": "0+000-1+000", "cbr": 8.0, "cvpd": 3000, "vdf": 2.5, "ldf": 0.75},
            {"ch": "1+000-2+000", "cbr": 6.0, "cvpd": 3000, "vdf": 2.5, "ldf": 0.75},
        ])
        files = {"file": ("corridor.csv", csv_content.encode(), "text/csv")}
        resp = client.post("/api/v2/corridor", files=files)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "job_id" in body
        assert body["total_sections"] == 2

    def test_corridor_status_not_found(self):
        resp = client.get("/api/v2/corridor/nonexistent/status")
        assert resp.status_code == 404

    def test_corridor_empty_csv_returns_400(self):
        csv_content = "Chainage,Subgrade_CBR,CVPD,VDF,LDF\n"
        files = {"file": ("empty.csv", csv_content.encode(), "text/csv")}
        resp = client.post("/api/v2/corridor", files=files)
        assert resp.status_code == 400

    def test_corridor_csv_parsing(self):
        """Test the CSV parser function directly."""
        from mep_opt.advanced.corridor import parse_corridor_csv

        csv_text = "Chainage,Subgrade_CBR,CVPD,VDF,LDF\n0+000,8.0,3000,2.5,0.75\n1+000,6.0,2000,3.0,0.80"
        sections = parse_corridor_csv(csv_text)
        assert len(sections) == 2
        assert sections[0]["chainage"] == "0+000"
        assert sections[0]["cbr"] == 8.0
        assert sections[0]["cvpd"] == 3000.0
        assert sections[1]["ldf"] == 0.80


# ═══════════════════════════════════════════════════════════════════════════
# Module F: Monte Carlo Risk Analysis
# ═══════════════════════════════════════════════════════════════════════════

class TestMonteCarloEndpoint:
    """POST /api/v2/montecarlo — requires bridge mock."""

    @patch.object(mc_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_montecarlo_basic(self, mock_bridge):
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "eval_points": SAMPLE_POINTS,
            "cumulative_msa": 50.0,
            "mix_modulus": 1250,
            "n_simulations": 10,
            "reliability": 90,
        }
        resp = client.post("/api/v2/montecarlo", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["n_simulations"] == 10
        assert "n_adequate" in body
        assert "probability_adequate" in body
        assert 0 <= body["probability_adequate"] <= 100

    @patch.object(mc_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_montecarlo_statistics(self, mock_bridge):
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "eval_points": SAMPLE_POINTS,
            "cumulative_msa": 50.0,
            "mix_modulus": 1250,
            "n_simulations": 20,
        }
        resp = client.post("/api/v2/montecarlo", json=payload)
        body = resp.json()

        # CDF statistics should be present
        assert "cdf_f_stats" in body
        assert "cdf_r_stats" in body
        stats = body["cdf_f_stats"]
        assert "mean" in stats
        assert "std" in stats
        assert "p5" in stats
        assert "p95" in stats
        assert stats["p5"] <= stats["mean"] <= stats["p95"]

    @patch.object(mc_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_montecarlo_histogram(self, mock_bridge):
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "eval_points": SAMPLE_POINTS,
            "cumulative_msa": 50.0,
            "mix_modulus": 1250,
            "n_simulations": 30,
        }
        resp = client.post("/api/v2/montecarlo", json=payload)
        body = resp.json()
        assert "histogram" in body
        hist = body["histogram"]
        assert len(hist) == 20  # 20 bins
        # Total count across bins should equal n_simulations (or close)
        total = sum(b["count"] for b in hist)
        assert total <= 30

        for b in hist:
            assert "bin_start" in b
            assert "bin_end" in b
            assert "count" in b
            assert b["bin_start"] < b["bin_end"]

    @patch.object(mc_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_montecarlo_custom_sigmas(self, mock_bridge):
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "eval_points": SAMPLE_POINTS,
            "cumulative_msa": 50.0,
            "mix_modulus": 1250,
            "n_simulations": 10,
            "sigmas": [2.0, 3.0, 5.0, 5.0, 0.0],
        }
        resp = client.post("/api/v2/montecarlo", json=payload)
        body = resp.json()
        assert body["status"] == "ok"
        # sigmas_used excludes subgrade
        assert body["sigmas_used"] == [2.0, 3.0, 5.0, 5.0]

    @patch.object(mc_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_montecarlo_reproducible(self, mock_bridge):
        """Seeded RNG should give reproducible results."""
        payload = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "eval_points": SAMPLE_POINTS,
            "cumulative_msa": 50.0,
            "mix_modulus": 1250,
            "n_simulations": 15,
        }
        resp1 = client.post("/api/v2/montecarlo", json=payload).json()
        resp2 = client.post("/api/v2/montecarlo", json=payload).json()
        assert resp1["n_adequate"] == resp2["n_adequate"]
        assert resp1["probability_adequate"] == resp2["probability_adequate"]

    @patch.object(mc_mod, "run_bridge_from_stack", side_effect=_fake_bridge)
    def test_montecarlo_auto_escalation(self, mock_bridge):
        """Traffic >= 20.0 msa should auto-escalate R80 -> R90, yielding same adequacy as R90."""
        payload_base = {
            "layers": SAMPLE_LAYERS,
            "load": SAMPLE_LOAD,
            "eval_points": SAMPLE_POINTS,
            "mix_modulus": 1250,
            "n_simulations": 15,
        }
        resp_r80 = client.post("/api/v2/montecarlo", json={**payload_base, "cumulative_msa": 20.0, "reliability": 80}).json()
        resp_r90 = client.post("/api/v2/montecarlo", json={**payload_base, "cumulative_msa": 20.0, "reliability": 90}).json()
        
        # Both must have resolved to R90, giving identical results.
        assert resp_r80["probability_adequate"] == resp_r90["probability_adequate"]
        assert resp_r80["n_adequate"] == resp_r90["n_adequate"]
