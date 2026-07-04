// Static fallback material data — used if the API is unreachable.
// The MaterialPicker prefers live data from GET /api/v2/materials.
// Values marked "per IRC:37-2018" mirror mep_opt/solver/materials.py and
// mep_opt/advanced/materials_library.py (Table 9.2 at the 35 °C design
// temperature); entries marked "indicative" are engineering estimates that
// have no IRC:37 tabulated value.

export const CATEGORIES = [
  { id: 'all',            label: 'All' },
  { id: 'bituminous',     label: 'Bituminous' },
  { id: 'granular',       label: 'Granular' },
  { id: 'cement_treated', label: 'Cement' },
  { id: 'recycled',       label: 'Recycled' },
  { id: 'stabilized',     label: 'Specialty' },
];

export const FALLBACK_MATERIALS = [
  { code: 'BC', name: 'Bituminous Concrete (BC)', category: 'bituminous', E_default: 2000, nu: 0.35, density: 2400, cost_multiplier: 1.0, description: 'Standard BC — 2000 MPa per IRC:37-2018 Table 9.2 (VG30 @ 35 °C).', source: 'base' },
  { code: 'DBM', name: 'Dense Bituminous Macadam (DBM)', category: 'bituminous', E_default: 2000, nu: 0.35, density: 2350, cost_multiplier: 1.0, description: 'Standard DBM — 2000 MPa per IRC:37-2018 Table 9.2 (VG30 @ 35 °C).', source: 'base' },
  // Modified binders share ONE IRC:37-2018 Table 9.2 row: 5700/3800/2400/1600/1300 MPa at 20–40 °C.
  { code: 'PMB40', name: 'Polymer Modified Bitumen (PMB-40)', category: 'bituminous', E_default: 1600, nu: 0.35, density: 2400, cost_multiplier: 1.25, description: 'Modified binder — 1600 MPa @ 35 °C per IRC:37-2018 Table 9.2 modified-bitumen row.', source: 'advanced' },
  { code: 'CRMB55', name: 'Crumb Rubber Modified Bitumen (CRMB-55)', category: 'bituminous', E_default: 1600, nu: 0.35, density: 2380, cost_multiplier: 1.15, description: 'Recycled rubber-modified binder — 1600 MPa @ 35 °C per IRC:37-2018 Table 9.2 modified-bitumen row.', source: 'advanced' },
  { code: 'WMM', name: 'Wet Mix Macadam (WMM)', category: 'granular', E_default: 300, nu: 0.35, density: 2200, cost_multiplier: 1.0, description: 'Unbound granular base — indicative 300 MPa; IRC:37-2018 derives the design value from Eq. 7.1 (thickness + support).', source: 'base' },
  { code: 'GSB', name: 'Granular Sub-Base (GSB)', category: 'granular', E_default: 200, nu: 0.35, density: 2000, cost_multiplier: 1.0, description: 'Unbound granular sub-base — indicative 200 MPa; IRC:37-2018 derives the design value from Eq. 7.1 (thickness + support).', source: 'base' },
  { code: 'GEO_GSB', name: 'Geogrid-Reinforced GSB', category: 'granular', E_default: 350, nu: 0.30, density: 2050, cost_multiplier: 1.40, description: 'GSB with geogrid interlock (indicative, non-IRC value — prefer the geogrid MIF option on a plain granular layer).', source: 'advanced' },
  { code: 'CTB', name: 'Cement Treated Base (CTB)', category: 'cement_treated', E_default: 5000, nu: 0.25, density: 2200, cost_multiplier: 1.0, description: 'Standard CTB — 5000 MPa design modulus per IRC:37-2018.', source: 'base' },
  { code: 'CTB5', name: 'Cement Treated Base (5%)', category: 'cement_treated', E_default: 5000, nu: 0.25, density: 2200, cost_multiplier: 1.10, description: 'High-cement CTB — 5000 MPa per IRC:37-2018 design value.', source: 'advanced' },
  { code: 'CTB3', name: 'Cement Treated Base (3%)', category: 'cement_treated', E_default: 3000, nu: 0.25, density: 2150, cost_multiplier: 1.00, description: 'Lean CTB for moderate traffic (indicative, non-IRC value — IRC:37-2018 tabulates 5000 MPa for CTB).', source: 'advanced' },
  { code: 'RAP40', name: 'RAP 40% Blend', category: 'recycled', E_default: 1000, nu: 0.35, density: 2250, cost_multiplier: 0.70, description: '40% reclaimed asphalt pavement blend (indicative, non-IRC value — verify with project mix testing).', source: 'advanced' },
  { code: 'FBS', name: 'Foam Bitumen Stabilized Base', category: 'stabilized', E_default: 800, nu: 0.35, density: 2100, cost_multiplier: 0.85, description: 'Cold-recycled foamed-bitumen base (indicative, within the 600–800 MPa range IRC:37-2018 cites for bitumen-stabilised RAP).', source: 'advanced' },
];
