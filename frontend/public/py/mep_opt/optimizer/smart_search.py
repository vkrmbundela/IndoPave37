"""
Smart Pavement Search Optimizer
================================
Brute-force Pareto search over a discrete, MoRTH-500-aligned lift schedule.

For a typical 4-layer pavement (BC/DBM/WMM/GSB) the constructable lift
sizes give roughly 100–300 valid combinations — small enough to evaluate
exhaustively. The optimizer:

  1. Enumerates every (BC, DBM, WMM, GSB, ...) combination whose values
     are taken from the lift schedule and lie within the user's bounds.
  2. Runs each design through IIT Pave (one or two bridge calls, depending
     on whether a CTB layer is present — IRC 37 mandates a separate
     0.80 MPa pressure for cement-treated tensile-stress analysis).
  3. Filters to designs with all CDFs ≤ 1.0 (IRC adequacy).
  4. Computes the non-dominated Pareto front in (cost, max-CDF) space.
  5. Picks three archetypes from the front:
       Economy  = lowest cost
       Premium  = cheapest design with max(CDF) ≤ premium_cdf_ceiling
                  (default 0.6 — gives a 40% reserve)
       Balanced = the knee of the cost-vs-CDF Pareto curve (Kneedle)

Every evaluation runs the IIT Pave legacy executable via the bridge.
"""

import logging
import itertools
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Optional, Tuple

from mep_opt.solver.irc37 import (
    AxleLoadGroup, ReliabilityLevel,
    check_design_adequacy, check_ctb_adequacy,
    BituminousLayerInput, GranularLayerInput, build_layer_stack,
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
GRANULAR_TYPES = {"WMM", "WBM", "GSB", "CTB"}
CEMENT_TREATED_TYPES = {"CTB"}

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
        reliability = getattr(self.problem, "reliability", ReliabilityLevel.R90)

        if growth_rate < 0.05:
            warnings.append(
                f"Traffic growth rate {growth_rate:.3f} is below 5%; "
                "design traffic may be optimistic relative to standard practice."
            )

        if msa >= 30.0 and reliability != ReliabilityLevel.R90:
            warnings.append(
                f"High-MSA traffic ({msa:.1f} MSA) normally uses R90; "
                f"current reliability {getattr(reliability, 'name', reliability)} will be treated conservatively."
            )

        if getattr(self.problem, "ctb_axle_spectrum", None) and not getattr(self.problem, "ctb_per_class_bridge_recompute", False):
            warnings.append(
                "CTB axle-spectrum damage is being estimated by linear stress scaling from the reference bridge call; "
                "set ctb_per_class_bridge_recompute=True to re-run the bridge for each axle class."
            )

        return warnings

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
        where ctb_depth is the depth (mm) to the bottom of the first CTB
        layer if any, else None.
        """
        layer_types = self.problem.layer_types
        subgrade = self.problem.subgrade
        temp = self.problem.temperature

        cost_specs = []
        input_bituminous = []
        input_granular = []

        for i, l_type in enumerate(layer_types):
            h = thicknesses[i]
            cost_specs.append(LayerCostSpec(l_type, h))

            if l_type in BITUMINOUS_TYPES:
                custom_props = (self.problem.layer_props or {}).get(l_type, {})
                mod = custom_props.get('E', get_modulus(l_type, temperature=temp))
                nu = custom_props.get('nu', get_poisson(l_type))
                input_bituminous.append(
                    BituminousLayerInput(l_type, h, mod, nu)
                )
            elif l_type in GRANULAR_TYPES:
                custom_props = (self.problem.layer_props or {}).get(l_type, {})
                custom_E = custom_props.get('E')
                custom_nu = custom_props.get('nu')
                # CTB is cement-treated, not granular: it must use its own
                # stiffness (~5000 MPa) instead of the empirical
                # 0.2·h^0.45·MR_support formula that build_layer_stack falls
                # back to for unbound granular layers.
                if l_type in CEMENT_TREATED_TYPES and custom_E is None:
                    custom_E = get_modulus(l_type)
                input_granular.append({
                    "thickness": h,
                    "layer_type": l_type,
                    "E": custom_E,
                    "nu": custom_nu,
                    "geogrid": custom_props.get('geogrid'),
                })

        solver_stack = build_layer_stack(
            subgrade, input_granular, input_bituminous, self.problem.layer_props
        )

        # Depth (mm from surface) to the bottom of the first CTB layer, if any.
        # Order in the actual solver stack is: bituminous (top) → granular → subgrade,
        # so depth = sum(bituminous thicknesses) + sum(granular thicknesses up to & incl CTB).
        ctb_depth: Optional[float] = None
        cum = sum(l.thickness for l in input_bituminous)
        for gran in input_granular:
            cum += gran["thickness"]
            if gran["layer_type"] in CEMENT_TREATED_TYPES:
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

        # Subgrade top — always present (every pavement has a subgrade)
        std_idx_map["sub_top"] = [
            len(std_points),
            len(std_points) + 1,
        ]
        std_points.extend([
            {"z": depth_sub - 0.1, "r": 0},
            {"z": depth_sub - 0.1, "r": 155},
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

        # Fatigue tensile strain — only meaningful when bituminous layers exist.
        # Granular-only sections have no fatigue criterion (eps_t = 0 → CDF = 0).
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
        rel = self.problem.reliability

        chk = check_design_adequacy(eps_t, eps_v, msa, bot_mod, rel)
        cost_res = estimate_cost(
            cost_specs,
            lane_width_m=self.problem.lane_width_m,
            rates=self._material_rates,
        )
        moduli = [l['modulus'] for l in solver_stack]

        # CTB fatigue check — uses the SECOND bridge call's σ_t at 0.80 MPa
        # (IRC-compliant) instead of reading from the 0.56 MPa pass. Earlier
        # code conflated the two pressures and under-reported σ_t by ~30–40%.
        ctb_cdf: Optional[float] = None
        ctb_adequate = True
        sigma_t_ctb: Optional[float] = None
        ctb_details: Optional[dict] = None
        if "ctb_bottom" in ctb_idx_map:
            ctb_props = (self.problem.layer_props or {}).get("CTB", {})
            mor = ctb_props.get("MOR", 1.4)  # IRC 37 default modulus of rupture (MPa)
            ctb_rows = [results_ctb[i] for i in ctb_idx_map["ctb_bottom"]]
            sigma_t_ctb = max(abs(r["sigma_t"]) for r in ctb_rows)
            ctb_spec = list(getattr(self.problem, "ctb_axle_spectrum", None) or [])
            if ctb_spec:
                if getattr(self.problem, "ctb_per_class_bridge_recompute", False):
                    computed_stresses: List[float] = []
                    for load_group in ctb_spec:
                        load_ctb = dict(load_standard)
                        load_ctb["load"] = float(load_group.load_kn) * 1000.0
                        try:
                            group_results = self._bridge_call(solver_stack, load_ctb, ctb_points)
                        except Exception as e:
                            logger.exception("Bridge evaluation failed for CTB spectrum group=%s thicknesses=%s", load_group, thicknesses)
                            try:
                                self._errors.append(str(e))
                            except Exception:
                                logger.exception("Failed to record CTB spectrum error")
                            raise
                        if not group_results or len(group_results) < len(ctb_points):
                            raise RuntimeError("Legacy bridge returned insufficient CTB spectrum results")
                        computed_stresses.append(max(abs(r["sigma_t"]) for r in group_results))
                else:
                    ref_load_n = float(load_standard["load"])
                    if ref_load_n <= 0:
                        raise ValueError("Reference load must be positive for CTB spectrum scaling")
                    computed_stresses = [
                        sigma_t_ctb * ((float(load_group.load_kn) * 1000.0) / ref_load_n)
                        for load_group in ctb_spec
                    ]
                ctb_check = check_ctb_adequacy(ctb_spec, computed_stresses, mor)
                ctb_details = ctb_check
                ctb_cdf = ctb_check["CDF_ctb"]
                ctb_adequate = ctb_check["ctb_adequate"]
            else:
                single_group = [AxleLoadGroup("reference", float(load_standard["load"]) / 1000.0, msa * 1e6)]
                ctb_check = check_ctb_adequacy(single_group, [sigma_t_ctb], mor)
                ctb_details = ctb_check
                ctb_cdf = ctb_check["CDF_ctb"]
                ctb_adequate = ctb_check["ctb_adequate"]

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
            "CDF_fatigue": chk["CDF_fatigue"],
            "CDF_rutting": chk["CDF_rutting"],
            "CDF_ctb": ctb_cdf,
            "ctb_details": ctb_details,
            "Nf": chk["Nf"],
            "NR": chk["NR"],
            "overall_adequate": overall_adequate,
            "ctb_adequate": ctb_adequate,
            "governing_mode": governing_mode,
            "msa": msa,
            "cost_per_km": cost_res.total_cost_per_km,
            "co2_per_km": cost_res.total_co2_per_km,
            # Layer report is keyed off the user's layer_types (one row per
            # logical layer + subgrade) — NOT off solver_stack, because
            # solver_stack collapses unbound granular layers into a single
            # composite row per IRC 37 §7.2.3. Modulus is read from the
            # logical-row -> solver-row mapping below.
            "layers": self._build_layer_report(
                thicknesses, solver_stack, moduli, input_bituminous,
            ),
        }

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

        rows: List[dict] = []
        for i, l_type in enumerate(layer_types):
            h = thicknesses[i] if i < len(thicknesses) else 0.0
            if i < n_bit:
                mod = moduli[i]
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
            rows.append({
                "id": i + 1,
                "name": l_type,
                "thickness": h,
                "modulus": mod,
            })
        # Subgrade row — always last in solver_stack
        rows.append({
            "id": len(layer_types) + 1,
            "name": "Subgrade",
            "thickness": 0.0,
            "modulus": moduli[-1] if moduli else 0.0,
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

    def _passes_irc_minimums(self, combo: Tuple[float, ...]) -> bool:
        """
        True if `combo` satisfies the active traffic-tier minimums.

        Two checks:
          1. Per-layer minimums (e.g. BC ≥ 40 mm for >20 MSA).
          2. Bituminous-bundle minimum (e.g. BC + DBM ≥ 100 mm for
             CTB pavements > 20 MSA — IRC 37:2018 page 42 mandatory rule).

        The IRC-direct CTB+>20MSA bundle rule is enforced unconditionally;
        the per-layer minimums are MoRTH practice and can be overridden
        through `OptimizationProblem.traffic_tier_minimums` or disabled
        with `ignore_minimum_thickness=True`.
        """
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
        combos = [c for c in combos if self._passes_irc_minimums(c)]
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
    # Pareto front + Kneedle (Balanced) + premium-ceiling (Premium)
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
        Pick Economy, Balanced, Premium from the Pareto front.

        Selection rules:
          - Economy  : minimum cost on the front (= front[0])
          - Premium  : cheapest design with max(CDF) ≤ premium_cdf_ceiling.
                       If no front point clears the ceiling, fall back to
                       the lowest-CDF point on the front (= front[-1]).
          - Balanced : Kneedle knee point of the (cost, CDF) Pareto curve.
                       Skipped if the front has fewer than three distinct
                       points (Economy and Premium are then sufficient).
        """
        if not adequate:
            return []

        front = self._pareto_front(adequate, use_cost=self._use_cost)
        if not front:
            return []

        archetypes: List[ParetoSolution] = []

        def _to_pareto(data: dict, label: str) -> ParetoSolution:
            data["strategy"] = label
            return ParetoSolution(
                optimal_thicknesses=data["thicknesses"],
                optimal_materials={},
                cost=data["cost_per_km"],
                co2=data["co2_per_km"],
                performance=data,
            )

        # Economy — cheapest on the front. Local-monotonicity probe attached
        # so the UI can warn if a thinner neighbour somehow has lower CDF
        # (Severity-4 #4.1). The probe re-uses the existing brute-force
        # adequate set — no extra bridge calls.
        econ = front[0]
        non_monotone = self._detect_non_monotonicity(econ, adequate)
        if non_monotone:
            econ = dict(econ)  # don't mutate the original
            econ["non_monotonic_neighbours"] = non_monotone
            logger.warning(
                "Economy design has non-monotonic neighbours: %s",
                non_monotone,
            )
        archetypes.append(_to_pareto(econ, "Economy"))

        # Premium = argmin(cost) subject to max(CDF) ≤ ceiling.
        # Severity-4 #4.2 — explicit (cost, CDF) tiebreaker: cost is the
        # primary key (cheapest design that clears the ceiling); CDF is
        # the tiebreaker when two designs have identical cost (rare but
        # possible — e.g. layer-thickness symmetries or rounding).
        ceiling = float(getattr(self.problem, 'premium_cdf_ceiling', 0.6))
        x_key = "cost_per_km" if self._use_cost else "total_thickness"
        below_ceiling = sorted(
            [d for d in front if self._governing_cdf(d) <= ceiling],
            key=lambda d: (d[x_key], self._governing_cdf(d)),
        )
        if below_ceiling:
            prem = below_ceiling[0]
        else:
            # No design clears the ceiling — fall back to the lowest-CDF
            # point on the front, breaking ties by cost.
            prem = sorted(
                front,
                key=lambda d: (self._governing_cdf(d), d["cost_per_km"]),
            )[0]
        if prem["thicknesses"] != econ["thicknesses"]:
            archetypes.append(_to_pareto(prem, "Premium"))

        # Balanced — Kneedle knee, only if it isn't already Economy or Premium
        bal = self._kneedle_balanced(front, use_cost=self._use_cost)
        if bal is not None and all(
            bal["thicknesses"] != a.optimal_thicknesses for a in archetypes
        ):
            archetypes.append(_to_pareto(bal, "Balanced"))

        # Carbon — Severity-4 #4.6: optional 4th archetype behind a flag.
        # Carbon ranking ≈ cost ranking in most projects, so we only add
        # this when the user asks AND the design differs from the others.
        if getattr(self.problem, 'include_carbon_archetype', False):
            # Lowest CO₂/km among adequate designs, tiebreak by lowest cost
            carbon = sorted(
                adequate,
                key=lambda d: (d.get("co2_per_km", 0.0), d.get("cost_per_km", 0.0)),
            )[0]
            if all(
                carbon["thicknesses"] != a.optimal_thicknesses for a in archetypes
            ):
                archetypes.append(_to_pareto(carbon, "Carbon"))

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
            2. Evaluate each through IIT Pave; collect designs whose three
               IRC CDFs (fatigue + rutting + CTB if applicable) all ≤ 1.
            3. Compute the Pareto front in (cost, max-CDF) space.
            4. Pick Economy / Balanced / Premium from the front.

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

        # Severity-4 #4.4 — enable the bridge result cache for the duration
        # of this run. The cache is keyed on the full call signature and
        # turns same-stack-different-eval-points or repeat-stack queries
        # (e.g. CTB designs evaluated at both 0.56 and 0.80 MPa) into
        # near-instant hits. Capacity sized for one optimizer run.
        prev_cache_stats = get_bridge_cache_stats()
        set_bridge_cache_size(max(prev_cache_stats.get("max", 0), 4096))

        adequate_list, n_evals = self._brute_force()
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
            else:
                infeasibility_msg = (
                    f"Infeasible at given bounds for {msa:.1f} MSA traffic. "
                    f"No design was successfully evaluated — check that the "
                    f"lift schedule and bounds intersect, and that the "
                    f"bridge executable is reachable."
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
        # Carry the infeasibility message into the errors list so the API
        # surfaces it without changing the response schema.
        result_errors = list(getattr(self, '_errors', None) or [])
        if infeasibility_msg:
            result_errors.insert(0, infeasibility_msg)

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
