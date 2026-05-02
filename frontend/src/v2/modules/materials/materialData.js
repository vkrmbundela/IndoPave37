// Static fallback material data — used if the API is unreachable.
// The MaterialPicker prefers live data from GET /api/v2/materials.

export const CATEGORIES = [
  { id: 'all',            label: 'All' },
  { id: 'bituminous',     label: 'Bituminous' },
  { id: 'granular',       label: 'Granular' },
  { id: 'cement_treated', label: 'Cement' },
  { id: 'recycled',       label: 'Recycled' },
  { id: 'stabilized',     label: 'Specialty' },
];

export const FALLBACK_MATERIALS = [
  { code: 'BC', name: 'Bituminous Concrete (BC)', category: 'bituminous', E_default: 1250, nu: 0.35, density: 2400, cost_multiplier: 1.0, description: 'Standard BC per IRC:37-2018.', source: 'base' },
  { code: 'DBM', name: 'Dense Bituminous Macadam (DBM)', category: 'bituminous', E_default: 1250, nu: 0.35, density: 2350, cost_multiplier: 1.0, description: 'Standard DBM per IRC:37-2018.', source: 'base' },
  { code: 'PMB40', name: 'Polymer Modified Bitumen (PMB-40)', category: 'bituminous', E_default: 3000, nu: 0.35, density: 2400, cost_multiplier: 1.25, description: 'High-performance modified binder for heavy traffic.', source: 'advanced' },
  { code: 'CRMB55', name: 'Crumb Rubber Modified Bitumen (CRMB-55)', category: 'bituminous', E_default: 2000, nu: 0.35, density: 2380, cost_multiplier: 1.15, description: 'Recycled rubber-modified binder.', source: 'advanced' },
  { code: 'WMM', name: 'Wet Mix Macadam (WMM)', category: 'granular', E_default: 300, nu: 0.35, density: 2200, cost_multiplier: 1.0, description: 'Standard WMM per IRC:37-2018.', source: 'base' },
  { code: 'GSB', name: 'Granular Sub-Base (GSB)', category: 'granular', E_default: 200, nu: 0.35, density: 2000, cost_multiplier: 1.0, description: 'Standard GSB per IRC:37-2018.', source: 'base' },
  { code: 'GEO_GSB', name: 'Geogrid-Reinforced GSB', category: 'granular', E_default: 350, nu: 0.30, density: 2050, cost_multiplier: 1.40, description: 'GSB with biaxial geogrid interlock.', source: 'advanced' },
  { code: 'CTB', name: 'Cement Treated Base (CTB)', category: 'cement_treated', E_default: 5000, nu: 0.25, density: 2200, cost_multiplier: 1.0, description: 'Standard CTB per IRC:37-2018.', source: 'base' },
  { code: 'CTB5', name: 'Cement Treated Base (5%)', category: 'cement_treated', E_default: 5000, nu: 0.25, density: 2200, cost_multiplier: 1.10, description: 'High-cement CTB for heavy-duty pavements.', source: 'advanced' },
  { code: 'CTB3', name: 'Cement Treated Base (3%)', category: 'cement_treated', E_default: 3000, nu: 0.25, density: 2150, cost_multiplier: 1.00, description: 'Lean CTB for moderate traffic.', source: 'advanced' },
  { code: 'RAP40', name: 'RAP 40% Blend', category: 'recycled', E_default: 1000, nu: 0.35, density: 2250, cost_multiplier: 0.70, description: '40% reclaimed asphalt pavement blend.', source: 'advanced' },
  { code: 'FBS', name: 'Foam Bitumen Stabilized Base', category: 'stabilized', E_default: 800, nu: 0.35, density: 2100, cost_multiplier: 0.85, description: 'Cold-recycled base using foamed bitumen.', source: 'advanced' },
];
