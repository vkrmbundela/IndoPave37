"""
IndoPave-37 — PDF Design Report Generator
=========================================
Produces a branded, multi-page **IRC:37-2018 / 2019 flexible-pavement design
report** with:
  * an IndoPave-37 cover page with a live COMPLIANT / NON-COMPLIANT stamp,
  * the full design basis (traffic, subgrade, load, reliability, mix),
  * the pavement composition + a scaled cross-section,
  * a mechanistic-empirical compliance check that prints the actual IRC
    performance equations, the computed vs. allowable strains, the CDFs and
    the governing mode — with the relevant IRC clause cited for each, and
  * an IRC clause-compliance checklist + alternative adequate designs.

Rendered with ReportLab. The public entry point `generate_report(...)` keeps a
stable signature so the API/frontend need no changes.
"""

from io import BytesIO
from datetime import datetime
from typing import List, Dict, Any, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
    KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line

# --------------------------------------------------------------------------- #
# Brand palette
# --------------------------------------------------------------------------- #
BRAND      = HexColor('#E8631A')   # IndoPave orange
BRAND_DK   = HexColor('#B84E12')
INK        = HexColor('#0F172A')   # slate-900
MUTED      = HexColor('#64748B')   # slate-500
FAINT      = HexColor('#94A3B8')   # slate-400
LINE       = HexColor('#E2E8F0')   # slate-200
SURFACE    = HexColor('#F8FAFC')   # slate-50
PANEL      = HexColor('#F1F5F9')   # slate-100
GREEN      = HexColor('#15803D')
GREEN_BG   = HexColor('#ECFDF5')
RED        = HexColor('#B91C1C')
RED_BG     = HexColor('#FEF2F2')
AMBER      = HexColor('#B45309')

LAYER_COLORS = {
    'BC':  HexColor('#1E293B'), 'DBM': HexColor('#334155'),
    'SMA': HexColor('#283548'), 'SDBC': HexColor('#3F4E63'),
    'BM':  HexColor('#475569'), 'WMM': HexColor('#9A7B4F'),
    'WBM': HexColor('#A98E63'), 'GSB': HexColor('#C9B084'),
    'CRL': HexColor('#B79A6A'), 'CTB': HexColor('#6B7B8C'),
    'CTSB': HexColor('#7E8C9A'), 'RAP': HexColor('#5A6B5A'),
}
SUBGRADE_COLOR = HexColor('#6B4423')

# Fatigue / rutting exponents (IRC:37-2018 Eq. 3.3-3.4 / 3.1-3.2)
_FATIGUE_EXP = 3.89
_RUTTING_EXP = 4.5337


# --------------------------------------------------------------------------- #
# Fonts — register a Unicode TrueType family so engineering glyphs (ε, σ, ≤,
# µ, ×, ✓) render correctly. ReportLab's built-in Helvetica is WinAnsi-only and
# drops those. Prefer Arial (Windows) → DejaVuSans (Linux) → Vera (always
# bundled with ReportLab). Falls back to Helvetica if every option fails.
# --------------------------------------------------------------------------- #
FONT, FONT_B, FONT_I = 'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique'


def _register_unicode_font():
    global FONT, FONT_B, FONT_I
    import os
    import reportlab
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfbase.pdfmetrics import registerFontFamily
    rl_fonts = os.path.join(os.path.dirname(reportlab.__file__), 'fonts')
    families = [
        (r'C:\Windows\Fonts\arial.ttf', r'C:\Windows\Fonts\arialbd.ttf',
         r'C:\Windows\Fonts\ariali.ttf', r'C:\Windows\Fonts\arialbi.ttf'),
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf',
         '/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf'),
        (os.path.join(rl_fonts, 'Vera.ttf'), os.path.join(rl_fonts, 'VeraBd.ttf'),
         os.path.join(rl_fonts, 'VeraIt.ttf'), os.path.join(rl_fonts, 'VeraBI.ttf')),
    ]
    for reg, bold, ital, bi in families:
        try:
            if not (os.path.exists(reg) and os.path.exists(bold) and os.path.exists(ital)):
                continue
            pdfmetrics.registerFont(TTFont('IPSans', reg))
            pdfmetrics.registerFont(TTFont('IPSans-Bold', bold))
            pdfmetrics.registerFont(TTFont('IPSans-Oblique', ital))
            bi_name = 'IPSans-Bold'
            if os.path.exists(bi):
                pdfmetrics.registerFont(TTFont('IPSans-BoldOblique', bi))
                bi_name = 'IPSans-BoldOblique'
            registerFontFamily('IPSans', normal='IPSans', bold='IPSans-Bold',
                               italic='IPSans-Oblique', boldItalic=bi_name)
            FONT, FONT_B, FONT_I = 'IPSans', 'IPSans-Bold', 'IPSans-Oblique'
            return
        except Exception:
            continue


_register_unicode_font()


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _subgrade_mr(cbr: float) -> float:
    """IRC:37-2018 Eq. 6.1/6.2 with the Cl. 6.4.2 design ceiling of 100 MPa."""
    cbr = _f(cbr)
    mr = 10.0 * cbr if cbr <= 5 else 17.6 * (cbr ** 0.64)
    return min(mr, 100.0)


def _allowable_strain(eps, cdf, exponent):
    """
    Back-compute the limiting (allowable) strain from the computed strain and
    its CDF. Since N ∝ (1/ε)^exponent and CDF = N_applied / N_allowable,
    ε_allow = ε_computed · CDF^(-1/exponent). Returns None when not derivable.
    """
    eps = abs(_f(eps)); cdf = _f(cdf, 0.0)
    if eps <= 0 or cdf <= 0:
        return None
    return eps * (cdf ** (-1.0 / exponent))


def _styles():
    base = getSampleStyleSheet()
    def mk(name, **kw):
        return ParagraphStyle(name, parent=base['Normal'], **kw)
    return {
        'cover_title': mk('cover_title', fontName=FONT_B, fontSize=23,
                          textColor=INK, leading=27, spaceAfter=2),
        'cover_sub':   mk('cover_sub', fontName=FONT, fontSize=11,
                          textColor=MUTED, leading=15),
        'h1':  mk('h1', fontName=FONT_B, fontSize=13, textColor=INK,
                  spaceBefore=4, spaceAfter=8, leading=16),
        'h2':  mk('h2', fontName=FONT_B, fontSize=10.5, textColor=BRAND_DK,
                  spaceBefore=10, spaceAfter=5, leading=13),
        'body': mk('body', fontName=FONT, fontSize=9, textColor=INK,
                   leading=13, spaceAfter=3),
        'small': mk('small', fontName=FONT, fontSize=7.6, textColor=MUTED,
                    leading=10),
        'eqn': mk('eqn', fontName=FONT_I, fontSize=9.5, textColor=INK,
                  leading=14, spaceBefore=2, spaceAfter=2),
        'clause': mk('clause', fontName=FONT_B, fontSize=7.5,
                     textColor=BRAND_DK, leading=10),
        'cell': mk('cell', fontName=FONT, fontSize=8.2, textColor=INK, leading=11),
        'cellb': mk('cellb', fontName=FONT_B, fontSize=8.2, textColor=INK, leading=11),
        'cellc': mk('cellc', fontName=FONT, fontSize=8.2, textColor=INK,
                    leading=11, alignment=TA_CENTER),
    }


# --------------------------------------------------------------------------- #
# Branding marks
# --------------------------------------------------------------------------- #
def _logo_mark(c, x, y, size):
    """Draw the rounded-square 'IP' monogram with its bottom-left origin at (x, y)."""
    c.setFillColor(BRAND)
    c.roundRect(x, y, size, size, size * 0.24, stroke=0, fill=1)
    # subtle darker corner accent
    c.setFillColor(BRAND_DK)
    c.roundRect(x, y, size, size * 0.36, size * 0.24, stroke=0, fill=1)
    c.setFillColor(BRAND)
    c.rect(x, y + size * 0.18, size, size * 0.18, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont(FONT_B, size * 0.52)
    c.drawCentredString(x + size / 2, y + size * 0.30, "IP")


def _cover_canvas(c, doc):
    """Page-1 decoration: top brand bar + footer."""
    w, h = A4
    # top brand band
    c.setFillColor(INK)
    c.rect(0, h - 16 * mm, w, 16 * mm, stroke=0, fill=1)
    c.setFillColor(BRAND)
    c.rect(0, h - 16 * mm, w, 1.6 * mm, stroke=0, fill=1)
    _logo_mark(c, 18 * mm, h - 13.2 * mm, 9 * mm)
    c.setFillColor(white)
    c.setFont(FONT_B, 12)
    c.drawString(30 * mm, h - 9.0 * mm, "IndoPave-37")
    c.setFillColor(HexColor('#CBD5E1'))
    c.setFont(FONT, 8)
    c.drawString(30 * mm, h - 12.6 * mm, "Mechanistic-Empirical Pavement Design Suite")
    c.setFillColor(HexColor('#94A3B8'))
    c.setFont(FONT, 8)
    c.drawRightString(w - 18 * mm, h - 10.6 * mm, "IRC:37-2018 / 2019")
    _footer(c, doc)


def _running_header_footer(c, doc):
    """Pages 2+: compact running header + footer."""
    w, h = A4
    _logo_mark(c, 20 * mm, h - 17 * mm, 6.5 * mm)
    c.setFillColor(INK)
    c.setFont(FONT_B, 9.5)
    c.drawString(28.5 * mm, h - 15.3 * mm, "IndoPave-37")
    c.setFillColor(MUTED)
    c.setFont(FONT, 7.5)
    c.drawRightString(w - 20 * mm, h - 15.3 * mm, "Flexible Pavement Design Report  ·  IRC:37-2018/2019")
    c.setStrokeColor(LINE); c.setLineWidth(0.6)
    c.line(20 * mm, h - 18.5 * mm, w - 20 * mm, h - 18.5 * mm)
    _footer(c, doc)


def _footer(c, doc):
    w, h = A4
    c.setStrokeColor(LINE); c.setLineWidth(0.6)
    c.line(20 * mm, 14 * mm, w - 20 * mm, 14 * mm)
    c.setFillColor(FAINT); c.setFont(FONT, 7)
    c.drawString(20 * mm, 10.2 * mm,
                 f"Generated {datetime.now().strftime('%d %b %Y, %H:%M')}  ·  IndoPave-37 v1.0")
    c.drawCentredString(w / 2, 10.2 * mm, "Native multi-layer elastic (Burmister) solver — IITPAVE-equivalent")
    c.drawRightString(w - 20 * mm, 10.2 * mm, f"Page {doc.page}")


# --------------------------------------------------------------------------- #
# Reusable table styles
# --------------------------------------------------------------------------- #
def _kv_style():
    return TableStyle([
        ('FONTNAME', (0, 0), (0, -1), FONT),
        ('FONTNAME', (1, 0), (1, -1), FONT_B),
        ('FONTSIZE', (0, 0), (-1, -1), 8.6),
        ('TEXTCOLOR', (0, 0), (0, -1), MUTED),
        ('TEXTCOLOR', (1, 0), (1, -1), INK),
        ('TEXTCOLOR', (2, 0), (2, -1), FAINT),
        ('FONTNAME', (2, 0), (2, -1), FONT),
        ('FONTSIZE', (2, 0), (2, -1), 7),
        ('LINEBELOW', (0, 0), (-1, -2), 0.4, LINE),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, -1), white),
    ])


def _section(styles, title, clause=None):
    if clause:
        return Table(
            [[Paragraph(title, styles['h2']), Paragraph(clause, styles['clause'])]],
            colWidths=[120 * mm, 50 * mm],
            style=TableStyle([
                ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('LINEBELOW', (0, 0), (-1, -1), 1.0, BRAND),
            ]),
        )
    return Paragraph(title, styles['h2'])


# --------------------------------------------------------------------------- #
# Page 1 — Cover
# --------------------------------------------------------------------------- #
def _cover(styles, project_name, traffic_params, subgrade_cbr, sol):
    story = [Spacer(1, 20 * mm)]
    story.append(Paragraph("Flexible Pavement Design Report", styles['cover_title']))
    story.append(Paragraph(
        "Mechanistic-Empirical design &amp; verification in accordance with "
        "<b>IRC:37-2018 / 2019</b> (Guidelines for the Design of Flexible Pavements).",
        styles['cover_sub']))
    story.append(Spacer(1, 6 * mm))

    story.append(Table(
        [[Paragraph("PROJECT", styles['small']),
          Paragraph(project_name or "Untitled Design Session", styles['cellb'])]],
        colWidths=[26 * mm, 144 * mm],
        style=TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), PANEL),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('LINEBEFORE', (0, 0), (0, 0), 3, BRAND),
        ]),
    ))
    story.append(Spacer(1, 8 * mm))

    details = (sol or {}).get('details', {}) or {}
    adequate = bool(details.get('overall_adequate', False))
    msa = _f(details.get('msa', traffic_params.get('msa', 0)))
    total_t = _f((sol or {}).get('total_thickness', 0))
    mr = _subgrade_mr(subgrade_cbr)
    gov = (details.get('governing_mode') or '—')
    gov_cdf = max(_f(details.get('CDF_fatigue')), _f(details.get('CDF_rutting')),
                  _f(details.get('CDF_ctb')))
    reserve = (1.0 / gov_cdf - 1.0) * 100.0 if gov_cdf > 0 else None

    # Compliance stamp (colour must be embedded in the font tag — a Table
    # TEXTCOLOR does not recolour a Paragraph flowable).
    stamp_txt = "IRC:37 COMPLIANT" if adequate else "IRC:37 NON-COMPLIANT"
    stamp_hex = '#15803D' if adequate else '#B91C1C'
    stamp_clr = GREEN if adequate else RED
    stamp_bg = GREEN_BG if adequate else RED_BG
    sub = (f"All cumulative damage factors ≤ 1.0 &nbsp;·&nbsp; governed by {gov}"
           if adequate else
           "One or more damage factors exceed 1.0 — revise the section")
    story.append(Table(
        [[Paragraph(f"<font size=15 color='{stamp_hex}'><b>{stamp_txt}</b></font><br/>"
                    f"<font size=8 color='#475569'>{sub}</font>", styles['body'])]],
        colWidths=[170 * mm],
        style=TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), stamp_bg),
            ('BOX', (0, 0), (-1, -1), 1.4, stamp_clr),
            ('TOPPADDING', (0, 0), (-1, -1), 10), ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (-1, -1), 12),
        ]),
    ))
    story.append(Spacer(1, 9 * mm))

    # Key-result cards (2 x 2)
    def card(label, value, unit):
        return Paragraph(
            f"<font size=7 color='#64748B'>{label}</font><br/>"
            f"<font size=16 color='#0F172A'><b>{value}</b></font>"
            f"<font size=8 color='#64748B'> {unit}</font>", styles['body'])

    reserve_txt = (f"{reserve:+.0f}" if reserve is not None and reserve < 1e5 else "≫")
    cards = [
        [card("DESIGN TRAFFIC", f"{msa:.1f}", "MSA"),
         card("SUBGRADE MODULUS", f"{mr:.0f}", "MPa  (CBR " + f"{_f(subgrade_cbr):g}%)")],
        [card("TOTAL CRUST", f"{total_t:.0f}", "mm"),
         card("STRUCTURAL RESERVE", reserve_txt, "%  ·  gov: " + str(gov))],
    ]
    story.append(Table(
        cards, colWidths=[85 * mm, 85 * mm], rowHeights=[20 * mm, 20 * mm],
        style=TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), SURFACE),
            ('BOX', (0, 0), (-1, -1), 0.6, LINE),
            ('INNERGRID', (0, 0), (-1, -1), 0.6, LINE),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 12), ('TOPPADDING', (0, 0), (-1, -1), 6),
        ]),
    ))
    story.append(Spacer(1, 10 * mm))
    story.append(Paragraph(
        "This report is generated by IndoPave-37 using a native, in-process "
        "multi-layer elastic (Burmister) solver — the mathematical equivalent of "
        "the official IITPAVE engine, validated against the IRC:37-2018 Annex-II "
        "worked examples (ε<sub>t</sub> 146 vs 146 µε; ε<sub>v</sub> 245 vs 243 µε; "
        "CTB σ<sub>t</sub> 0.699 vs 0.700 MPa) and a reference IITPAVE run. "
        "Final designs must be reviewed and approved by a qualified pavement engineer.",
        styles['small']))
    return story


# --------------------------------------------------------------------------- #
# Page 2 — Design basis
# --------------------------------------------------------------------------- #
def _design_basis(styles, traffic_params, subgrade_cbr, sol):
    details = (sol or {}).get('details', {}) or {}
    story = [Paragraph("1.  Design Basis &amp; Inputs", styles['h1'])]

    cvpd = traffic_params.get('cvpd', 0)
    gr = _f(traffic_params.get('growth_rate', 0))
    gr_pct = gr * 100 if abs(gr) <= 1 else gr      # accept fraction or percent
    vdf = traffic_params.get('vdf', 2.5)
    dl = traffic_params.get('design_life', 20)
    msa = _f(details.get('msa', traffic_params.get('msa', 0)))
    mr = _subgrade_mr(subgrade_cbr)
    cbr = _f(subgrade_cbr)
    mr_eqn = ("10 × CBR" if cbr <= 5 else "17.6 × CBR<super>0.64</super>")

    story.append(_section(styles, "Traffic", "IRC:37-2018 §4 — cumulative MSA"))
    story.append(Table([
        ["Commercial vehicles / day (CVPD)", f"{cvpd}", ""],
        ["Annual growth rate", f"{gr_pct:.1f} %", ""],
        ["Vehicle damage factor (VDF)", f"{vdf}", "std axles / CV"],
        ["Design life", f"{dl} years", ""],
        ["Cumulative design traffic", f"{msa:.2f} MSA", "= 365·A·D·F·((1+r)ⁿ−1)/r"],
    ], colWidths=[70 * mm, 50 * mm, 50 * mm], style=_kv_style()))
    story.append(Spacer(1, 4 * mm))

    story.append(_section(styles, "Subgrade", "IRC:37-2018 §6 — Eqs. 6.1/6.2, Cl. 6.4.2"))
    story.append(Table([
        ["Design CBR (4-day soaked)", f"{cbr:g} %", "IS:2720 Pt-16"],
        ["Effective resilient modulus Mᵣₛ", f"{mr:.1f} MPa", mr_eqn.replace('<super>','^').replace('</super>','')],
        ["Design ceiling on Mᵣₛ", "100 MPa", "Cl. 6.4.2"],
        ["Poisson's ratio (subgrade)", "0.35", "§6.3"],
    ], colWidths=[70 * mm, 50 * mm, 50 * mm], style=_kv_style()))
    story.append(Spacer(1, 4 * mm))

    story.append(_section(styles, "Standard Axle &amp; Loading", "IRC:37-2018 §3.6.1"))
    story.append(Table([
        ["Standard axle", "80 kN single axle, dual wheels", "§3.6.1"],
        ["Wheel load (one of a dual set)", "20 000 N", ""],
        ["Tyre contact pressure", "0.56 MPa", "0.80 MPa for CTB σₜ (§3.6.1)"],
        ["Dual-wheel spacing (c/c)", "310 mm", ""],
        ["Layer interface", "fully bonded", "§3.6.1"],
    ], colWidths=[70 * mm, 50 * mm, 50 * mm], style=_kv_style()))
    story.append(Spacer(1, 4 * mm))

    rel = "90% (mandatory ≥ 20 MSA)" if msa >= 20 else "80% (low-volume, < 20 MSA)"
    story.append(_section(styles, "Reliability &amp; Mix", "IRC:37-2018 §3.7, §3.6.2"))
    av = _f(details.get('air_voids', 3.0)) or 3.0
    vbe = _f(details.get('bitumen_volume', 11.5)) or 11.5
    story.append(Table([
        ["Design reliability level", rel, "§3.7"],
        ["Air void content, Vₐ (bottom mix)", f"{av:g} %", "fatigue C-factor"],
        ["Effective bitumen volume, Vₕₑ", f"{vbe:g} %", "fatigue C-factor"],
    ], colWidths=[70 * mm, 50 * mm, 50 * mm], style=_kv_style()))
    return story


# --------------------------------------------------------------------------- #
# Page 3 — Composition + cross-section
# --------------------------------------------------------------------------- #
def _composition(styles, sol):
    details = (sol or {}).get('details', {}) or {}
    story = [Paragraph("2.  Pavement Composition", styles['h1'])]

    # Prefer the rich layer report (carries per-layer modulus); fall back to optimal_layers.
    rich = details.get('layers')
    if rich:
        layer_rows = [{'name': l.get('name', '?'),
                       'thickness': _f(l.get('thickness')),
                       'modulus': _f(l.get('modulus'))} for l in rich]
    else:
        layer_rows = [{'name': l.get('type', '?'),
                       'thickness': _f(l.get('thickness')),
                       'modulus': None}
                      for l in (sol or {}).get('optimal_layers', [])]

    header = ['#', 'Layer / Material', 'Thickness (mm)', 'Elastic Modulus E (MPa)', 'Poisson ν']
    rows = [header]
    nu_map = {'CTB': '0.25', 'CTSB': '0.25'}
    n_struct = 0
    for i, l in enumerate(layer_rows):
        is_sub = str(l['name']).lower().startswith('sub')
        thk = "∞ (half-space)" if is_sub or l['thickness'] == 0 else f"{l['thickness']:.0f}"
        modv = f"{l['modulus']:.0f}" if l['modulus'] else "—"
        nu = nu_map.get(str(l['name']).upper(), '0.35')
        rows.append([("—" if is_sub else str(i + 1)), l['name'], thk, modv, nu])
        if not is_sub:
            n_struct += _f(l['thickness'])
    rows.append(['', 'Total bound + unbound crust', f"{n_struct:.0f}", '', ''])

    t = Table(rows, colWidths=[10 * mm, 62 * mm, 34 * mm, 44 * mm, 20 * mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), FONT_B),
        ('FONTSIZE', (0, 0), (-1, -1), 8.4),
        ('BACKGROUND', (0, 0), (-1, 0), INK),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [white, SURFACE]),
        ('BACKGROUND', (0, -1), (-1, -1), PANEL),
        ('FONTNAME', (0, -1), (-1, -1), FONT_B),
        ('LINEBELOW', (0, 0), (-1, -1), 0.4, LINE),
        ('GRID', (0, 0), (-1, -1), 0.3, LINE),
        ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Paragraph(
        "Granular-layer moduli are derived from IRC:37-2018 Eq. 7.1 "
        "(M<sub>R,gran</sub> = 0.2·h<super>0.45</super>·M<sub>R,support</sub>); unbound "
        "base + sub-base are combined into one equivalent granular layer per §7.2.3. "
        "Poisson's ratios per §3.6 (0.35 bituminous/granular/subgrade, 0.25 cement-treated).",
        styles['small']))
    story.append(Spacer(1, 6 * mm))

    story.append(_section(styles, "Cross-Section", None))
    story.append(_cross_section(layer_rows))
    return story


def _cross_section(layer_rows):
    W, H = 470, 250
    sec_w = 250
    x0 = 36
    d = Drawing(W, H)
    struct = [l for l in layer_rows if not str(l['name']).lower().startswith('sub')]
    total = sum(l['thickness'] for l in struct) or 1
    avail = H - 64
    scale = avail / total
    min_px = 22

    y = H - 24
    # depth ruler baseline
    cum = 0.0
    for l in struct:
        t = l['thickness']
        h = max(t * scale, min_px)
        color = LAYER_COLORS.get(str(l['name']).upper(), HexColor('#8A94A6'))
        d.add(Rect(x0, y - h, sec_w, h, fillColor=color, strokeColor=white, strokeWidth=1))
        d.add(String(x0 + sec_w / 2, y - h / 2 - 3.5, f"{l['name']}  —  {t:.0f} mm",
                     fontName=FONT_B, fontSize=8.5, textAnchor='middle', fillColor=white))
        if l['modulus']:
            d.add(String(x0 + sec_w + 8, y - h / 2 - 3, f"E = {l['modulus']:.0f} MPa",
                         fontName=FONT, fontSize=7.5, fillColor=MUTED))
        cum += t
        d.add(String(x0 - 6, y - h - 3 if False else y - 3, f"{cum - t:.0f}",
                     fontName=FONT, fontSize=6.5, textAnchor='end', fillColor=FAINT))
        y -= h
    d.add(String(x0 - 6, y - 3, f"{cum:.0f}", fontName=FONT, fontSize=6.5,
                 textAnchor='end', fillColor=FAINT))
    # subgrade
    sh = 26
    d.add(Rect(x0, y - sh, sec_w, sh, fillColor=SUBGRADE_COLOR, strokeColor=white, strokeWidth=1))
    d.add(String(x0 + sec_w / 2, y - sh / 2 - 3.5, "SUBGRADE  (semi-infinite)",
                 fontName=FONT_B, fontSize=7.5, textAnchor='middle', fillColor=white))
    d.add(String(x0 - 16, (H - 24 + y) / 2, "depth (mm)", fontName=FONT,
                 fontSize=6.5, textAnchor='middle', fillColor=FAINT))
    return d


# --------------------------------------------------------------------------- #
# Page 4 — Compliance check (technical core)
# --------------------------------------------------------------------------- #
def _criterion_block(styles, title, clause, equation, rows, ok):
    """A framed criterion: title bar, IRC equation, and a computed/allowable table."""
    clr = GREEN if ok else RED
    clr_hex = '#15803D' if ok else '#B91C1C'
    head = Table(
        [[Paragraph(f"<b>{title}</b>", styles['cellb']),
          Paragraph(clause, styles['clause']),
          Paragraph(f"<font color='{clr_hex}'><b>{'PASS' if ok else 'FAIL'}</b></font>", styles['cellb'])]],
        colWidths=[95 * mm, 50 * mm, 25 * mm],
        style=TableStyle([
            ('ALIGN', (1, 0), (1, 0), 'CENTER'), ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BACKGROUND', (0, 0), (-1, -1), PANEL),
            ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LINEBELOW', (0, 0), (-1, -1), 1.0, clr),
        ]),
    )
    eq = Paragraph(equation, styles['eqn'])
    body = Table(rows, colWidths=[44 * mm, 42 * mm, 42 * mm, 42 * mm])
    body.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), FONT_B),
        ('FONTSIZE', (0, 0), (-1, -1), 8.2),
        ('TEXTCOLOR', (0, 0), (-1, 0), MUTED),
        ('BACKGROUND', (0, 0), (-1, 0), SURFACE),
        ('GRID', (0, 0), (-1, -1), 0.3, LINE),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    wrap = Table([[eq], [body]], colWidths=[170 * mm],
                 style=TableStyle([
                     ('BOX', (0, 0), (-1, -1), 0.8, LINE),
                     ('BACKGROUND', (0, 0), (0, 0), white),
                     ('LEFTPADDING', (0, 0), (-1, -1), 8), ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                     ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                 ]))
    return KeepTogether([head, wrap, Spacer(1, 5 * mm)])


def _compliance(styles, sol):
    details = (sol or {}).get('details', {}) or {}
    story = [Paragraph("3.  Mechanistic-Empirical Compliance Check", styles['h1'])]
    if not details:
        story.append(Paragraph("No analysis data available for the selected design.", styles['body']))
        return story

    msa = _f(details.get('msa'))
    n_app = msa * 1e6
    story.append(Paragraph(
        f"Design repetitions N<sub>applied</sub> = {msa:.2f} × 10<super>6</super> standard axles. "
        "A criterion passes when its Cumulative Damage Factor "
        "CDF = N<sub>applied</sub> / N<sub>allowable</sub> ≤ 1.0.",
        styles['body']))
    story.append(Spacer(1, 4 * mm))

    def fmt_strain(v):
        return f"{abs(_f(v))*1e6:.1f} µε" if v is not None else "—"

    # --- Rutting (subgrade) ---
    ev = details.get('eps_v'); cdf_r = _f(details.get('CDF_rutting'))
    nr = _f(details.get('NR')); ev_allow = _allowable_strain(ev, cdf_r, _RUTTING_EXP)
    # Coefficients of the reliability level the ENGINE actually used
    # (post IRC §3.7 escalation) — previously the R90 values were always
    # printed, even for R80 designs.
    is_r80 = str(details.get('reliability') or 'R90').upper() == 'R80'
    rel_txt = "80% reliability" if is_r80 else "90% reliability"
    rut_coeff = "4.1656 × 10<super>−8</super>" if is_r80 else "1.41 × 10<super>−8</super>"
    fat_coeff = "1.6064" if is_r80 else "0.5161"
    story.append(_criterion_block(
        styles, "Subgrade Rutting", "IRC:37-2018 §3.6.1 · Eq. 3.1/3.2",
        f"N<sub>R</sub> = {rut_coeff} · (1/ε<sub>v</sub>)<super>4.5337</super>"
        f"&nbsp;&nbsp;<font color='#64748B'>({rel_txt}; ε<sub>v</sub> = vertical "
        "compressive strain at the top of the subgrade)</font>",
        [["Quantity", "Computed", "Allowable", "CDF (≤ 1.0)"],
         ["εᵥ (top of subgrade)", fmt_strain(ev),
          fmt_strain((ev_allow) if ev_allow else None), ""],
         ["Nᵣ (allowable reps)", f"{nr:.2e}", f"≥ {n_app:.2e}",
          f"{cdf_r:.3f}"]],
        ok=(cdf_r <= 1.0)))

    # --- Fatigue (bituminous) ---
    et = details.get('eps_t'); cdf_f = _f(details.get('CDF_fatigue'))
    nf = _f(details.get('Nf')); et_allow = _allowable_strain(et, cdf_f, _FATIGUE_EXP)
    fatigue_applicable = abs(_f(et)) > 1e-12
    if fatigue_applicable:
        story.append(_criterion_block(
            styles, "Bituminous Fatigue Cracking", "IRC:37-2018 §3.6.2 · Eq. 3.3/3.4",
            f"N<sub>f</sub> = {fat_coeff} · C · 10<super>−4</super> · (1/ε<sub>t</sub>)<super>3.89</super> · "
            "(1/M<sub>Rm</sub>)<super>0.854</super>&nbsp;&nbsp;"
            f"<font color='#64748B'>({rel_txt}; C = 10<super>M</super>, M = 4.84·(V<sub>be</sub>/(V<sub>a</sub>+V<sub>be</sub>) − 0.69); "
            "ε<sub>t</sub> at bottom of the bottom bituminous layer)</font>",
            [["Quantity", "Computed", "Allowable", "CDF (≤ 1.0)"],
             ["εₜ (bottom of bound layer)", fmt_strain(et),
              fmt_strain(et_allow if et_allow else None), ""],
             ["Nₒ (allowable reps)", f"{nf:.2e}", f"≥ {n_app:.2e}",
              f"{cdf_f:.3f}"]],
            ok=(cdf_f <= 1.0)))

    # --- CTB fatigue (only if present) ---
    cdf_c = details.get('CDF_ctb')
    sig = details.get('sigma_t_ctb')
    if cdf_c is not None and sig is not None:
        cdf_c = _f(cdf_c)
        rf = details.get('ctb_rf')
        rf_txt = f"{_f(rf):g}" if rf is not None else "—"
        cdf_strain = details.get('CDF_ctb_strain')
        spec = details.get('ctb_details') or {}
        spec_cdf = spec.get('CDF_ctb') if isinstance(spec, dict) else None
        rows = [["Quantity", "Computed", "Limit", "CDF (≤ 1.0)"]]
        if details.get('eps_t_ctb') is not None:
            rows.append(["εₜ (bottom of CTB, 0.80 MPa)", fmt_strain(details.get('eps_t_ctb')), "—", ""])
        rows.append(["σₜ (bottom of CTB, 0.80 MPa)", f"{abs(_f(sig)):.3f} MPa", "—", ""])
        if cdf_strain is not None:
            rows.append(["Strain criterion (Eq. 3.5)", "", "≤ 1.0", f"{_f(cdf_strain):.3f}"])
        if spec_cdf is not None:
            rows.append(["Stress-ratio CFD over spectrum (Eq. 3.6/3.7)", "", "≤ 1.0", f"{_f(spec_cdf):.3f}"])
        rows.append(["Governing CTB fatigue damage", "", "≤ 1.0", f"{cdf_c:.3f}"])
        story.append(_criterion_block(
            styles, "Cement-Treated Base (CTB) Fatigue", "IRC:37-2018 §3.6.3 · Eq. 3.5 / 3.6",
            f"N = RF · [(113000/E<super>0.804</super> + 191)/ε<sub>t</sub>]<super>12</super>, RF = {rf_txt}"
            + (";&nbsp;N = 10<super>(0.972 − SR)/0.0825</super>, SR = σ<sub>t</sub>/M<sub>Rup</sub>"
               if spec_cdf is not None else "")
            + "&nbsp;&nbsp;<font color='#64748B'>(stress/strain at the bottom of the CTB "
              "at 0.80 MPa contact pressure)</font>",
            rows,
            ok=(cdf_c <= 1.0)))

    # Overall verdict line
    adequate = bool(details.get('overall_adequate', False))
    clr = GREEN if adequate else RED
    clr_hex = '#15803D' if adequate else '#B91C1C'
    gov = details.get('governing_mode', '—')
    verdict = (f"OVERALL: IRC:37 ADEQUATE — all damage factors ≤ 1.0 (governed by {gov})."
               if adequate else
               "OVERALL: NOT ADEQUATE — revise layer thicknesses or materials.")
    story.append(Table([[Paragraph(f"<font color='{clr_hex}'><b>{verdict}</b></font>", styles['body'])]],
                       colWidths=[170 * mm],
                       style=TableStyle([
                           ('BACKGROUND', (0, 0), (-1, -1), GREEN_BG if adequate else RED_BG),
                           ('BOX', (0, 0), (-1, -1), 1, clr),
                           ('LEFTPADDING', (0, 0), (-1, -1), 10),
                           ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                       ])))
    return story


# --------------------------------------------------------------------------- #
# Page 5 — Clause checklist + alternatives
# --------------------------------------------------------------------------- #
def _clause_checklist(styles, sol):
    details = (sol or {}).get('details', {}) or {}
    has_ctb = details.get('CDF_ctb') is not None
    items = [
        ("Standard axle: dual wheels, 2 × 20 kN at 0.56 MPa, 310 mm c/c", "§3.6.1"),
        ("εᵥ evaluated at the top of the subgrade (rutting)", "§3.6.1"),
        ("εₜ evaluated at the bottom of the bottom bituminous layer (fatigue)", "§3.6.2"),
        ("Subgrade Mᵣₛ from Eq. 6.1/6.2, capped at 100 MPa", "§6.3 / Cl. 6.4.2"),
        ("Granular modulus from Eq. 7.1; unbound base+sub-base combined", "§7.2.3"),
        ("Reliability auto-set: 90% for ≥ 20 MSA, else 80%", "§3.7"),
        ("All cumulative damage factors checked against the 1.0 limit", "§3.6"),
    ]
    if has_ctb:
        items.append(("CTB tensile stress at 0.80 MPa; crack-relief layer required above CTB", "§3.6 / §8.3"))
    story = [Paragraph("4.  IRC:37 Clause Compliance", styles['h1'])]
    rows = [["", "Requirement honoured by the analysis", "Clause"]]
    for txt, cl in items:
        rows.append(["✓", Paragraph(txt, styles['cell']), Paragraph(cl, styles['clause'])])
    t = Table(rows, colWidths=[8 * mm, 132 * mm, 30 * mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), FONT_B),
        ('FONTSIZE', (0, 0), (-1, -1), 8.4),
        ('BACKGROUND', (0, 0), (-1, 0), INK), ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('TEXTCOLOR', (0, 1), (0, -1), GREEN), ('FONTNAME', (0, 1), (0, -1), FONT_B),
        ('ALIGN', (0, 0), (0, -1), 'CENTER'), ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, SURFACE]),
        ('GRID', (0, 0), (-1, -1), 0.3, LINE), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (1, 0), (1, -1), 6),
    ]))
    story.append(t)
    return story


def _alternatives(styles, adequate_designs):
    story = [Paragraph("5.  Alternative Adequate Designs", styles['h1'])]
    if not adequate_designs:
        story.append(Paragraph("No alternative designs were returned.", styles['body']))
        return story
    story.append(Paragraph(
        f"{len(adequate_designs)} IRC-adequate archetype(s). Cost and CO₂ columns are "
        "populated only for the objectives that were enabled.", styles['small']))
    story.append(Spacer(1, 3 * mm))

    first = adequate_designs[0].get('optimal_layers', [])
    ltypes = [l.get('type', '?') for l in first]
    header = ['Archetype'] + ltypes + ['Total', 'CDF_fat', 'CDF_rut', 'Cost ₹L/km', 'CO₂ T/km']
    rows = [header]
    for sol in adequate_designs[:12]:
        d = sol.get('details', {}) or {}
        strat = (d.get('strategy') or sol.get('strategy') or '—')
        row = [Paragraph(f"<font size=7><b>{strat}</b></font>", styles['cell'])]
        for l in sol.get('optimal_layers', []):
            row.append(f"{_f(l.get('thickness')):.0f}")
        row.append(f"{_f(sol.get('total_thickness')):.0f}")
        row.append(f"{_f(d.get('CDF_fatigue')):.2f}")
        row.append(f"{_f(d.get('CDF_rutting')):.2f}")
        cost = sol.get('cost'); co2 = sol.get('co2')
        row.append(f"{_f(cost)/1e5:.1f}" if cost else "—")
        row.append(f"{_f(co2)/1000.0:.1f}" if co2 else "—")
        rows.append(row)

    ncol = len(header)
    body_w = 170 * mm - 28 * mm
    col_w = [28 * mm] + [body_w / (ncol - 1)] * (ncol - 1)
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), FONT_B),
        ('FONTSIZE', (0, 0), (-1, -1), 7.4),
        ('BACKGROUND', (0, 0), (-1, 0), INK), ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, SURFACE]),
        ('GRID', (0, 0), (-1, -1), 0.3, LINE),
        ('ALIGN', (1, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3.5), ('BOTTOMPADDING', (0, 0), (-1, -1), 3.5),
    ]))
    story.append(t)
    story.append(Spacer(1, 6 * mm))
    story.append(Paragraph(
        "<b>Disclaimer.</b> IndoPave-37 is a design-aid tool. Results are produced by a "
        "mechanistic-empirical analysis per IRC:37-2018/2019 and must be checked and "
        "sealed by a qualified pavement engineer before construction. The native solver "
        "agrees with IITPAVE to within ~1% on standard cases; mixed-Poisson dual-wheel "
        "configurations may deviate more.", styles['small']))
    return story


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def generate_report(
    project_name: str,
    traffic_params: dict,
    subgrade_cbr: float,
    selected_solution: dict,
    adequate_designs: list,
) -> bytes:
    """Generate the branded IRC:37 PDF report and return it as bytes."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=24 * mm, bottomMargin=20 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
        title=f"IndoPave-37 Design Report — {project_name}",
        author="IndoPave-37",
    )
    s = _styles()
    sol = selected_solution or {}
    story = []
    story += _cover(s, project_name, traffic_params, subgrade_cbr, sol)
    story.append(PageBreak())
    story += _design_basis(s, traffic_params, subgrade_cbr, sol)
    story.append(PageBreak())
    story += _composition(s, sol)
    story.append(PageBreak())
    story += _compliance(s, sol)
    story.append(PageBreak())
    story += _clause_checklist(s, sol)
    story.append(Spacer(1, 8 * mm))
    story += _alternatives(s, adequate_designs or [])

    doc.build(story, onFirstPage=_cover_canvas, onLaterPages=_running_header_footer)
    return buffer.getvalue()
