import logging
from dataclasses import dataclass, field
from typing import Any, List, Dict, Tuple, Optional, Union

from mep_opt.solver.irc37 import (
    TrafficInput, SubgradeInput, ReliabilityLevel, BitumenGrade, AxleLoadGroup,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constructable lift sizes per MoRTH 500 series + IRC site practice.
# A pavement built on-site is laid in standard lifts; outputs like
# "DBM = 117 mm" cannot be tendered, so the optimizer enumerates only
# values an engineer would actually specify. Users can override via
# `OptimizationProblem.lift_schedule`. A layer type absent here (or a
# fixed/zero-range layer) falls back to the bounds-and-step behaviour.
# ---------------------------------------------------------------------------
DEFAULT_LIFT_SCHEDULE: Dict[str, List[float]] = {
    # Bituminous wearing & binder courses (MoRTH 500 standard lift sizes)
    "BC":   [30, 40, 50],
    "DBM":  [50, 60, 65, 75, 90, 100, 130, 150],
    "BM":   [50, 60, 75, 100, 150],
    "SDBC": [25, 30, 40],
    "SMA":  [40, 50],
    # Granular base / sub-base (multiples of 50 mm; sub-lifts ≥ 100 mm)
    "WMM":  [150, 200, 250, 300],
    "WBM":  [75, 100, 150, 200],
    "GSB":  [150, 200, 250, 300],
    # Cement-treated layers
    "CTB":  [100, 150, 200, 250],
    "CTSB": [100, 150, 200, 250],
    # Recycled
    "RAP":  [100, 150, 200],
}


# ---------------------------------------------------------------------------
# Traffic-tier minimum-thickness rules.
#
# IRC 37:2018 page 42 mandates ONE direct rule:
#   "In the case of pavements with Cement Treated Bases (CTB) for traffic
#    exceeding 20 msa, the combined total thickness of surface course and
#    base/binder course shall not be less than 100 mm."
#
# The other entries below are MoRTH 500 / IRC SP-89 engineering practice —
# widely cited in design catalogues, not literally in IRC 37 prose. Users
# with a different convention can pass their own table on
# `OptimizationProblem.traffic_tier_minimums`. Set
# `ignore_minimum_thickness=True` to disable the filter entirely (e.g.
# when comparing against the IRC 37 catalogue tables verbatim).
#
# Schema: tuple of
#   (msa_lower_inclusive, msa_upper_exclusive,
#    {layer_type: minimum_mm}, bituminous_bundle_minimum_mm)
# Layers not listed in the tier dict have no per-layer minimum.
# ---------------------------------------------------------------------------
DEFAULT_TRAFFIC_TIER_MINIMUMS: Tuple = (
    (0.0,   5.0,   {"BC": 30, "DBM": 50},   0),
    (5.0,   20.0,  {"BC": 30, "DBM": 50},  80),
    (20.0,  50.0,  {"BC": 40, "DBM": 50}, 100),
    (50.0,  1e9,   {"BC": 50, "DBM": 70}, 100),
)


@dataclass
class OptimizationProblem:
    """Defines the pavement optimization problem."""
    traffic: TrafficInput
    subgrade: SubgradeInput
    reliability: ReliabilityLevel = ReliabilityLevel.R90
    lane_width_m: float = 3.5
    temperature: float = 35.0   # Pavement temperature (deg C) for modulus lookup

    # Fixed layer structure for this run
    layer_types: List[str] = None  # e.g., ["BC", "DBM", "WMM", "GSB"]

    # Thickness constraints (min, max) mm
    layer_props: Dict[str, dict] = None
    thickness_bounds: Dict[str, Tuple[float, float]] = None

    # Material options (layer mapping to allowed BitumenGrades)
    material_options: Dict[str, List[BitumenGrade]] = None

    # Optional unit rates override — drives both the optimizer's cost-aware
    # decisions AND the cost report. Keys are layer type codes ("BC", "GSB", ...).
    # Values may be:
    #   - a number              → cost_per_cum override only (CO₂/density use defaults)
    #   - a dict                → partial override of any MaterialRate field
    #   - a MaterialRate object → full override
    # Layer types not present here use DEFAULT_MATERIAL_RATES from mep_opt.cost.
    material_rates: Optional[Dict[str, Any]] = None

    # Constructable-lift-size override per layer type. Defaults to
    # DEFAULT_LIFT_SCHEDULE when None. Keys are layer type codes ("BC",
    # "DBM", ...); values are the discrete thickness options the optimizer
    # may explore. Values outside thickness_bounds are filtered. Layer
    # types not in the schedule fall back to bounds-and-5mm-step behaviour.
    lift_schedule: Optional[Dict[str, List[float]]] = None

    # CDF ceiling that defines a "Premium" archetype — IRC 37 doesn't
    # specify this; engineers typically request a 30–40% structural
    # reserve for high-traffic corridors, hence the 0.6 default.
    # Premium = the cheapest design with max(CDF) ≤ this ceiling.
    premium_cdf_ceiling: float = 0.6

    # IRC 37:2018 page 28 / Cl. 8.3 — when CTB is used, a *crack relief
    # layer* is mandatory between the bituminous bundle and the CTB. The
    # crack relief can be either:
    #   1. an aggregate interlayer (typically 100 mm WMM / "CRL"), OR
    #   2. a stress-absorbing membrane interlayer (SAMI), which is non-
    #      structural and so does not appear in `layer_types`.
    # Set `has_sami=True` when the project specifies a SAMI; otherwise
    # the validator requires an aggregate interlayer above CTB. This
    # protects against the silent omission that the optimizer could not
    # otherwise catch.
    has_sami: bool = False

    # Traffic-tier minimum-thickness pre-filter (IRC 37:2018 page 42 +
    # MoRTH 500 practice). When None the optimizer uses the table at the
    # top of this module. Set `ignore_minimum_thickness=True` to skip the
    # filter — useful when reproducing IRC catalogue values verbatim.
    traffic_tier_minimums: Optional[Tuple] = None
    ignore_minimum_thickness: bool = False

    # Severity-4 #4.6 — emit an optional 4th archetype with the lowest
    # embodied-carbon design among the adequate set. Skipped silently
    # when carbon ranking duplicates the cost ranking (the design would
    # already be Economy/Balanced/Premium).
    include_carbon_archetype: bool = False

    # Cost and CO₂ optimization toggles — when False (default), the
    # optimizer ranks by total_thickness instead of cost, and returns
    # null for cost / co2 in the API response. The user must explicitly
    # enable these (and optionally supply material_rates) to get
    # cost-aware or carbon-aware optimization.
    optimize_by_cost: bool = False
    optimize_by_co2: bool = False

    # Number of parallel workers for brute-force evaluation. The native
    # solver is thread-safe, so each worker uses ThreadPoolExecutor
    # directly without scratch directories.
    parallel_workers: int = 1

    # Optional load and evaluation configuration forwarded from the UI/API
    wheel_load: float = 20000.0
    tire_pressure: float = 0.56
    wheel_type: str = "Single"
    wheel_spacing: float = 310.0
    # Optional CTB axle-load spectrum. When provided, the optimizer uses
    # check_ctb_adequacy() to score CTB fatigue across the spectrum.
    # The default path keeps using the reference CTB stress from the main
    # bridge call; setting ctb_per_class_bridge_recompute=True opts into a
    # separate bridge evaluation per axle class.
    ctb_axle_spectrum: Optional[List[AxleLoadGroup]] = None
    ctb_per_class_bridge_recompute: bool = False
    # Optional list of evaluation points for optimizer to use (overrides internal points)
    eval_points: Optional[List[dict]] = None

    def __post_init__(self):
        if self.layer_types is None:
            self.layer_types = ["BC", "DBM", "WMM", "GSB"]

        if self.thickness_bounds is None:
            self.thickness_bounds = {
                "BC": (30, 50),
                "DBM": (50, 150),
                "WMM": (150, 300),
                "GSB": (150, 300),
                "SMA": (40, 50),
            }
        else:
            # If the caller supplied bounds, every layer in the stack must have
            # an entry. Otherwise the optimizer would silently fall back to a
            # generic (50, 200) range, exploring a design space the engineer
            # never asked for.
            missing = [lt for lt in self.layer_types if lt not in self.thickness_bounds]
            if missing:
                raise ValueError(
                    f"thickness_bounds is missing entries for layer_types: {missing}. "
                    f"Provide bounds for every layer, or pass thickness_bounds=None to use defaults."
                )

        # Validate bounds shape and ordering for every layer used in the run.
        for lt in self.layer_types:
            entry = self.thickness_bounds.get(lt)
            if entry is None:
                continue
            try:
                lo, hi = entry
            except (TypeError, ValueError):
                raise ValueError(
                    f"thickness_bounds[{lt!r}] must be a (min_mm, max_mm) tuple, got {entry!r}"
                )
            if lo < 0 or hi < 0:
                raise ValueError(
                    f"thickness_bounds[{lt!r}] = ({lo}, {hi}) must be non-negative"
                )
            if lo > hi:
                raise ValueError(
                    f"thickness_bounds[{lt!r}] has min ({lo}) > max ({hi})"
                )

        if self.material_options is None:
            self.material_options = {
                "BC": [BitumenGrade.VG30],
                "DBM": [BitumenGrade.VG30]
            }

        self._validate_ctb_crack_relief()

    # ------------------------------------------------------------------
    # IRC 37:2018 §8.3 / page 28 — crack relief between CTB and bituminous
    # ------------------------------------------------------------------
    def _validate_ctb_crack_relief(self) -> None:
        """
        When CTB is in the layer stack, a crack relief layer (either an
        aggregate interlayer such as WMM/CRL, or a SAMI) MUST sit between
        the bituminous bundle and the CTB. Without it the bituminous layer
        cracks reflectively from the CTB within ~5–7 years.

        The validator accepts EITHER:
            (a) ``has_sami=True`` on the problem (SAMI is non-structural,
                so it doesn't appear in layer_types), OR
            (b) An aggregate interlayer (WMM, WBM, CRL, or any unbound
                granular type) immediately above the CTB layer.
        Otherwise it raises ValueError to surface the problem before any
        bridge call is made.
        """
        BITUMINOUS = {"BC", "DBM", "BM", "SDBC", "SMA"}
        AGGREGATE_INTERLAYERS = {"WMM", "WBM", "CRL", "GSB"}

        layer_types_upper = [str(lt).upper().strip() for lt in (self.layer_types or [])]
        if "CTB" not in layer_types_upper:
            return

        if self.has_sami:
            return  # SAMI is non-structural; user has flagged its presence

        ctb_idx = layer_types_upper.index("CTB")
        # The layer ABOVE CTB in the stack — i.e. the one with the
        # immediately-smaller index — must be the crack relief layer.
        if ctb_idx == 0:
            raise ValueError(
                "CTB cannot be the topmost layer; IRC 37:2018 requires a "
                "crack relief layer above CTB (and a bituminous bundle "
                "above that). Set has_sami=True or add an aggregate "
                "interlayer (WMM/CRL) above the CTB."
            )
        layer_above_ctb = layer_types_upper[ctb_idx - 1]
        if layer_above_ctb in BITUMINOUS:
            raise ValueError(
                f"IRC 37:2018 §8.3 / page 28 requires a crack relief layer "
                f"between the bituminous bundle and CTB. Got {layer_above_ctb} "
                f"directly above CTB. Either insert an aggregate interlayer "
                f"(typically 100 mm WMM/CRL) or set has_sami=True."
            )
        # If layer above CTB is an aggregate interlayer or an unbound type,
        # the crack relief is satisfied — accept the configuration.
        if layer_above_ctb not in AGGREGATE_INTERLAYERS:
            logger.warning(
                "Layer %s above CTB is neither bituminous, an aggregate "
                "interlayer, nor a recognised type — accepting but please "
                "confirm it satisfies IRC 37:2018 §8.3 crack-relief intent.",
                layer_above_ctb,
            )

    def resolved_material_rates(self) -> Dict[str, "Any"]:
        """
        Merge user-supplied `material_rates` with the IRC/MORTH defaults.
        Returns a fully-populated `Dict[str, MaterialRate]` covering every
        layer type referenced by the problem.

        Defaults come from `mep_opt.cost.DEFAULT_MATERIAL_RATES`. User values
        only replace the fields they explicitly set.
        """
        # Local import avoids a circular dependency at module load time
        from mep_opt.cost import DEFAULT_MATERIAL_RATES, MaterialRate

        resolved: Dict[str, MaterialRate] = dict(DEFAULT_MATERIAL_RATES)
        if not self.material_rates:
            return resolved

        for raw_key, override in self.material_rates.items():
            key = str(raw_key).upper().strip()
            base = resolved.get(key) or MaterialRate(
                name=key, cost_per_cum=5000.0, co2_per_cum=100.0, density=2400.0,
            )
            if isinstance(override, MaterialRate):
                resolved[key] = override
            elif isinstance(override, (int, float)) and not isinstance(override, bool):
                resolved[key] = MaterialRate(
                    name=base.name,
                    cost_per_cum=float(override),
                    co2_per_cum=base.co2_per_cum,
                    density=base.density,
                    transport_co2_factor=base.transport_co2_factor,
                )
            elif isinstance(override, dict):
                resolved[key] = MaterialRate(
                    name=str(override.get("name", base.name)),
                    cost_per_cum=float(override.get("cost_per_cum", base.cost_per_cum)),
                    co2_per_cum=float(override.get("co2_per_cum", base.co2_per_cum)),
                    density=float(override.get("density", base.density)),
                    transport_co2_factor=float(
                        override.get("transport_co2_factor", base.transport_co2_factor)
                    ),
                )
            else:
                logger.warning(
                    "Ignoring unsupported material_rates value for %s: %r",
                    key, override,
                )
        return resolved


@dataclass
class ParetoSolution:
    """A single solution on the Pareto Front."""
    optimal_thicknesses: List[float]
    optimal_materials: Dict[str, BitumenGrade]
    cost: float
    co2: float
    performance: dict

@dataclass
class OptimizationResult:
    """Result of an optimization run."""
    optimal_thicknesses: List[float]
    optimal_materials: Dict[str, BitumenGrade]
    layer_types: List[str]
    cost: float
    co2: float
    is_feasible: bool
    performance: dict
    population_log: List[dict] = None
    pareto_front: List[ParetoSolution] = None
    errors: Optional[List[str]] = None
    warnings: Optional[List[str]] = None
