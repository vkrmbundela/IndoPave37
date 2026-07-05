// Layout regression guard for the client-side PDF report.
//
// The July-2026 overlap bugs (units overprinting cover-card values, the
// criterion rule striking through equation text, content risking the footer
// band) all came from unmeasured layout. This test builds REAL reports via
// buildPdfReport() and scans the raw PDF content-stream operations of every
// page, asserting that no text is placed into the footer band except the
// three footer strings that belong there. A content overflow past the
// footer immediately fails this test.
//
// Run: npm test   (vitest resolves the extensionless './irc' import like Vite)

import { describe, it, expect } from 'vitest';
import { buildPdfReport } from './pdf-report';

// PDF user-space units are points, origin bottom-left. A4 = 595.28 x 841.89.
const FOOTER_BAND_PT = 36;  // headerFooter() draws its rule at ~34 pt; the
                            // 3 footer strings sit at ~22.7 pt baselines.
const FOOTER_TEXT_ALLOWANCE = 3; // "Generated...", "Native solver...", "Page x of y"

// jsPDF's internal page buffers hold multi-operation chunks — flatten to
// individual content-stream lines before matching operations.
function pageOpLines(pageChunks) {
  return pageChunks.map(String).join('\n').split('\n').map((l) => l.trim());
}

function textOpYs(pageChunks) {
  // jsPDF emits absolute "x y Td" positioning for every doc.text() call.
  const ys = [];
  for (const line of pageOpLines(pageChunks)) {
    const m = /^(-?[\d.]+) (-?[\d.]+) Td$/.exec(line);
    if (m) ys.push(parseFloat(m[2]));
  }
  return ys;
}

function assertNoFooterCollisions(doc, label) {
  // doc.internal.pages: index 0 unused; 1..n are arrays of content lines.
  const pages = doc.internal.pages;
  for (let p = 1; p < pages.length; p++) {
    const ys = textOpYs(pages[p]);
    expect(ys.length, `${label} page ${p}: no text ops found`).toBeGreaterThan(0);
    const inFooterBand = ys.filter((y) => y < FOOTER_BAND_PT);
    expect(
      inFooterBand.length,
      `${label} page ${p}: ${inFooterBand.length} text ops in the footer band ` +
      `(y < ${FOOTER_BAND_PT} pt) — content overflowed past the footer rule`
    ).toBeLessThanOrEqual(FOOTER_TEXT_ALLOWANCE);
    // Nothing may be positioned off the bottom of the page.
    expect(Math.min(...ys), `${label} page ${p}: text below the page edge`).toBeGreaterThan(10);
  }
}

const layer = (name, thickness, modulus, poisson = 0.35, id = 0) =>
  ({ id, name, thickness, modulus, poisson });

function flexibleSolution() {
  const layers = [
    layer('BC', 40, 2000, 0.35, 1),
    layer('DBM', 50, 2000, 0.35, 2),
    layer('WMM', 250, 218, 0.35, 3),
    layer('GSB', 250, 218, 0.35, 4),
    layer('Subgrade', 0, 66.6, 0.35, 5),
  ];
  return {
    total_thickness: 590,
    cost: 8.1e6,
    co2: 96000,
    optimal_layers: layers.slice(0, 4).map((l) => ({ type: l.name, thickness: l.thickness })),
    details: {
      overall_adequate: true, governing_mode: 'fatigue', msa: 18.1, reliability: 'R80',
      eps_t: 315.6e-6, eps_v: 380.4e-6, Nf: 3.19e7, NR: 1.33e8,
      CDF_fatigue: 0.567, CDF_rutting: 0.136,
      air_voids: 3, bitumen_volume: 11.5, strategy: 'Structural',
      layers,
    },
  };
}

function ctbSolution() {
  const layers = [
    layer('BC', 40, 2000, 0.35, 1),
    layer('DBM', 50, 2000, 0.35, 2),
    layer('WMM', 100, 450, 0.35, 3),
    layer('CTB', 150, 5000, 0.25, 4),
    layer('GSB', 250, 218, 0.35, 5),
    layer('Subgrade', 0, 66.6, 0.35, 6),
  ];
  return {
    total_thickness: 590,
    cost: 8.1e6,
    co2: 96000,
    optimal_layers: layers.slice(0, 5).map((l) => ({ type: l.name, thickness: l.thickness })),
    details: {
      overall_adequate: true, governing_mode: 'ctb', msa: 48.7, reliability: 'R90',
      eps_t: 180e-6, eps_v: 260e-6, Nf: 9e7, NR: 2e8,
      CDF_fatigue: 0.54, CDF_rutting: 0.24,
      CDF_ctb: 0.41, CDF_ctb_strain: 0.41, Nf_ctb_strain: 4.4e7,
      sigma_t_ctb: 0.313, eps_t_ctb: 53.5e-6,
      ctb_details: { CDF_ctb: 0.22, details: [{ load_kn: 80 }, { load_kn: 120 }, { load_kn: 190 }] },
      air_voids: 3, bitumen_volume: 11.5, strategy: 'Structural',
      layers,
    },
  };
}

// Worst-case geometry: 10 structural layers (cross-section minimum heights),
// 12 alternative designs (section-5 table pagination), long project name,
// two-line CTB equation — everything that previously relied on guessed space.
function stressSolution() {
  const names = ['BC', 'SMA', 'DBM', 'BM', 'WMM', 'WBM', 'CRL', 'CTB', 'CTSB', 'GSB'];
  const layers = names.map((n, i) => layer(n, 100 + 10 * i, 500 + 100 * i, 0.35, i + 1));
  layers.push(layer('Subgrade', 0, 55, 0.35, names.length + 1));
  return {
    total_thickness: layers.slice(0, -1).reduce((s, l) => s + l.thickness, 0),
    cost: 2.4e7,
    co2: 310000,
    optimal_layers: layers.slice(0, -1).map((l) => ({ type: l.name, thickness: l.thickness })),
    details: {
      overall_adequate: false, governing_mode: 'rutting', msa: 165.2, reliability: 'R90',
      eps_t: 410e-6, eps_v: 505e-6, Nf: 4.1e6, NR: 8.8e6,
      CDF_fatigue: 1.71, CDF_rutting: 2.02,
      CDF_ctb: 1.35, CDF_ctb_strain: 1.35, Nf_ctb_strain: 1.2e8,
      sigma_t_ctb: 0.62, eps_t_ctb: 92e-6,
      ctb_details: { CDF_ctb: 0.9, details: [{ load_kn: 190 }] },
      air_voids: 5.5, bitumen_volume: 10.0, strategy: 'Structural',
      layers,
    },
  };
}

function build(sol, designs, extra = {}) {
  return buildPdfReport({
    projectName: extra.projectName ?? 'IndoPave-37 — layout regression',
    trafficParams: { cvpd: 800, growth_rate: 0.05, vdf: 2.5, ldf: 0.75, design_life: 20 },
    subgradeCbr: 8,
    selectedSolution: sol,
    adequateDesigns: designs,
    airVoids: 3,
    bitumenVolume: 11.5,
    granularAutoE: extra.granularAutoE ?? true,
  });
}

describe('pdf-report layout regression', () => {
  it('flexible report builds with no footer-band collisions', () => {
    const doc = build(flexibleSolution(), [flexibleSolution()]);
    expect(doc.getNumberOfPages()).toBeGreaterThanOrEqual(5);
    assertNoFooterCollisions(doc, 'flexible');
  });

  it('CTB report (dual-check block, two-line equation) stays inside the page', () => {
    const doc = build(ctbSolution(), [ctbSolution(), ctbSolution()]);
    expect(doc.getNumberOfPages()).toBeGreaterThanOrEqual(5);
    assertNoFooterCollisions(doc, 'ctb');
  });

  it('stress case: 10 layers, 12 designs, long name, manual moduli, FAIL stamps', () => {
    const sol = stressSolution();
    const doc = build(sol, Array.from({ length: 12 }, () => sol), {
      projectName:
        'A deliberately very long project name that must be clamped to a single ' +
        'line inside the cover bar instead of escaping across the page margin — ' +
        'National Corridor Package 7B, Section 12, km 118+400 to 163+250',
      granularAutoE: false,
    });
    expect(doc.getNumberOfPages()).toBeGreaterThanOrEqual(5);
    assertNoFooterCollisions(doc, 'stress');
  });

  it('cover value/unit composition is width-measured (no overprint possible)', () => {
    // Regression for the "18.1MSA" overlap: the unit's x offset must be at
    // least the value's width at the VALUE font size. Rebuild the cover and
    // read back consecutive Td x-positions on page 1 for the four cards.
    const doc = build(flexibleSolution(), [flexibleSolution()]);
    const page1 = pageOpLines(doc.internal.pages[1]);
    // Find the card value "18.1" op and the following unit op on the same baseline.
    const tdOps = [];
    for (let i = 0; i < page1.length; i++) {
      const m = /^(-?[\d.]+) (-?[\d.]+) Td$/.exec(page1[i]);
      const t = i + 1 < page1.length && /^\((.*)\) Tj$/.exec(page1[i + 1]);
      if (m && t) tdOps.push({ x: parseFloat(m[1]), y: parseFloat(m[2]), text: t[1] });
    }
    const value = tdOps.find((o) => o.text === '18.1');
    expect(value, 'cover card value "18.1" not found').toBeTruthy();
    const unit = tdOps.find((o) => o.text === 'MSA' && Math.abs(o.y - value.y) < 0.5);
    expect(unit, 'cover card unit "MSA" not found on the value baseline').toBeTruthy();
    // 16 pt bold "18.1" is ~9.5 mm ≈ 27 pt wide; the old bug measured it at
    // 8 pt (~13.5 pt) and overprinted. Require a sane 16-pt-scale offset.
    expect(unit.x - value.x).toBeGreaterThan(20);
  });
});
