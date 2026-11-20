"""Turns a session plan (the JSON from the backend) into a PDF with fpdf2."""

from fpdf import FPDF
from fpdf.enums import XPos, YPos

PHASE_LABELS = {
    "warm_up": "Warm-up",
    "main": "Main part",
    "game": "Game",
    "cool_down": "Cool-down",
}

GREEN = (22, 101, 52)
LIGHT = (240, 247, 242)
GREY = (90, 90, 90)

# The built-in PDF fonts only support basic Latin characters.
REPLACEMENTS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", "•": "-",
    "→": "->", " ": " ", "≤": "<=", "≥": ">=",
}


def clean(text) -> str:
    text = str(text or "")
    for bad, good in REPLACEMENTS.items():
        text = text.replace(bad, good)
    return text.encode("latin-1", "replace").decode("latin-1")


def pretty(value: str) -> str:
    return value.replace("_", " ")


class SessionPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(*GREY)
            self.cell(0, 6, "Football Training Session Planner", align="R",
                      new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*GREY)
        self.cell(0, 6, f"Page {self.page_no()}", align="C")

    # ---- small helpers ----
    def line_text(self, text, size=10, style="", color=(0, 0, 0), h=5.5):
        self.set_font("Helvetica", style, size)
        self.set_text_color(*color)
        self.multi_cell(0, h, clean(text), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def label_value(self, label, value):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(0, 0, 0)
        self.cell(32, 5.5, clean(label))
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 5.5, clean(value), new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    def bullets(self, title, items):
        if not items:
            return
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*GREEN)
        self.cell(0, 6, clean(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(0, 0, 0)
        for item in items:
            self.set_x(self.l_margin + 3)
            self.multi_cell(0, 5.2, clean(f"- {item}"), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)


def build_pdf(plan: dict) -> bytes:
    pdf = SessionPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()

    # ---- Title block ----
    pdf.line_text(plan["title"], size=18, style="B", color=GREEN, h=8)
    who = (f"{plan['players']} players" if plan["mode"] == "team" else "Individual session")
    meta = (f"{pretty(plan['age_group']).title()}  |  {who}  |  {plan['session_length']} min  |  "
            f"Focus: {', '.join(pretty(f) for f in plan['focus'])}")
    pdf.line_text(meta, size=10, color=GREY)
    pdf.ln(2)
    if plan.get("summary"):
        pdf.line_text(plan["summary"], size=10)
        pdf.ln(2)

    # ---- Overview table ----
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(*GREEN)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(30, 7, "Phase", fill=True)
    pdf.cell(20, 7, "Minutes", fill=True, align="C")
    pdf.cell(0, 7, "Drill", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(0, 0, 0)
    for i, d in enumerate(plan["drills"]):
        pdf.set_fill_color(*(LIGHT if i % 2 == 0 else (255, 255, 255)))
        pdf.cell(30, 7, PHASE_LABELS.get(d["phase"], d["phase"]), fill=True)
        pdf.cell(20, 7, str(d["minutes"]), fill=True, align="C")
        pdf.cell(0, 7, clean(d["name"]), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(30, 7, "Total")
    pdf.cell(20, 7, str(plan["total_minutes"]), align="C", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    # ---- Drill details ----
    for n, d in enumerate(plan["drills"], start=1):
        if pdf.get_y() > 230:
            pdf.add_page()
        pdf.set_fill_color(*LIGHT)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*GREEN)
        heading = f"{n}. {PHASE_LABELS.get(d['phase'], d['phase'])}: {d['name']}  ({d['minutes']} min)"
        pdf.multi_cell(0, 8, clean(heading), fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.ln(1)

        pdf.label_value("Area:", d["area"])
        pdf.label_value("Players:", d["players_setup"])
        pdf.label_value("Equipment:", ", ".join(pretty(e) for e in d["equipment"]) or "None")
        pdf.label_value("Timing:", d["work_rest"])
        pdf.label_value("Trains:", ", ".join(d["trains"]))
        pdf.ln(1)

        pdf.line_text("How it works", size=10, style="B", color=GREEN)
        pdf.line_text(d["description"])
        if d.get("adaptation_note"):
            pdf.line_text(f"For this group: {d['adaptation_note']}", style="I", color=GREY)
        pdf.ln(1)

        pdf.bullets("Coaching points", d["coaching_points"])
        pdf.bullets("Progressions", d["progressions"])
        pdf.bullets("Regressions", d["regressions"])

        source = f"Inspired by: {d['inspired_by']}"
        if d.get("reference"):
            source += f" (Source: {d['reference']})"
        pdf.line_text(source, size=9, style="I", color=GREY, h=5)
        pdf.ln(4)

    if plan.get("generated_by") == "fallback":
        pdf.line_text("This plan was assembled from the drill library without AI.", size=8, color=GREY)

    return bytes(pdf.output())
