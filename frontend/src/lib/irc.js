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

// Cumulative design traffic in MSA (IRC:37-2018 §4 / cumulative_msa()):
//   N = 365 * A * D * F * ((1+r)^n - 1) / r  / 1e6
// where A = CVPD, D = lane distribution factor, F = VDF, r = growth, n = life.
// The advanced panels previously fed raw CVPD in as "MSA", which massively
// over-states the traffic (e.g. 800 CVPD -> "800 MSA").
export function cumulativeMSA({ cvpd, growthRate = 0.05, designLife = 20, ldf = 0.75, vdf = 2.5 }) {
  const A = Number(cvpd) || 0;
  const r = Number(growthRate);
  const n = Number(designLife) || 0;
  const D = Number(ldf);
  const F = Number(vdf);
  const factor = Math.abs(r) < 1e-10 ? n : ((1 + r) ** n - 1) / r;
  return (365 * A * D * F * factor) / 1e6;
}

// ---------------------------------------------------------------------------
// Geogrid Modulus Improvement Factor — mirrors mep_opt/solver/geosynthetic.py
// (Saride et al. 2021 MIF table; linear interpolation, clamped outside range).
// ---------------------------------------------------------------------------
const MIF_TABLE = {
  PP30:  [[10, 3.13], [30, 1.88], [50, 1.60], [70, 1.50]],
  PET30: [[10, 3.50], [30, 2.06], [50, 1.80]],
  PET60: [[30, 2.25], [50, 2.00]],
};

export function getMif(subgradeModulus, geogridType) {
  if (!geogridType || geogridType === 'none') return 1.0;
  const pts = MIF_TABLE[geogridType];
  if (!pts) return 1.0;
  const mrs = Number(subgradeModulus) || 0;
  if (mrs <= pts[0][0]) return pts[0][1];
  if (mrs >= pts[pts.length - 1][0]) return pts[pts.length - 1][1];
  for (let i = 0; i < pts.length - 1; i++) {
    const [m0, v0] = pts[i]; const [m1, v1] = pts[i + 1];
    if (m0 <= mrs && mrs <= m1) return v0 + ((mrs - m0) / (m1 - m0)) * (v1 - v0);
  }
  return pts[pts.length - 1][1];
}

// ---------------------------------------------------------------------------
// Layer classification shared by the auto-modulus chain and role detection.
// ---------------------------------------------------------------------------
const UNBOUND_GRANULAR = new Set(['WMM', 'WBM', 'GSB', 'CRL']);
const CEMENT_TREATED = new Set(['CTB', 'CTSB']);

const typeOf = (l) => String(l?.type || l?.name || '').toUpperCase().trim();
// Nominal thickness convention shared with doSingleRun / the advanced panels:
// fixed layers use fixed_h, range layers use min_h.
const nominalThickness = (l) => {
  const h = l?.is_fixed ? Number(l?.fixed_h) : Number(l?.min_h);
  return Number.isFinite(h) && h > 0 ? h : 0;
};

// ---------------------------------------------------------------------------
// IRC:37-2018 Eq. 7.1 auto-moduli for unbound granular layers.
// Mirrors mep_opt/solver/irc37.py::build_layer_stack so the cockpit shows the
// SAME granular moduli the engine derives when E is sent as null ("auto"):
//   - all-unbound + all-auto + no geogrid -> single composite layer of total
//     thickness (§7.2.3): E = 0.2 * (Σh)^0.45 * MRS
//   - otherwise -> bottom-up per-layer chain: E_i = 0.2 * h_i^0.45 * support
//     (custom E pins the chain; cement-treated layers use their own E;
//      an unbound layer directly above a cement-treated base gets the fixed
//      450 MPa crack-relief modulus; geogrid multiplies by the MIF).
// Returns [{ index, E }] for every auto-mode granular layer (index into the
// full `layers` array), rounded to 2 dp. Layers with no usable thickness are
// skipped so a half-typed row never zeroes the modulus.
// ---------------------------------------------------------------------------
export function computeGranularAutoE(layers, numLayers, subgradeCbr) {
  if (!Array.isArray(layers) || layers.length < 2) return [];
  const n = Math.min(numLayers ?? layers.length, layers.length);
  const structural = layers.slice(0, n - 1);
  const mrs = subgradeModulusFromCBR(subgradeCbr);

  const granIdx = [];
  structural.forEach((l, i) => {
    const t = typeOf(l);
    if (UNBOUND_GRANULAR.has(t) || CEMENT_TREATED.has(t)) granIdx.push(i);
  });
  if (!granIdx.length) return [];

  const isAuto = (l) => !!l?.auto_E && UNBOUND_GRANULAR.has(typeOf(l));
  const hasGeogrid = (l) => !!l?.geogrid && l.geogrid !== 'none';

  const allUnbound = granIdx.every((i) => UNBOUND_GRANULAR.has(typeOf(structural[i])));
  const allAuto = granIdx.every((i) => isAuto(structural[i]));
  const anyGeogrid = granIdx.some((i) => hasGeogrid(structural[i]));

  const out = [];

  if (allUnbound && allAuto && !anyGeogrid && granIdx.length > 1) {
    // IRC §7.2.3 composite collapse — every collapsed layer reports the
    // composite modulus (two stacked layers with the same E and ν are
    // mechanically identical to one combined layer).
    const hTotal = granIdx.reduce((s, i) => s + nominalThickness(structural[i]), 0);
    if (hTotal <= 0) return [];
    const eComp = 0.2 * Math.pow(hTotal, 0.45) * mrs;
    granIdx.forEach((i) => out.push({ index: i, E: Math.round(eComp * 100) / 100 }));
    return out;
  }

  // Per-layer bottom-up chain (mirrors the mixed/treated branch).
  let support = mrs;
  for (let k = granIdx.length - 1; k >= 0; k--) {
    const i = granIdx[k];
    const l = structural[i];
    const t = typeOf(l);
    let E;
    if (CEMENT_TREATED.has(t)) {
      E = Number(l.E) > 0 ? Number(l.E) : (t === 'CTB' ? 5000 : 600);
    } else if (isAuto(l)) {
      const belowT = i + 1 < structural.length ? typeOf(structural[i + 1]) : '';
      if (CEMENT_TREATED.has(belowT)) {
        // IRC:37-2018 §8.3 crack-relief interlayer above a cement-treated base
        E = 450;
      } else {
        const h = nominalThickness(l);
        if (h <= 0) continue; // half-typed row — leave E and the chain as-is
        E = 0.2 * Math.pow(h, 0.45) * support;
      }
      if (hasGeogrid(l)) E *= getMif(mrs, l.geogrid);
      out.push({ index: i, E: Math.round(E * 100) / 100 });
    } else {
      E = Number(l.E) > 0 ? Number(l.E) : support;
      if (hasGeogrid(l)) E *= getMif(mrs, l.geogrid);
    }
    support = E;
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
