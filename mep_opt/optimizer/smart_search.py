"""
Smart Pavement Search Optimizer
================================
Hybrid incremental + targeted grid search for pavement thickness optimization.
Replaces the GA with a deterministic, fast algorithm that exploits monotonicity:
  "thicker layers always improve (or maintain) structural adequacy"

Phase 1 — Greedy Climb: Start from min thicknesses, increment cheapest layer
           by 5mm until first adequate design is found. (~80-200 bridge calls)

Phase 2 — Boundary Sweep: Grid-search combinations near the boundary,
           sorted by ascending total thickness with early termination.
           Collects Economy / Balanced / Premium archetypes. (~200-2000 calls)

Every evaluation runs the IIT Pave legacy executable via the bridge.
"""

import logging
import itertools
from typing import List, Dict, Tuple

from mep_opt.solver.irc37 import (
    check_design_adequacy, BituminousLayerInput,
    GranularLayerInput, build_layer_stack,
)
from mep_opt.solver.materials import get_modulus, get_poisson
from mep_opt.solver.legacy_bridge import run_bridge_from_stack, is_bridge_available
from mep_opt.cost import estimate_cost, LayerCostSpec
from mep_opt.optimizer.problem import OptimizationProblem, OptimizationResult, ParetoSolution

logger = logging.getLogger(__name__)

BITUMINOUS_TYPES = {"BC", "DBM", "BM", "SDBC", "SMA"}
GRANULAR_TYPES = {"WMM", "WBM", "GSB", "CTB"}

# Cost weight per mm thickness — cheaper layers are incremented first
# (granular is cheap to add, bituminous is expensive)
_LAYER_COST_WEIGHT = {
    "GSB": 1, "WBM": 2, "WMM": 3, "CTB": 5,
    "BM": 8, "SDBC": 9, "DBM": 10, "BC": 12, "SMA": 14,
}


class SmartPavementSearch:
    """
    Deterministic optimizer for pavement layer thicknesses.
    Finds the thinnest adequate design, then collects archetypes.
    """

    def __init__(self, problem: OptimizationProblem):
        self.problem = problem
        if not is_bridge_available():
            raise RuntimeError(
                "Legacy bridge executable not found. "
                "Cannot run optimization without the IIT Pave solver."
            )

    # ------------------------------------------------------------------
    # Core evaluation (same bridge call as old GA)
    # ------------------------------------------------------------------

    def _build_solver_inputs(self, thicknesses: List[float]):
        """Build the layer stack from thicknesses — identical to old GA."""
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
                input_granular.append({
                    "thickness": h,
                    "layer_type": l_type,
                    "E": custom_props.get('E'),
                    "nu": custom_props.get('nu'),
                })

        solver_stack = build_layer_stack(
            subgrade, input_granular, input_bituminous, self.problem.layer_props
        )
        return solver_stack, cost_specs, input_bituminous

    def _evaluate(self, thicknesses: List[float]) -> dict:
        """
        Run IIT Pave for one thickness combination.
        Returns dict with eps_t, eps_v, CDF values, adequacy, cost, co2.
        """
        solver_stack, cost_specs, input_bituminous = \
            self._build_solver_inputs(thicknesses)

        depth_bit = sum(l.thickness for l in input_bituminous)
        depth_sub = sum(l['thickness'] for l in solver_stack[:-1])

        load_cfg = {
            "load": 20000, "pressure": 0.56,
            "is_dual": True, "spacing": 310,
        }
        eval_points = [
            {"z": depth_bit - 0.1, "r": 0},
            {"z": depth_bit - 0.1, "r": 155},
            {"z": depth_sub - 0.1, "r": 0},
            {"z": depth_sub - 0.1, "r": 155},
        ]

        results = run_bridge_from_stack(solver_stack, load_cfg, eval_points)
        if not results:
            raise RuntimeError("Legacy bridge returned no results")

        eps_t = max(abs(r["eps_t"]) for r in results[:2])
        eps_v = max(abs(r["eps_z"]) for r in results[2:])

        msa = self.problem.traffic.cumulative_msa()
        bot_mod = input_bituminous[-1].modulus if input_bituminous else 1250.0
        rel = self.problem.reliability

        chk = check_design_adequacy(eps_t, eps_v, msa, bot_mod, rel)
        cost_res = estimate_cost(cost_specs, lane_width_m=self.problem.lane_width_m)
        moduli = [l['modulus'] for l in solver_stack]

        return {
            "thicknesses": list(thicknesses),
            "total_thickness": sum(thicknesses),
            "eps_t": eps_t,
            "eps_v": eps_v,
            "CDF_fatigue": chk["CDF_fatigue"],
            "CDF_rutting": chk["CDF_rutting"],
            "Nf": chk["Nf"],
            "NR": chk["NR"],
            "overall_adequate": chk["overall_adequate"],
            "governing_mode": chk["governing_mode"],
            "msa": msa,
            "cost_per_km": cost_res.total_cost_per_km,
            "co2_per_km": cost_res.total_co2_per_km,
            "layers": [
                {
                    "id": i + 1,
                    "name": self.problem.layer_types[i] if i < len(self.problem.layer_types) else "Subgrade",
                    "thickness": thicknesses[i] if i < len(thicknesses) else 0.0,
                    "modulus": moduli[i],
                }
                for i in range(len(solver_stack))
            ],
        }

    # ------------------------------------------------------------------
    # Phase 1: Greedy climb from minimum thicknesses
    # ------------------------------------------------------------------

    def _greedy_climb(self) -> Tuple[List[float], dict, int]:
        """
        Start from minimum thicknesses. Each step, increment the
        cheapest-to-add layer by 5mm. Stop at first adequate design.

        Returns: (thicknesses, evaluation_result, n_evaluations)
        """
        layer_types = self.problem.layer_types
        bounds = self.problem.thickness_bounds

        # Start at minimum
        current = [bounds.get(lt, (50, 200))[0] for lt in layer_types]
        maxes = [bounds.get(lt, (50, 200))[1] for lt in layer_types]

        # Sort layers by cost weight — increment cheapest first
        layer_order = sorted(
            range(len(layer_types)),
            key=lambda i: _LAYER_COST_WEIGHT.get(layer_types[i], 10),
        )

        n_evals = 0
        max_evals = 500  # safety cap

        while n_evals < max_evals:
            try:
                result = self._evaluate(current)
                n_evals += 1
            except Exception:
                n_evals += 1
                result = {"overall_adequate": False}

            if result["overall_adequate"]:
                logger.info(
                    "Phase 1: Found adequate design in %d evaluations: %s (total=%.0fmm)",
                    n_evals, current, sum(current),
                )
                return list(current), result, n_evals

            # Increment cheapest layer that still has room
            incremented = False
            for idx in layer_order:
                if current[idx] + 5 <= maxes[idx]:
                    current[idx] += 5
                    incremented = True
                    break

            if not incremented:
                # All layers at max — no adequate design possible in bounds
                logger.warning("Phase 1: All layers at maximum, no adequate design found.")
                return list(current), result, n_evals

        logger.warning("Phase 1: Reached %d evaluation cap without adequacy.", max_evals)
        return list(current), result, n_evals

    # ------------------------------------------------------------------
    # Phase 2: Boundary sweep — grid near the first adequate design
    # ------------------------------------------------------------------

    def _boundary_sweep(
        self,
        anchor: List[float],
        max_adequate: int = 30,
        max_evals: int = 3000,
    ) -> Tuple[List[dict], int]:
        """
        Generate all 5mm-step combinations in a window around the anchor.
        Sort by total thickness ascending. Evaluate cheapest first.
        Stop once we have enough adequate designs or hit eval cap.

        Returns: (list_of_adequate_results, n_evaluations)
        """
        layer_types = self.problem.layer_types
        bounds = self.problem.thickness_bounds

        # Build per-layer search ranges: [anchor - 20mm, anchor + 15mm] clamped to bounds
        ranges = []
        for i, lt in enumerate(layer_types):
            lo, hi = bounds.get(lt, (50, 200))
            sweep_lo = max(lo, anchor[i] - 20)
            sweep_hi = min(hi, anchor[i] + 15)
            layer_range = []
            v = sweep_lo
            while v <= sweep_hi:
                layer_range.append(v)
                v += 5
            ranges.append(layer_range)

        # Generate all combinations, sort by total thickness (cheapest first)
        all_combos = list(itertools.product(*ranges))
        all_combos.sort(key=lambda c: sum(c))

        logger.info(
            "Phase 2: Sweeping %d combinations in window around %s",
            len(all_combos), anchor,
        )

        adequate = []
        n_evals = 0
        seen = set()

        for combo in all_combos:
            if n_evals >= max_evals:
                break
            if len(adequate) >= max_adequate:
                break

            combo_key = tuple(combo)
            if combo_key in seen:
                continue
            seen.add(combo_key)

            try:
                result = self._evaluate(list(combo))
                n_evals += 1
            except Exception:
                n_evals += 1
                continue

            if result["overall_adequate"]:
                adequate.append(result)

        logger.info(
            "Phase 2: Found %d adequate designs in %d evaluations.",
            len(adequate), n_evals,
        )
        return adequate, n_evals

    # ------------------------------------------------------------------
    # Archetype selection
    # ------------------------------------------------------------------

    def _select_archetypes(self, adequate: List[dict]) -> List[ParetoSolution]:
        """Pick Economy, Balanced, Premium from adequate designs."""
        if not adequate:
            return []

        archetypes = []

        # 1. Economy — thinnest
        adequate.sort(key=lambda d: d["total_thickness"])
        econ_data = adequate[0]
        econ_data["strategy"] = "Economy"
        econ = ParetoSolution(
            optimal_thicknesses=econ_data["thicknesses"],
            optimal_materials={},
            cost=econ_data["cost_per_km"],
            co2=econ_data["co2_per_km"],
            performance=econ_data,
        )
        archetypes.append(econ)

        # 2. Premium — lowest governing CDF (safest)
        adequate.sort(key=lambda d: max(d["CDF_fatigue"], d["CDF_rutting"]))
        prem_data = adequate[0]
        if prem_data["thicknesses"] != econ_data["thicknesses"]:
            prem_data["strategy"] = "Premium"
            prem = ParetoSolution(
                optimal_thicknesses=prem_data["thicknesses"],
                optimal_materials={},
                cost=prem_data["cost_per_km"],
                co2=prem_data["co2_per_km"],
                performance=prem_data,
            )
            archetypes.append(prem)

        # 3. Balanced — closest to midpoint in normalized (thickness, CDF) space
        if len(adequate) > 2:
            t_all = [d["total_thickness"] for d in adequate]
            c_all = [max(d["CDF_fatigue"], d["CDF_rutting"]) for d in adequate]
            t_min, t_max = min(t_all), max(t_all)
            c_min, c_max = min(c_all), max(c_all)
            t_range = t_max - t_min if t_max > t_min else 1.0
            c_range = c_max - c_min if c_max > c_min else 1.0

            def score(d):
                tn = (d["total_thickness"] - t_min) / t_range
                cn = (max(d["CDF_fatigue"], d["CDF_rutting"]) - c_min) / c_range
                return (tn - 0.5) ** 2 + (cn - 0.5) ** 2

            bal_data = min(adequate, key=score)
            if (bal_data["thicknesses"] != econ_data["thicknesses"]
                    and bal_data["thicknesses"] != prem_data["thicknesses"]):
                bal_data["strategy"] = "Balanced"
                bal = ParetoSolution(
                    optimal_thicknesses=bal_data["thicknesses"],
                    optimal_materials={},
                    cost=bal_data["cost_per_km"],
                    co2=bal_data["co2_per_km"],
                    performance=bal_data,
                )
                archetypes.append(bal)

        return archetypes

    # ------------------------------------------------------------------
    # Public API — drop-in replacement for PavementGA.run()
    # ------------------------------------------------------------------

    def run(self) -> OptimizationResult:
        """
        Run the full hybrid search.
        Returns an OptimizationResult identical in structure to the old GA.
        """
        # Phase 1: greedy climb to first adequate design
        anchor, first_result, n1 = self._greedy_climb()

        # Phase 2: sweep around the anchor for archetypes
        if first_result.get("overall_adequate"):
            adequate_list, n2 = self._boundary_sweep(anchor)
            # Include the anchor itself if not already in list
            anchor_key = tuple(anchor)
            if not any(tuple(d["thicknesses"]) == anchor_key for d in adequate_list):
                adequate_list.append(first_result)
        else:
            adequate_list = []
            n2 = 0

        total_evals = n1 + n2
        logger.info("Search complete: %d total evaluations", total_evals)

        has_adequate = bool(adequate_list)
        archetypes = self._select_archetypes(adequate_list)

        # Fallback if nothing adequate
        if not archetypes:
            first_result["strategy"] = "Preliminary"
            fallback = ParetoSolution(
                optimal_thicknesses=anchor,
                optimal_materials={},
                cost=first_result.get("cost_per_km", 1e9),
                co2=first_result.get("co2_per_km", 1e9),
                performance=first_result,
            )
            archetypes = [fallback]

        best = archetypes[0]
        return OptimizationResult(
            optimal_thicknesses=best.optimal_thicknesses,
            optimal_materials={},
            layer_types=self.problem.layer_types,
            cost=best.cost,
            co2=best.co2,
            is_feasible=has_adequate,
            performance=best.performance,
            pareto_front=archetypes,
        )
