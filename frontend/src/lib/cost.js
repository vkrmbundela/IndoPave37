// Material cost and embodied CO2 of a section, per km of one lane: the same
// model as mep_opt/cost/__init__.py (estimate_cost, no haulage):
//   volume = lane width (m) × 1000 m × h (m)
//   cost   = volume × ₹/m³,  CO2 = volume × kg/m³.
// Defaults are the backend's DEFAULT_MATERIAL_RATES; a user rate replaces a
// default only when it is a positive finite number (a blank field keeps it).

export const COST_DEFAULTS = {
  BC: { cost_per_cum: 12500, co2_per_cum: 180 },
  DBM: { cost_per_cum: 10800, co2_per_cum: 165 },
  SMA: { cost_per_cum: 14000, co2_per_cum: 195 },
  SDBC: { cost_per_cum: 9800, co2_per_cum: 160 },
  BM: { cost_per_cum: 8500, co2_per_cum: 145 },
  WMM: { cost_per_cum: 2800, co2_per_cum: 35 },
  WBM: { cost_per_cum: 2500, co2_per_cum: 30 },
  GSB: { cost_per_cum: 1800, co2_per_cum: 25 },
  CTB: { cost_per_cum: 3500, co2_per_cum: 120 },
  CTSB: { cost_per_cum: 3000, co2_per_cum: 90 },
  CRL: { cost_per_cum: 2800, co2_per_cum: 35 },
  RAP: { cost_per_cum: 6000, co2_per_cum: 85 },
};
// estimate_cost() fallback for a material with no rate.
const FALLBACK = { cost_per_cum: 5000, co2_per_cum: 100 };

const positive = (v) => (Number.isFinite(Number(v)) && Number(v) > 0 ? Number(v) : null);

/**
 * @param {{type: string, h: number}[]} layers  structural layers (no subgrade)
 * @param {object} [userRates]  { CODE: { cost_per_cum, co2_per_cum } }
 * @param {number} [laneWidthM]
 * @returns {{cost: number, co2: number}}  ₹ per km and kg CO2 per km
 */
export function sectionCostCo2(layers, userRates = {}, laneWidthM = 3.5) {
  let cost = 0;
  let co2 = 0;
  (layers || []).forEach((l) => {
    const h = Number(l.h);
    if (!(h > 0)) return;
    const code = String(l.type || '').toUpperCase().trim();
    const base = COST_DEFAULTS[code] || FALLBACK;
    const user = userRates?.[code] || {};
    const volume = laneWidthM * 1000 * (h / 1000);
    cost += volume * (positive(user.cost_per_cum) ?? base.cost_per_cum);
    co2 += volume * (positive(user.co2_per_cum) ?? base.co2_per_cum);
  });
  return { cost: Math.round(cost), co2: Math.round(co2 * 10) / 10 };
}
