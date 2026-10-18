// Content checks for the client-side PDF report: the printed traffic inputs
// must reproduce the printed MSA (IRC Eq. 4.6 x term, road category), the
// reliability labels must follow the level the engine used (IRC:37-2018
// Sec 3.7), and an all-compressive bituminous strain must be reported as
// "fatigue not checked" (Annex III) instead of a fake fatigue criterion.
//
// Run: npm test

import { describe, it, expect } from 'vitest';
import { buildPdfReport } from './pdf-report';

// Concatenate every "(...) Tj" string of one page; wrapped continuation lines
// are emitted as "T* (...) Tj" (jsPDF escapes parens).
function pageText(doc, p) {
  const ops = doc.internal.pages[p].map(String).join('\n').split('\n');
  const out = [];
  for (const line of ops) {
    const m = /^(?:T\* )?\((.*)\) Tj$/.exec(line.trim());
    if (m) out.push(m[1].replace(/\\([()\\])/g, '$1'));
  }
  return out.join(' ');
}
const allText = (doc) =>
  Array.from({ length: doc.getNumberOfPages() }, (_, i) => pageText(doc, i + 1)).join('\n');

function solution(details = {}) {
  const layers = [
    { id: 1, name: 'BC', thickness: 40, modulus: 2000, poisson: 0.35 },
    { id: 2, name: 'DBM', thickness: 60, modulus: 2000, poisson: 0.35 },
    { id: 3, name: 'WMM', thickness: 250, modulus: 220, poisson: 0.35 },
    { id: 4, name: 'GSB', thickness: 200, modulus: 220, poisson: 0.35 },
    { id: 5, name: 'Subgrade', thickness: 0, modulus: 62, poisson: 0.35 },
  ];
  return {
    total_thickness: 550,
    cost: 7e6,
    co2: 90000,
    optimal_layers: layers.slice(0, 4).map((l) => ({ type: l.name, thickness: l.thickness })),
    details: {
      overall_adequate: true, governing_mode: 'rutting', msa: 6.4,
      eps_t: 210e-6, eps_v: 400e-6, Nf: 4e7, NR: 2e7,
      CDF_fatigue: 0.16, CDF_rutting: 0.32,
      air_voids: 3, bitumen_volume: 11.5, strategy: 'Structural',
      layers,
      ...details,
    },
  };
}

function build(sol, traffic = {}) {
  return buildPdfReport({
    projectName: 'content test',
    trafficParams: {
      cvpd: 400, growth_rate: 0.05, vdf: 2.5, ldf: 0.75, design_life: 15,
      construction_years: 2, road_category: 'nh', ...traffic,
    },
    subgradeCbr: 6,
    selectedSolution: sol,
    adequateDesigns: [sol],
    airVoids: 3,
    bitumenVolume: 11.5,
    granularAutoE: true,
  });
}

describe('pdf-report content', () => {
  it('prints the count-to-opening years (Eq 4.6) and the road category', () => {
    const basis = pageText(build(solution({ reliability: 'R90', road_category: 'nh' })), 2);
    expect(basis).toContain('Years from count to opening (x)');
    expect(basis).toContain('2 years');
    expect(basis).toContain('A = P(1+r)^x');
    expect(basis).toContain('Road category');
    expect(basis).toContain('National Highway');
  });

  it('labels reliability from the engine-reported level (NH below 20 msa is 90%)', () => {
    const doc = build(solution({ reliability: 'R90', road_category: 'nh' }));
    expect(pageText(doc, 2)).toContain('90% (National Highway)');
    expect(pageText(doc, 4)).toContain('90% reliability');
    expect(allText(doc)).toContain('this design: 90%');
  });

  it('falls back to the Sec 3.7 rule only when the engine level is absent', () => {
    const nh = build(solution(), { road_category: 'nh' });
    expect(pageText(nh, 2)).toContain('90% (National Highway)');
    const other = build(solution(), { road_category: 'other' });
    expect(pageText(other, 2)).toContain('80% (Other road, < 20 MSA)');
    expect(pageText(other, 4)).toContain('80% reliability');
  });

  it('states the Sec 3.7 rule in the clause checklist (not the MSA-only rule)', () => {
    const text = allText(build(solution({ reliability: 'R90', road_category: 'nh' })));
    expect(text).not.toContain('Reliability auto-set');
    expect(text).toMatch(/Expressways, National\s+Highways, State Highways and Urban Roads at any traffic/);
  });

  it('reports an all-compressive bituminous strain as fatigue not checked (Annex III)', () => {
    const doc = build(solution({
      reliability: 'R90', road_category: 'nh',
      eps_t: -35e-6, fatigue_compressive: true, CDF_fatigue: 0, Nf: null,
    }));
    const compliancePage = pageText(doc, 4);
    expect(compliancePage).toContain('NOT CHECKED');
    expect(compliancePage).toContain('Annex III');
    expect(compliancePage).not.toContain('N_f (allowable reps)');
  });
});

describe('pdf-report content (verification round 3)', () => {
  it('follows the engine level even where the Sec 3.7 fallback disagrees', () => {
    // 'other' road at 6.4 msa: the fallback would give 80%; the engine said R90.
    const doc = build(solution({ reliability: 'R90', road_category: 'other' }), { road_category: 'other' });
    const page4 = pageText(doc, 4);
    expect(page4).toContain('90% reliability');
    expect(page4).toContain('0.5161');
    expect(page4).not.toContain('1.6064');
  });

  it('uses the road category for the fallback on the compliance page too', () => {
    const doc = build(solution({ reliability: undefined, road_category: undefined }), { road_category: 'nh' });
    expect(pageText(doc, 4)).toContain('90% reliability');
  });

  it('numbers the performance equations as IRC:37-2018 does', () => {
    const page4 = pageText(build(solution({ reliability: 'R80', road_category: 'other' }), { road_category: 'other' }), 4);
    expect(page4).toMatch(/Subgrade Rutting.*Eq 3\.1\/3\.2/);
    expect(page4).toMatch(/Bituminous Fatigue Cracking.*Eq 3\.3\/3\.4/);
  });
});

describe('long-life pavement and mix basis (IRC:37-2018 Sec 10, Table 9.2)', () => {
  it('prints the endurance-limit check when the design is long-life', () => {
    const sol = solution({ msa: 320, eps_t: 76e-6, eps_v: 150e-6,
      long_life: { eps_t_limit: 80e-6, eps_v_limit: 200e-6, ratio_t: 0.95, ratio_v: 0.75, ratio: 0.95, governing: 'fatigue', ok: true } });
    const text = allText(buildPdfReport({
      projectName: 'll', trafficParams: { cvpd: 4000, growth_rate: 0.05, vdf: 5, ldf: 0.6, design_life: 30, road_category: 'expressway' },
      subgradeCbr: 7, selectedSolution: sol, adequateDesigns: [sol], airVoids: 3, bitumenVolume: 11.5,
      binderGrade: 'VG40', temperature: 35, table92: 3000,
    }));
    expect(text).toContain('Long-Life Pavement (Endurance Limits)');
    expect(text).toContain('80 ue');
    expect(text).toContain('0.950');
    expect(text).toContain('Binder of the bottom mix');
    expect(text).toContain('VG40');
    expect(text).toContain('3000 MPa');
  });
  it('omits the long-life check for a conventional design', () => {
    const text = allText(build(solution()));
    expect(text).not.toContain('Long-Life Pavement');
  });
});
