"""
PDF Report Generator for MEP-Opt
=================================
Generates certified multi-page PDF reports with structural cross-section
diagrams and IRC:37-2018 compliance stamps using reportlab.
"""

from io import BytesIO
from datetime import datetime
from typing import List, Dict, Any, Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor, black, white, Color
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line
from reportlab.graphics import renderPDF

# Color scheme matching Industrial Blueprint aesthetic
PRIMARY = HexColor('#2563eb')
SURFACE = HexColor('#f7f9fb')
TEXT_DARK = HexColor('#111621')
TEXT_MUTED = HexColor('#566166')
GREEN = HexColor('#16a34a')
RED = HexColor('#dc2626')

# Layer colors for cross-section diagram
LAYER_COLORS = {
    'BC': HexColor('#1e3a5f'),
    'DBM': HexColor('#2d5986'),
    'SMA': HexColor('#1a4570'),
    'SDBC': HexColor('#3b6d9e'),
    'BM': HexColor('#4a7db3'),
    'WMM': HexColor('#8B7355'),
    'WBM': HexColor('#A0896C'),
    'GSB': HexColor('#C4A882'),
    'CTB': HexColor('#7B8D8E'),
    'RAP': HexColor('#5a6b5a'),
}


def _make_styles():
    """Create custom paragraph styles."""
    base = getSampleStyleSheet()
    styles = {
        'title': ParagraphStyle(
            'ReportTitle', parent=base['Title'],
            fontName='Helvetica-Bold', fontSize=18, spaceAfter=6,
            textColor=TEXT_DARK,
        ),
        'heading': ParagraphStyle(
            'ReportHeading', parent=base['Heading2'],
            fontName='Helvetica-Bold', fontSize=13, spaceAfter=10,
            spaceBefore=16, textColor=TEXT_DARK,
        ),
        'subheading': ParagraphStyle(
            'ReportSubheading', parent=base['Heading3'],
            fontName='Helvetica-Bold', fontSize=10, spaceAfter=6,
            textColor=TEXT_MUTED,
        ),
        'body': ParagraphStyle(
            'ReportBody', parent=base['Normal'],
            fontName='Helvetica', fontSize=9, spaceAfter=4,
            textColor=TEXT_DARK,
        ),
        'small': ParagraphStyle(
            'ReportSmall', parent=base['Normal'],
            fontName='Helvetica', fontSize=7.5, spaceAfter=2,
            textColor=TEXT_MUTED,
        ),
    }
    return styles


def _header_footer(canvas, doc):
    """Draw header and footer on every page."""
    canvas.saveState()
    w, h = A4

    # Header line
    canvas.setStrokeColor(PRIMARY)
    canvas.setLineWidth(1.5)
    canvas.line(20 * mm, h - 18 * mm, w - 20 * mm, h - 18 * mm)

    canvas.setFont('Helvetica-Bold', 9)
    canvas.setFillColor(TEXT_DARK)
    canvas.drawString(20 * mm, h - 15 * mm, "MEP-Opt FlexPave v3.4")

    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawRightString(w - 20 * mm, h - 15 * mm, "IRC:37-2018 Compliance Report")

    # Footer
    canvas.setStrokeColor(HexColor('#e0e0e0'))
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 15 * mm, w - 20 * mm, 15 * mm)

    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(TEXT_MUTED)
    canvas.drawString(20 * mm, 10 * mm, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    canvas.drawRightString(w - 20 * mm, 10 * mm, f"Page {doc.page}")

    canvas.restoreState()


def _build_summary_page(styles, project_name, traffic_params, subgrade_cbr, selected_solution):
    """Page 1: Project summary."""
    story = []

    story.append(Paragraph(f"Pavement Design Report", styles['title']))
    story.append(Paragraph(f"Project: {project_name}", styles['subheading']))
    story.append(Spacer(1, 8 * mm))

    # Traffic parameters table
    story.append(Paragraph("Traffic Parameters", styles['heading']))
    cvpd = traffic_params.get('cvpd', 0)
    gr = traffic_params.get('growth_rate', 0)
    vdf_val = traffic_params.get('vdf', 2.5)
    dl = traffic_params.get('design_life', 20)

    traffic_data = [
        ['Parameter', 'Value'],
        ['CVPD (Commercial Vehicles/Day)', str(cvpd)],
        ['Growth Rate', f"{gr}%"],
        ['Vehicle Damage Factor (VDF)', str(vdf_val)],
        ['Design Life', f"{dl} years"],
        ['Subgrade CBR', f"{subgrade_cbr}%"],
    ]

    # Compute MR
    if subgrade_cbr <= 5:
        mr = 10 * subgrade_cbr
    else:
        mr = 17.6 * (subgrade_cbr ** 0.64)
    traffic_data.append(['Resilient Modulus (MR)', f"{mr:.2f} MPa"])

    t = Table(traffic_data, colWidths=[120 * mm, 40 * mm])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e0e0e0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, SURFACE]),
    ]))
    story.append(t)
    story.append(Spacer(1, 8 * mm))

    # Selected design summary
    if selected_solution:
        story.append(Paragraph("Selected Design", styles['heading']))
        layers = selected_solution.get('optimal_layers', [])
        total_t = selected_solution.get('total_thickness', sum(l.get('thickness', 0) for l in layers))
        details = selected_solution.get('details', {})

        design_data = [['Layer', 'Thickness (mm)']]
        for l in layers:
            design_data.append([l.get('type', ''), f"{l.get('thickness', 0):.0f}"])
        design_data.append(['Total', f"{total_t:.0f}"])

        t2 = Table(design_data, colWidths=[80 * mm, 80 * mm])
        t2.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('BACKGROUND', (0, -1), (-1, -1), HexColor('#e8f0fe')),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e0e0e0')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(t2)

        # Cost/CO2 info
        story.append(Spacer(1, 4 * mm))
        cost = selected_solution.get('cost', 0)
        co2 = selected_solution.get('co2', 0)
        story.append(Paragraph(
            f"Estimated Cost: INR {cost:,.0f}/km &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Embodied CO<sub>2</sub>: {co2:,.1f} T/km",
            styles['small']
        ))

    return story


def _build_cross_section_page(styles, selected_solution):
    """Page 2: Structural cross-section diagram."""
    story = []
    story.append(Paragraph("Structural Cross-Section", styles['heading']))

    layers = selected_solution.get('optimal_layers', [])
    if not layers:
        story.append(Paragraph("No design data available.", styles['body']))
        return story

    # Drawing dimensions
    draw_width = 400
    draw_height = 300
    section_width = 220
    x_start = (draw_width - section_width) / 2
    y_top = draw_height - 30
    total_thickness = sum(l.get('thickness', 50) for l in layers)

    # Min height per layer for visibility
    min_layer_px = 30
    available_height = draw_height - 80  # leave room for labels
    scale = available_height / max(total_thickness, 1)

    d = Drawing(draw_width, draw_height)

    # Title
    d.add(String(draw_width / 2, draw_height - 10, "PAVEMENT LAYER PROFILE",
                 fontName='Helvetica-Bold', fontSize=9, textAnchor='middle',
                 fillColor=TEXT_DARK))

    y_cursor = y_top - 20
    for layer in layers:
        t = layer.get('thickness', 50)
        layer_type = layer.get('type', '?')
        h = max(t * scale, min_layer_px)

        color = LAYER_COLORS.get(layer_type, HexColor('#999999'))
        d.add(Rect(x_start, y_cursor - h, section_width, h,
                   fillColor=color, strokeColor=black, strokeWidth=0.5))

        # Layer label (white text centered)
        label_y = y_cursor - h / 2 - 4
        d.add(String(x_start + section_width / 2, label_y,
                     f"{layer_type} — {t:.0f} mm",
                     fontName='Helvetica-Bold', fontSize=8, textAnchor='middle',
                     fillColor=white))

        # Dimension line on right
        dim_x = x_start + section_width + 10
        d.add(Line(dim_x, y_cursor, dim_x, y_cursor - h, strokeColor=TEXT_MUTED, strokeWidth=0.5))
        d.add(String(dim_x + 5, label_y, f"{t:.0f}",
                     fontName='Helvetica', fontSize=7, fillColor=TEXT_MUTED))

        y_cursor -= h

    # Subgrade
    sub_h = 30
    d.add(Rect(x_start, y_cursor - sub_h, section_width, sub_h,
               fillColor=HexColor('#6B4423'), strokeColor=black, strokeWidth=0.5))
    d.add(String(x_start + section_width / 2, y_cursor - sub_h / 2 - 4,
                 "SUBGRADE (Semi-Infinite)",
                 fontName='Helvetica-Bold', fontSize=7, textAnchor='middle',
                 fillColor=white))

    # Total thickness annotation
    d.add(String(draw_width / 2, y_cursor - sub_h - 15,
                 f"Total Pavement Thickness: {total_thickness:.0f} mm",
                 fontName='Helvetica-Bold', fontSize=9, textAnchor='middle',
                 fillColor=PRIMARY))

    story.append(d)
    return story


def _build_compliance_page(styles, selected_solution):
    """Page 3: IRC:37 compliance table and stamp."""
    story = []
    story.append(Paragraph("IRC:37-2018 Design Adequacy Check", styles['heading']))

    details = selected_solution.get('details', {})
    if not details:
        story.append(Paragraph("No analysis data available.", styles['body']))
        return story

    is_adequate = details.get('overall_adequate', False)

    # Compliance table
    data = [
        ['Parameter', 'Value', 'Criterion', 'Status'],
        ['Tensile Strain (eps_t)', f"{details.get('eps_t', 0):.4e}", 'Fatigue check', ''],
        ['Vertical Strain (eps_v)', f"{details.get('eps_v', 0):.4e}", 'Rutting check', ''],
        ['Fatigue Life (Nf)', f"{details.get('Nf', 0):.2e}", '> N_applied', ''],
        ['Rutting Life (NR)', f"{details.get('NR', 0):.2e}", '> N_applied', ''],
        ['CDF Fatigue', f"{details.get('CDF_fatigue', 0):.4f}", '<= 1.0',
         'PASS' if details.get('CDF_fatigue', 2) <= 1.0 else 'FAIL'],
        ['CDF Rutting', f"{details.get('CDF_rutting', 0):.4f}", '<= 1.0',
         'PASS' if details.get('CDF_rutting', 2) <= 1.0 else 'FAIL'],
        ['Design Traffic', f"{details.get('msa', 0):.1f} MSA", '', ''],
        ['Governing Mode', details.get('governing_mode', '—').upper(), '', ''],
        ['Overall Adequacy', '', '', 'ADEQUATE' if is_adequate else 'INADEQUATE'],
    ]

    t = Table(data, colWidths=[55 * mm, 40 * mm, 35 * mm, 30 * mm])
    table_style = [
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e0e0e0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, SURFACE]),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]

    # Color the status column
    for row_idx in range(1, len(data)):
        status = data[row_idx][-1]
        if status in ('PASS', 'ADEQUATE'):
            table_style.append(('TEXTCOLOR', (-1, row_idx), (-1, row_idx), GREEN))
        elif status in ('FAIL', 'INADEQUATE'):
            table_style.append(('TEXTCOLOR', (-1, row_idx), (-1, row_idx), RED))

    t.setStyle(TableStyle(table_style))
    story.append(t)
    story.append(Spacer(1, 12 * mm))

    # Compliance stamp
    stamp_text = "IRC:37-2018 COMPLIANT" if is_adequate else "IRC:37-2018 NON-COMPLIANT"
    stamp_color = GREEN if is_adequate else RED
    stamp_style = ParagraphStyle(
        'Stamp', fontName='Helvetica-Bold', fontSize=20,
        textColor=stamp_color, alignment=1, spaceAfter=4,
        borderWidth=2, borderColor=stamp_color, borderPadding=10,
    )
    story.append(Paragraph(stamp_text, stamp_style))

    return story


def _build_designs_table_page(styles, adequate_designs, layer_types_order=None):
    """Page 4: All adequate designs table."""
    story = []
    story.append(Paragraph("All Adequate Designs", styles['heading']))
    story.append(Paragraph(
        f"{len(adequate_designs)} structurally adequate design(s) found. "
        "Sorted by total thickness (thinnest first). Cost and CO2 shown as informational metrics.",
        styles['small']
    ))
    story.append(Spacer(1, 4 * mm))

    if not adequate_designs:
        story.append(Paragraph("No adequate designs found.", styles['body']))
        return story

    # Determine layer types from first solution
    first_layers = adequate_designs[0].get('optimal_layers', [])
    layer_types = [l['type'] for l in first_layers]

    # Build header
    header = ['#'] + layer_types + ['Total (mm)', 'CDF_fat', 'CDF_rut', 'Cost (M)', 'CO2 (T)']

    # Limit to 25 designs for page space
    designs_to_show = adequate_designs[:25]
    rows = [header]

    for i, sol in enumerate(designs_to_show):
        layers = sol.get('optimal_layers', [])
        details = sol.get('details', {})
        row = [str(i + 1)]
        for l in layers:
            row.append(f"{l.get('thickness', 0):.0f}")
        row.append(f"{sol.get('total_thickness', 0):.0f}")
        row.append(f"{details.get('CDF_fatigue', 0):.3f}")
        row.append(f"{details.get('CDF_rutting', 0):.3f}")
        row.append(f"{sol.get('cost', 0) / 1e6:.2f}")
        row.append(f"{sol.get('co2', 0):.1f}")
        rows.append(row)

    n_cols = len(header)
    col_w = 160 * mm / n_cols
    col_widths = [8 * mm] + [col_w] * (n_cols - 1)

    t = Table(rows, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 7),
        ('BACKGROUND', (0, 0), (-1, 0), PRIMARY),
        ('TEXTCOLOR', (0, 0), (-1, 0), white),
        ('GRID', (0, 0), (-1, -1), 0.3, HexColor('#e0e0e0')),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, SURFACE]),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
    ]))
    story.append(t)

    if len(adequate_designs) > 25:
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph(
            f"Showing 25 of {len(adequate_designs)} designs. Full data available in .mep project file.",
            styles['small']
        ))

    return story


def generate_report(
    project_name: str,
    traffic_params: dict,
    subgrade_cbr: float,
    selected_solution: dict,
    adequate_designs: list,
) -> bytes:
    """Generate a certified PDF report and return as bytes."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=22 * mm, bottomMargin=20 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
    )

    styles = _make_styles()
    story = []

    # Page 1: Project Summary
    story.extend(_build_summary_page(styles, project_name, traffic_params,
                                      subgrade_cbr, selected_solution))
    story.append(PageBreak())

    # Page 2: Structural Cross-Section
    story.extend(_build_cross_section_page(styles, selected_solution))
    story.append(PageBreak())

    # Page 3: IRC:37 Compliance
    story.extend(_build_compliance_page(styles, selected_solution))
    story.append(PageBreak())

    # Page 4: All Adequate Designs
    story.extend(_build_designs_table_page(styles, adequate_designs))

    doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
    return buffer.getvalue()
