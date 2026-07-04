// Client-side IRC:37 PDF report (jsPDF) — works with no backend, so the
// "PDF Report" button functions on the static GitHub-Pages deploy too.
// Mirrors the content of the server-side ReportLab report. Text is kept
// ASCII-safe because jsPDF's built-in fonts don't carry ε/σ/≤/✓ glyphs.
import { jsPDF } from 'jspdf';
import autoTable from 'jspdf-autotable';
import { subgradeModulusFromCBR } from './irc';

const BRAND = [232, 99, 26];
const BRAND_DK = [184, 78, 18];
const INK = [15, 23, 42];
const MUTED = [100, 116, 139];
const LINE = [226, 232, 240];
const PANEL = [241, 245, 249];
const SURFACE = [248, 250, 252];
const GREEN = [21, 128, 61];
const GREEN_BG = [236, 253, 245];
const RED = [185, 28, 28];
const RED_BG = [254, 242, 242];

const PAGE_W = 210, PAGE_H = 297, M = 18;
const CONTENT_W = PAGE_W - 2 * M;

const FAT_EXP = 3.89, RUT_EXP = 4.5337;

const num = (v, d = 0) => (Number.isFinite(Number(v)) ? Number(v) : d);
const allowableStrain = (eps, cdf, n) => {
  eps = Math.abs(num(eps)); cdf = num(cdf);
  return (eps > 0 && cdf > 0) ? eps * Math.pow(cdf, -1 / n) : null;
};
const ue = (v) => (v == null ? '--' : `${(Math.abs(num(v)) * 1e6).toFixed(1)} ue`);

function logoMark(doc, x, y, s) {
  doc.setFillColor(...BRAND); doc.roundedRect(x, y, s, s, s * 0.24, s * 0.24, 'F');
  doc.setFillColor(255, 255, 255);
  doc.setFont('helvetica', 'bold'); doc.setFontSize(s * 1.5);
  doc.text('IP', x + s / 2, y + s * 0.68, { align: 'center' });
}

function headerFooter(doc, totalPages) {
  for (let p = 1; p <= totalPages; p++) {
    doc.setPage(p);
    if (p > 1) {
      logoMark(doc, M, 8, 5);
      doc.setFont('helvetica', 'bold'); doc.setFontSize(9); doc.setTextColor(...INK);
      doc.text('IndoPave-37', M + 6.5, 11.5);
      doc.setFont('helvetica', 'normal'); doc.setFontSize(7); doc.setTextColor(...MUTED);
      doc.text('Flexible Pavement Design Report  -  IRC:37-2018/2019', PAGE_W - M, 11.5, { align: 'right' });
      doc.setDrawColor(...LINE); doc.setLineWidth(0.2); doc.line(M, 14, PAGE_W - M, 14);
    }
    doc.setDrawColor(...LINE); doc.setLineWidth(0.2); doc.line(M, PAGE_H - 12, PAGE_W - M, PAGE_H - 12);
    doc.setFont('helvetica', 'normal'); doc.setFontSize(7); doc.setTextColor(150, 160, 175);
    doc.text(`Generated ${new Date().toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })}  -  IndoPave-37`, M, PAGE_H - 8);
    doc.text('Native multi-layer elastic (Burmister) solver - IITPAVE-equivalent', PAGE_W / 2, PAGE_H - 8, { align: 'center' });
    doc.text(`Page ${p} of ${totalPages}`, PAGE_W - M, PAGE_H - 8, { align: 'right' });
  }
}

function sectionHeading(doc, y, title, clause) {
  doc.setFont('helvetica', 'bold'); doc.setFontSize(10.5); doc.setTextColor(...BRAND_DK);
  doc.text(title, M, y);
  if (clause) {
    doc.setFont('helvetica', 'bold'); doc.setFontSize(7.5);
    doc.text(clause, PAGE_W - M, y, { align: 'right' });
  }
  doc.setDrawColor(...BRAND); doc.setLineWidth(0.5); doc.line(M, y + 1.5, PAGE_W - M, y + 1.5);
  return y + 7;
}

function kvTable(doc, y, rows) {
  autoTable(doc, {
    startY: y, margin: { left: M, right: M },
    body: rows, theme: 'plain',
    styles: { fontSize: 8.6, cellPadding: 1.6, textColor: INK, lineColor: LINE, lineWidth: { bottom: 0.15 } },
    columnStyles: {
      0: { cellWidth: 72, textColor: MUTED },
      1: { cellWidth: 50, fontStyle: 'bold' },
      2: { cellWidth: CONTENT_W - 122, textColor: [150, 160, 175], fontSize: 7 },
    },
  });
  return doc.lastAutoTable.finalY + 4;
}

// ---- Cover ----
function cover(doc, project, traffic, cbr, sol) {
  doc.setFillColor(...INK); doc.rect(0, 0, PAGE_W, 16, 'F');
  doc.setFillColor(...BRAND); doc.rect(0, 16, PAGE_W, 1.6, 'F');
  logoMark(doc, M, 3.4, 9);
  doc.setFont('helvetica', 'bold'); doc.setFontSize(12); doc.setTextColor(255, 255, 255);
  doc.text('IndoPave-37', M + 12, 8.5);
  doc.setFont('helvetica', 'normal'); doc.setFontSize(8); doc.setTextColor(203, 213, 225);
  doc.text('Mechanistic-Empirical Pavement Design Suite', M + 12, 12.5);
  doc.setTextColor(148, 163, 184);
  doc.text('IRC:37-2018 / 2019', PAGE_W - M, 10.5, { align: 'right' });

  let y = 34;
  doc.setFont('helvetica', 'bold'); doc.setFontSize(22); doc.setTextColor(...INK);
  doc.text('Flexible Pavement Design Report', M, y); y += 8;
  doc.setFont('helvetica', 'normal'); doc.setFontSize(10.5); doc.setTextColor(...MUTED);
  doc.text('Mechanistic-empirical design & verification per IRC:37-2018 / 2019.', M, y); y += 10;

  // Project bar
  doc.setFillColor(...PANEL); doc.rect(M, y, CONTENT_W, 11, 'F');
  doc.setFillColor(...BRAND); doc.rect(M, y, 1.6, 11, 'F');
  doc.setFont('helvetica', 'normal'); doc.setFontSize(7); doc.setTextColor(...MUTED);
  doc.text('PROJECT', M + 5, y + 4.5);
  doc.setFont('helvetica', 'bold'); doc.setFontSize(10); doc.setTextColor(...INK);
  doc.text(String(project || 'Untitled Design Session'), M + 5, y + 8.5);
  y += 18;

  const d = sol.details || {};
  const adequate = !!d.overall_adequate;
  const msa = num(d.msa, num(traffic.msa));
  const totalT = num(sol.total_thickness);
  const mr = subgradeModulusFromCBR(cbr);
  const gov = d.governing_mode || '--';
  const govCdf = Math.max(num(d.CDF_fatigue), num(d.CDF_rutting), num(d.CDF_ctb));
  const reserve = govCdf > 0 ? (1 / govCdf - 1) * 100 : null;

  // Stamp
  const [bg, fg] = adequate ? [GREEN_BG, GREEN] : [RED_BG, RED];
  doc.setFillColor(...bg); doc.setDrawColor(...fg); doc.setLineWidth(0.5);
  doc.rect(M, y, CONTENT_W, 18, 'FD');
  doc.setFont('helvetica', 'bold'); doc.setFontSize(15); doc.setTextColor(...fg);
  doc.text(adequate ? 'IRC:37 COMPLIANT' : 'IRC:37 NON-COMPLIANT', M + 6, y + 8);
  doc.setFont('helvetica', 'normal'); doc.setFontSize(8); doc.setTextColor(71, 85, 105);
  doc.text(adequate ? `All cumulative damage factors <= 1.0  -  governed by ${gov}`
                    : 'One or more damage factors exceed 1.0 - revise the section', M + 6, y + 13.5);
  y += 26;

  // Key cards 2x2
  const cw = (CONTENT_W - 6) / 2, ch = 20;
  const cards = [
    ['DESIGN TRAFFIC', `${msa.toFixed(1)}`, 'MSA'],
    ['SUBGRADE MODULUS', `${mr.toFixed(0)}`, `MPa  (CBR ${num(cbr)}%)`],
    ['TOTAL CRUST', `${totalT.toFixed(0)}`, 'mm'],
    ['STRUCTURAL RESERVE', reserve == null ? '--' : `${reserve >= 0 ? '+' : ''}${reserve.toFixed(0)}`, `%  -  gov: ${gov}`],
  ];
  cards.forEach((c, i) => {
    const cx = M + (i % 2) * (cw + 6), cy = y + Math.floor(i / 2) * (ch + 6);
    doc.setFillColor(...SURFACE); doc.setDrawColor(...LINE); doc.setLineWidth(0.2);
    doc.rect(cx, cy, cw, ch, 'FD');
    doc.setFont('helvetica', 'normal'); doc.setFontSize(7); doc.setTextColor(...MUTED);
    doc.text(c[0], cx + 5, cy + 6);
    doc.setFont('helvetica', 'bold'); doc.setFontSize(16); doc.setTextColor(...INK);
    doc.text(c[1], cx + 5, cy + 14);
    doc.setFont('helvetica', 'normal'); doc.setFontSize(8); doc.setTextColor(...MUTED);
    doc.text(c[2], cx + 5 + doc.getTextWidth(c[1]) + 2, cy + 14);
  });
  y += 2 * ch + 6 + 8;

  doc.setFont('helvetica', 'normal'); doc.setFontSize(7.6); doc.setTextColor(...MUTED);
  const note = doc.splitTextToSize(
    'Generated by IndoPave-37 using a native multi-layer elastic (Burmister) solver - the mathematical equivalent of the official IITPAVE engine, validated against the IRC:37-2018 Annex-II worked examples (et 146 vs 146 ue; ev 245 vs 243 ue; CTB sigma_t 0.699 vs 0.700 MPa) and a recorded IITPAVE run. Final designs must be reviewed and approved by a qualified pavement engineer.',
    CONTENT_W);
  doc.text(note, M, y);
}

// ---- Design basis ----
function designBasis(doc, traffic, cbr, sol, mix) {
  let y = 24;
  doc.setFont('helvetica', 'bold'); doc.setFontSize(13); doc.setTextColor(...INK);
  doc.text('1.  Design Basis & Inputs', M, y); y += 8;
  const d = sol.details || {};
  const gr = num(traffic.growth_rate);
  const grPct = Math.abs(gr) <= 1 ? gr * 100 : gr;
  const msa = num(d.msa, num(traffic.msa));
  const c = num(cbr);
  const mr = subgradeModulusFromCBR(c);

  y = sectionHeading(doc, y, 'Traffic', 'IRC:37-2018 Sec 4');
  y = kvTable(doc, y, [
    ['Commercial vehicles / day (CVPD)', String(num(traffic.cvpd)), ''],
    ['Annual growth rate', `${grPct.toFixed(1)} %`, ''],
    ['Vehicle damage factor (VDF)', String(num(traffic.vdf, 2.5)), 'std axles / CV'],
    ['Design life', `${num(traffic.design_life, 20)} years`, ''],
    ['Cumulative design traffic', `${msa.toFixed(2)} MSA`, '365.A.D.F.((1+r)^n-1)/r'],
  ]);
  y = sectionHeading(doc, y, 'Subgrade', 'IRC:37-2018 Sec 6 - Eq 6.1/6.2, Cl 6.4.2');
  y = kvTable(doc, y, [
    ['Design CBR (4-day soaked)', `${c}%`, 'IS:2720 Pt-16'],
    ['Effective resilient modulus MRS', `${mr.toFixed(1)} MPa`, c <= 5 ? '10 x CBR' : '17.6 x CBR^0.64'],
    ['Design ceiling on MRS', '100 MPa', 'Cl. 6.4.2'],
    ["Poisson's ratio (subgrade)", '0.35', 'Sec 6.3'],
  ]);
  y = sectionHeading(doc, y, 'Standard Axle & Loading', 'IRC:37-2018 Sec 3.6.1');
  y = kvTable(doc, y, [
    ['Standard axle', '80 kN single axle, dual wheels', 'Sec 3.6.1'],
    ['Wheel load (one of a dual set)', '20 000 N', ''],
    ['Tyre contact pressure', '0.56 MPa', '0.80 MPa for CTB'],
    ['Dual-wheel spacing (c/c)', '310 mm', ''],
    ['Layer interface', 'fully bonded', 'Sec 3.6.1'],
  ]);
  // Prefer the reliability the ENGINE actually used (post §3.7 escalation,
  // reported on the solution details); fall back to the MSA heuristic.
  const relUsed = d.reliability || (msa >= 20 ? 'R90' : 'R80');
  const rel = relUsed === 'R90'
    ? '90% (mandatory >= 20 MSA)'
    : '80% (low-volume, < 20 MSA)';
  y = sectionHeading(doc, y, 'Reliability & Mix', 'IRC:37-2018 Sec 3.7, 3.6.2');
  const va = num(mix?.airVoids, num(d.air_voids, 3));
  const vbe = num(mix?.bitumenVolume, num(d.bitumen_volume, 11.5));
  kvTable(doc, y, [
    ['Design reliability level', rel, 'Sec 3.7'],
    ['Air voids Va (bottom mix)', `${va} %`, 'fatigue C-factor'],
    ['Effective bitumen volume Vbe', `${vbe} %`, 'fatigue C-factor'],
  ]);
}

// ---- Composition + cross-section ----
function composition(doc, sol, granularAutoE) {
  let y = 24;
  doc.setFont('helvetica', 'bold'); doc.setFontSize(13); doc.setTextColor(...INK);
  doc.text('2.  Pavement Composition', M, y); y += 8;
  const d = sol.details || {};
  const rich = d.layers && d.layers.length
    ? d.layers.map((l) => ({ name: l.name, thickness: num(l.thickness), modulus: num(l.modulus), poisson: l.poisson }))
    : (sol.optimal_layers || []).map((l) => ({ name: l.type, thickness: num(l.thickness), modulus: null, poisson: null }));
  const nuMap = { CTB: '0.25', CTSB: '0.25' };
  const body = []; let crust = 0;
  rich.forEach((l, i) => {
    const sub = String(l.name).toLowerCase().startsWith('sub');
    if (!sub) crust += l.thickness;
    // Prefer the engine-reported Poisson ratio; only fall back to the IRC
    // defaults when the backend didn't include it (older responses).
    const nuShown = Number.isFinite(Number(l.poisson)) && Number(l.poisson) > 0
      ? Number(l.poisson).toFixed(2)
      : (nuMap[String(l.name).toUpperCase()] || '0.35');
    body.push([sub ? '--' : String(i + 1), l.name, sub || !l.thickness ? 'inf (half-space)' : l.thickness.toFixed(0),
      l.modulus ? l.modulus.toFixed(0) : '--', nuShown]);
  });
  body.push(['', 'Total bound + unbound crust', crust.toFixed(0), '', '']);
  autoTable(doc, {
    startY: y, margin: { left: M, right: M },
    head: [['#', 'Layer / Material', 'Thickness (mm)', 'Modulus E (MPa)', 'Poisson']],
    body, theme: 'grid',
    headStyles: { fillColor: INK, textColor: 255, fontSize: 8.4 },
    styles: { fontSize: 8.2, cellPadding: 1.6, lineColor: LINE },
    columnStyles: { 0: { cellWidth: 10, halign: 'center' }, 2: { halign: 'center' }, 3: { halign: 'center' }, 4: { halign: 'center' } },
    didParseCell: (h) => { if (h.row.index === body.length - 1) { h.cell.styles.fillColor = PANEL; h.cell.styles.fontStyle = 'bold'; } },
  });
  y = doc.lastAutoTable.finalY + 3;
  doc.setFont('helvetica', 'normal'); doc.setFontSize(7.4); doc.setTextColor(...MUTED);
  doc.text(doc.splitTextToSize(
    granularAutoE
      ? 'Granular moduli from IRC:37-2018 Eq. 7.1 (0.2.h^0.45.MR_support); unbound base + sub-base combined per Sec 7.2.3.'
      : 'Granular moduli are USER-SPECIFIED (Auto Eq. 7.1 mode was off) - IRC:37-2018 Eq. 7.1 / Sec 7.2.3 derivation was NOT applied; verify the pinned values against project material testing.',
    CONTENT_W), M, y);
  y += 8;

  // Cross-section
  y = sectionHeading(doc, y, 'Cross-Section', null);
  const struct = rich.filter((l) => !String(l.name).toLowerCase().startsWith('sub'));
  const total = struct.reduce((a, l) => a + l.thickness, 0) || 1;
  const maxH = Math.min(PAGE_H - 30 - y, 120);
  const secW = 95, x0 = M + 6; let yy = y;
  const colors = { BC: [30, 41, 59], DBM: [51, 65, 85], SMA: [40, 53, 72], SDBC: [63, 78, 99], BM: [71, 85, 105], WMM: [154, 123, 79], WBM: [169, 142, 99], GSB: [201, 176, 132], CRL: [183, 154, 106], CTB: [107, 123, 140], CTSB: [126, 140, 154] };
  let cum = 0;
  struct.forEach((l) => {
    const h = Math.max((l.thickness / total) * maxH, 9);
    const col = colors[String(l.name).toUpperCase()] || [138, 148, 166];
    doc.setFillColor(...col); doc.setDrawColor(255, 255, 255); doc.setLineWidth(0.4);
    doc.rect(x0, yy, secW, h, 'FD');
    doc.setFont('helvetica', 'bold'); doc.setFontSize(8); doc.setTextColor(255, 255, 255);
    doc.text(`${l.name}  -  ${l.thickness.toFixed(0)} mm`, x0 + secW / 2, yy + h / 2 + 1.2, { align: 'center' });
    if (l.modulus) { doc.setFont('helvetica', 'normal'); doc.setFontSize(7); doc.setTextColor(...MUTED); doc.text(`E = ${l.modulus.toFixed(0)} MPa`, x0 + secW + 4, yy + h / 2 + 1); }
    doc.setFontSize(6.5); doc.setTextColor(150, 160, 175); doc.text(`${cum.toFixed(0)}`, x0 - 2, yy + 1.5, { align: 'right' });
    cum += l.thickness; yy += h;
  });
  doc.setFontSize(6.5); doc.setTextColor(150, 160, 175); doc.text(`${cum.toFixed(0)}`, x0 - 2, yy + 1.5, { align: 'right' });
  doc.setFillColor(107, 68, 35); doc.rect(x0, yy, secW, 10, 'FD');
  doc.setFont('helvetica', 'bold'); doc.setFontSize(7.5); doc.setTextColor(255, 255, 255);
  doc.text('SUBGRADE (semi-infinite)', x0 + secW / 2, yy + 6, { align: 'center' });
}

// ---- Criterion block ----
function criterion(doc, y, title, clause, equation, rows, ok) {
  const [bg, fg] = ok ? [GREEN_BG, GREEN] : [RED_BG, RED];
  doc.setFillColor(...PANEL); doc.rect(M, y, CONTENT_W, 7, 'F');
  doc.setDrawColor(...fg); doc.setLineWidth(0.6); doc.line(M, y + 7, PAGE_W - M, y + 7);
  doc.setFont('helvetica', 'bold'); doc.setFontSize(8.6); doc.setTextColor(...INK);
  doc.text(title, M + 2, y + 4.8);
  doc.setFontSize(7.5); doc.setTextColor(...BRAND_DK); doc.text(clause, M + 95, y + 4.8);
  doc.setFontSize(8.6); doc.setTextColor(...fg); doc.text(ok ? 'PASS' : 'FAIL', PAGE_W - M - 2, y + 4.8, { align: 'right' });
  y += 9;
  doc.setFont('helvetica', 'italic'); doc.setFontSize(8.4); doc.setTextColor(...INK);
  doc.text(doc.splitTextToSize(equation, CONTENT_W - 4), M + 2, y); y += equation.length > 90 ? 7 : 4;
  autoTable(doc, {
    startY: y, margin: { left: M, right: M }, head: [rows[0]], body: rows.slice(1), theme: 'grid',
    headStyles: { fillColor: SURFACE, textColor: MUTED, fontSize: 8 },
    styles: { fontSize: 8.2, cellPadding: 1.6, lineColor: LINE, halign: 'center' },
    columnStyles: { 0: { halign: 'left' } },
  });
  return doc.lastAutoTable.finalY + 5;
}

function compliance(doc, sol) {
  let y = 24;
  doc.setFont('helvetica', 'bold'); doc.setFontSize(13); doc.setTextColor(...INK);
  doc.text('3.  Mechanistic-Empirical Compliance Check', M, y); y += 8;
  const d = sol.details || {};
  const msa = num(d.msa); const nApp = msa * 1e6;
  doc.setFont('helvetica', 'normal'); doc.setFontSize(9); doc.setTextColor(...INK);
  doc.text(doc.splitTextToSize(`Design repetitions N_applied = ${msa.toFixed(2)} x 10^6 standard axles. A criterion passes when CDF = N_applied / N_allowable <= 1.0.`, CONTENT_W), M, y);
  y += 9;

  // Reliability the engine actually used (post §3.7 auto-escalation) — the
  // printed coefficients must match the computation, not always the R90 row.
  const relUsed = d.reliability || (msa >= 20 ? 'R90' : 'R80');
  const rutCoeff = relUsed === 'R90' ? '1.41 x 10^-8' : '4.1656 x 10^-8';
  const fatCoeff = relUsed === 'R90' ? '0.5161' : '1.6064';
  const relPct = relUsed === 'R90' ? '90%' : '80%';

  const cdfR = num(d.CDF_rutting), nr = num(d.NR);
  // NOTE: in IRC:37-2018, Eq. 3.1/3.2 are the FATIGUE models and Eq. 3.3/3.4
  // are the RUTTING models (an earlier report revision had them swapped).
  y = criterion(doc, y, 'Subgrade Rutting', 'IRC:37 Sec 3.6.1 - Eq 3.3/3.4',
    `N_R = ${rutCoeff} . (1/ev)^4.5337   (${relPct} reliability; ev = vertical compressive strain at top of subgrade)`,
    [['Quantity', 'Computed', 'Allowable', 'CDF (<=1.0)'],
     ['ev (top of subgrade)', ue(d.eps_v), ue(allowableStrain(d.eps_v, cdfR, RUT_EXP)), ''],
     ['N_R (allowable reps)', nr.toExponential(2), `>= ${nApp.toExponential(2)}`, cdfR.toFixed(3)]],
    cdfR <= 1.0);

  if (Math.abs(num(d.eps_t)) > 1e-12) {
    const cdfF = num(d.CDF_fatigue), nf = num(d.Nf);
    y = criterion(doc, y, 'Bituminous Fatigue Cracking', 'IRC:37 Sec 3.6.2 - Eq 3.1/3.2',
      `N_f = ${fatCoeff} . C . 10^-4 . (1/et)^3.89 . (1/MRm)^0.854   (${relPct} reliability; et at bottom of the bottom bituminous layer)`,
      [['Quantity', 'Computed', 'Allowable', 'CDF (<=1.0)'],
       ['et (bottom of bound layer)', ue(d.eps_t), ue(allowableStrain(d.eps_t, cdfF, FAT_EXP)), ''],
       ['N_f (allowable reps)', nf.toExponential(2), `>= ${nApp.toExponential(2)}`, cdfF.toFixed(3)]],
      cdfF <= 1.0);
  }
  if (d.CDF_ctb != null) {
    const cdfC = num(d.CDF_ctb);
    const cdfCs = d.CDF_ctb_strain != null ? num(d.CDF_ctb_strain) : null;
    const hasSpectrum = !!(d.ctb_details && d.ctb_details.details && d.ctb_details.details.length);
    const rf = relUsed === 'R90' ? '1' : '2';
    const rows = [['Quantity', 'Computed', 'Limit', 'CDF (<=1.0)']];
    if (d.eps_t_ctb != null) rows.push(['et (bottom of CTB, 0.80 MPa)', ue(d.eps_t_ctb), '--', '']);
    if (d.sigma_t_ctb != null) rows.push(['sigma_t (bottom of CTB, 0.80 MPa)', `${Math.abs(num(d.sigma_t_ctb)).toFixed(3)} MPa`, '--', '']);
    if (cdfCs != null) rows.push(['Strain criterion (Eq 3.5)', '', '<= 1.0', cdfCs.toFixed(3)]);
    if (hasSpectrum) rows.push(['Stress-ratio CFD over spectrum (Eq 3.6)', '', '<= 1.0', num(d.ctb_details.CDF_ctb).toFixed(3)]);
    rows.push(['Governing CTB fatigue damage', '', '<= 1.0', cdfC.toFixed(3)]);
    y = criterion(doc, y, 'Cement-Treated Base (CTB) Fatigue', 'IRC:37 Sec 3.5 - Eq 3.5' + (hasSpectrum ? ' & 3.6' : ''),
      `N = RF.[(113000/E^0.804 + 191)/et]^12 with RF = ${rf} (${relPct} reliability)` +
      (hasSpectrum
        ? '; plus N = 10^((0.972 - SR)/0.0825), SR = sigma_t/MRup, over the axle spectrum'
        : '   (stress-ratio spectrum check not run - no axle spectrum supplied)'),
      rows,
      cdfC <= 1.0);
  }
  const ok = !!d.overall_adequate;
  const [bg, fg] = ok ? [GREEN_BG, GREEN] : [RED_BG, RED];
  doc.setFillColor(...bg); doc.setDrawColor(...fg); doc.setLineWidth(0.4); doc.rect(M, y, CONTENT_W, 9, 'FD');
  doc.setFont('helvetica', 'bold'); doc.setFontSize(9); doc.setTextColor(...fg);
  doc.text(ok ? `OVERALL: IRC:37 ADEQUATE - all damage factors <= 1.0 (governed by ${d.governing_mode || '--'}).`
              : 'OVERALL: NOT ADEQUATE - revise layer thicknesses or materials.', M + 3, y + 5.6);
}

function clausesAndAlternatives(doc, sol, designs, granularAutoE) {
  let y = 24;
  doc.setFont('helvetica', 'bold'); doc.setFontSize(13); doc.setTextColor(...INK);
  doc.text('4.  IRC:37 Clause Compliance', M, y); y += 8;
  const hasCtb = (sol.details || {}).CDF_ctb != null;
  const hasSpectrum = !!((sol.details || {}).ctb_details && sol.details.ctb_details.details && sol.details.ctb_details.details.length);
  // Each item: [status, text, clause]. Status 'OK' only when the analysis
  // actually honoured the clause for THIS run — never claim Eq. 7.1 when the
  // user pinned the granular moduli manually.
  const items = [
    ['OK', 'Standard axle: dual wheels, 2 x 20 kN at 0.56 MPa, 310 mm c/c', 'Sec 3.6.1'],
    ['OK', 'ev evaluated at the top of the subgrade (rutting)', 'Sec 3.6.1'],
    ['OK', 'et evaluated at the bottom of the bottom bituminous layer (fatigue)', 'Sec 3.6.2'],
    ['OK', 'Subgrade MRS from Eq. 6.1/6.2, capped at 100 MPa', 'Sec 6.3 / Cl 6.4.2'],
    granularAutoE
      ? ['OK', 'Granular modulus from Eq. 7.1; unbound base+sub-base combined', 'Sec 7.2.3']
      : ['N/A', 'Granular moduli USER-SPECIFIED (Auto Eq. 7.1 off) - Eq. 7.1 / Sec 7.2.3 not applied; justify pinned values from material testing', 'Sec 7.2.3'],
    ['OK', 'Reliability auto-set: 90% for >= 20 MSA, else 80%', 'Sec 3.7'],
    ['OK', 'All cumulative damage factors checked against the 1.0 limit', 'Sec 3.6'],
  ];
  if (hasCtb) {
    items.push(['OK', 'CTB strain fatigue (Eq. 3.5) at 0.80 MPa; crack-relief layer above CTB', 'Sec 3.5 / 8.3']);
    items.push(hasSpectrum
      ? ['OK', 'CTB stress-ratio cumulative damage over the supplied axle spectrum (Eq. 3.6)', 'Sec 3.5']
      : ['N/A', 'CTB stress-ratio spectrum check (Eq. 3.6) NOT run - supply an axle-load spectrum for the full IRC dual check', 'Sec 3.5']);
  }
  autoTable(doc, {
    startY: y, margin: { left: M, right: M },
    head: [['', 'Requirement status for this analysis', 'Clause']],
    body: items, theme: 'grid',
    headStyles: { fillColor: INK, textColor: 255, fontSize: 8.4 },
    styles: { fontSize: 8.2, cellPadding: 1.6, lineColor: LINE },
    columnStyles: { 0: { cellWidth: 10, halign: 'center', fontStyle: 'bold' }, 2: { cellWidth: 32, textColor: BRAND_DK, fontStyle: 'bold', fontSize: 7.5 } },
    didParseCell: (h) => {
      if (h.section === 'body' && h.column.index === 0) {
        h.cell.styles.textColor = h.cell.raw === 'OK' ? GREEN : [180, 83, 9];
      }
    },
  });
  y = doc.lastAutoTable.finalY + 8;

  doc.setFont('helvetica', 'bold'); doc.setFontSize(13); doc.setTextColor(...INK);
  doc.text('5.  Alternative Adequate Designs', M, y); y += 7;
  const first = (designs[0] || {}).optimal_layers || [];
  const ltypes = first.map((l) => l.type);
  const head = ['Archetype', ...ltypes, 'Total', 'CDF_f', 'CDF_r', 'Cost L/km', 'CO2 T/km'];
  const body = designs.slice(0, 12).map((s) => {
    const dd = s.details || {};
    return [dd.strategy || s.strategy || '--',
      ...(s.optimal_layers || []).map((l) => num(l.thickness).toFixed(0)),
      num(s.total_thickness).toFixed(0), num(dd.CDF_fatigue).toFixed(2), num(dd.CDF_rutting).toFixed(2),
      s.cost ? (num(s.cost) / 1e5).toFixed(1) : '--', s.co2 ? (num(s.co2) / 1000).toFixed(1) : '--'];
  });
  autoTable(doc, {
    startY: y, margin: { left: M, right: M }, head: [head], body, theme: 'grid',
    headStyles: { fillColor: INK, textColor: 255, fontSize: 7.4 },
    styles: { fontSize: 7.4, cellPadding: 1.4, lineColor: LINE, halign: 'center' },
    columnStyles: { 0: { halign: 'left', cellWidth: 30 } },
  });
  y = doc.lastAutoTable.finalY + 6;
  doc.setFont('helvetica', 'normal'); doc.setFontSize(7.4); doc.setTextColor(...MUTED);
  doc.text(doc.splitTextToSize('Disclaimer. IndoPave-37 is a design-aid tool. Results are produced by a mechanistic-empirical analysis per IRC:37-2018/2019 and must be checked and sealed by a qualified pavement engineer before construction.', CONTENT_W), M, y);
}

export function generatePdfReport({ projectName, trafficParams, subgradeCbr, selectedSolution, adequateDesigns, airVoids, bitumenVolume, granularAutoE = false }) {
  const doc = new jsPDF({ unit: 'mm', format: 'a4' });
  const sol = selectedSolution || {};
  const traffic = trafficParams || {};
  const mix = { airVoids, bitumenVolume };
  cover(doc, projectName, traffic, subgradeCbr, sol);
  doc.addPage(); designBasis(doc, traffic, subgradeCbr, sol, mix);
  doc.addPage(); composition(doc, sol, granularAutoE);
  doc.addPage(); compliance(doc, sol);
  doc.addPage(); clausesAndAlternatives(doc, sol, adequateDesigns || [], granularAutoE);
  headerFooter(doc, doc.getNumberOfPages());
  doc.save('IndoPave37_Report.pdf');
}
