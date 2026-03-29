"""Build ProductTeam Architecture & User Guide PDF with SVG diagrams."""

import os
from pathlib import Path
from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch, cm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    Image, KeepTogether, Flowable,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Group, Polygon
from reportlab.graphics import renderPDF

# ── Colors ──────────────────────────────────────────────────────────────
BG_DARK = HexColor("#0e1117")
SURFACE = HexColor("#161b22")
BORDER = HexColor("#30363d")
TEXT = HexColor("#e6edf3")
TEXT_MUTED = HexColor("#8b949e")
ACCENT = HexColor("#58a6ff")
GREEN = HexColor("#3fb950")
RED = HexColor("#f85149")
YELLOW = HexColor("#d29922")
WHITE = HexColor("#ffffff")
DARK_HEADER = HexColor("#0d1117")

# ── Styles ──────────────────────────────────────────────────────────────
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_MONO = "Courier"

style_body = ParagraphStyle("Body", fontName=FONT, fontSize=10, leading=14,
                            textColor=HexColor("#333333"), spaceAfter=8)
style_body_sm = ParagraphStyle("BodySm", fontName=FONT, fontSize=9, leading=12,
                               textColor=HexColor("#555555"), spaceAfter=6)
style_h1 = ParagraphStyle("H1", fontName=FONT_BOLD, fontSize=22, leading=28,
                           textColor=DARK_HEADER, spaceAfter=12, spaceBefore=24)
style_h2 = ParagraphStyle("H2", fontName=FONT_BOLD, fontSize=16, leading=20,
                           textColor=HexColor("#1a1f2e"), spaceAfter=8, spaceBefore=16)
style_h3 = ParagraphStyle("H3", fontName=FONT_BOLD, fontSize=12, leading=16,
                           textColor=HexColor("#333333"), spaceAfter=6, spaceBefore=12)
style_code = ParagraphStyle("Code", fontName=FONT_MONO, fontSize=9, leading=12,
                             textColor=HexColor("#1a1a1a"), backColor=HexColor("#f0f0f0"),
                             borderPadding=4, spaceAfter=8)
style_center = ParagraphStyle("Center", fontName=FONT, fontSize=10, leading=14,
                               textColor=HexColor("#333333"), alignment=TA_CENTER)
style_warning = ParagraphStyle("Warning", fontName=FONT, fontSize=10, leading=14,
                                textColor=HexColor("#8a6d00"), backColor=HexColor("#fff8e1"),
                                borderPadding=8, spaceAfter=12, spaceBefore=8,
                                borderColor=YELLOW, borderWidth=1)
style_accent = ParagraphStyle("Accent", fontName=FONT_BOLD, fontSize=10, leading=14,
                               textColor=ACCENT, spaceAfter=4)

# ── SVG-like Drawing Helpers ────────────────────────────────────────────

def _box(d, x, y, w, h, label, sublabel="", fill=SURFACE, border=BORDER, text_color=WHITE, font_size=9):
    """Draw a rounded-corner box with label."""
    d.add(Rect(x, y, w, h, rx=6, ry=6, fillColor=fill, strokeColor=border, strokeWidth=1))
    d.add(String(x + w/2, y + h/2 + (4 if sublabel else 0), label,
                 fontName=FONT_BOLD, fontSize=font_size, fillColor=text_color, textAnchor="middle"))
    if sublabel:
        d.add(String(x + w/2, y + h/2 - 10, sublabel,
                     fontName=FONT, fontSize=7, fillColor=TEXT_MUTED, textAnchor="middle"))


def _arrow(d, x1, y1, x2, y2, color=TEXT_MUTED):
    """Draw an arrow from (x1,y1) to (x2,y2)."""
    d.add(Line(x1, y1, x2 - 6, y2, strokeColor=color, strokeWidth=1.5))
    # arrowhead
    d.add(Polygon([x2, y2, x2 - 8, y2 + 4, x2 - 8, y2 - 4],
                  fillColor=color, strokeColor=color, strokeWidth=0.5))


def _double_arrow(d, x1, y1, x2, y2, color=YELLOW):
    """Draw a double-headed arrow."""
    d.add(Line(x1 + 6, y1, x2 - 6, y2, strokeColor=color, strokeWidth=1.5))
    d.add(Polygon([x2, y2, x2 - 8, y2 + 4, x2 - 8, y2 - 4],
                  fillColor=color, strokeColor=color, strokeWidth=0.5))
    d.add(Polygon([x1, y1, x1 + 8, y1 + 4, x1 + 8, y1 - 4],
                  fillColor=color, strokeColor=color, strokeWidth=0.5))


# ── Diagram: Dual Path Architecture ────────────────────────────────────

def build_dual_path_diagram():
    """Build the wizard flow / dual-path architecture diagram."""
    d = Drawing(500, 280)
    # Background
    d.add(Rect(0, 0, 500, 280, fillColor=HexColor("#f8f9fa"), strokeColor=HexColor("#dee2e6"), strokeWidth=1, rx=8, ry=8))

    # Title
    d.add(String(250, 260, "Interactive Wizard Flow", fontName=FONT_BOLD, fontSize=11,
                 fillColor=DARK_HEADER, textAnchor="middle"))

    # Step 1: productteam command
    _box(d, 180, 220, 140, 30, "$ productteam", fill=HexColor("#1a1f2e"), border=HexColor("#30363d"),
         text_color=GREEN, font_size=10)

    # Arrow down
    _arrow(d, 250, 220, 250, 200, ACCENT)

    # Step 2: Concept input
    _box(d, 150, 170, 200, 28, "What are we building?", fill=HexColor("#ffffff"),
         border=ACCENT, text_color=HexColor("#333333"), font_size=9)

    # Arrow down
    _arrow(d, 250, 170, 250, 152, ACCENT)

    # Step 3: Choice
    d.add(Polygon([250, 152, 310, 132, 250, 112, 190, 132],
                  fillColor=HexColor("#fff8e1"), strokeColor=YELLOW, strokeWidth=1))
    d.add(String(250, 128, "A or B?", fontName=FONT_BOLD, fontSize=9,
                 fillColor=HexColor("#8a6d00"), textAnchor="middle"))

    # Path A: Local AI (left)
    _arrow(d, 190, 132, 110, 95, GREEN)
    _box(d, 20, 60, 180, 34, "A  Local AI (Ollama)", "Free  |  ~20 min/step  |  No API key",
         fill=HexColor("#e8f5e9"), border=GREEN, text_color=HexColor("#1b5e20"), font_size=9)

    # Path B: Cloud AI (right)
    _arrow(d, 310, 132, 390, 95, ACCENT)
    _box(d, 300, 60, 180, 34, "B  Cloud AI", "Deeper & faster  |  API key required",
         fill=HexColor("#e3f2fd"), border=ACCENT, text_color=HexColor("#0d47a1"), font_size=9)

    # Both converge to setup
    _arrow(d, 110, 60, 210, 32, TEXT_MUTED)
    _arrow(d, 390, 60, 290, 32, TEXT_MUTED)

    # Setup checks
    _box(d, 175, 15, 150, 28, "Setup checks + Preflight", fill=HexColor("#ffffff"),
         border=TEXT_MUTED, text_color=HexColor("#555555"), font_size=8)

    return d


# ── Diagram: Pipeline Architecture ─────────────────────────────────────

def build_pipeline_diagram():
    """Build the pipeline architecture diagram with gates."""
    d = Drawing(500, 200)
    d.add(Rect(0, 0, 500, 200, fillColor=HexColor("#f8f9fa"), strokeColor=HexColor("#dee2e6"),
               strokeWidth=1, rx=8, ry=8))

    d.add(String(250, 182, "Pipeline Architecture", fontName=FONT_BOLD, fontSize=11,
                 fillColor=DARK_HEADER, textAnchor="middle"))

    y = 110
    bw, bh = 72, 36

    # PRD Writer
    _box(d, 10, y, bw, bh, "PRD Writer", "Product Mgr", fill=HexColor("#e3f2fd"),
         border=ACCENT, text_color=HexColor("#0d47a1"))

    # Gate 1
    d.add(String(100, y - 18, "Gate 1", fontName=FONT_BOLD, fontSize=7, fillColor=YELLOW, textAnchor="middle"))

    _arrow(d, 82, y + bh/2, 104, y + bh/2, ACCENT)

    # Planner
    _box(d, 104, y, bw, bh, "Planner", "Tech Lead", fill=HexColor("#e3f2fd"),
         border=ACCENT, text_color=HexColor("#0d47a1"))

    # Gate 2
    d.add(String(194, y - 18, "Gate 2", fontName=FONT_BOLD, fontSize=7, fillColor=YELLOW, textAnchor="middle"))

    _arrow(d, 176, y + bh/2, 198, y + bh/2, ACCENT)

    # Build-Evaluate loop box
    loop_x, loop_w = 198, 168
    d.add(Rect(loop_x, y - 8, loop_w, bh + 16, rx=8, ry=8,
               fillColor=HexColor("#fff8e1"), strokeColor=YELLOW, strokeWidth=1, strokeDashArray=[4, 2]))
    d.add(String(loop_x + loop_w/2, y + bh + 14, "max 3 loops", fontName=FONT_BOLD,
                 fontSize=7, fillColor=YELLOW, textAnchor="middle"))

    # Builder
    _box(d, 206, y, 68, bh, "Builder", "Engineer", fill=HexColor("#e8f5e9"),
         border=GREEN, text_color=HexColor("#1b5e20"))

    # Double arrow
    _double_arrow(d, 274, y + bh/2, 296, y + bh/2, YELLOW)

    # Evaluator
    _box(d, 296, y, 62, bh, "Evaluator", "QA", fill=HexColor("#fce4ec"),
         border=RED, text_color=HexColor("#b71c1c"))

    _arrow(d, 366, y + bh/2, 388, y + bh/2, ACCENT)

    # Doc Writer
    _box(d, 388, y, 50, bh, "Docs", "Writer", fill=HexColor("#e3f2fd"),
         border=ACCENT, text_color=HexColor("#0d47a1"))

    # Gate 3
    d.add(String(455, y - 18, "Gate 3", fontName=FONT_BOLD, fontSize=7, fillColor=YELLOW, textAnchor="middle"))

    _arrow(d, 438, y + bh/2, 456, y + bh/2, GREEN)

    # Ship
    _box(d, 456, y, 36, bh, "Ship", "", fill=GREEN, border=GREEN, text_color=WHITE)

    # Legend at bottom
    legend_y = 40
    d.add(String(30, legend_y, "Legend:", fontName=FONT_BOLD, fontSize=8, fillColor=HexColor("#555555")))

    d.add(Rect(80, legend_y - 4, 12, 12, fillColor=HexColor("#e3f2fd"), strokeColor=ACCENT, strokeWidth=0.5))
    d.add(String(96, legend_y, "Thinker stage", fontName=FONT, fontSize=7, fillColor=HexColor("#555555")))

    d.add(Rect(175, legend_y - 4, 12, 12, fillColor=HexColor("#e8f5e9"), strokeColor=GREEN, strokeWidth=0.5))
    d.add(String(191, legend_y, "Doer stage", fontName=FONT, fontSize=7, fillColor=HexColor("#555555")))

    d.add(Rect(255, legend_y - 4, 12, 12, fillColor=HexColor("#fff8e1"), strokeColor=YELLOW, strokeWidth=0.5))
    d.add(String(271, legend_y, "Build-eval loop", fontName=FONT, fontSize=7, fillColor=HexColor("#555555")))

    d.add(Rect(360, legend_y - 4, 12, 12, fillColor=YELLOW, strokeColor=YELLOW, strokeWidth=0.5))
    d.add(String(376, legend_y, "Human approval gate", fontName=FONT, fontSize=7, fillColor=HexColor("#555555")))

    return d


# ── Cover Page ──────────────────────────────────────────────────────────

class CoverPage(Flowable):
    """Full-page cover with dark background."""
    def __init__(self, width, height):
        Flowable.__init__(self)
        self.page_width = width
        self.page_height = height

    def wrap(self, availWidth, availHeight):
        # Return dimensions that fit within the available frame
        self.width = availWidth
        self.height = availHeight
        return (availWidth, availHeight)

    def draw(self):
        c = self.canv
        w, h = self.width, self.height

        # Dark background
        c.setFillColor(DARK_HEADER)
        c.roundRect(-36, -36, w + 72, h + 72, 0, fill=True, stroke=False)

        # Accent line
        c.setStrokeColor(ACCENT)
        c.setLineWidth(3)
        c.line(w/2 - 80, h - 200, w/2 + 80, h - 200)

        # Title
        c.setFillColor(WHITE)
        c.setFont(FONT_BOLD, 32)
        c.drawCentredString(w/2, h - 160, "ProductTeam v2.6.0")

        c.setFillColor(TEXT_MUTED)
        c.setFont(FONT, 16)
        c.drawCentredString(w/2, h - 220, "Architecture & User Guide")

        # Subtitle
        c.setFillColor(ACCENT)
        c.setFont(FONT, 13)
        c.drawCentredString(w/2, h - 260, "Structured AI Software Delivery Pipeline")

        # Dual path tagline
        c.setFillColor(TEXT_MUTED)
        c.setFont(FONT, 11)
        c.drawCentredString(w/2, h - 310, "Free local AI  or  fast cloud APIs")
        c.drawCentredString(w/2, h - 328, "You choose. The wizard handles the rest.")

        # Green pill - local
        c.setFillColor(GREEN)
        c.setFont(FONT_BOLD, 10)
        c.drawCentredString(w/2 - 90, h - 370, "A  LOCAL AI")
        c.setFillColor(TEXT_MUTED)
        c.setFont(FONT, 9)
        c.drawCentredString(w/2 - 90, h - 385, "Free  |  Ollama  |  ~20 min/step")

        # Blue pill - cloud
        c.setFillColor(ACCENT)
        c.setFont(FONT_BOLD, 10)
        c.drawCentredString(w/2 + 90, h - 370, "B  CLOUD AI")
        c.setFillColor(TEXT_MUTED)
        c.setFont(FONT, 9)
        c.drawCentredString(w/2 + 90, h - 385, "Deeper & faster  |  API Key")

        # Author
        c.setFillColor(TEXT_MUTED)
        c.setFont(FONT, 11)
        c.drawCentredString(w/2, 80, "Scott Converse")
        c.setFont(FONT, 9)
        c.drawCentredString(w/2, 60, "March 2026")


# ── Table Helpers ───────────────────────────────────────────────────────

def make_table(headers, rows, col_widths=None):
    """Create a styled table."""
    data = [headers] + rows
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), DARK_HEADER),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), FONT),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("LEADING", (0, 0), (-1, -1), 13),
        ("BACKGROUND", (0, 1), (-1, -1), HexColor("#ffffff")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [HexColor("#ffffff"), HexColor("#f8f9fa")]),
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#dee2e6")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


# ── Build PDF ───────────────────────────────────────────────────────────

def build_pdf(output_path: str):
    w, h = letter
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.75*inch, bottomMargin=0.75*inch,
    )
    story = []
    usable_w = w - 1.5*inch

    # ── Cover Page ──
    story.append(CoverPage(usable_w, h))
    story.append(PageBreak())

    # ── Table of Contents ──
    story.append(Paragraph("Table of Contents", style_h1))
    toc_items = [
        "1. Two Ways to Run",
        "2. Pipeline Architecture",
        "3. Agent Roles",
        "4. Local AI Setup",
        "5. Cloud AI Setup",
        "6. Cost Comparison",
        "7. CLI Reference",
        "8. Safety & Recovery",
    ]
    for item in toc_items:
        story.append(Paragraph(item, style_body))
    story.append(PageBreak())

    # ── 1. Two Ways to Run ──
    story.append(Paragraph("1. Two Ways to Run", style_h1))
    story.append(Paragraph(
        "ProductTeam offers two paths to run the pipeline. Just type <b>productteam</b> "
        "(no arguments) and the interactive wizard walks you through setup.",
        style_body))
    story.append(Spacer(1, 12))

    # Dual path diagram
    story.append(build_dual_path_diagram())
    story.append(Spacer(1, 16))

    # Comparison table
    story.append(Paragraph("Comparison", style_h3))
    story.append(make_table(
        ["", "Local AI (Ollama)", "Cloud AI"],
        [
            ["Cost", "Free", "Standard API costs"],
            ["Speed", "~20 min/step", "Faster with cloud models"],
            ["Setup", "Install Ollama + pull model", "Paste API key"],
            ["Recommended model", "gpt-oss:20b (13 GB)", "Claude Sonnet / GPT-4o"],
            ["Internet required", "No (after model download)", "Yes"],
            ["Privacy", "Everything stays on your machine", "Prompts sent to provider API"],
        ],
        col_widths=[usable_w*0.22, usable_w*0.39, usable_w*0.39],
    ))
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "<b>Note:</b> Local models are free but slower. Each pipeline step takes ~20 minutes "
        "on a 20B parameter model running on consumer hardware with 32K context, so a full "
        "project takes hours. Cloud APIs are significantly faster.",
        style_warning))
    story.append(PageBreak())

    # ── 2. Pipeline Architecture ──
    story.append(Paragraph("2. Pipeline Architecture", style_h1))
    story.append(Paragraph(
        "The pipeline transforms a product concept into working code through seven "
        "specialized agents. Three human approval gates let you confirm intent, scope, "
        "and readiness. The builder never grades its own work -- a separate, skeptical "
        "evaluator does.",
        style_body))
    story.append(Spacer(1, 12))

    # Pipeline diagram
    story.append(build_pipeline_diagram())
    story.append(Spacer(1, 16))

    story.append(Paragraph(
        "<b>Thinker stages</b> (PRD Writer, Design Evaluator) take context in and produce "
        "a text artifact out. One LLM call. No filesystem access.",
        style_body))
    story.append(Paragraph(
        "<b>Doer stages</b> (Planner, Builder, Evaluator, Doc Writer) use an agentic "
        "tool-use loop with exactly four tools: <font face='Courier' size='9'>read_file</font>, "
        "<font face='Courier' size='9'>write_file</font>, "
        "<font face='Courier' size='9'>run_bash</font>, "
        "<font face='Courier' size='9'>list_dir</font>.",
        style_body))
    story.append(Paragraph(
        "The <b>Build-Evaluate loop</b> runs up to 3 iterations. If the Evaluator grades "
        "NEEDS_WORK, findings route back to the Builder automatically. After loop 3, "
        "the plan is wrong -- not the implementation.",
        style_body))
    story.append(PageBreak())

    # ── 3. Agent Roles ──
    story.append(Paragraph("3. Agent Roles", style_h1))
    story.append(Paragraph(
        "Each agent is a standalone markdown skill file. Readable, editable, replaceable. "
        "Use the full pipeline or drop in only the skills you need.",
        style_body))
    story.append(Spacer(1, 8))
    story.append(make_table(
        ["Agent", "Role", "Description"],
        [
            ["prd-writer", "Product Manager",
             "Converts concept to structured PRD with requirements, constraints, and success criteria."],
            ["planner", "Tech Lead",
             "Decomposes PRD into sprint contracts with testable acceptance criteria. Writes sprint YAML."],
            ["builder", "Engineer",
             "Implements sprint contracts with production-quality code and tests. Declares 'ready for review.'"],
            ["ui-builder", "Frontend Engineer",
             "Specialized builder for visual work. Landing pages, dashboards, web UIs."],
            ["evaluator", "QA Engineer",
             "Skeptical by default. Reads source, runs tests, verifies acceptance criteria. PASS / NEEDS_WORK / FAIL."],
            ["evaluator-design", "Design Reviewer",
             "Grades visual artifacts on Coherence, Originality, Craft, Functionality. 1-5 scale, 4.0+ to pass."],
            ["doc-writer", "Technical Writer",
             "Reads every source file. Produces README, changelog with real data only. Never fabricates."],
            ["orchestrator", "Project Manager",
             "Routes work between agents, manages loops (max 3), handles approval gates."],
        ],
        col_widths=[usable_w*0.16, usable_w*0.16, usable_w*0.68],
    ))
    story.append(PageBreak())

    # ── 4. Local AI Setup ──
    story.append(Paragraph("4. Local AI Setup", style_h1))
    story.append(Paragraph(
        "ProductTeam runs entirely free using Ollama, a local AI runtime. "
        "No API key, no cloud dependency, no per-token costs.",
        style_body))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Installation", style_h2))
    story.append(Paragraph("1. Download Ollama from <b>https://ollama.com/download</b>", style_body))
    story.append(Paragraph("2. Run the installer", style_body))
    story.append(Paragraph("3. Pull the recommended model:", style_body))
    story.append(Paragraph("<font face='Courier' size='9'>ollama pull gpt-oss:20b</font>", style_code))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Recommended Models", style_h2))
    story.append(make_table(
        ["Model", "Size", "Role", "Notes"],
        [
            ["gpt-oss:20b", "13 GB", "Primary", "Best tool-calling reliability and speed. OpenAI open-weight."],
            ["devstral:24b", "14 GB", "Backup", "Mistral coding agent. Strong code generation."],
        ],
        col_widths=[usable_w*0.2, usable_w*0.12, usable_w*0.13, usable_w*0.55],
    ))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Preflight Check", style_h2))
    story.append(Paragraph(
        "Before committing to a long pipeline run, verify your model works:",
        style_body))
    story.append(Paragraph("<font face='Courier' size='9'>productteam preflight</font>", style_code))
    story.append(Paragraph(
        "Preflight runs three quick tests: basic response, tool calling, and multi-turn "
        "tool use. Takes about 30-60 seconds. If all three pass, the model is pipeline-ready.",
        style_body))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Auto-Tuning", style_h2))
    story.append(Paragraph(
        "When you choose Local AI, ProductTeam automatically:", style_body))
    story.append(Paragraph("- Sets stage timeouts to 60 minutes (vs 5-10 min for cloud)", style_body))
    story.append(Paragraph("- Disables design review (saves time)", style_body))
    story.append(Paragraph("- Sets all approval gates to auto-approve", style_body))
    story.append(Paragraph("- Recommends 32K context window in Ollama settings", style_body))
    story.append(PageBreak())

    # ── 5. Cloud AI Setup ──
    story.append(Paragraph("5. Cloud AI Setup", style_h1))
    story.append(Paragraph(
        "For deeper and faster pipeline runs, use a cloud API provider.",
        style_body))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Supported Providers", style_h2))
    story.append(make_table(
        ["Provider", "Default Model", "Cost", "Context Window"],
        [
            ["Anthropic", "Claude Sonnet 4", "Standard API costs", "200K tokens"],
            ["OpenAI", "GPT-4o", "Standard API costs", "128K tokens"],
            ["Google", "Gemini 2.0 Flash", "Standard API costs", "1M tokens"],
        ],
        col_widths=[usable_w*0.2, usable_w*0.25, usable_w*0.25, usable_w*0.3],
    ))
    story.append(Spacer(1, 12))

    story.append(Paragraph("API Key Handling", style_h2))
    story.append(Paragraph(
        "When you select Cloud AI, the wizard prompts for your API key. "
        "The key is stored locally in <font face='Courier' size='9'>~/.productteam/prefs.json</font>. "
        "It never leaves your machine and is never sent to ProductTeam or any third party. "
        "Only the LLM provider receives API calls.",
        style_body))
    story.append(Paragraph(
        "If your API key is already set as an environment variable "
        "(e.g. <font face='Courier' size='9'>ANTHROPIC_API_KEY</font>), the wizard detects "
        "it automatically and asks if you want to use it.",
        style_body))
    story.append(PageBreak())

    # ── 6. Cost Comparison ──
    story.append(Paragraph("6. Cost Comparison", style_h1))
    story.append(Paragraph(
        "Estimated costs for a typical small project (2-3 sprints, CLI tool complexity):",
        style_body))
    story.append(Spacer(1, 8))
    story.append(make_table(
        ["Path", "Model", "Cost", "Notes"],
        [
            ["Local AI", "gpt-oss:20b (Ollama)", "Free", "Runs on your hardware. ~20 min/step."],
            ["Cloud (cheap)", "Claude Haiku", "Standard API costs", "Best value for simple projects."],
            ["Cloud (balanced)", "GPT-4o", "Standard API costs", "Good balance of cost and quality."],
            ["Cloud (powerful)", "Claude Sonnet", "Standard API costs", "Best output quality."],
        ],
        col_widths=[usable_w*0.14, usable_w*0.23, usable_w*0.22, usable_w*0.41],
    ))
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Costs scale with concept complexity (more features = more sprints = more tokens), "
        "quality level (strict costs 3-5x more than standard), and model choice.",
        style_body))
    story.append(Paragraph(
        "The <b>cost circuit breaker</b> (default $2.00) kills the pipeline if cumulative cost "
        "exceeds the limit, saving all work to disk. Set with "
        "<font face='Courier' size='9'>--budget</font> or in "
        "<font face='Courier' size='9'>productteam.toml</font>.",
        style_body))
    story.append(PageBreak())

    # ── 7. CLI Reference ──
    story.append(Paragraph("7. CLI Reference", style_h1))
    story.append(make_table(
        ["Command", "Description"],
        [
            ["productteam", "Interactive wizard. Concept input, provider selection, auto-setup."],
            ["productteam preflight", "Test Ollama model capability (basic, tools, multi-turn)."],
            ["productteam init", "Initialize a project directory."],
            ["productteam run \"concept\"", "Run the full pipeline with a concept."],
            ["productteam run", "Resume from current state."],
            ["productteam run --auto-approve", "Headless / CI mode."],
            ["productteam run --budget 1.50", "Set cost limit (default $2.00)."],
            ["productteam run --step prd", "Run only a specific stage."],
            ["productteam recover", "Reset stuck stages and re-run."],
            ["productteam status", "Show pipeline status."],
            ["productteam doctor", "Check environment and config."],
            ["productteam config set KEY VALUE", "Set configuration value."],
            ["productteam test", "Run the test suite."],
            ["productteam test --live", "Run live integration tests."],
            ["productteam forge \"idea\"", "Submit an idea to the Forge queue."],
            ["productteam forge --listen --dashboard", "Start the Forge daemon + dashboard."],
            ["productteam forge status [JOB-ID]", "Check job status."],
        ],
        col_widths=[usable_w*0.45, usable_w*0.55],
    ))
    story.append(PageBreak())

    # ── 8. Safety & Recovery ──
    story.append(Paragraph("8. Safety & Recovery", style_h1))
    story.append(Paragraph(
        "ProductTeam runs LLM-generated shell commands on your machine. "
        "That is inherently risky. Here is how it is mitigated:",
        style_body))
    story.append(Spacer(1, 8))

    safety_items = [
        ("Path validation", "All file operations are locked to the project directory. No ../ traversal, no absolute paths."),
        ("Environment isolation", "Builder subprocesses receive a minimal allowlisted environment (PATH, HOME, TMP, locale). API keys, tokens, and credentials from the parent process are not forwarded."),
        ("Command filtering", "Known credential-adjacent paths (.ssh/, .aws/, /proc/environ) are blocked in run_bash."),
        ("Loop detection", "If the LLM calls the same tool with identical arguments three consecutive times, the loop breaks automatically."),
        ("Tool call limits", "Maximum 75 tool calls per doer run (configurable). After that, the stage stops and escalates."),
        ("State persistence", "state.json is written on every state change. Crash at any point, resume with productteam run."),
        ("Timeouts", "Every stage has a configurable timeout. Default: 300s for thinkers, 600s for doers. Auto-tuned to 3600s for Ollama."),
        ("Budget circuit breaker", "The --budget flag sets a hard dollar limit (default $2.00). Kills the pipeline mid-loop and saves all work to disk when exceeded."),
    ]
    for title, desc in safety_items:
        story.append(Paragraph(f"<b>{title}</b>", style_h3))
        story.append(Paragraph(desc, style_body))

    # Build
    doc.build(story)
    print(f"PDF generated: {output_path}")


if __name__ == "__main__":
    out = str(Path(__file__).parent / "ProductTeam-Architecture.pdf")
    build_pdf(out)
