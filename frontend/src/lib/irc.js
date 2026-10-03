// Shared IRC:37-2018 helpers for the frontend (advanced panels).
// Mirrors mep_opt/solver/irc37.py so the dashboard's client-side previews
// use the same relationships as the backend optimizer.

// Effective resilient modulus of the subgrade (MPa) from CBR (%).
//   MRS = 10 * CBR            for CBR <= 5 %      (IRC:37-2018 Eq. 6.1)
//   MRS = 17.6 * CBR^0.64     for CBR > 5 %       (IRC:37-2018 Eq. 6.2)
//   capped at 100 MPa for design                 (IRC:37-2018 Cl. 6.4.2)
// The advanced panels previously used a flat `CBR * 10`, which is only valid
// for CBR <= 5 % and over-stiffens the subgrade for typical CBR (6-10 %).
export function subgradeModulusFromCBR(cbr) {
  const c = Number(cbr) || 0;
  const mr = c <= 5 ? 10 * c : 17.6 * Math.pow(c, 0.64);
  return Math.min(mr, 100);
}

// Bituminous mix types (IRC fatigue uses the BOTTOM bituminous layer modulus).
const BITUMINOUS = new Set(['BC', 'DBM', 'BM', 'SDBC', 'SMA']);

function classify(layer) {
  return String(layer?.type || layer?.name || '').toUpperCase().trim();
}

// Resilient modulus (MPa) of the BOTTOM bituminous layer, for the fatigue
// criterion (IRC:37-2018 §3.6.2). Falls back to the first/last layer's E when
// no layer is clearly bituminous.
export function bottomBituminousModulus(layers, numLayers) {
  if (!Array.isArray(layers) || layers.length === 0) return 1250;
  const n = numLayers ?? layers.length;
  let mod = null;
  for (let i = 0; i < n && i < layers.length; i++) {
    const t = classify(layers[i]);
    if ([...BITUMINOUS].some((b) => t.includes(b))) {
      mod = Number(layers[i].E) || mod;   // keep the deepest bituminous layer
    }
  }
  return mod ?? (Number(layers[0]?.E) || 1250);
}

// Cumulative design traffic in MSA (IRC:37-2018 Eq. 4.5 / 4.6, cumulative_msa()):
//   A = P (1+r)^x   (P = CVPD at the last count, x = years to completion)
//   N = 365 * A * D * F * ((1+r)^n - 1) / r  / 1e6
// where D = lane distribution factor, F = VDF, r = growth, n = life.
// The advanced panels previously fed raw CVPD in as "MSA", which massively
// over-states the traffic (e.g. 800 CVPD -> "800 MSA").
export function cumulativeMSA({ cvpd, growthRate = 0.05, designLife = 20, ldf = 0.75, vdf = 2.5, constructionYears = 0 }) {
  const r = Number(growthRate);
  const x = Number(constructionYears) || 0;
  const A = (Number(cvpd) || 0) * Math.pow(1 + r, x);
  const n = Number(designLife) || 0;
  const D = Number(ldf);
  const F = Number(vdf);
  const factor = Math.abs(r) < 1e-10 ? n : ((1 + r) ** n - 1) / r;
  return (365 * A * D * F * factor) / 1e6;
}

// ---------------------------------------------------------------------------
// Road category (IRC:37-2018 §3.7 and Eq. 3.5) — mirrors irc37.py.
// ---------------------------------------------------------------------------
export const ROAD_CATEGORIES = [
  { id: 'nh', label: 'National Highway' },
  { id: 'sh', label: 'State Highway' },
  { id: 'expressway', label: 'Expressway' },
  { id: 'urban', label: 'Urban road' },
  { id: 'other', label: 'Other (MDR / ODR / VR)' },
];
const IMPORTANT_ROADS = new Set(['expressway', 'nh', 'sh', 'urban']);

// 90 % for Expressways / NH / SH / urban roads at any traffic, and for every
// other road at >= 20 msa; 80 % otherwise (IRC:37-2018 §3.7).
export function requiredReliabilityPercent(msa, roadCategory) {
  return IMPORTANT_ROADS.has(roadCategory) || Number(msa) >= 20 ? 90 : 80;
}

// RF of IRC:37-2018 Eq. 3.5: 1 for important roads or >= 10 msa, else 2.
export function ctbReliabilityFactor(msa, roadCategory) {
  return IMPORTANT_ROADS.has(roadCategory) || Number(msa) >= 10 ? 1 : 2;
}

// ---------------------------------------------------------------------------
// Geogrid Modulus Improvement Factor — mirrors mep_opt/solver/geosynthetic.py
// Saride et al. (2022) research table: linear interpolation, first value held
// below the table, last segment extrapolated (never below 1.0) above it, and
// the result capped at the IRC:SP:59-2019 §3.1.3 design maximum of 2.0.
// ---------------------------------------------------------------------------
const MIF_TABLE = {
  PP30:  [[10, 3.13], [30, 1.88], [50, 1.60], [70, 1.50]],
  PET30: [[10, 3.50], [30, 2.06], [50, 1.80]],
  PET60: [[30, 2.25], [50, 2.00]],
};
export const SP59_GEOGRID_MIF_MAX = 2.0;

export function researchMif(subgradeModulus, geogridType) {
  if (!geogridType || geogridType === 'none') return 1.0;
  const pts = MIF_TABLE[geogridType];
  if (!pts) return 1.0;
  const mrs = Number(subgradeModulus) || 0;
  if (mrs <= pts[0][0]) return pts[0][1];
  const last = pts[pts.length - 1];
  if (mrs >= last[0]) {
    if (pts.length < 2) return last[1];
    const prev = pts[pts.length - 2];
    const slope = (last[1] - prev[1]) / (last[0] - prev[0]);
    return Math.max(1.0, last[1] + slope * (mrs - last[0]));
  }
  for (let i = 0; i < pts.length - 1; i++) {
    const [m0, v0] = pts[i]; const [m1, v1] = pts[i + 1];
    if (m0 <= mrs && mrs <= m1) return v0 + ((mrs - m0) / (m1 - m0)) * (v1 - v0);
  }
  return last[1];
}

export function getMif(subgradeModulus, geogridType) {
  return Math.min(SP59_GEOGRID_MIF_MAX, researchMif(subgradeModulus, geogridType));
}

// IRC:37-2018 Eq. 6.3 effective (equivalent half-space) modulus of a layered
// foundation from its surface deflection under a 40 kN single wheel at
// 0.56 MPa (a = 150.8 mm), mu = 0.35. `rows` = [{E, nu, h}, ..., subgrade].
// `solve` is solver-client's solveAnalysis (same engine as the optimizer).
const EFF_LOAD = 40000;
const EFF_P = 0.56;
const effCache = new Map();
export async function effectiveModulus(rows, solve) {
  if (rows.length === 1) return Number(rows[0].E);
  const key = JSON.stringify(rows.map((r) => [Number(r.E), Number(r.nu), Number(r.h)]));
  if (effCache.has(key)) return effCache.get(key);
  const res = await solve({
    layers: rows.map((r, i) => ({ E: Number(r.E), nu: Number(r.nu), h: i === rows.length - 1 ? 0 : Number(r.h) })),
    wheel_load: EFF_LOAD,
    tire_pressure: EFF_P,
    wheel_type: 'Single',
    wheel_spacing: 310,
    points: [{ z: 0, r: 0 }],
  });
  const delta = Number(res?.results?.[0]?.disp_z);
  if (!(delta > 0)) throw new Error('Effective-modulus solve returned no surface deflection');
  const a = Math.sqrt(EFF_LOAD / (Math.PI * EFF_P));
  const e = (2 * (1 - 0.35 ** 2) * EFF_P * a) / delta;
  if (effCache.size > 500) effCache.clear();
  effCache.set(key, e);
  return e;
}

// ---------------------------------------------------------------------------
// Layer classification shared by the auto-modulus chain and role detection.
// ---------------------------------------------------------------------------
const UNBOUND_GRANULAR = new Set(['WMM', 'WBM', 'GSB', 'CRL']);
const CEMENT_TREATED = new Set(['CTB', 'CTSB']);
const COLD_RECYCLED = new Set(['RAP']);
const GEOGRID_ELIGIBLE = new Set(['WMM', 'WBM', 'GSB']);
// IRC:37-2018 §8.1 / Table 11.1 — granular base on a CTSB: 350 MPa crushed
// rock (WMM/WBM/CRL), 300 MPa natural gravel (GSB). Crack-relief interlayer
// directly above a CTB: 450 MPa (§8.3).
const GRANULAR_OVER_CTSB = { WMM: 350, WBM: 350, CRL: 350, GSB: 300 };
const CRACK_RELIEF_E = 450;

const typeOf = (l) => String(l?.type || l?.name || '').toUpperCase().trim();
// Nominal thickness convention shared with doSingleRun / the advanced panels:
// fixed layers use fixed_h, range layers use min_h.
const nominalThickness = (l) => {
  const h = l?.is_fixed ? Number(l?.fixed_h) : Number(l?.min_h);
  return Number.isFinite(h) && h > 0 ? h : 0;
};

// Fixed IRC modulus an AUTO unbound layer takes from its lower neighbour
// (CTB -> 450, CTSB -> 350/300), else null (Eq. 7.1 applies).
function fixedModulusFromBelow(t, belowT) {
  if (belowT === 'CTB') return CRACK_RELIEF_E;
  if (belowT === 'CTSB') return GRANULAR_OVER_CTSB[t] ?? null;
  return null;
}

// ---------------------------------------------------------------------------
// Engine moduli of the non-bituminous layers. Mirrors
// mep_opt/optimizer/smart_search.py::_build_solver_inputs + irc37.py::
// build_layer_stack so the cockpit, Evaluate and the advanced panels use the
// SAME moduli the optimizer analyses:
//   - all-unbound + all-auto + no geogrid -> single composite layer of total
//     thickness (§7.2.3): E = 0.2 * (sum h)^0.45 * MRS
//   - otherwise bottom-up per layer: cement-treated / RAP / pinned layers keep
//     their E; an auto unbound layer above a CTB is 450 MPa, above a CTSB
//     350/300 MPa; any other auto unbound layer uses Eq. 7.1 on the EFFECTIVE
//     modulus of everything below it (Eq. 6.3 via `solve`; the subgrade
//     modulus for the lowest layer); a geogrid multiplies by the capped MIF.
// Returns [{ index, E, auto }] for every non-bituminous structural layer
// (`auto` = the displayed E should follow this value). Layers with no usable
// thickness are skipped so a half-typed row never zeroes the modulus.
// Throws on IRC-invalid geogrid placement.
// ---------------------------------------------------------------------------
export async function computeGranularAutoE(layers, numLayers, subgradeCbr, solve) {
  if (!Array.isArray(layers) || layers.length < 2) return [];
  const n = Math.min(numLayers ?? layers.length, layers.length);
  const structural = layers.slice(0, n - 1);
  const subgrade = layers[n - 1] || {};
  const mrs = subgradeModulusFromCBR(subgradeCbr);
  const subNu = Number.isFinite(Number(subgrade.nu)) ? Number(subgrade.nu) : 0.35;

  const granIdx = [];
  structural.forEach((l, i) => {
    const t = typeOf(l);
    if (UNBOUND_GRANULAR.has(t) || CEMENT_TREATED.has(t) || COLD_RECYCLED.has(t)) granIdx.push(i);
  });
  if (!granIdx.length) return [];

  const isAuto = (l) => !!l?.auto_E && UNBOUND_GRANULAR.has(typeOf(l));
  const hasGeogrid = (l) => !!l?.geogrid && l.geogrid !== 'none';

  const allUnbound = granIdx.every((i) => UNBOUND_GRANULAR.has(typeOf(structural[i])));
  const allAuto = granIdx.every((i) => isAuto(structural[i]));
  const anyGeogrid = granIdx.some((i) => hasGeogrid(structural[i]));

  if (allUnbound && allAuto && !anyGeogrid && granIdx.length > 1) {
    const hTotal = granIdx.reduce((s, i) => s + nominalThickness(structural[i]), 0);
    if (hTotal <= 0) return [];
    const eComp = 0.2 * Math.pow(hTotal, 0.45) * mrs;
    return granIdx.map((i) => ({ index: i, E: Math.round(eComp * 100) / 100, auto: true }));
  }

  const out = [];
  const below = []; // rows beneath the current layer, top -> bottom
  for (let k = granIdx.length - 1; k >= 0; k--) {
    const i = granIdx[k];
    const l = structural[i];
    const t = typeOf(l);
    const h = nominalThickness(l);
    const nu = Number.isFinite(Number(l.nu)) ? Number(l.nu) : 0.35;
    const belowT = i + 1 < structural.length ? typeOf(structural[i + 1]) : '';
    const fixedE = isAuto(l) ? fixedModulusFromBelow(t, belowT) : null;
    if (hasGeogrid(l) && (!GEOGRID_ELIGIBLE.has(t) || fixedE != null)) {
      throw new Error(
        `Geogrid on ${t} is not supported: MIF applies to an Eq. 7.1 granular modulus ` +
        `(not to cement-treated layers or to the fixed IRC moduli over CTB/CTSB).`
      );
    }
    let E;
    if (!isAuto(l)) {
      E = Number(l.E) > 0 ? Number(l.E) : null;
      if (E == null) continue;
    } else if (fixedE != null) {
      E = fixedE;
    } else {
      if (h <= 0) continue; // half-typed row — leave E and the chain as-is
      const support = below.length
        ? await effectiveModulus([...below, { E: mrs, nu: subNu, h: 0 }], solve)
        : mrs;
      E = 0.2 * Math.pow(h, 0.45) * support;
    }
    if (hasGeogrid(l)) E *= getMif(mrs, l.geogrid);
    out.push({ index: i, E: Math.round(E * 100) / 100, auto: isAuto(l) });
    below.unshift({ E, nu, h });
  }
  return out;
}

// ---------------------------------------------------------------------------
// Role classification for analysis points — which result rows sit at the
// bituminous bottom (fatigue) and which at the top of the subgrade (rutting).
// The advanced panels previously hard-assumed rows 0-1 / 2-3, which misreads
// 6-point CTB layouts (rows 2-3 there are the CTB bottom). Classifying by
// depth against the CURRENT layer interfaces fixes that and also detects
// stale points after a thickness edit.
// Returns { bit_bottom: [...], sub_top: [...], ok, bitBottomZ, subTopZ }.
// ---------------------------------------------------------------------------
export function classifyPointRoles(layers, numLayers, points, tolMm = 5) {
  const empty = { bit_bottom: [], sub_top: [], ok: false, bitBottomZ: null, subTopZ: null };
  if (!Array.isArray(layers) || layers.length < 2 || !Array.isArray(points)) return empty;
  const n = Math.min(numLayers ?? layers.length, layers.length);
  const structural = layers.slice(0, n - 1);
  if (!structural.length) return empty;

  let cum = 0;
  let bitBottom = null;
  structural.forEach((l) => {
    const t = typeOf(l);
    cum += nominalThickness(l);
    if (BITUMINOUS.has(t) || [...BITUMINOUS].some((b) => t.includes(b))) bitBottom = cum;
  });
  const subTop = cum;

  const roles = { bit_bottom: [], sub_top: [] };
  points.forEach((p, idx) => {
    const z = Number(p?.z);
    if (!Number.isFinite(z)) return;
    if (bitBottom != null && Math.abs(z - bitBottom) <= tolMm) roles.bit_bottom.push(idx);
    else if (Math.abs(z - subTop) <= tolMm) roles.sub_top.push(idx);
  });

  return {
    ...roles,
    // Usable when we found the rutting probe and, if the stack has a
    // bituminous bundle, the fatigue probe too.
    ok: roles.sub_top.length > 0 && (bitBottom == null || roles.bit_bottom.length > 0),
    bitBottomZ: bitBottom,
    subTopZ: subTop,
  };
}
