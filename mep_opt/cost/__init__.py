"""
Cost and Embodied CO₂ Estimator
================================
Estimates construction cost and embodied carbon for pavement sections.
Uses configurable unit rates from IRC/MORTH SoR.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class MaterialRate:
    """Unit rate for a material/layer type."""
    name: str
    cost_per_cum: float    # INR per cubic meter
    co2_per_cum: float     # kg CO₂ per cubic meter (Static EPD value)
    density: float = 2400  # kg/m³ (approx)
    transport_co2_factor: float = 0.105 # kg CO₂ per tonne-km


# Default material cost and CO₂ databases (per IRC/MORTH Schedule of Rates)
DEFAULT_MATERIAL_RATES: Dict[str, MaterialRate] = {
    # Bituminous layers
    "BC": MaterialRate("Bituminous Concrete", 12500, 180, 2350),
    "DBM": MaterialRate("Dense Bituminous Macadam", 10800, 165, 2350),
    "SMA": MaterialRate("Stone Matrix Asphalt", 14000, 195, 2350),
    "SDBC": MaterialRate("Semi-Dense Bituminous Concrete", 9800, 160, 2300),
    "BM": MaterialRate("Bituminous Macadam", 8500, 145, 2300),

    # Granular layers
    "WMM": MaterialRate("Wet Mix Macadam", 2800, 35, 2200),
    "WBM": MaterialRate("Water Bound Macadam", 2500, 30, 2100),
    "GSB": MaterialRate("Granular Sub-Base", 1800, 25, 2000),

    # Special
    "CTB": MaterialRate("Cement Treated Base", 3500, 120, 2200),
    "RAP": MaterialRate("Reclaimed Asphalt Pavement", 6000, 85, 2300),
}


@dataclass
class LayerCostSpec:
    """Layer specification for cost estimation."""
    material_type: str     # Key into material rates
    thickness_mm: float
    hauling_distance_km: float = 0.0 # Default local transport
    custom_epd: Optional[float] = None # Optional override for baseline CO2 EPD
    custom_rate: Optional[MaterialRate] = None


@dataclass
class CostResult:
    """Result of cost/CO₂ estimation."""
    total_cost_per_km: float       # INR per km per lane
    total_co2_per_km: float        # kg CO₂ per km per lane
    layer_breakdown: List[dict]     # Per-layer details
    lane_width_m: float


def estimate_cost(layers: List[LayerCostSpec],
                  lane_width_m: float = 3.5,
                  length_km: float = 1.0,
                  rates: Optional[Dict[str, MaterialRate]] = None
                  ) -> CostResult:
    """
    Estimate construction cost and embodied CO₂ for a pavement section.

    Args:
        layers: List of layer specifications
        lane_width_m: Lane width (m)
        length_km: Length (km) — costs scaled to per-km
        rates: Custom material rates (uses defaults if None)

    Returns:
        CostResult with totals and per-layer breakdown
    """
    if rates is None:
        rates = DEFAULT_MATERIAL_RATES

    total_cost = 0.0
    total_co2 = 0.0
    breakdown = []

    for layer in layers:
        rate = layer.custom_rate or rates.get(layer.material_type)
        if rate is None:
            rate = MaterialRate(layer.material_type, 5000, 100)

        # Volume per km per lane width
        thickness_m = layer.thickness_mm / 1000.0
        volume_per_km = lane_width_m * 1000.0 * thickness_m  # m³/km

        # Material CO2 (Baseline EPD or Custom EPD override)
        base_co2_rate = layer.custom_epd if layer.custom_epd is not None else rate.co2_per_cum
        material_co2 = volume_per_km * base_co2_rate
        
        # Transportation CO2 (Hauling)
        mass_tonnes = (volume_per_km * rate.density) / 1000.0
        transport_co2 = mass_tonnes * layer.hauling_distance_km * rate.transport_co2_factor

        cost = volume_per_km * rate.cost_per_cum
        co2 = material_co2 + transport_co2

        total_cost += cost
        total_co2 += co2

        breakdown.append({
            "material": rate.name,
            "type": layer.material_type,
            "thickness_mm": layer.thickness_mm,
            "volume_m3_per_km": round(volume_per_km, 1),
            "cost_inr_per_km": round(cost, 0),
            "co2_kg_per_km": round(co2, 1),
            "material_co2": round(material_co2, 1),
            "transport_co2": round(transport_co2, 1),
            "cost_rate": rate.cost_per_cum,
            "co2_rate": base_co2_rate,
        })

    return CostResult(
        total_cost_per_km=round(total_cost, 0),
        total_co2_per_km=round(total_co2, 1),
        layer_breakdown=breakdown,
        lane_width_m=lane_width_m,
    )
