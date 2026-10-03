"""
Smart Pavement Search Optimizer
================================
Brute-force Pareto search over a discrete, MoRTH-500-aligned lift schedule.

For a typical 4-layer pavement (BC/DBM/WMM/GSB) the constructable lift
sizes give roughly 100–300 valid combinations — small enough to evaluate
exhaustively. The optimizer:

  1. Enumerates every (BC, DBM, WMM, GSB, ...) combination whose values
     are taken from the lift schedule and lie within the user's bounds.
  2. Runs each design through the native Burmister solver (one or two calls,
     depending on whether a CTB layer is present — IRC 37 mandates a separate
     0.80 MPa pressure for cement-treated tensile-stress analysis).
  3. Filters to designs with all CDFs ≤ 1.0 (IRC adequacy). Cost and embodied
     CO₂ are computed for every adequate design.
  4. Returns four single-purpose archetypes from the adequate set:
       Structural  = thinnest (minimum total material — the solver optimum)
       Economy     = cheapest (minimum ₹/km)
       Sustainable = greenest (minimum embodied CO₂/km)
       Premium     = best COMBINED optimum (jointly minimises normalised
                     thickness + cost + CO₂)
     When one design wins several objectives its labels merge onto one card.

All structural analysis runs through the native Python Burmister solver
(no external executable).
"""

import logging
import itertools
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Tuple

from mep_opt.solver.irc37 import (
    ReliabilityLevel,
    check_design_adequacy, check_ctb_adequacy, ctb_fatigue_life_strain,
    BituminousLayerInput, GranularLayerInput, build_layer_stack,
    required_reliability, ctb_reliability_factor, expand_axle_spectrum,
    GRANULAR_OVER_CTSB_MODULUS, BitumenGrade, get_bituminous_modulus,
)
from mep_opt.solver.materials import get_modulus, get_poisson
from mep_opt.solver.legacy_bridge import (
    run_bridge_from_stack, is_bridge_available,
    set_bridge_cache_size, get_bridge_cache_stats,
    BridgeWorkerPool,
)
from mep_opt.cost import estimate_cost, LayerCostSpec
from mep_opt.optimizer.problem import (
    DEFAULT_LIFT_SCHEDULE,
    DEFAULT_TRAFFIC_TIER_MINIMUMS,
    OptimizationProblem, OptimizationResult, ParetoSolution,
)

logger = logging.getLogger(__name__)

BITUMINOUS_TYPES = {"BC", "DBM", "BM", "SDBC", "SMA"}
# Non-bituminous structural layers routed to build_layer_stack: unbound
# granular, granular crack-relief (CRL), cement-treated base/sub-base and the
# emulsion/foam-bitumen stabilised RAP base (800 MPa, IRC:37-2018 §8.4).
# Layer types outside BITUMINOUS_TYPES | GRANULAR_TYPES are rejected by
# OptimizationProblem instead of being silently left out of the analysis.
GRANULAR_TYPES = {"WMM", "WBM", "GSB", "CRL", "CTB", "CTSB", "RAP"}
CEMENT_TREATED_TYPES = {"CTB", "CTSB"}
# Only a cement-treated BASE is checked for fatigue (IRC:37-2018 §3.6.3,
# Figs. 3.2/3.3). The CTSB is a 600 MPa design-value sub-base with no
# fatigue criterion.
CTB_TYPES = {"CTB"}
COLD_RECYCLED_TYPES = {"RAP"}
# Unbound granular types eligible to act as an IRC:37-2018 §8.3 crack-relief
# interlayer (assigned a fixed 450 MPa when sandwiched directly above a CTB),
# or as a granular base over a CTSB (300/350 MPa, §8.1 / Table 11.1).
UNBOUND_CRACK_RELIEF_TYPES = {"WMM", "WBM", "GSB", "CRL"}
# IRC:37-2018 page 27 — fixed resilient modulus of the sandwiched granular
# crack-relief layer above a cement-treated base.
CRACK_RELIEF_MODULUS_MPA = 450.0

# Fallback cost when a material has no entry in the rate table.
# Matches the fallback used by estimate_cost() so optimizer ranking and the
# final cost report stay consistent.
_DEFAULT_COST_PER_CUM = 5000.0

# Step size used when no lift schedule is available for a layer type. This
# is a fallback only — the optimizer prefers MoRTH-aligned lifts whenever
# the layer type is in DEFAULT_LIFT_SCHEDULE.
_FALLBACK_STEP_MM = 5.0


class SmartPavementSearch:
    """
    Deterministic optimizer for pavement layer thicknesses.
    Finds the thinnest adequate design, then collects archetypes.
    """

    def __init__(self, problem: OptimizationProblem):
        self.problem = problem
        # Resolve material rates once: user overrides merged over IRC/MORTH defaults.
        # Used for both layer ranking (greedy climb / sweep ordering) and the
        # cost report, so the two always agree.
        self._material_rates = problem.resolved_material_rates()
        # Collect errors encountered during evaluation to return when debug is requested
        self._errors: List[str] = []
        # Optional absolute deadline (time.monotonic() value). When set, the
        # search returns whatever adequate designs it has found instead of
        # running to completion. None disables the deadline.
        self._deadline: Optional[float] = None
        # Severity-4 #4.5 — thread-local pointer to the currently-bound
        # worker scratch dir. When set, `_bridge_call` routes through that
        # directory instead of the shared LEGACY_DIR; that's how the
        # parallel pool gives each worker its own .IN/.OUT files.
        self._tls = threading.local()
        self._worker_pool: Optional[BridgeWorkerPool] = None

        # The native Python Burmister solver runs in-memory and is thread-safe.
        # No legacy executable is needed for any mode.
        n_parallel = int(getattr(self.problem, 'parallel_workers', 1) or 1)
        self._use_cost = bool(getattr(self.problem, 'optimize_by_cost', False))
        self._use_co2 = bool(getattr(self.problem, 'optimize_by_co2', False))

        # IRC:37-2018 §3.7 — 90% reliability is mandatory for Expressways,
        # National Highways, State Highways and Urban Roads irrespective of
        # traffic, and for every other road at 20 msa or more. The requested
        # level is escalated when IRC requires it (never lowered).
        # IRC:37-2018 Eq. 3.5 — the CTB reliability factor RF is set by road
        # category and traffic (1 for important roads or >= 10 msa, else 2),
        # NOT by the reliability level.
        _msa = self.problem.traffic.cumulative_msa()
        _cat = getattr(self.problem, 'road_category', 'other')
        self._reliability = required_reliability(_msa, _cat, self.problem.reliability)
        if self._reliability != self.problem.reliability:
            logger.warning(
                "Reliability escalated %s -> %s per IRC:37-2018 §3.7 "
                "(road category %s, %.1f msa).",
                self.problem.reliability.name, self._reliability.name, _cat, _msa,
            )
        self._ctb_rf = ctb_reliability_factor(_msa, _cat)

    def _bridge_call(self, solver_stack, load_cfg, eval_points):
        """
        Route a solver call through the native Burmister solver with caching.
        """
        return run_bridge_from_stack(solver_stack, load_cfg, eval_points)

    def _cost_per_cum(self, layer_type: str) -> float:
        """₹/m³ for a layer type, using user overrides if provided."""
        rate = self._material_rates.get(layer_type)
        return rate.cost_per_cum if rate else _DEFAULT_COST_PER_CUM

    def _build_warnings(self) -> List[str]:
        """Advisory messages that help the UI surface non-fatal design choices."""
        warnings: List[str] = []
        msa = self.problem.traffic.cumulative_msa()
        growth_rate = getattr(self.problem.traffic, "traffic_growth_rate", 0.0)
        requested = getattr(self.problem, "reliability", ReliabilityLevel.R90)
        category = getattr(self.problem, "road_category", "other")
        layer_types = [str(lt).upper().strip() for lt in (self.problem.layer_types or [])]

        if growth_rate < 0.05:
            warnings.append(
                f"Traffic growth rate {growth_rate:.3f} is below 5%; "
                "design traffic may be optimistic relative to standard practice."
            )

        # IRC:37-2018 §3.7 — reliability escalation (category or >= 20 msa).
        if self._reliability != requested:
            reason = (
                f"road category '{category}'" if msa < 20.0
                else f"design traffic {msa:.1f} MSA >= 20 MSA"
            )
            warnings.append(
                f"Reliability escalated {requested.name} -> {self._reliability.name} "
                f"per IRC:37-2018 §3.7 ({reason})."
            )

        # IRC:37-2018 §5 / §9.2 — the bituminous bundle is ONE layer in the
        # analysis, with the modulus of the bottom (DBM/BM) mix.
        bit = [lt for lt in layer_types if lt in BITUMINOUS_TYPES]
        if len(bit) > 1:
            raw = self._raw_bituminous_moduli()
            e_bot = raw[-1][1]
            upper_diff = [lt for lt, E in raw[:-1] if abs(E - e_bot) > 1e-6]
            if upper_diff:
                warnings.append(
                    f"All bituminous layers are analysed with the modulus of the bottom "
                    f"mix ({bit[-1]}, {e_bot:.0f} MPa) per IRC:37-2018 §5 / §9.2; the "
                    f"moduli of {', '.join(upper_diff)} are not used in the structural analysis."
                )
        if bit:
            e_bot = self._bundle_modulus_for_report()
            limit = self._irc_max_bituminous_modulus(bit[-1])
            if e_bot is not None and limit is not None and e_bot > limit + 1e-6:
                warnings.append(
                    f"Bituminous design modulus {e_bot:.0f} MPa exceeds the IRC:37-2018 "
                    f"Table 9.2 maximum ({limit:.0f} MPa for {bit[-1]} at "
                    f"{self.problem.temperature:g} °C). IRC requires the smaller of the "
                    f"tested value and the table value."
                )

        # IRC:SP:59-2019 §3.1.3 — geogrid MIF for design is capped at 2.0 and
        # must be third-party validated for the product used.
        props = self.problem.layer_props or {}
        if any((props.get(lt) or {}).get('geogrid') for lt in layer_types):
            warnings.append(
                "Geogrid MIF is taken from the Saride et al. (2022) research table, capped "
                "at the IRC:SP:59-2019 §3.1.3 design maximum of 2.0, with the reinforced "
                "base resting on the effective modulus of the layers below (IRC:37-2018 "
                "§8.1). SP:59 requires third-party-validated MIF for the actual product."
            )

        # IRC:37-2018 checks CTB fatigue two ways: the strain-based Eq. 3.5
        # against design traffic (always run here) AND the stress-ratio
        # cumulative-damage analysis over the heavy-axle spectrum (Eq. 3.6),
        # which needs project axle-load data the tool cannot invent.
        has_ctb = any(lt in CTB_TYPES for lt in layer_types)
        if has_ctb:
            warnings.append(
                f"CTB fatigue (IRC:37-2018 Eq. 3.5) uses RF = {self._ctb_rf:g} "
                f"(road category '{category}', {msa:.1f} MSA)."
            )
            if not getattr(self.problem, "ctb_axle_spectrum", None):
                warnings.append(
                    "CTB fatigue was checked with the strain-based criterion only "
                    "(IRC:37-2018 Eq. 3.5). The complementary stress-ratio cumulative "
                    "damage check (Eq. 3.6) needs an axle-load spectrum - provide "
                    "ctb_axle_spectrum for the full IRC dual check."
                )
            elif not getattr(self.problem, "ctb_per_class_bridge_recompute", False):
                warnings.append(
                    "CTB axle-spectrum damage (Eq. 3.6) is computed exactly for every design "
                    "that passes the other criteria; designs that already fail are not "
                    "spectrum-checked (set ctb_per_class_bridge_recompute=True to evaluate all)."
                )

        return warnings

    def _raw_bituminous_moduli(self) -> List[Tuple[str, float]]:
        """(type, modulus) per bituminous layer: pinned E, else IRC Table 9.2."""
        out = []
        for lt in (self.problem.layer_types or []):
            if lt not in BITUMINOUS_TYPES:
                continue
            E = ((self.problem.layer_props or {}).get(lt) or {}).get('E')
            if E is None:
                E = get_modulus(lt, temperature=self.problem.temperature)
            out.append((lt, float(E)))
        return out

    def _bundle_modulus_for_report(self) -> Optional[float]:
        """Bottom bituminous modulus actually used (for warnings)."""
        raw = self._raw_bituminous_moduli()
        return raw[-1][1] if raw else None

    def _irc_max_bituminous_modulus(self, bottom_type: str) -> Optional[float]:
        """IRC:37-2018 Table 9.2 ceiling for the bottom mix at the design temperature."""
        if bottom_type == "BM":
            return 700.0
        # Highest unmodified row (VG40) — modified binders are not permitted in DBM.
        return float(get_bituminous_modulus(BitumenGrade.VG40, self.problem.temperature))

    def _deadline_passed(self) -> bool:
        """True if a deadline was set and has been reached."""
        return self._deadline is not None and time.monotonic() >= self._deadline

    # ------------------------------------------------------------------
    # Core evaluation (same bridge call as old GA)
    # ------------------------------------------------------------------

    def _build_solver_inputs(self, thicknesses: List[float]):
        """
        Build the layer stack from thicknesses.

        Returns: (solver_stack, cost_specs, input_bituminous, ctb_depth)
        where ctb_depth is the depth (mm) to the bottom of the CTB layer if
        any, else None. (A CTSB is not a CTB: it has no fatigue criterion.)
        """
        layer_types = self.problem.layer_types
        subgrade = self.problem.subgrade
        props_all = self.problem.layer_props or {}

        cost_specs = []
        input_bituminous = []
        input_granular = []

        # IRC:37-2018 §5 and §9.2: all bituminous layers are ONE layer in the
        # analysis, assigned the elastic properties of the bottom (DBM/BM) mix.
        raw_bit = self._raw_bituminous_moduli()
        if raw_bit:
            bundle_E = raw_bit[-1][1]
            bottom_type = raw_bit[-1][0]
            bundle_nu = (props_all.get(bottom_type) or {}).get('nu')
            if bundle_nu is None:
                bundle_nu = get_poisson(bottom_type)

        for i, l_type in enumerate(layer_types):
            h = thicknesses[i]
            cost_specs.append(LayerCostSpec(l_type, h))

            if l_type in BITUMINOUS_TYPES:
                # Carry the project mix volumetrics (Va, Vbe) so the fatigue
                # C-factor uses the bottom bituminous layer's actual mix
                # (IRC:37-2018 §3.6.2) rather than a hard-coded default.
                input_bituminous.append(
                    BituminousLayerInput(
                        l_type, h, bundle_E, bundle_nu,
                        air_voids=getattr(self.problem, 'air_voids', 3.0),
                        bitumen_volume=getattr(self.problem, 'bitumen_volume', 11.5),
                    )
                )
            elif l_type in GRANULAR_TYPES:
                custom_props = props_all.get(l_type, {}) or {}
                custom_E = custom_props.get('E')
                custom_nu = custom_props.get('nu')
                below = (
                    str(layer_types[i + 1]).upper().strip()
                    if i + 1 < len(layer_types) else None
                )
                unbound = str(l_type).upper().strip() in UNBOUND_CRACK_RELIEF_TYPES
                # CTB/CTSB are cement-treated, not granular: they use their IRC
                # design moduli (CTB 5000 MPa, CTSB 600 MPa); the RAP base uses
                # the IRC cold-recycled value (800 MPa) — never Eq. 7.1.
                if (l_type in CEMENT_TREATED_TYPES or l_type in COLD_RECYCLED_TYPES) \
                        and custom_E is None:
                    custom_E = get_modulus(l_type)
                # IRC:37-2018 §8.3 / page 27 — a granular crack-relief layer
                # sandwiched directly above a cement-treated BASE takes a FIXED
                # 450 MPa (not Eq. 7.1).
                elif custom_E is None and unbound and below in CTB_TYPES:
                    custom_E = CRACK_RELIEF_MODULUS_MPA
                # IRC:37-2018 §8.1 / Table 11.1 — a granular base resting on a
                # CTSB takes 350 MPa (crushed rock) / 300 MPa (natural gravel).
                elif custom_E is None and unbound and below == "CTSB":
                    custom_E = GRANULAR_OVER_CTSB_MODULUS[str(l_type).upper().strip()]
                if custom_nu is None and (l_type in CEMENT_TREATED_TYPES or l_type in COLD_RECYCLED_TYPES):
                    custom_nu = get_poisson(l_type)
                # IRC:SP:59 MIF scales an Eq. 7.1 granular modulus; the fixed
                # IRC moduli of the crack-relief layer (over CTB) and of a base
                # over CTSB are not Eq. 7.1 values, so reinforcement is rejected.
                if (custom_props.get('geogrid') not in (None, "", "none")
                        and custom_props.get('E') is None and unbound
                        and (below in CTB_TYPES or below == "CTSB")):
                    raise ValueError(
                        f"Geogrid on {l_type} directly above {below} is not supported: its "
                        f"modulus is a fixed IRC value, not an Eq. 7.1 modulus the MIF scales."
                    )
                input_granular.append({
                    "thickness": h,
                    "layer_type": l_type,
                    "E": custom_E,
                    "nu": custom_nu,
                    "geogrid": custom_props.get('geogrid'),
                })
            else:  # pragma: no cover - OptimizationProblem rejects unknown types
                raise ValueError(f"Unsupported layer type {l_type!r}")

        solver_stack = build_layer_stack(
            subgrade, input_granular, input_bituminous, self.problem.layer_props
        )

        # Depth (mm from surface) to the bottom of the CTB layer, if any.
        # Order in the actual solver stack is: bituminous (top) → granular → subgrade,
        # so depth = sum(bituminous thicknesses) + sum(granular thicknesses up to & incl CTB).
        ctb_depth: Optional[float] = None
        cum = sum(l.thickness for l in input_bituminous)
        for gran in input_granular:
            cum += gran["thickness"]
            if gran["layer_type"] in CTB_TYPES:
                ctb_depth = cum
                break

        return solver_stack, cost_specs, input_bituminous, ctb_depth

    def _evaluate(self, thicknesses: List[float]) -> dict:
        """
        Run IIT Pave for one thickness combination.
        Returns dict with eps_t, eps_v, CDF values, adequacy, cost, co2.
        If a CTB layer is present, also evaluates CTB tensile stress and
        includes CDF_ctb in the overall adequacy decision.
        """
        solver_stack, cost_specs, input_bituminous, ctb_depth = \
            self._build_solver_inputs(thicknesses)

        depth_bit = sum(l.thickness for l in input_bituminous)
        depth_sub = sum(l['thickness'] for l in solver_stack[:-1])

        # wheel_type may be None (legacy callers); coerce to a string default
        # so .lower() is always safe.
        wheel_type_val = getattr(self.problem, 'wheel_type', 'Single') or 'Single'

        # IRC 37:2018 Table 3.1 (page 19) — different contact stresses for
        # different criteria:
        #     0.56 MPa for bituminous fatigue (eps_t) and subgrade rutting (eps_v)
        #     0.80 MPa for cement-treated-base tensile strain (sigma_t)
        # When a CTB layer is in the stack we therefore need TWO bridge calls.
        # Falling back to the user-supplied tire_pressure for the standard
        # call lets analysis-API callers override the default 0.56 MPa for
        # research scenarios while still keeping the CTB call IRC-compliant.
        IRC_PRESSURE_STANDARD = 0.56
        IRC_PRESSURE_CTB = 0.80
        user_pressure = getattr(self.problem, 'tire_pressure', IRC_PRESSURE_STANDARD)
        load_standard = {
            "load": getattr(self.problem, 'wheel_load', 20000.0),
            "pressure": user_pressure,
            "is_dual": (wheel_type_val.lower() == 'dual'),
            "spacing": getattr(self.problem, 'wheel_spacing', 310.0),
        }

        # Build the optimizer's physics-meaningful eval points and track each
        # point's role by index. This mirrors the IRC example layout used by
        # the benchmark suite: r ∈ {0, 155} at the critical locations, with
        # fatigue using max(|eps_t|, |eps_r|) at the bituminous bottom.
        # We split into two parallel lists so the standard-pressure (0.56 MPa)
        # bridge call gets bit_bottom + sub_top, and the CTB-pressure (0.80 MPa)
        # bridge call gets ctb_bottom only.
        std_points: List[dict] = []
        std_idx_map: Dict[str, List[int]] = {}
        ctb_points: List[dict] = []
        ctb_idx_map: Dict[str, List[int]] = {}

        if input_bituminous and depth_bit > 0:
            std_idx_map["bit_bottom"] = [
                len(std_points),
                len(std_points) + 1,
            ]
            std_points.extend([
                {"z": depth_bit - 0.1, "r": 0},
                {"z": depth_bit - 0.1, "r": 155},
            ])

        # Subgrade top — always present (every pavement has a subgrade).
        # IRC:37-2018 §3.6.1: eps_v is the vertical compressive strain at the
        # TOP OF THE SUBGRADE. eps_z is DISCONTINUOUS across the granular/
        # subgrade interface (sigma_z is continuous but E drops sharply), so
        # the probe must sit just BELOW the interface, inside the subgrade
        # (z = depth_sub + delta). Sampling just ABOVE it (the old
        # depth_sub - 0.1, inside the granular layer) under-reported eps_v by
        # ~40% and over-estimated rutting life by ~10x — systematically
        # under-designing against subgrade rutting. The IRC Annex-II benchmark
        # likewise probes at Z = depth_sub + 0.01.
        std_idx_map["sub_top"] = [
            len(std_points),
            len(std_points) + 1,
        ]
        std_points.extend([
            {"z": depth_sub + 0.1, "r": 0},
            {"z": depth_sub + 0.1, "r": 155},
        ])

        if ctb_depth is not None:
            ctb_idx_map["ctb_bottom"] = [
                len(ctb_points),
                len(ctb_points) + 1,
            ]
            ctb_points.extend([
                {"z": ctb_depth - 0.1, "r": 0},
                {"z": ctb_depth - 0.1, "r": 155},
            ])

        # User-supplied additional eval_points are appended to the standard
        # call only — they're meant for analysis, not for IRC compliance.
        user_extra = list(getattr(self.problem, 'eval_points', None) or [])
        std_eval_points = std_points + user_extra

        # --- Standard call (0.56 MPa, fatigue + rutting) -------------------
        try:
            results_std = self._bridge_call(solver_stack, load_standard, std_eval_points)
        except Exception as e:
            logger.exception("Bridge evaluation failed for thicknesses=%s load_cfg=%s eval_points=%s", thicknesses, load_standard, std_eval_points)
            try:
                self._errors.append(str(e))
            except Exception:
                logger.exception("Failed to record evaluation error")
            raise
        if not results_std or len(results_std) < len(std_points):
            logger.error(
                "Legacy bridge returned %d results; expected at least %d for thicknesses=%s",
                len(results_std) if results_std else 0, len(std_points), thicknesses,
            )
            raise RuntimeError("Legacy bridge returned insufficient results")

        # --- CTB call (0.80 MPa per IRC 37 Table 3.1) ---------------------
        # Only when a CTB layer is present. This doubles the bridge cost
        # for CTB designs, but mixing the two pressures is non-negotiable
        # for IRC-compliant CTB σ_t.
        results_ctb = []
        if ctb_depth is not None:
            load_ctb = dict(load_standard)
            load_ctb["pressure"] = IRC_PRESSURE_CTB
            try:
                results_ctb = self._bridge_call(solver_stack, load_ctb, ctb_points)
            except Exception as e:
                logger.exception("Bridge evaluation failed for CTB call thicknesses=%s eval_points=%s", thicknesses, ctb_points)
                try:
                    self._errors.append(str(e))
                except Exception:
                    logger.exception("Failed to record CTB-call error")
                raise
            if not results_ctb or len(results_ctb) < len(ctb_points):
                raise RuntimeError("Legacy bridge returned insufficient CTB results")

        # Fatigue strain — only meaningful when bituminous layers exist.
        # Granular-only sections have no fatigue criterion (eps_t = 0 → CDF = 0).
        # IRC:37-2018 Table 3.1 notes: (a) only ABSOLUTE values of strains and
        # stresses are used in the performance equations; (b) under thin
        # bituminous layers / strong bases the strain at the bottom of the
        # bituminous layer may be compressive. Hence the largest |eps| of the
        # two horizontal components at r = 0 and r = 155 mm.
        if "bit_bottom" in std_idx_map:
            bit_results = [results_std[i] for i in std_idx_map["bit_bottom"]]
            eps_t = max(
                max(abs(r["eps_t"]), abs(r.get("eps_r", 0.0)))
                for r in bit_results
            )
        else:
            eps_t = 0.0

        # Rutting vertical strain — always present
        sub_results = [results_std[i] for i in std_idx_map["sub_top"]]
        eps_v = max(abs(r["eps_z"]) for r in sub_results)

        msa = self.problem.traffic.cumulative_msa()
        bot_mod = input_bituminous[-1].modulus if input_bituminous else 1250.0
        # Use the IRC §3.7 reliability resolved in __init__ (auto-escalated to
        # R90 for >= 20 msa). IRC §3.6.2: Va/Vbe are the BOTTOM bituminous
        # layer's mix volumetrics — thread them into the fatigue C-factor.
        rel = self._reliability
        if input_bituminous:
            av = getattr(input_bituminous[-1], 'air_voids', getattr(self.problem, 'air_voids', 3.0))
            bv = getattr(input_bituminous[-1], 'bitumen_volume', getattr(self.problem, 'bitumen_volume', 11.5))
        else:
            av = getattr(self.problem, 'air_voids', 3.0)
            bv = getattr(self.problem, 'bitumen_volume', 11.5)

        chk = check_design_adequacy(
            eps_t, eps_v, msa, bot_mod, rel,
            air_voids=av, bitumen_volume=bv,
        )
        # Cost & embodied-CO2 are computed ONLY when the user has opted into a
        # cost- or CO2-based objective (Economy / Sustainable / Premium). With
        # neither enabled, the Structural archetype is selected purely on
        # thickness, so the cost estimator is never run and the values stay None.
        if self._use_cost or self._use_co2:
            cost_res = estimate_cost(
                cost_specs,
                lane_width_m=self.problem.lane_width_m,
                rates=self._material_rates,
            )
            cost_per_km = cost_res.total_cost_per_km
            co2_per_km = cost_res.total_co2_per_km
        else:
            cost_per_km = None
            co2_per_km = None
        moduli = [l['modulus'] for l in solver_stack]

        # CTB fatigue check — uses the SECOND bridge call at 0.80 MPa
        # (IRC:37-2018 §3.6.1 / Table 3.1) instead of the 0.56 MPa pass.
        #
        # IRC:37-2018 requires TWO CTB fatigue checks:
        #   1. Strain-based Eq. 3.5 against the design traffic, with RF set by
        #      road category and traffic (always run).
        #   2. Stress-ratio cumulative damage (Eq. 3.6/3.7) over the axle-load
        #      spectrum — run when a spectrum is supplied. Each class is solved
        #      exactly: tandems/tridems are resolved into 2/3 single axles at
        #      1/2 and 1/3 of the group load, each single axle loads one dual
        #      set with wheel load = axle/4, at 0.80 MPa (§3.6.3.2, Annex II.4).
        # The critical stress/strain is the largest |value| of the radial and
        # tangential components at r = 0 and 155 mm (Annex II.4).
        ctb_cdf: Optional[float] = None
        ctb_adequate = True
        sigma_t_ctb: Optional[float] = None
        eps_t_ctb: Optional[float] = None
        ctb_cdf_strain: Optional[float] = None
        ctb_nf_strain: Optional[float] = None
        ctb_details: Optional[dict] = None
        ctb_rf: Optional[float] = None
        if "ctb_bottom" in ctb_idx_map:
            ctb_props = (self.problem.layer_props or {}).get("CTB", {}) or {}
            mor = ctb_props.get("MOR", 1.4)  # IRC 37 default modulus of rupture (MPa)
            if not (mor > 0):
                raise ValueError(f"CTB modulus of rupture must be > 0 MPa (got {mor!r})")
            ctb_rows = [results_ctb[i] for i in ctb_idx_map["ctb_bottom"]]
            sigma_t_ctb = max(
                max(abs(r["sigma_t"]), abs(r.get("sigma_r", 0.0))) for r in ctb_rows
            )
            eps_t_ctb = max(
                max(abs(r.get("eps_t", 0.0)), abs(r.get("eps_r", 0.0)))
                for r in ctb_rows
            )

            # CTB modulus for Eq. 3.5: the solver-stack row whose cumulative
            # bottom depth equals ctb_depth is the CTB layer itself (the
            # collapse branch never fires when a cement-treated layer exists,
            # so granular rows map 1:1).
            ctb_modulus = 5000.0  # IRC:37-2018 §8.4 design value fallback
            _cum_depth = 0.0
            for _row in solver_stack[:-1]:
                _cum_depth += float(_row.get("thickness", 0.0) or 0.0)
                if abs(_cum_depth - ctb_depth) < 1e-6:
                    ctb_modulus = float(_row.get("modulus", ctb_modulus))
                    break

            # --- Check 1: strain-based Eq. 3.5 vs design traffic ---
            ctb_rf = self._ctb_rf
            ctb_nf_strain = ctb_fatigue_life_strain(eps_t_ctb, ctb_modulus, rel, rf=ctb_rf)
            ctb_cdf_strain = (msa * 1e6) / ctb_nf_strain if ctb_nf_strain > 0 else float("inf")
            ctb_cdf = ctb_cdf_strain
            ctb_adequate = ctb_cdf_strain <= 1.0

            # --- Check 2: stress-ratio CFD over the axle spectrum (Eq. 3.6) ---
            ctb_spec = list(getattr(self.problem, "ctb_axle_spectrum", None) or [])
            if ctb_spec:
                others_pass = bool(chk["overall_adequate"]) and ctb_adequate
                if others_pass or getattr(self.problem, "ctb_per_class_bridge_recompute", False):
                    ctb_details = self._ctb_spectrum_damage(
                        solver_stack, load_standard, ctb_points, ctb_spec, mor,
                    )
                    ctb_cdf = max(ctb_cdf_strain, ctb_details["CDF_ctb"])
                    ctb_adequate = ctb_adequate and ctb_details["ctb_adequate"]
                else:
                    ctb_details = {
                        "CDF_ctb": None,
                        "ctb_adequate": None,
                        "details": [],
                        "skipped": "design already fails another IRC criterion",
                    }

        overall_adequate = bool(chk["overall_adequate"]) and ctb_adequate

        # Determine governing mode including CTB
        cdfs = {
            "fatigue": chk["CDF_fatigue"],
            "rutting": chk["CDF_rutting"],
        }
        if ctb_cdf is not None:
            cdfs["ctb"] = ctb_cdf
        governing_mode = max(cdfs, key=cdfs.get)

        return {
            "thicknesses": list(thicknesses),
            "total_thickness": sum(thicknesses),
            "eps_t": eps_t,
            "eps_v": eps_v,
            "sigma_t_ctb": sigma_t_ctb,
            "eps_t_ctb": eps_t_ctb,
            "CDF_fatigue": chk["CDF_fatigue"],
            "CDF_rutting": chk["CDF_rutting"],
            "CDF_ctb": ctb_cdf,
            "CDF_ctb_strain": ctb_cdf_strain,
            "Nf_ctb_strain": ctb_nf_strain,
            "ctb_rf": ctb_rf,
            "ctb_details": ctb_details,
            # Reliability level actually used for the performance equations
            # (post §3.7 auto-escalation) — consumed by the UI/PDF so the
            # printed coefficients match the computation.
            "reliability": rel.name,
            "road_category": getattr(self.problem, "road_category", "other"),
            "Nf": chk["Nf"],
            "NR": chk["NR"],
            "overall_adequate": overall_adequate,
            "ctb_adequate": ctb_adequate,
            "governing_mode": governing_mode,
            "msa": msa,
            "cost_per_km": cost_per_km,
            "co2_per_km": co2_per_km,
            # Layer report is keyed off the user's layer_types (one row per
            # logical layer + subgrade) — NOT off solver_stack, because
            # solver_stack collapses unbound granular layers into a single
            # composite row per IRC 37 §7.2.3. Modulus is read from the
            # logical-row -> solver-row mapping below.
            "layers": self._build_layer_report(
                thicknesses, solver_stack, moduli, input_bituminous,
            ),
        }

    def _ctb_spectrum_damage(self, solver_stack, load_standard, ctb_points, spectrum, mor) -> dict:
        """
        Exact cumulative fatigue damage of the CTB over an axle-load spectrum
        (IRC:37-2018 Eq. 3.6/3.7, §3.6.3.2). Each distinct equivalent
        single-axle load is solved once at 0.80 MPa contact pressure.
        """
        classes = expand_axle_spectrum(spectrum)
        stress_by_load: Dict[float, float] = {}
        for c in classes:
            key = round(c["wheel_load_n"], 6)
            if key in stress_by_load:
                continue
            load_cfg = dict(load_standard)
            load_cfg["load"] = c["wheel_load_n"]
            load_cfg["pressure"] = 0.80  # IRC:37-2018 §3.6.3.2
            try:
                rows = self._bridge_call(solver_stack, load_cfg, ctb_points)
            except Exception as e:
                logger.exception("Bridge evaluation failed for CTB spectrum class=%s", c)
                try:
                    self._errors.append(str(e))
                except Exception:
                    logger.exception("Failed to record CTB spectrum error")
                raise
            if not rows or len(rows) < len(ctb_points):
                raise RuntimeError("Legacy bridge returned insufficient CTB spectrum results")
            stress_by_load[key] = max(
                max(abs(r["sigma_t"]), abs(r.get("sigma_r", 0.0))) for r in rows
            )

        from mep_opt.solver.irc37 import AxleLoadGroup as _ALG
        singles = [
            _ALG("single", c["single_axle_kn"], c["single_axle_repetitions"]) for c in classes
        ]
        stresses = [stress_by_load[round(c["wheel_load_n"], 6)] for c in classes]
        result = check_ctb_adequacy(singles, stresses, mor)
        for d, c in zip(result["details"], classes):
            d["axle_type"] = c["axle_type"]
            d["group_load_kn"] = c["group_load_kn"]
            d["single_axle_kn"] = c["single_axle_kn"]
            d["wheel_load_n"] = c["wheel_load_n"]
        return result

    def _build_layer_report(
        self,
        thicknesses: List[float],
        solver_stack: list,
        moduli: List[float],
        input_bituminous: list,
    ) -> List[dict]:
        """
        One result row per logical layer (BC, DBM, WMM, GSB, ...) plus a
        Subgrade row at the bottom. When the solver collapsed unbound
        granular layers into a composite row, every collapsed logical
        layer reports the composite modulus — this is the modulus IIT
        Pave actually used for them.
        """
        layer_types = self.problem.layer_types
        n_bit = len(input_bituminous)
        # solver_stack is bituminous (top, 1:1) → granular block (1 or N rows) → subgrade.
        # The granular block may be a single composite row even when the
        # user defined multiple unbound granular layers.
        n_solver_granular = max(0, len(solver_stack) - 1 - n_bit)
        poissons = [l.get("poisson", 0.35) for l in solver_stack]

        rows: List[dict] = []
        for i, l_type in enumerate(layer_types):
            h = thicknesses[i] if i < len(thicknesses) else 0.0
            if i < n_bit:
                solver_row = i
            else:
                # Map logical granular index → solver-stack row.
                # When collapsed: every granular maps to the single composite row.
                # When per-layer: granular rows map 1:1 in original order.
                granular_logical_idx = i - n_bit
                if n_solver_granular == 1:
                    solver_row = n_bit
                else:
                    solver_row = n_bit + granular_logical_idx
            mod = moduli[solver_row] if solver_row < len(moduli) else moduli[-1]
            nu = poissons[solver_row] if solver_row < len(poissons) else poissons[-1]
            rows.append({
                "id": i + 1,
                "name": l_type,
                "thickness": h,
                "modulus": mod,
                "poisson": nu,
            })
        # Subgrade row — always last in solver_stack
        rows.append({
            "id": len(layer_types) + 1,
            "name": "Subgrade",
            "thickness": 0.0,
            "modulus": moduli[-1] if moduli else 0.0,
            "poisson": poissons[-1] if poissons else 0.35,
        })
        return rows

    # ------------------------------------------------------------------
    # Lift-aware enumeration of constructable thickness combinations
    # ------------------------------------------------------------------

    def _layer_lift_values(self, layer_type: str, lo: float, hi: float) -> List[float]:
        """
        Discrete thicknesses to explore for a single layer.

        Order of precedence:
          1. Fixed layer (lo == hi) ⇒ exactly one value.
          2. User-supplied lift override on the problem ⇒ filter to bounds.
          3. DEFAULT_LIFT_SCHEDULE for the layer type ⇒ filter to bounds.
          4. Fallback: 5 mm-step grid across [lo, hi].
        """
        # Fixed layer — bounds collapsed
        if abs(hi - lo) < 1e-9:
            return [float(lo)]

        # Resolve the lift list from problem override or module default
        user_schedule = getattr(self.problem, 'lift_schedule', None) or {}
        lifts = user_schedule.get(layer_type)
        if lifts is None:
            lifts = DEFAULT_LIFT_SCHEDULE.get(layer_type)

        if lifts:
            in_bounds = sorted({float(v) for v in lifts if lo <= float(v) <= hi})
            if in_bounds:
                return in_bounds
            logger.warning(
                "Layer %s: bounds [%s, %s] exclude every lift in the schedule; "
                "falling back to 5 mm-step grid",
                layer_type, lo, hi,
            )

        # Fallback grid
        values: List[float] = []
        v = float(lo)
        while v <= float(hi) + 1e-9:
            values.append(round(v, 3))
            v += _FALLBACK_STEP_MM
        return values

    # ------------------------------------------------------------------
    # IRC 37 / MoRTH minimum-thickness pre-filter (Severity-3 #3.1)
    # ------------------------------------------------------------------

    def _resolve_min_thickness_tier(self) -> Tuple[Dict[str, float], float]:
        """Return ({layer_type: min_mm}, bituminous_bundle_min_mm) for the
        current MSA, using the user's table if provided and the IRC/MoRTH
        defaults otherwise."""
        msa = self.problem.traffic.cumulative_msa()
        table = (
            getattr(self.problem, 'traffic_tier_minimums', None)
            or DEFAULT_TRAFFIC_TIER_MINIMUMS
        )
        for lo, hi, layer_mins, bundle_min in table:
            if lo <= msa < hi:
                return dict(layer_mins), float(bundle_min)
        # Fall through (msa above the topmost tier upper bound) — apply
        # the strictest entry's minimums.
        last = table[-1]
        return dict(last[2]), float(last[3])

    def _irc_mandatory_violation(self, combo: Tuple[float, ...]) -> Optional[str]:
        """
        Thickness rules stated explicitly in IRC:37-2018 (always enforced):
          * §9.2 (p. 42): pavements with a CTB carrying > 20 msa need a
            combined bituminous surface + base/binder thickness >= 100 mm;
          * §8.1: unbound granular layers >= 150 mm, except the crack-relief
            layer over a CTB, which is 100 mm (>= 100 mm accepted);
          * §8.4: emulsion/foam bitumen stabilised RAP base >= 100 mm.
        Returns a description of the first violation, or None.
        """
        layer_types = [str(lt).upper().strip() for lt in self.problem.layer_types]
        msa = self.problem.traffic.cumulative_msa()
        if any(lt in CTB_TYPES for lt in layer_types) and msa > 20.0:
            bit_total = sum(combo[i] for i, lt in enumerate(layer_types) if lt in BITUMINOUS_TYPES)
            if bit_total < 100.0 - 1e-9:
                return "bituminous bundle < 100 mm over a CTB for > 20 msa (IRC:37-2018 §9.2)"
        for i, lt in enumerate(layer_types):
            below = layer_types[i + 1] if i + 1 < len(layer_types) else None
            if lt == "CRL" or (lt in UNBOUND_CRACK_RELIEF_TYPES and below in CTB_TYPES):
                if combo[i] < 100.0 - 1e-9:
                    return f"crack-relief layer {lt} < 100 mm (IRC:37-2018 §8.1)"
            elif lt in UNBOUND_CRACK_RELIEF_TYPES:
                if combo[i] < 150.0 - 1e-9:
                    return f"unbound granular layer {lt} < 150 mm (IRC:37-2018 §8.1)"
            elif lt in COLD_RECYCLED_TYPES:
                if combo[i] < 100.0 - 1e-9:
                    return "stabilised RAP base < 100 mm (IRC:37-2018 §8.4)"
        return None

    def _passes_irc_minimums(self, combo: Tuple[float, ...]) -> bool:
        """
        True if `combo` satisfies the minimum thicknesses.

          1. IRC:37-2018 mandatory rules (_irc_mandatory_violation) — always.
          2. Traffic-tier practice minimums (MoRTH 500 / IRC SP-89): per-layer
             minimums and a bituminous-bundle minimum. These can be
             overridden through `OptimizationProblem.traffic_tier_minimums`
             or disabled with `ignore_minimum_thickness=True`.
        """
        if self._irc_mandatory_violation(combo) is not None:
            return False

        if getattr(self.problem, 'ignore_minimum_thickness', False):
            return True

        layer_mins, bundle_min = self._resolve_min_thickness_tier()
        layer_types = self.problem.layer_types

        # Per-layer minimums
        for i, lt in enumerate(layer_types):
            lt_up = str(lt).upper().strip()
            if lt_up in layer_mins and combo[i] < layer_mins[lt_up]:
                return False

        # Bituminous bundle — sum of all bituminous-class layers
        if bundle_min > 0:
            bit_total = sum(
                combo[i] for i, lt in enumerate(layer_types)
                if str(lt).upper().strip() in BITUMINOUS_TYPES
            )
            if bit_total < bundle_min:
                return False

        return True

    # ------------------------------------------------------------------
    # Lift-aware enumeration of constructable thickness combinations
    # ------------------------------------------------------------------

    def _enumerate_combinations(self) -> List[Tuple[float, ...]]:
        """
        Cartesian product of constructable lift sizes for every layer,
        filtered by traffic-tier minimum thicknesses (IRC 37 / MoRTH 500),
        and sorted by ascending real ₹/km cost so the brute-force loop
        hits cheapest designs first.
        """
        layer_types = self.problem.layer_types
        bounds = self.problem.thickness_bounds or {}

        per_layer: List[List[float]] = []
        for lt in layer_types:
            lo, hi = bounds.get(lt, (50.0, 200.0))
            per_layer.append(self._layer_lift_values(lt, lo, hi))

        sizes = [len(v) for v in per_layer]
        total = 1
        for s in sizes:
            total *= s
        if total == 0:
            return []
        if total > 50_000:
            logger.warning(
                "Search space is %d combinations (>50k); brute-force will be slow. "
                "Consider tighter thickness_bounds or a coarser lift_schedule.",
                total,
            )

        combos = list(itertools.product(*per_layer))

        # Apply IRC 37 / MoRTH minimum-thickness pre-filter BEFORE evaluation.
        # Catches non-compliant designs before they consume any bridge calls.
        before = len(combos)
        self._prefilter_reasons = sorted({
            v for v in (self._irc_mandatory_violation(c) for c in combos) if v
        })
        combos = [c for c in combos if self._passes_irc_minimums(c)]
        self._prefilter_emptied = before > 0 and not combos
        dropped = before - len(combos)
        if dropped:
            logger.info(
                "Minimum-thickness pre-filter dropped %d / %d combinations",
                dropped, before,
            )

        # Ordering — when optimize_by_cost is enabled, sort by ascending
        # ₹/km cost so the brute-force loop hits cheapest designs first.
        # Otherwise, sort by ascending total thickness (structural economy).
        if self._use_cost:
            cost_per_mm = [self._cost_per_cum(lt) for lt in layer_types]
            def _combo_sort_key(combo):
                return sum(combo[i] * cost_per_mm[i] for i in range(len(combo)))
        else:
            def _combo_sort_key(combo):
                return sum(combo)

        combos.sort(key=_combo_sort_key)
        return combos

    # ------------------------------------------------------------------
    # Brute-force evaluation with deadline / error / dedup discipline
    # ------------------------------------------------------------------

    def _brute_force(self) -> Tuple[List[dict], int]:
        """
        Evaluate every constructable combination once, in cost-ascending
        order. Returns (adequate_designs, n_evaluations).

        Designs are deduped by their thickness tuple; failed bridge calls
        are recorded but never re-tried. All successful evaluations are
        retained on `self._all_evaluated` for the infeasibility diagnostic.

        Severity-4 #4.5 — When `problem.parallel_workers > 1`, bridge
        calls are dispatched across N worker scratch directories so the
        legacy executable can run in parallel without colliding on the
        shared `IITPAVE.IN`/`.OUT` files.
        """
        combos = self._enumerate_combinations()
        logger.info("Brute-force search: %d valid lift combinations", len(combos))

        n_workers = max(1, int(getattr(self.problem, 'parallel_workers', 1) or 1))
        if n_workers > 1 and len(combos) >= 2:
            return self._brute_force_parallel(combos, n_workers)
        return self._brute_force_serial(combos)

    def _brute_force_serial(self, combos) -> Tuple[List[dict], int]:
        """Single-threaded brute-force pass (the default)."""
        adequate: List[dict] = []
        all_evaluated: List[dict] = []
        n_evals = 0
        seen: set = set()

        for combo in combos:
            if self._deadline_passed():
                logger.warning(
                    "Brute force: deadline reached after %d / %d evaluations",
                    n_evals, len(combos),
                )
                break
            key = tuple(combo)
            if key in seen:
                continue
            seen.add(key)
            try:
                result = self._evaluate(list(combo))
                n_evals += 1
            except Exception as e:
                n_evals += 1
                logger.exception("Bridge evaluation failed for combo=%s", combo)
                try:
                    self._errors.append(f"brute:{combo}:{e}")
                except Exception:
                    logger.exception("Failed to record brute-force error")
                continue
            all_evaluated.append(result)
            if result.get("overall_adequate"):
                adequate.append(result)

        self._all_evaluated = all_evaluated
        logger.info(
            "Brute-force complete: %d adequate / %d evaluated", len(adequate), n_evals,
        )
        return adequate, n_evals

    def _brute_force_parallel(self, combos, n_workers: int) -> Tuple[List[dict], int]:
        """
        Multi-threaded brute-force pass using the native solver.
        The native solver is thread-safe so no scratch directories are needed.
        """
        n_workers = min(n_workers, len(combos))
        logger.info("Brute-force parallel: %d workers", n_workers)

        adequate: List[dict] = []
        all_evaluated: List[dict] = []
        seen: set = set()
        cancel = threading.Event()
        eval_lock = threading.Lock()

        def worker(combo):
            if cancel.is_set() or self._deadline_passed():
                cancel.set()
                return None
            try:
                return self._evaluate(list(combo))
            except Exception:
                return None

        # Pre-dedup
        unique_combos = []
        for combo in combos:
            key = tuple(combo)
            if key in seen:
                continue
            seen.add(key)
            unique_combos.append(combo)

        with ThreadPoolExecutor(max_workers=n_workers) as ex:
            futures = {ex.submit(worker, c): c for c in unique_combos}
            n_evals = 0
            for fut in futures:
                if self._deadline_passed():
                    cancel.set()
                combo = futures[fut]
                try:
                    result = fut.result()
                except Exception as e:
                    with eval_lock:
                        n_evals += 1
                    logger.exception("Evaluation failed for combo=%s", combo)
                    try:
                        self._errors.append(f"brute:{combo}:{e}")
                    except Exception:
                        pass
                    continue
                if result is None:
                    continue
                with eval_lock:
                    n_evals += 1
                    all_evaluated.append(result)
                    if result.get("overall_adequate"):
                        adequate.append(result)

        # Determinism — re-sort by a stable key.
        sort_key = "cost_per_km" if self._use_cost else "total_thickness"
        adequate.sort(key=lambda d: (d[sort_key], tuple(d["thicknesses"])))
        all_evaluated.sort(key=lambda d: (d[sort_key], tuple(d["thicknesses"])))

        self._all_evaluated = all_evaluated
        logger.info(
            "Brute-force parallel complete: %d adequate / %d evaluated", len(adequate), n_evals,
        )
        return adequate, n_evals

    # ------------------------------------------------------------------
    # Archetype selection helpers.
    # _governing_cdf is used by the adequacy/diagnostic paths. _pareto_front
    # and _kneedle_balanced are retained as standalone analysis utilities
    # (and are unit-tested directly); the four user-facing archetypes are
    # selected by _select_archetypes via direct single-objective optima.
    # ------------------------------------------------------------------

    @staticmethod
    def _governing_cdf(d: dict) -> float:
        """Worst-case CDF among the three failure modes."""
        return max(
            d.get("CDF_fatigue", 0.0) or 0.0,
            d.get("CDF_rutting", 0.0) or 0.0,
            d.get("CDF_ctb") or 0.0,
        )

    @staticmethod
    def _pareto_front(adequate: List[dict], use_cost: bool = True) -> List[dict]:
        """
        Non-dominated front in (X, governing-CDF) space where X is
        cost_per_km (when optimize_by_cost) or total_thickness (default).
        """
        if not adequate:
            return []
        x_key = "cost_per_km" if use_cost else "total_thickness"
        sorted_by_x = sorted(adequate, key=lambda d: d[x_key])
        front: List[dict] = []
        best_cdf = float("inf")
        for d in sorted_by_x:
            cdf = SmartPavementSearch._governing_cdf(d)
            if cdf < best_cdf - 1e-12:
                front.append(d)
                best_cdf = cdf
        return front

    @staticmethod
    def _kneedle_balanced(front: List[dict], use_cost: bool = True) -> Optional[dict]:
        """
        Pareto knee detection. Uses cost_per_km or total_thickness as the
        X axis depending on optimize_by_cost toggle.
        """
        if len(front) < 3:
            return None
        x_key = "cost_per_km" if use_cost else "total_thickness"
        xs = [d[x_key] for d in front]
        cdfs = [SmartPavementSearch._governing_cdf(d) for d in front]
        x_lo, x_hi = min(xs), max(xs)
        d_lo, d_hi = min(cdfs), max(cdfs)
        x_range = (x_hi - x_lo) if x_hi > x_lo else 1.0
        d_range = (d_hi - d_lo) if d_hi > d_lo else 1.0

        best_idx = min(
            range(len(front)),
            key=lambda i: (xs[i] - x_lo) / x_range + (cdfs[i] - d_lo) / d_range,
        )
        if best_idx in (0, len(front) - 1):
            best_idx = len(front) // 2
        return front[best_idx]

    def _select_archetypes(self, adequate: List[dict]) -> List[ParetoSolution]:
        """
        Pick four single-purpose archetypes from the IRC-adequate design set.
        Every candidate already satisfies all IRC:37 CDFs ≤ 1.0; each archetype
        is a direct optimum of one objective (or a balance of all three):

          - Structural : THINNEST adequate design — minimum total material
                         (the pure structural optimum / direct solver result).
          - Economy    : CHEAPEST adequate design (minimum ₹/km).
          - Sustainable: GREENEST adequate design (minimum embodied CO₂/km).
          - Premium    : best COMBINED optimum — jointly minimises thickness,
                         cost AND CO₂ (closest to the utopia corner in
                         equally-weighted, min-max-normalised space).

        Cost and CO₂ are only consumed by the Economy / Sustainable / Premium
        archetypes, which are emitted only when the user opts into that
        objective; the cost estimator is not even run otherwise (cost_per_km /
        co2_per_km stay None). When two archetypes resolve to the same design
        their labels are merged (e.g. "Economy + Sustainable") so the UI never
        shows duplicate cards.
        """
        if not adequate:
            return []

        def _thk(d): return float(d.get("total_thickness", 0.0) or 0.0)
        def _cost(d): return float(d.get("cost_per_km", 0.0) or 0.0)
        def _co2(d): return float(d.get("co2_per_km", 0.0) or 0.0)
        def _key(d): return tuple(d.get("thicknesses") or [])

        # Structural (thinnest) is ALWAYS returned — the pure IRC structural
        # optimum, selected purely on thickness, needing no economic data.
        structural = min(adequate, key=lambda d: (_thk(d), _cost(d), _co2(d), _key(d)))

        non_monotone = self._detect_non_monotonicity(structural, adequate)

        # The cost/CO₂-based archetypes are computed ONLY for the objectives the
        # user opted into — so cost/CO₂ values (which are None when no objective
        # is active) are never consumed unless they were actually computed:
        #   Economy     ← optimize_by_cost   (needs ₹/m³ rates)
        #   Sustainable ← optimize_by_co2    (needs kg CO₂/m³ rates)
        #   Premium     ← BOTH (it is the combined thickness+cost+CO₂ optimum)
        want_cost = bool(getattr(self.problem, 'optimize_by_cost', False))
        want_co2 = bool(getattr(self.problem, 'optimize_by_co2', False))

        ordered = [(structural, "Structural")]
        if want_cost:
            economy = min(adequate, key=lambda d: (_cost(d), _thk(d), _co2(d), _key(d)))
            ordered.append((economy, "Economy"))
        if want_co2:
            sustainable = min(adequate, key=lambda d: (_co2(d), _cost(d), _thk(d), _key(d)))
            ordered.append((sustainable, "Sustainable"))
        if want_cost and want_co2:
            # Premium = equally-weighted combined optimum (thickness+cost+CO₂).
            # Min-max normalise each objective so the three units are comparable.
            def _span(vals):
                lo, hi = min(vals), max(vals)
                return lo, (hi - lo) if hi > lo else 1.0
            t_lo, t_rng = _span([_thk(d) for d in adequate])
            c_lo, c_rng = _span([_cost(d) for d in adequate])
            g_lo, g_rng = _span([_co2(d) for d in adequate])

            def _combined(d):
                return (
                    (_thk(d) - t_lo) / t_rng
                    + (_cost(d) - c_lo) / c_rng
                    + (_co2(d) - g_lo) / g_rng
                )
            premium = min(adequate, key=lambda d: (_combined(d), _cost(d), _thk(d), _key(d)))
            ordered.append((premium, "Premium"))
        by_key: Dict[tuple, dict] = {}
        order: List[tuple] = []
        for design, label in ordered:
            k = _key(design)
            if k in by_key:
                by_key[k]["_labels"].append(label)
                continue
            entry = dict(design)
            entry["_labels"] = [label]
            if k == _key(structural) and non_monotone:
                entry["non_monotonic_neighbours"] = non_monotone
            by_key[k] = entry
            order.append(k)

        archetypes: List[ParetoSolution] = []
        for k in order:
            data = by_key[k]
            data["strategy"] = " + ".join(data.pop("_labels"))
            archetypes.append(ParetoSolution(
                optimal_thicknesses=data["thicknesses"],
                optimal_materials={},
                cost=data["cost_per_km"],
                co2=data["co2_per_km"],
                performance=data,
            ))
        return archetypes

    def _detect_non_monotonicity(
        self,
        anchor: dict,
        adequate: List[dict],
    ) -> List[dict]:
        """
        Severity-4 #4.1 — verify that the chosen anchor sits on a locally
        monotone region of the (thickness → CDF) surface. For each layer,
        find a neighbour that's one lift smaller in just that layer (others
        unchanged); if its governing CDF is *lower* than the anchor's, the
        surface is non-monotone here and the engineer should review.

        Returns a list of {"layer_index", "thickness_drop_mm", "anchor_cdf",
        "neighbour_cdf"} entries — empty if everything is monotone.

        We never issue extra bridge calls — every neighbour is already in
        the brute-force adequate set, so this is essentially free.
        """
        flags: List[dict] = []
        anchor_thk = list(anchor.get("thicknesses") or [])
        anchor_cdf = self._governing_cdf(anchor)

        # Index adequate designs by their thickness tuple for O(1) lookup
        index = {tuple(d["thicknesses"]): d for d in adequate}

        for layer_idx in range(len(anchor_thk)):
            # Find the next-smaller adequate thickness for this single layer
            others = list(anchor_thk)
            candidates = [
                t for t in
                {d["thicknesses"][layer_idx] for d in adequate if d["thicknesses"][:layer_idx] + d["thicknesses"][layer_idx+1:] == others[:layer_idx] + others[layer_idx+1:]}
                if t < anchor_thk[layer_idx]
            ]
            if not candidates:
                continue
            closest = max(candidates)
            others[layer_idx] = closest
            neighbour = index.get(tuple(others))
            if neighbour is None:
                continue
            neigh_cdf = self._governing_cdf(neighbour)
            if neigh_cdf < anchor_cdf - 1e-9:
                flags.append({
                    "layer_index": layer_idx,
                    "layer_name": self.problem.layer_types[layer_idx]
                        if layer_idx < len(self.problem.layer_types) else f"L{layer_idx}",
                    "thickness_drop_mm": anchor_thk[layer_idx] - closest,
                    "anchor_cdf": round(anchor_cdf, 4),
                    "neighbour_cdf": round(neigh_cdf, 4),
                })
        return flags

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self,
            timeout: Optional[float] = None,
            deadline: Optional[float] = None) -> OptimizationResult:
        """
        Run the brute-force lift-aware search.

        Pipeline:
            1. Enumerate every constructable combination of layer thicknesses
               (lift schedule × bounds). Default schedule is MoRTH 500.
            2. Evaluate each through the native Burmister solver; collect
               designs whose IRC CDFs (fatigue + rutting + CTB if applicable)
               are all ≤ 1. Cost and CO₂ are computed for each.
            3. Select four archetypes from the adequate set: Structural
               (thinnest), Economy (cheapest), Sustainable (lowest CO₂) and
               Premium (best combined thickness+cost+CO₂); coincident designs
               merge their labels.

        Args:
            timeout: optional wall-clock budget in seconds. The optimizer
                checks the deadline between bridge calls and returns early
                with whatever adequate designs were collected so far.
            deadline: alternative form — an absolute ``time.monotonic()``
                value. Wins over ``timeout`` when both are supplied.
        """
        # Resolve the absolute deadline (if any) once at the top of the run.
        if deadline is not None:
            self._deadline = float(deadline)
        elif timeout is not None:
            self._deadline = time.monotonic() + float(timeout)
        else:
            self._deadline = None

        # Severity-4 #4.4 — size the iitpave_bridge result cache for this run
        # and restore the caller's setting afterwards. Note: the optimizer's
        # own calls go through legacy_bridge.run_bridge_from_stack, which is
        # the UNCACHED solver facade; the cache only serves direct callers of
        # iitpave_bridge.run_iitpave_bridge.
        prev_cache_max = get_bridge_cache_stats().get("max", 0)
        set_bridge_cache_size(max(prev_cache_max, 4096))
        try:
            adequate_list, n_evals = self._brute_force()
        finally:
            set_bridge_cache_size(prev_cache_max)
        has_adequate = bool(adequate_list)
        logger.info("Search complete: %d evaluations, %d adequate designs",
                     n_evals, len(adequate_list))

        archetypes = self._select_archetypes(adequate_list)

        # Fallback: nothing satisfied IRC adequacy. Return the cheapest
        # *evaluated* design as a "Preliminary" suggestion with its real
        # cost (NOT a placeholder) so the UI surfaces an honest answer.
        # Severity-4 #4.3 — explicit infeasibility messaging. The earlier
        # behaviour returned a "Preliminary" archetype with no diagnostic
        # info, leaving the engineer to guess why no design passed. Now
        # we emit a structured error message with the most-failed CDF and
        # an actionable hint (relax bounds / revisit traffic / revisit CBR).
        infeasibility_msg: Optional[str] = None
        if not archetypes:
            preliminary_thicknesses = self._fallback_thicknesses()
            try:
                cost_specs = [
                    LayerCostSpec(self.problem.layer_types[i], preliminary_thicknesses[i])
                    for i in range(len(preliminary_thicknesses))
                ]
                cost_res = estimate_cost(
                    cost_specs,
                    lane_width_m=self.problem.lane_width_m,
                    rates=self._material_rates,
                )
                fallback_cost = cost_res.total_cost_per_km
                fallback_co2 = cost_res.total_co2_per_km
            except Exception:
                logger.exception("Failed to compute fallback cost")
                fallback_cost = 0.0
                fallback_co2 = 0.0

            # Find the design that came closest to passing — minimum
            # max(CDF) across the EVALUATED set (not adequate_list, which
            # is empty here). We re-evaluate with the brute-force budget
            # cap to capture this for diagnostic output.
            closest_to_passing = self._closest_to_passing_diagnostic()
            msa = self.problem.traffic.cumulative_msa()

            if closest_to_passing is not None:
                worst_cdf = closest_to_passing["max_cdf"]
                gov = closest_to_passing.get("governing_mode", "fatigue")
                infeasibility_msg = (
                    f"Infeasible at given bounds for {msa:.1f} MSA traffic. "
                    f"Best evaluated design has max CDF = {worst_cdf:.2f} "
                    f"(governed by {gov}). To find an adequate design, "
                    f"either: (a) relax thickness_bounds upward, "
                    f"(b) revisit subgrade CBR (current effective modulus "
                    f"{self.problem.subgrade.modulus:.0f} MPa), "
                    f"or (c) revisit traffic inputs (CVPD/VDF/growth/design life)."
                )
            elif getattr(self, '_prefilter_emptied', False):
                reasons = getattr(self, '_prefilter_reasons', []) or [
                    "the traffic-tier practice minimums (set ignore_minimum_thickness "
                    "to disable them)"
                ]
                infeasibility_msg = (
                    f"Infeasible at given bounds for {msa:.1f} MSA traffic: every "
                    f"thickness combination violates a minimum-thickness rule — "
                    f"{'; '.join(reasons)}. Raise the thickness bounds."
                )
            else:
                infeasibility_msg = (
                    f"Infeasible at given bounds for {msa:.1f} MSA traffic. "
                    f"No design was successfully evaluated — check that the "
                    f"lift schedule and the thickness bounds intersect."
                )

            logger.warning(infeasibility_msg)

            placeholder = {
                "thicknesses": preliminary_thicknesses,
                "total_thickness": sum(preliminary_thicknesses),
                "overall_adequate": False,
                "strategy": "Preliminary",
                "cost_per_km": fallback_cost,
                "co2_per_km": fallback_co2,
                "infeasibility_reason": infeasibility_msg,
            }
            archetypes = [
                ParetoSolution(
                    optimal_thicknesses=preliminary_thicknesses,
                    optimal_materials={},
                    cost=fallback_cost,
                    co2=fallback_co2,
                    performance=placeholder,
                )
            ]

        best = archetypes[0]
        warnings = self._build_warnings()
        # Carry the infeasibility message into the errors list AND the
        # warnings list. Errors are only returned by the API in debug mode,
        # so warnings are the channel that reaches the dashboard user.
        result_errors = list(getattr(self, '_errors', None) or [])
        if infeasibility_msg:
            result_errors.insert(0, infeasibility_msg)
            warnings.insert(0, infeasibility_msg)

        return OptimizationResult(
            optimal_thicknesses=best.optimal_thicknesses,
            optimal_materials={},
            layer_types=self.problem.layer_types,
            cost=best.cost,
            co2=best.co2,
            is_feasible=has_adequate,
            performance=best.performance,
            pareto_front=archetypes,
            errors=result_errors or None,
            warnings=warnings or None,
        )

    def _closest_to_passing_diagnostic(self) -> Optional[dict]:
        """
        Pull the lowest-max-CDF design from any cached evaluation results.
        We stash these on `self._all_evaluated` during the brute-force run
        so this diagnostic doesn't issue extra bridge calls.
        """
        evaluated = getattr(self, '_all_evaluated', None) or []
        if not evaluated:
            return None
        scored = [
            (self._governing_cdf(d), d) for d in evaluated
        ]
        scored.sort(key=lambda x: x[0])
        max_cdf, best = scored[0]
        return {
            "max_cdf": max_cdf,
            "thicknesses": best.get("thicknesses"),
            "governing_mode": best.get("governing_mode"),
        }

    def _fallback_thicknesses(self) -> List[float]:
        """Smallest constructable design within bounds — used when no
        combination satisfies IRC adequacy. Returns the thinnest lift
        size for each layer (or its lower bound if the lift schedule
        doesn't cover the bound)."""
        layer_types = self.problem.layer_types
        bounds = self.problem.thickness_bounds or {}
        out: List[float] = []
        for lt in layer_types:
            lo, hi = bounds.get(lt, (50.0, 200.0))
            options = self._layer_lift_values(lt, lo, hi)
            out.append(options[0] if options else float(lo))
        return out
