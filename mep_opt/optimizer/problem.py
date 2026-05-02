from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

from mep_opt.solver.irc37 import TrafficInput, SubgradeInput, ReliabilityLevel, BitumenGrade


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
            
        if self.material_options is None:
            self.material_options = {
                "BC": [BitumenGrade.VG30],
                "DBM": [BitumenGrade.VG30]
            }


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
