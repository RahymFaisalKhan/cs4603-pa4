"""Generate the PA4 corpus: a fictional company annual report.

Produces two files in this folder from one source of truth:
  - annual_report.pdf   (ingested by rag/ingest.py via ai_parse_document)
  - annual_report.md    (human-readable version, easy to edit/review)

The company (Meridian Motor Corporation) and all figures are FICTIONAL, so
there are no copyright or accuracy concerns. Figures are internally consistent:
segment and regional revenue both sum to the FY2023 net revenue of
¥16.91 trillion, and the marquee example query
    16.91 × 1.08^3 = 21.30 (trillion)
resolves exactly.

Run:  python generate_report.py
Deps: reportlab  (pip install reportlab)
"""

from __future__ import annotations

import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

HERE = os.path.dirname(os.path.abspath(__file__))
PDF_PATH = os.path.join(HERE, "annual_report.pdf")
MD_PATH = os.path.join(HERE, "annual_report.md")

COMPANY = "Meridian Motor Corporation"
FY = "fiscal year ended March 31, 2023 (FY2023)"
NAVY = colors.HexColor("#1a2b4a")
ACCENT = colors.HexColor("#b02a37")

# ─── Source content ──────────────────────────────────────────────────────────
# Each "page" is a section forced onto its own PDF page so page numbers are
# deterministic. Financial Highlights is page 4 to match the assignment's
# citations ("net revenue ... page 4", "net income ... p.4").

FIVE_YEAR = [
    ["¥ billions (except per-share)", "FY2019", "FY2020", "FY2021", "FY2022", "FY2023"],
    ["Net revenue", "11,280", "12,110", "13,170", "14,550", "16,910"],
    ["Operating profit", "720", "610", "880", "905", "1,124"],
    ["Net income (owners)", "512", "455", "657", "707", "1,107"],
    ["Operating margin", "6.4%", "5.0%", "6.7%", "6.2%", "6.6%"],
    ["R&D expense", "690", "705", "760", "815", "880"],
    ["Capital expenditure", "480", "455", "500", "540", "590"],
    ["Total assets", "19,900", "20,600", "22,100", "23,700", "25,300"],
    ["Total equity", "8,600", "8,900", "9,800", "10,400", "11,200"],
    ["EPS (¥)", "296", "263", "380", "409", "640"],
    ["Dividend per share (¥)", "100", "100", "120", "135", "150"],
    ["Vehicle unit sales (000s)", "3,410", "3,120", "3,490", "3,680", "4,070"],
    ["Employees", "196,000", "199,000", "203,000", "206,000", "210,000"],
]

INCOME_STMT = [
    ["¥ billions", "FY2022", "FY2023", "Change"],
    ["Net revenue", "14,550", "16,910", "+16.2%"],
    ["Cost of sales", "(11,780)", "(13,560)", "+15.1%"],
    ["Gross profit", "2,770", "3,350", "+20.9%"],
    ["SG&A expenses", "(1,050)", "(1,346)", "+28.2%"],
    ["R&D expense", "(815)", "(880)", "+8.0%"],
    ["Operating profit", "905", "1,124", "+24.2%"],
    ["Finance income, net", "62", "78", "+25.8%"],
    ["Share of profit of associates", "140", "168", "+20.0%"],
    ["Profit before tax", "1,107", "1,370", "+23.8%"],
    ["Income tax expense", "(360)", "(233)", "-35.3%"],
    ["Profit for the year", "747", "1,137", "+52.2%"],
    ["Attributable to owners", "707", "1,107", "+56.6%"],
    ["Attributable to NCI", "40", "30", "-25.0%"],
]

SEGMENT = [
    ["Segment (FY2023, ¥B)", "Net revenue", "Operating profit", "Op. margin"],
    ["Automobile", "12,900", "560", "4.3%"],
    ["Motorcycle", "2,510", "360", "14.3%"],
    ["Financial Services", "1,100", "180", "16.4%"],
    ["Power Products & Other", "400", "24", "6.0%"],
    ["Consolidated total", "16,910", "1,124", "6.6%"],
]

REGION = [
    ["Region (FY2023, ¥B)", "Net revenue", "% of total", "YoY change"],
    ["Japan", "3,050", "18.0%", "+7.4%"],
    ["North America", "7,420", "43.9%", "+21.8%"],
    ["Europe", "1,680", "9.9%", "+11.3%"],
    ["Asia (ex-Japan)", "3,900", "23.1%", "+18.5%"],
    ["Other regions", "860", "5.1%", "+9.6%"],
    ["Consolidated total", "16,910", "100.0%", "+16.2%"],
]

BALANCE = [
    ["¥ billions", "FY2022", "FY2023"],
    ["Cash and cash equivalents", "3,720", "4,150"],
    ["Trade receivables", "2,410", "2,690"],
    ["Inventories", "2,050", "2,320"],
    ["Finance receivables", "6,900", "7,480"],
    ["Property, plant & equipment", "5,180", "5,460"],
    ["Other assets", "3,440", "3,200"],
    ["Total assets", "23,700", "25,300"],
    ["Trade payables", "2,260", "2,540"],
    ["Debt (short + long term)", "8,900", "9,300"],
    ["Other liabilities", "2,140", "2,260"],
    ["Total liabilities", "13,300", "14,100"],
    ["Total equity", "10,400", "11,200"],
]

CASHFLOW = [
    ["¥ billions", "FY2022", "FY2023"],
    ["Operating cash flow", "1,540", "1,760"],
    ["Capital expenditure", "(540)", "(590)"],
    ["Free cash flow", "1,000", "1,170"],
    ["Investing cash flow", "(1,020)", "(1,180)"],
    ["Financing cash flow", "(360)", "(420)"],
    ["Net change in cash", "160", "160"],
    ["Cash, end of year", "3,720", "4,150"],
]

SECTIONS = [
    # (title, list of ("para"|"table"|"bullet", content))
    (
        "Letter from the President and CEO",
        [
            ("para",
             f"To our shareholders, customers, and employees: {COMPANY} delivered "
             "record results in the fiscal year ended March 31, 2023. Consolidated "
             "net revenue rose 16.2% to \u00a516,910 billion (\u00a516.91 trillion), and "
             "operating profit increased 24.2% to \u00a51,124 billion. Net income "
             "attributable to owners of the parent reached \u00a51,107 billion, our "
             "highest ever."),
            ("para",
             "Demand recovered strongly across all major markets as supply-chain "
             "constraints eased. Global vehicle unit sales grew to 4.07 million "
             "units, up from 3.68 million a year earlier, led by our electrified "
             "line-up in North America and Asia. Our Motorcycle business remained "
             "the profitability anchor of the group, with a 14.3% operating margin."),
            ("para",
             "We continued to invest for the long term. Research and development "
             "expense rose to \u00a5880 billion, or 5.2% of net revenue, concentrated "
             "on battery-electric platforms, software-defined vehicle architecture, "
             "and advanced driver assistance. Capital expenditure was \u00a5590 billion."),
            ("para",
             "Looking ahead to FY2024, we forecast net revenue of \u00a518.20 trillion "
             "and operating profit of \u00a51.30 trillion, and we have raised the annual "
             "dividend to \u00a5150 per share. On behalf of the Board, thank you for "
             "your continued trust in Meridian Motor Corporation."),
        ],
    ),
    (
        "Financial Highlights \u2014 Five-Year Summary",
        [
            ("para",
             f"The table below summarizes the consolidated performance of {COMPANY} "
             "over the past five fiscal years. In FY2023, net revenue was "
             "\u00a516.91 trillion and net income attributable to owners was "
             "\u00a51,107 billion (\u00a51.11 trillion)."),
            ("table", FIVE_YEAR),
            ("para",
             "Net revenue grew at a five-year compound annual growth rate (CAGR) of "
             "10.7%, from \u00a511,280 billion in FY2019 to \u00a516,910 billion in FY2023. "
             "Earnings per share more than doubled over the same period to \u00a5640."),
        ],
    ),
    (
        "Consolidated Statement of Operations",
        [
            ("para",
             "The following condensed statement of operations compares FY2023 with "
             "the prior fiscal year. All amounts are in billions of Japanese yen "
             "unless otherwise stated."),
            ("table", INCOME_STMT),
            ("para",
             "Gross profit improved to \u00a53,350 billion as pricing and mix more than "
             "offset higher input costs. The effective tax rate fell to 17.0% "
             "following the recognition of previously unrecognized deferred tax "
             "assets."),
        ],
    ),
    (
        "About Meridian Motor Corporation",
        [
            ("para",
             f"{COMPANY} is a global mobility company headquartered in Tokyo, Japan, "
             "and listed on the Tokyo Stock Exchange (Prime Market, code 7000). "
             "Founded in 1959, the company designs, manufactures, and sells "
             "automobiles, motorcycles, and power products, and provides related "
             "financial services."),
            ("para",
             "The company operates 38 production facilities across 14 countries and "
             "employs approximately 210,000 people worldwide. Its four reportable "
             "segments are Automobile, Motorcycle, Financial Services, and Power "
             "Products & Other."),
            ("bullet", [
                "Headquarters: Tokyo, Japan",
                "Listing: Tokyo Stock Exchange, Prime Market (code 7000)",
                "Fiscal year end: March 31",
                "Reporting currency: Japanese yen (\u00a5)",
                "Employees: approximately 210,000",
                "FY2023 vehicle unit sales: 4.07 million",
                "FY2023 motorcycle unit sales: 18.5 million",
            ]),
        ],
    ),
    (
        "Segment Information",
        [
            ("para",
             "Meridian reports four operating segments. The Automobile segment is "
             "the largest by revenue, while the Motorcycle and Financial Services "
             "segments deliver the highest operating margins."),
            ("table", SEGMENT),
            ("para",
             "The Automobile segment's operating margin of 4.3% reflects continued "
             "investment in electrification and elevated logistics costs. The "
             "Financial Services segment benefited from a larger finance-receivables "
             "portfolio, which reached \u00a57,480 billion at year end."),
        ],
    ),
    (
        "Regional Performance",
        [
            ("para",
             "Net revenue is presented below by the geographic location of "
             "customers. North America remained the largest market, accounting for "
             "43.9% of consolidated net revenue."),
            ("table", REGION),
            ("para",
             "Asia (excluding Japan) was the fastest-growing major region on an "
             "absolute basis, adding \u00a5610 billion of net revenue year over year, "
             "driven by motorcycle demand in India and Southeast Asia."),
        ],
    ),
    (
        "Consolidated Balance Sheet (Summary)",
        [
            ("para",
             "Total assets increased to \u00a525,300 billion, and total equity rose to "
             "\u00a511,200 billion. The equity ratio was 44.3% at year end."),
            ("table", BALANCE),
        ],
    ),
    (
        "Consolidated Statements of Cash Flows (Summary)",
        [
            ("para",
             "Operating cash flow increased to \u00a51,760 billion. Free cash flow, "
             "defined as operating cash flow less capital expenditure, was "
             "\u00a51,170 billion."),
            ("table", CASHFLOW),
        ],
    ),
    (
        "Research & Development and Capital Investment",
        [
            ("para",
             "Research and development expense was \u00a5880 billion in FY2023, equal to "
             "5.2% of net revenue, up from \u00a5815 billion (5.6% of net revenue) in "
             "FY2022. Capital expenditure was \u00a5590 billion."),
            ("para",
             "R&D was concentrated in three priority areas: battery-electric vehicle "
             "platforms, software-defined vehicle architecture and connected "
             "services, and advanced driver-assistance systems. The company targets "
             "30 new battery-electric models globally by FY2030 and plans to raise "
             "R&D expense to approximately \u00a51,000 billion in FY2024."),
        ],
    ),
    (
        "Risk Factors",
        [
            ("para",
             "The following summarizes principal risks that could materially affect "
             "the company's results. This summary is illustrative and not "
             "exhaustive."),
            ("bullet", [
                "Market risk: cyclical demand for automobiles and motorcycles, and "
                "intensifying price competition in electrified vehicles.",
                "Supply-chain risk: availability and cost of semiconductors, "
                "batteries, and critical raw materials such as lithium and nickel.",
                "Foreign-exchange risk: a significant share of revenue is earned "
                "outside Japan; a stronger yen reduces reported revenue and profit.",
                "Regulatory risk: tightening emissions and safety regulations "
                "increase compliance and development costs.",
                "Technology risk: rapid shifts toward electrification and software "
                "could render existing investments less competitive.",
            ]),
        ],
    ),
    (
        "Outlook and Guidance (FY2024)",
        [
            ("para",
             "For the fiscal year ending March 31, 2024, management provides the "
             "following consolidated forecast. Guidance assumes an average exchange "
             "rate of \u00a5135 to the US dollar."),
            ("table", [
                ["Metric", "FY2023 actual", "FY2024 forecast", "Change"],
                ["Net revenue (\u00a5T)", "16.91", "18.20", "+7.6%"],
                ["Operating profit (\u00a5B)", "1,124", "1,300", "+15.7%"],
                ["Net income (\u00a5B)", "1,107", "1,240", "+12.0%"],
                ["Vehicle unit sales (M)", "4.07", "4.35", "+6.9%"],
                ["Dividend per share (\u00a5)", "150", "165", "+10.0%"],
            ]),
            ("para",
             "The forecast reflects continued volume recovery, a richer product mix, "
             "and disciplined pricing, partly offset by higher R&D and launch costs "
             "for new electric models."),
        ],
    ),
    (
        "Notes and Glossary",
        [
            ("bullet", [
                "Net revenue: consolidated sales of products and services, net of "
                "returns and discounts.",
                "Operating profit: net revenue less cost of sales, SG&A, and R&D "
                "expense.",
                "Net income (owners): profit for the year attributable to owners of "
                "the parent, excluding non-controlling interests (NCI).",
                "Free cash flow: operating cash flow less capital expenditure.",
                "CAGR: compound annual growth rate.",
                "\u00a51 trillion = \u00a51,000 billion = \u00a51,000,000 million.",
                "All figures are fictional and provided solely for CS4603 coursework.",
            ]),
        ],
    ),
]


# ─── PDF builder ─────────────────────────────────────────────────────────────
def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("Cover", parent=ss["Title"], fontSize=30, textColor=NAVY,
                          leading=36, alignment=TA_CENTER, spaceAfter=18))
    ss.add(ParagraphStyle("CoverSub", parent=ss["Normal"], fontSize=15,
                          textColor=ACCENT, alignment=TA_CENTER, spaceAfter=8))
    ss.add(ParagraphStyle("H", parent=ss["Heading1"], fontSize=17, textColor=NAVY,
                          spaceBefore=4, spaceAfter=12))
    ss.add(ParagraphStyle("Body", parent=ss["Normal"], fontSize=10.5, leading=15,
                          alignment=TA_JUSTIFY, spaceAfter=9))
    ss.add(ParagraphStyle("Bul", parent=ss["Normal"], fontSize=10.5, leading=15,
                          leftIndent=14, spaceAfter=5, bulletIndent=4))
    ss.add(ParagraphStyle("TOC", parent=ss["Normal"], fontSize=11, leading=20))
    return ss


def _table(data):
    t = Table(data, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef1f6")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c3c9d4")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    # Bold any total/attributable-to-owners row.
    for i, row in enumerate(data):
        label = str(row[0]).lower()
        if "total" in label or "attributable to owners" in label or "free cash flow" in label:
            style.append(("FONTNAME", (0, i), (-1, i), "Helvetica-Bold"))
            style.append(("LINEABOVE", (0, i), (-1, i), 0.8, NAVY))
    t.setStyle(TableStyle(style))
    return t


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.drawString(2 * cm, 1.1 * cm, f"{COMPANY} \u2014 Annual Report FY2023")
    canvas.drawRightString(A4[0] - 2 * cm, 1.1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf():
    ss = _styles()
    doc = BaseDocTemplate(PDF_PATH, pagesize=A4,
                          leftMargin=2 * cm, rightMargin=2 * cm,
                          topMargin=2 * cm, bottomMargin=1.8 * cm,
                          title=f"{COMPANY} Annual Report FY2023",
                          author=COMPANY)
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=_footer)])

    flow = []

    # Page 1 — Cover
    flow += [Spacer(1, 5 * cm),
             Paragraph(COMPANY, ss["Cover"]),
             Paragraph("Annual Report", ss["CoverSub"]),
             Paragraph(f"For the {FY}", ss["CoverSub"]),
             Spacer(1, 1 * cm),
             Paragraph("Tokyo Stock Exchange (Prime Market) \u00b7 Code 7000", ss["CoverSub"]),
             PageBreak()]

    # Page 2 — Table of Contents
    toc_rows = ["Letter from the President and CEO ........................ 3",
                "Financial Highlights \u2014 Five-Year Summary ............ 4",
                "Consolidated Statement of Operations ................. 5",
                "About Meridian Motor Corporation ..................... 6",
                "Segment Information .......................................... 7",
                "Regional Performance ....................................... 8",
                "Consolidated Balance Sheet ............................. 9",
                "Consolidated Statements of Cash Flows ............ 10",
                "Research & Development and Capital Investment . 11",
                "Risk Factors .................................................... 12",
                "Outlook and Guidance (FY2024) ...................... 13",
                "Notes and Glossary ......................................... 14"]
    flow += [Paragraph("Table of Contents", ss["H"])]
    flow += [Paragraph(r, ss["TOC"]) for r in toc_rows]
    flow += [Spacer(1, 0.6 * cm),
             Paragraph("<i>All figures in this report are fictional and provided "
                       "solely for CS4603 coursework.</i>", ss["Body"]),
             PageBreak()]

    # Pages 3+ — sections
    for i, (title, blocks) in enumerate(SECTIONS):
        flow.append(Paragraph(title, ss["H"]))
        for kind, content in blocks:
            if kind == "para":
                flow.append(Paragraph(content, ss["Body"]))
            elif kind == "bullet":
                for b in content:
                    flow.append(Paragraph(b, ss["Bul"], bulletText="\u2022"))
                flow.append(Spacer(1, 4))
            elif kind == "table":
                flow.append(_table(content))
                flow.append(Spacer(1, 8))
        if i < len(SECTIONS) - 1:
            flow.append(PageBreak())

    doc.build(flow)


# ─── Markdown builder (readable mirror) ──────────────────────────────────────
def build_md():
    lines = [f"# {COMPANY} \u2014 Annual Report FY2023", "",
             f"*For the {FY}. Tokyo Stock Exchange (Prime Market), code 7000.*", "",
             "> All figures are fictional and provided solely for CS4603 coursework.",
             ""]

    def md_table(data):
        out = ["| " + " | ".join(data[0]) + " |",
               "|" + "|".join(["---"] * len(data[0])) + "|"]
        for row in data[1:]:
            out.append("| " + " | ".join(row) + " |")
        return out + [""]

    for title, blocks in SECTIONS:
        lines += [f"## {title}", ""]
        for kind, content in blocks:
            if kind == "para":
                lines += [content, ""]
            elif kind == "bullet":
                lines += [f"- {b}" for b in content] + [""]
            elif kind == "table":
                lines += md_table(content)

    with open(MD_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    build_pdf()
    build_md()
    print(f"Wrote {PDF_PATH}")
    print(f"Wrote {MD_PATH}")
