"""
Advanced Engineering API Router (v2)
=====================================
All advanced endpoints live under /api/v2/ to avoid any
conflict with existing /api/solve, /api/optimize, /api/report/pdf.
"""

import asyncio
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Optional

from .reserve import compute_reserve
from .materials_library import get_full_library, get_material_by_code
from .sensitivity import compute_sensitivity
from .strain_field import compute_strain_field
from .corridor import parse_corridor_csv, start_corridor_job, get_job_status
from .montecarlo import run_monte_carlo


advanced_router = APIRouter(prefix="/api/v2", tags=["advanced"])

# IRC 37:2018 defines exactly two reliability levels for highway pavement
# design — pick the right one for the traffic volume:
#   80% (R80): low-volume traffic, design MSA < 30
#   90% (R90): high-volume traffic, design MSA ≥ 30
# Anything outside this set is rejected at the API boundary so the
# advanced modules never silently run with a fabricated shift factor.
DEFAULT_RELIABILITY = 80
ALLOWED_RELIABILITY = (80, 90)
_RELIABILITY_DESCRIPTION = (
    "IRC 37:2018 reliability level. 80 (default) for low-volume traffic "
    "(<30 MSA); 90 for high-volume highways (≥30 MSA). No other values "
    "are IRC-compliant."
)


def _reliability_field(default: int = DEFAULT_RELIABILITY):
    """Pydantic Field factory shared by every advanced model."""
    return Field(default, description=_RELIABILITY_DESCRIPTION)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class LayerData(BaseModel):
    modulus: float
    poisson: float
    thickness: float
    name: Optional[str] = None
    friction_factor: float = 1.0

    @field_validator("modulus")
    @classmethod
    def _modulus_positive(cls, v):
        if v <= 0:
            raise ValueError("modulus must be positive")
        return v

    @field_validator("poisson")
    @classmethod
    def _poisson_range(cls, v):
        if not (0.0 <= v < 0.5):
            raise ValueError("poisson must be in [0, 0.5)")
        return v

    @field_validator("thickness")
    @classmethod
    def _thickness_non_negative(cls, v):
        if v < 0:
            raise ValueError("thickness must be non-negative")
        return v

    @field_validator("friction_factor")
    @classmethod
    def _friction_factor_positive(cls, v):
        if v <= 0:
            raise ValueError("friction_factor must be positive")
        return v

class LoadData(BaseModel):
    load: float = 20000
    pressure: float = 0.56
    is_dual: bool = True
    spacing: float = 310.0

    @field_validator("load")
    @classmethod
    def _load_positive(cls, v):
        if v <= 0:
            raise ValueError("load must be positive")
        return v

    @field_validator("pressure")
    @classmethod
    def _pressure_positive(cls, v):
        if v <= 0:
            raise ValueError("pressure must be positive")
        return v

    @field_validator("spacing")
    @classmethod
    def _spacing_range(cls, v):
        if not (0.0 <= v <= 2000.0):
            raise ValueError("spacing must be between 0 and 2000 mm")
        return v

    @model_validator(mode="after")
    def _check_dual_spacing(self):
        if self.is_dual and self.spacing <= 0:
            raise ValueError("dual-tire loads require a positive spacing")
        return self

class EvalPointData(BaseModel):
    z: float
    r: float

    @field_validator("z")
    @classmethod
    def _depth_non_negative(cls, v):
        if v < 0:
            raise ValueError("z must be non-negative")
        return v

    @field_validator("r")
    @classmethod
    def _radius_non_negative(cls, v):
        if v < 0:
            raise ValueError("r must be non-negative")
        return v

class ReserveRequest(BaseModel):
    """Inputs for the structural-reserve gauge. Mirrors the cockpit's
    traffic & reliability assumptions so the gauge agrees with the design
    it is evaluating."""
    eps_t: float
    eps_v: float
    mix_modulus: float
    design_msa: float
    reliability: int = _reliability_field()
    air_voids: float = 4.0
    bitumen_volume: float = 11.5

    @field_validator("reliability")
    @classmethod
    def _check_reliability(cls, v):
        if v not in ALLOWED_RELIABILITY:
            raise ValueError(
                f"reliability must be one of {ALLOWED_RELIABILITY}; got {v}"
            )
        return v

class SensitivityRequest(BaseModel):
    """Inputs for the layer-thickness sensitivity heatmap."""
    layers: List[LayerData]
    load: LoadData
    eval_points: List[EvalPointData]
    cumulative_msa: float
    mix_modulus: float
    reliability: int = _reliability_field()

    @field_validator("reliability")
    @classmethod
    def _check_reliability(cls, v):
        if v not in ALLOWED_RELIABILITY:
            raise ValueError(
                f"reliability must be one of {ALLOWED_RELIABILITY}; got {v}"
            )
        return v

class StrainFieldRequest(BaseModel):
    """Inputs for the 3D strain-bulb field."""
    layers: List[LayerData]
    load: LoadData
    r_steps: int = 12
    z_steps: int = 25
    r_max: float = 500.0

class CorridorConstraint(BaseModel):
    layer_type: str
    min_thickness: float
    max_thickness: float
    E: float
    nu: float
    is_fixed: bool = False

    @field_validator("layer_type")
    @classmethod
    def _layer_type_non_empty(cls, v):
        if not str(v).strip():
            raise ValueError("layer_type must be non-empty")
        return v

    @field_validator("min_thickness", "max_thickness")
    @classmethod
    def _thickness_non_negative(cls, v):
        if v < 0:
            raise ValueError("thickness bounds must be non-negative")
        return v

    @field_validator("E")
    @classmethod
    def _modulus_positive(cls, v):
        if v <= 0:
            raise ValueError("E must be positive")
        return v

    @field_validator("nu")
    @classmethod
    def _nu_range(cls, v):
        if not (0.0 <= v < 0.5):
            raise ValueError("nu must be in [0, 0.5)")
        return v

    @model_validator(mode="after")
    def _check_bounds(self):
        if self.min_thickness > self.max_thickness:
            raise ValueError("min_thickness cannot exceed max_thickness")
        return self

class CorridorRequest(BaseModel):
    """Inputs for batch corridor optimization."""
    layer_constraints: List[CorridorConstraint]
    growth_rate: float = 0.05
    design_life: int = 20
    reliability: int = _reliability_field()

    @field_validator("reliability")
    @classmethod
    def _check_reliability(cls, v):
        if v not in ALLOWED_RELIABILITY:
            raise ValueError(
                f"reliability must be one of {ALLOWED_RELIABILITY}; got {v}"
            )
        return v

class MonteCarloRequest(BaseModel):
    """Inputs for Monte Carlo construction-tolerance simulation."""
    layers: List[LayerData]
    load: LoadData
    eval_points: List[EvalPointData]
    cumulative_msa: float
    mix_modulus: float
    sigmas: Optional[List[float]] = None
    n_simulations: int = 100
    reliability: int = _reliability_field()

    @field_validator("reliability")
    @classmethod
    def _check_reliability(cls, v):
        if v not in ALLOWED_RELIABILITY:
            raise ValueError(
                f"reliability must be one of {ALLOWED_RELIABILITY}; got {v}"
            )
        return v

def _layers_to_dicts(layers: List[LayerData]) -> list[dict]:
    return [l.model_dump() for l in layers]

def _load_to_dict(load: LoadData) -> dict:
    return load.model_dump()

def _points_to_dicts(points: List[EvalPointData]) -> list[dict]:
    return [p.model_dump() for p in points]


# ---------------------------------------------------------------------------
# Module B: Structural Reserve Meter
# ---------------------------------------------------------------------------

@advanced_router.post("/reserve")
async def reserve_meter(req: ReserveRequest):
    """Compute structural capacity and reserve buffer."""
    try:
        result = compute_reserve(
            eps_t=req.eps_t, eps_v=req.eps_v,
            mix_modulus=req.mix_modulus, design_msa=req.design_msa,
            reliability=req.reliability, air_voids=req.air_voids,
            bitumen_volume=req.bitumen_volume,
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Module C: Material Library
# ---------------------------------------------------------------------------

@advanced_router.get("/materials")
async def list_materials():
    return {"status": "ok", "materials": get_full_library()}

@advanced_router.get("/materials/{code}")
async def get_material(code: str):
    mat = get_material_by_code(code)
    if mat is None:
        raise HTTPException(status_code=404, detail=f"Material '{code}' not found")
    return {"status": "ok", "material": mat}


# ---------------------------------------------------------------------------
# Module A: Sensitivity Heatmaps
# ---------------------------------------------------------------------------

@advanced_router.post("/sensitivity")
async def sensitivity_heatmap(req: SensitivityRequest):
    """Compute CDF sensitivity grid for each layer."""
    try:
        result = await asyncio.to_thread(
            compute_sensitivity,
            _layers_to_dicts(req.layers),
            _load_to_dict(req.load),
            _points_to_dicts(req.eval_points),
            req.cumulative_msa,
            req.mix_modulus,
            req.reliability,
        )
        return {"status": "ok", "layers": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Module D: 3D Strain Field
# ---------------------------------------------------------------------------

@advanced_router.post("/strain-field")
async def strain_field(req: StrainFieldRequest):
    """Compute strain values on an r-z grid for 3D visualization."""
    try:
        result = await asyncio.to_thread(
            compute_strain_field,
            _layers_to_dicts(req.layers),
            _load_to_dict(req.load),
            req.r_steps,
            req.z_steps,
            req.r_max,
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Module E: Corridor Optimization
# ---------------------------------------------------------------------------

@advanced_router.post("/corridor")
async def corridor_upload(file: UploadFile = File(...)):
    """Upload a CSV and start async corridor optimization."""
    try:
        content = (await file.read()).decode("utf-8")
        sections = parse_corridor_csv(content)
        if not sections:
            raise HTTPException(status_code=400, detail="No valid sections in CSV")

        # Use default layer constraints (will be customizable later)
        default_constraints = [
            {"layer_type": "BC", "min_thickness": 30, "max_thickness": 50, "E": 1250, "nu": 0.35, "is_fixed": True},
            {"layer_type": "DBM", "min_thickness": 50, "max_thickness": 200, "E": 1250, "nu": 0.35, "is_fixed": False},
            {"layer_type": "WMM", "min_thickness": 150, "max_thickness": 300, "E": 300, "nu": 0.35, "is_fixed": False},
            {"layer_type": "GSB", "min_thickness": 150, "max_thickness": 300, "E": 200, "nu": 0.35, "is_fixed": False},
        ]
        job_id = await start_corridor_job(sections, default_constraints)
        return {"status": "ok", "job_id": job_id, "total_sections": len(sections)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@advanced_router.get("/corridor/{job_id}/status")
async def corridor_status(job_id: str):
    """Poll corridor optimization progress."""
    job = get_job_status(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return {"status": "ok", **job}


# ---------------------------------------------------------------------------
# Module F: Monte Carlo Risk Analysis
# ---------------------------------------------------------------------------

@advanced_router.post("/montecarlo")
async def monte_carlo(req: MonteCarloRequest):
    """Run Monte Carlo simulation with construction tolerances."""
    try:
        result = await asyncio.to_thread(
            run_monte_carlo,
            _layers_to_dicts(req.layers),
            _load_to_dict(req.load),
            _points_to_dicts(req.eval_points),
            req.cumulative_msa,
            req.mix_modulus,
            req.sigmas,
            req.n_simulations,
            req.reliability,
        )
        return {"status": "ok", **result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
