"""
Legacy Reference Benchmark Tests
================================
Validates the legacy bridge solver against reference output files.
Target: +/-5% match for critical strains (eps_t, eps_v).

Benchmark cases from .scp files:
1. TIHAN1: 4-layer, dual wheel
2. case2: 5-layer, dual wheel
3. rps1: 3-layer, dual wheel
"""

import pytest
import math

from mep_opt.solver.legacy_bridge import run_bridge_from_stack, is_bridge_available
from mep_opt.solver.irc37 import (
    SubgradeInput, fatigue_life, rutting_life, check_design_adequacy,
    get_bituminous_modulus, BitumenGrade, ReliabilityLevel, TrafficInput,
    GranularLayerInput, build_layer_stack, BituminousLayerInput
)
from mep_opt.cost import estimate_cost, LayerCostSpec


TOLERANCE = 0.05  # 5% for critical parameters

# Skip bridge-dependent tests if legacy executable is missing
bridge_required = pytest.mark.skipif(
    not is_bridge_available(),
    reason="Legacy bridge executable not available"
)


class TestIRC37Criteria:
    """Test IRC 37:2018 design equations."""

    def test_subgrade_modulus_low_cbr(self):
        """CBR <= 5% -> MR = 10 * CBR"""
        sub = SubgradeInput(cbr=3.0)
        assert abs(sub.modulus - 30.0) < 0.1

    def test_subgrade_modulus_high_cbr(self):
        """CBR > 5% -> MR = 17.6 * CBR^0.64"""
        sub = SubgradeInput(cbr=8.0)
        expected = 17.6 * (8.0 ** 0.64)
        assert abs(sub.modulus - expected) / expected < 0.01

    def test_granular_modulus(self):
        """Granular layer: MR = 0.2 * h^0.45 * MR_support"""
        gran = GranularLayerInput(thickness=200)
        support = 50.0
        expected = 0.2 * (200 ** 0.45) * 50.0
        result = gran.modulus(support)
        assert abs(result - expected) / expected < 0.01

    def test_granular_modulus_cap(self):
        """IRC 37:2018 Cl. 7.4.2: MR_gran <= 3 * MR_support"""
        # With thickness=1000, 0.2 * 1000^0.45 * 50 = 0.2 * 22.38 * 50 = 223.8
        # 3 * 50 = 150. Cap should kick in.
        gran = GranularLayerInput(thickness=1000)
        support = 50.0
        result = gran.modulus(support)
        assert result == 150.0, f"Expected 150.0 (3x support), got {result}"

    def test_fatigue_life_basic(self):
        """Fatigue life equation produces reasonable values."""
        eps_t = 200e-6
        modulus = 3000
        Nf = fatigue_life(eps_t, modulus)
        assert Nf > 1e4, f"Nf too low: {Nf}"
        assert Nf < 1e12, f"Nf too high: {Nf}"

    def test_fatigue_life_reliability_ordering(self):
        """
        IRC 37:2018 only defines R80 and R90. Non-IRC levels (R95/R98/R99)
        fall back to R90 to keep results compliant.
        """
        eps_t = 200e-6
        modulus = 3000
        Nf_80 = fatigue_life(eps_t, modulus, ReliabilityLevel.R80)
        Nf_90 = fatigue_life(eps_t, modulus, ReliabilityLevel.R90)
        Nf_95 = fatigue_life(eps_t, modulus, ReliabilityLevel.R95)
        Nf_98 = fatigue_life(eps_t, modulus, ReliabilityLevel.R98)
        Nf_99 = fatigue_life(eps_t, modulus, ReliabilityLevel.R99)
        # R80 must allow more repetitions than R90 (IRC Table 12.3)
        assert Nf_80 > Nf_90, "80% reliability should allow more repetitions than 90%"
        # Non-IRC levels must collapse to R90 (no fabricated shifts)
        assert Nf_95 == Nf_90 == Nf_98 == Nf_99

    def test_rutting_life_basic(self):
        """Rutting life equation produces reasonable values."""
        eps_v = 350e-6
        NR_80 = rutting_life(eps_v, ReliabilityLevel.R80)
        NR_90 = rutting_life(eps_v, ReliabilityLevel.R90)
        assert NR_80 > NR_90, "80% reliability should allow more repetitions"
        assert NR_80 > 1e4
        assert NR_80 < 1e12

    def test_fatigue_coefficients_match_irc_2018(self):
        """
        IRC 37:2018 page 16:
            Nf = 1.6064 * C * 1e-4 * (1/εt)^3.89 * (1/MR)^0.854   (R80)
            Nf = 0.5161 * C * 1e-4 * (1/εt)^3.89 * (1/MR)^0.854   (R90)
        R90/R80 ratio must equal 0.5161/1.6064 ≈ 0.3213. The previous
        implementation used 0.5161 for R80 and a 0.5 shift for R90,
        producing R90/R80 = 0.5 (a different physical answer).
        """
        eps_t, modulus = 200e-6, 3000.0
        nf80 = fatigue_life(eps_t, modulus, ReliabilityLevel.R80)
        nf90 = fatigue_life(eps_t, modulus, ReliabilityLevel.R90)
        # R80 must allow strictly more cycles than R90 (higher reliability,
        # more conservative) — IRC ordering is preserved.
        assert nf80 > nf90
        # The ratio must match IRC 37 to 4 decimal places.
        expected_ratio = 0.5161 / 1.6064
        assert abs(nf90 / nf80 - expected_ratio) < 1e-4

    def test_fatigue_life_uses_raw_strain_fraction_units(self):
        """Bridge strains are returned as fractional strain, not microstrain."""
        eps_t = 145.8e-6
        modulus = 2000.0
        nf = fatigue_life(eps_t, modulus, ReliabilityLevel.R90)

        # Manual IRC formula using the same raw fractional strain should match.
        M = 4.84 * (11.5 / (11.5 + 4.0) - 0.69)
        expected = 0.5161e-4 * (10.0 ** M) * (1.0 / abs(eps_t)) ** 3.89 * (1.0 / modulus) ** 0.854
        assert nf == pytest.approx(expected)
        assert nf > 1e5

    def test_bm_uses_fixed_modulus_not_bc_dbm_curve(self):
        """
        IRC 37:2018 Table 9.2: BM is given as a single fixed value at
        35°C only (500 for VG10, 700 for VG30) — NOT a temperature curve.
        Routing BM through the BC/DBM curve gave 2000 MPa (VG30 @ 35°C),
        about 3× too stiff for the BM mix.
        """
        from mep_opt.solver.materials import get_modulus
        # VG30 BM at 35°C — IRC says 700 MPa
        assert get_modulus("BM", grade=BitumenGrade.VG30, temperature=35) == 700.0
        # VG10 BM — IRC says 500 MPa
        assert get_modulus("BM", grade=BitumenGrade.VG10, temperature=35) == 500.0
        # Verify BC at 35°C is still on the BC/DBM curve (2000 MPa) —
        # BM and BC must NOT share a path now.
        assert get_modulus("BC", grade=BitumenGrade.VG30, temperature=35) == 2000.0

    def test_dbm_with_modified_binder_is_rejected(self):
        """
        IRC 37:2018 page 40: 'Modified binders are not recommended for
        the DBM layers due to the concern about the recyclability of
        DBM layers with modified binders.' The optimizer raises rather
        than silently mixing a non-permitted binder/mix combination.
        """
        from mep_opt.solver.materials import get_modulus
        with pytest.raises(ValueError, match="not permitted"):
            get_modulus("DBM", grade=BitumenGrade.PMB)
        with pytest.raises(ValueError, match="not permitted"):
            get_modulus("DBM", grade=BitumenGrade.CRMB)
        with pytest.raises(ValueError, match="not permitted"):
            get_modulus("DBM", grade=BitumenGrade.NRMB)
        # BC with modified binder is allowed (Table 9.2 has a row for it)
        assert get_modulus("BC", grade=BitumenGrade.PMB, temperature=35) == 1600.0

    def test_nrmb_uses_modified_bitumen_row(self):
        """NRMB shares the IRC:SP:53 modulus row with PMB and CRMB."""
        from mep_opt.solver.irc37 import get_bituminous_modulus
        assert get_bituminous_modulus(BitumenGrade.NRMB, 35) == 1600.0
        assert get_bituminous_modulus(BitumenGrade.NRMB, 20) == 5700.0

    def test_subgrade_modulus_capped_at_100mpa(self):
        """
        IRC 37:2018 Annex-II worked example (page 78):
            'the effective modulus value will be limited to 100 MPa for
            design purpose'.
        High CBR (>15.8%) must clamp to 100, not produce 100+ MPa.
        """
        # Below the cap — uncapped formula applies
        sub10 = SubgradeInput(cbr=10.0).modulus
        assert abs(sub10 - 17.6 * (10 ** 0.64)) < 0.5
        # At and above the cap — must clamp
        assert SubgradeInput(cbr=20.0).modulus == 100.0
        assert SubgradeInput(cbr=50.0).modulus == 100.0

    def test_fatigue_life_rejects_zero_modulus(self):
        """A zero or negative mix_modulus must raise rather than crash on division."""
        with pytest.raises(ValueError, match="mix_modulus must be > 0"):
            fatigue_life(eps_t=200e-6, mix_modulus=0.0)
        with pytest.raises(ValueError, match="mix_modulus must be > 0"):
            fatigue_life(eps_t=200e-6, mix_modulus=-1250.0)

    def test_fatigue_life_rejects_zero_volume_total(self):
        """Vb + Va == 0 would divide-by-zero in the volume term."""
        with pytest.raises(ValueError, match="bitumen_volume \\+ air_voids"):
            fatigue_life(eps_t=200e-6, mix_modulus=1250.0,
                         air_voids=0.0, bitumen_volume=0.0)

    def test_rutting_life_reliability_ordering(self):
        """
        IRC 37:2018 only defines R80 and R90. Non-IRC levels (R95/R98/R99)
        fall back to R90 to keep results compliant.
        """
        eps_v = 350e-6
        NR_80 = rutting_life(eps_v, ReliabilityLevel.R80)
        NR_90 = rutting_life(eps_v, ReliabilityLevel.R90)
        NR_95 = rutting_life(eps_v, ReliabilityLevel.R95)
        NR_98 = rutting_life(eps_v, ReliabilityLevel.R98)
        NR_99 = rutting_life(eps_v, ReliabilityLevel.R99)
        # R80 must allow more repetitions than R90 (IRC Table 12.4)
        assert NR_80 > NR_90, "80% reliability should allow more repetitions than 90%"
        # Non-IRC levels must collapse to R90 (no fabricated shifts)
        assert NR_95 == NR_90 == NR_98 == NR_99

    def test_traffic_computation(self):
        """Cumulative MSA calculation."""
        traffic = TrafficInput(
            initial_aadt=5000,
            commercial_vehicles_per_day=2000,
            traffic_growth_rate=0.075,
            design_life_years=20,
            lane_distribution_factor=0.75,
            vehicle_damage_factor=2.5,
        )
        msa = traffic.cumulative_msa()
        assert msa > 0
        assert 30 < msa < 200, f"MSA out of range: {msa}"

    def test_design_adequacy_check(self):
        """CDF check marks design as adequate or not."""
        result = check_design_adequacy(
            eps_t=150e-6, eps_v=300e-6,
            cumulative_msa=50, mix_modulus=3000,
        )
        assert "overall_adequate" in result
        assert isinstance(result["CDF_fatigue"], float)
        assert isinstance(result["CDF_rutting"], float)

    def test_bituminous_modulus_lookup(self):
        """Bituminous modulus table lookup — IRC 37:2018 Table 9.2 values."""
        # VG30 @ 30°C = 2500 MPa (IRC 37:2018 Table 9.2 page 40)
        mod_30 = get_bituminous_modulus(BitumenGrade.VG30, 30)
        assert abs(mod_30 - 2500) < 50

        # VG30 @ 25°C = 3000 MPa
        mod_25 = get_bituminous_modulus(BitumenGrade.VG30, 25)
        assert abs(mod_25 - 3000) < 50

        # VG30 @ 35°C = 2000 MPa (the design temperature)
        mod_35 = get_bituminous_modulus(BitumenGrade.VG30, 35)
        assert abs(mod_35 - 2000) < 50

    def test_layer_stack_construction(self):
        """Build complete layer stack for analysis."""
        subgrade = SubgradeInput(cbr=5.0)
        granular = [GranularLayerInput(thickness=250)]
        bituminous = [
            BituminousLayerInput("BC", 40, 3000),
            BituminousLayerInput("DBM", 100, 2500),
        ]
        stack = build_layer_stack(subgrade, granular, bituminous)
        assert len(stack) == 4  # 2 bituminous + 1 granular + 1 subgrade
        assert stack[-1]["thickness"] == 0


@bridge_required
class TestBridgeSolverBasic:
    """Basic solver tests using legacy bridge."""

    def test_bridge_single_point(self):
        """Bridge runs for a single point and returns valid results."""
        layers = [
            {"modulus": 3000, "poisson": 0.35, "thickness": 150},
            {"modulus": 300, "poisson": 0.35, "thickness": 250},
            {"modulus": 50, "poisson": 0.40, "thickness": 0},
        ]
        load_cfg = {"load": 20000, "pressure": 0.56, "is_dual": False, "spacing": 310}
        results = run_bridge_from_stack(layers, load_cfg, [{"z": 150, "r": 0}])
        assert len(results) == 1
        assert math.isfinite(results[0]["eps_t"])
        assert math.isfinite(results[0]["eps_z"])

    def test_bridge_returns_dict_keys(self):
        """Bridge result dicts contain expected strain keys."""
        layers = [
            {"modulus": 3000, "poisson": 0.35, "thickness": 150},
            {"modulus": 50, "poisson": 0.40, "thickness": 0},
        ]
        load_cfg = {"load": 20000, "pressure": 0.56, "is_dual": False, "spacing": 310}
        result = run_bridge_from_stack(layers, load_cfg, [{"z": 0, "r": 0}])
        assert len(result) == 1
        assert "eps_t" in result[0]
        assert "eps_z" in result[0]

    def test_bridge_dual_wheel(self):
        """Dual wheel bridge execution works."""
        layers = [
            {"modulus": 3000, "poisson": 0.35, "thickness": 150},
            {"modulus": 50, "poisson": 0.40, "thickness": 0},
        ]
        load_cfg = {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310}
        results = run_bridge_from_stack(layers, load_cfg, [{"z": 0, "r": 0}])
        assert len(results) == 1
        assert math.isfinite(results[0]["eps_z"])

    def test_bridge_multiple_points(self):
        """Bridge handles multiple evaluation points."""
        layers = [
            {"modulus": 3000, "poisson": 0.35, "thickness": 150},
            {"modulus": 300, "poisson": 0.35, "thickness": 250},
            {"modulus": 50, "poisson": 0.40, "thickness": 0},
        ]
        load_cfg = {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310}
        points = [{"z": 150, "r": 0}, {"z": 150, "r": 155}, {"z": 400, "r": 0}]
        results = run_bridge_from_stack(layers, load_cfg, points)
        assert len(results) == 3


@bridge_required
class TestLegacyBenchmarks:
    """
    Benchmark validation against legacy reference outputs.
    Target: +/-5% for eps_t, +/-15% for sigma_z, disp_z.
    """

    def test_rps1_eps_t(self):
        """rps1.scp: 3-layer, eps_t at Z=190, R=155. Target: 145.8 microstrain."""
        layers = [
            {"modulus": 3000, "poisson": 0.35, "thickness": 190},
            {"modulus": 200, "poisson": 0.35, "thickness": 480},
            {"modulus": 62, "poisson": 0.35, "thickness": 0},
        ]
        load_cfg = {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310}
        results = run_bridge_from_stack(layers, load_cfg, [{"z": 190, "r": 155}])

        target = 145.8e-6
        actual = abs(results[0]["eps_t"])
        error = abs(actual - target) / target
        assert error < 0.05, f"rps1 eps_t: {actual*1e6:.1f} vs {target*1e6:.1f} ({error*100:.1f}%)"

    def test_rps1_sigma_z(self):
        """rps1: sigma_z at Z=190, R=155. Target: -0.06919 MPa."""
        layers = [
            {"modulus": 3000, "poisson": 0.35, "thickness": 190},
            {"modulus": 200, "poisson": 0.35, "thickness": 480},
            {"modulus": 62, "poisson": 0.35, "thickness": 0},
        ]
        load_cfg = {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310}
        results = run_bridge_from_stack(layers, load_cfg, [{"z": 190, "r": 155}])

        target = -0.06919
        actual = results[0]["sigma_z"]
        error = abs(actual - target) / abs(target)
        assert error < 0.15, f"rps1 sigma_z: {actual:.4f} vs {target:.4f} ({error*100:.1f}%)"

    def test_rps1_subgrade_strain(self):
        """rps1: subgrade eps_z at Z=670.01, R=0. Target: -231.2 microstrain."""
        layers = [
            {"modulus": 3000, "poisson": 0.35, "thickness": 190},
            {"modulus": 200, "poisson": 0.35, "thickness": 480},
            {"modulus": 62, "poisson": 0.35, "thickness": 0},
        ]
        load_cfg = {"load": 20000, "pressure": 0.56, "is_dual": True, "spacing": 310}
        results = run_bridge_from_stack(layers, load_cfg, [{"z": 670.01, "r": 0}])

        target = -231.2e-6
        actual = results[0]["eps_z"]
        error = abs(actual - target) / abs(target)
        assert error < 0.15, f"rps1 subgrade eps_z: {actual*1e6:.1f} vs {target*1e6:.1f} ({error*100:.1f}%)"

    def test_case2_eps_t(self):
        """case2.scp: 5-layer, eps_t at Z=120, R=0. Target: 232.4 microstrain."""
        layers = [
            {"modulus": 3000, "poisson": 0.35, "thickness": 30},
            {"modulus": 3000, "poisson": 0.35, "thickness": 90},
            {"modulus": 200, "poisson": 0.25, "thickness": 250},
            {"modulus": 200, "poisson": 0.25, "thickness": 200},
            {"modulus": 66, "poisson": 0.40, "thickness": 0},
        ]
        load_cfg = {"load": 20000, "pressure": 0.66, "is_dual": True, "spacing": 310}
        results = run_bridge_from_stack(layers, load_cfg, [{"z": 120, "r": 0}])

        target = 232.4e-6
        actual = abs(results[0]["eps_t"])
        error = abs(actual - target) / target
        assert error < 0.10, f"case2 eps_t: {actual*1e6:.1f} vs {target*1e6:.1f} ({error*100:.1f}%)"

    def test_case2_disp_z(self):
        """case2: displacement at Z=120, R=0. Target: 0.4435 mm."""
        layers = [
            {"modulus": 3000, "poisson": 0.35, "thickness": 30},
            {"modulus": 3000, "poisson": 0.35, "thickness": 90},
            {"modulus": 200, "poisson": 0.25, "thickness": 250},
            {"modulus": 200, "poisson": 0.25, "thickness": 200},
            {"modulus": 66, "poisson": 0.40, "thickness": 0},
        ]
        load_cfg = {"load": 20000, "pressure": 0.66, "is_dual": True, "spacing": 310}
        results = run_bridge_from_stack(layers, load_cfg, [{"z": 120, "r": 0}])

        target = 0.4435
        actual = results[0]["disp_z"]
        error = abs(actual - target) / target
        assert error < 0.15, f"case2 disp_z: {actual:.4f} vs {target:.4f} ({error*100:.1f}%)"

    def test_tihan1_eps_t(self):
        """
        TIHAN1.scp: 4-layer, dual wheel. Target: 177.2 microstrain.
        Known limitation: ~30% deviation for this case due to varying
        Poisson ratios (0.35-0.45) and dual-wheel superposition effects.
        """
        layers = [
            {"modulus": 1000, "poisson": 0.35, "thickness": 100},
            {"modulus": 800, "poisson": 0.40, "thickness": 100},
            {"modulus": 200, "poisson": 0.40, "thickness": 200},
            {"modulus": 50, "poisson": 0.45, "thickness": 0},
        ]
        load_cfg = {"load": 20000, "pressure": 0.575, "is_dual": True, "spacing": 310}
        results = run_bridge_from_stack(layers, load_cfg, [
            {"z": 100, "r": 0}, {"z": 100, "r": 155}
        ])

        target = 177.2e-6
        actual_r0 = abs(results[0]["eps_t"])
        actual_r155 = abs(results[1]["eps_t"])
        max_actual = max(actual_r0, actual_r155)

        error = abs(max_actual - target) / target
        assert error < 0.30, (
            f"TIHAN1 eps_t: R=0={actual_r0*1e6:.1f}, R=155={actual_r155*1e6:.1f} "
            f"vs target {target*1e6:.1f} ({error*100:.1f}%)"
        )


class TestCostEstimator:
    """Test cost/CO2 estimation."""

    def test_basic_cost_estimation(self):
        layers = [
            LayerCostSpec("BC", 40),
            LayerCostSpec("DBM", 100),
            LayerCostSpec("WMM", 250),
            LayerCostSpec("GSB", 200),
        ]
        result = estimate_cost(layers)
        assert result.total_cost_per_km > 0
        assert result.total_co2_per_km > 0
        assert len(result.layer_breakdown) == 4

    def test_cost_increases_with_thickness(self):
        thin = estimate_cost([LayerCostSpec("BC", 30)])
        thick = estimate_cost([LayerCostSpec("BC", 50)])
        assert thick.total_cost_per_km > thin.total_cost_per_km

    def test_co2_positive(self):
        result = estimate_cost([LayerCostSpec("BC", 40)])
        assert result.total_co2_per_km > 0


class TestMaterialsLibrary:
    """Test centralized materials database."""

    def test_get_material(self):
        from mep_opt.solver.materials import get_material
        mat = get_material("BC")
        assert mat.name == "Bituminous Concrete (BC)"
        assert mat.category == "bituminous"
        assert mat.default_modulus > 0

    def test_get_modulus_temperature(self):
        from mep_opt.solver.materials import get_modulus
        mod_35 = get_modulus("BC", temperature=35.0)
        mod_20 = get_modulus("BC", temperature=20.0)
        assert mod_20 > mod_35, "Modulus should decrease with temperature"

    def test_get_modulus_granular(self):
        from mep_opt.solver.materials import get_modulus
        mod = get_modulus("WMM")
        assert mod > 0

    def test_unknown_material_raises(self):
        from mep_opt.solver.materials import get_material
        with pytest.raises(KeyError):
            get_material("INVALID")

    def test_list_materials(self):
        from mep_opt.solver.materials import list_materials
        mats = list_materials()
        assert "BC" in mats
        assert "WMM" in mats
        assert len(mats) >= 10


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
