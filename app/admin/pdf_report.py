"""Renders a session-analysis report dict (app/agents/report.py) to PDF bytes.

fpdf2 with the built-in Helvetica font: core fonts are latin-1 only, so all
text is sanitized with errors='replace' — a stray emoji becomes '?' instead of
crashing the download.
"""
from fpdf import FPDF

from app.profile_utils import gender_label

_MARGIN = 16


def _txt(value):
    return str(value if value is not None else "-").encode(
        "latin-1", "replace").decode("latin-1")


class _ReportPDF(FPDF):
    def header(self):
        self.set_font("helvetica", "B", 15)
        self.set_text_color(88, 66, 155)  # the app's purple
        self.cell(0, 9, "MindMate - Session Analysis Report",
                  new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(88, 66, 155)
        self.line(_MARGIN, self.get_y() + 1, self.w - _MARGIN, self.get_y() + 1)
        self.ln(5)

    def footer(self):
        self.set_y(-14)
        self.set_font("helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, f"Confidential - staff use only  |  page {self.page_no()}",
                  align="C")

    def kv(self, label, value):
        self.set_font("helvetica", "B", 10)
        self.set_text_color(60, 60, 60)
        self.cell(38, 6, _txt(label))
        self.set_font("helvetica", "", 10)
        self.set_text_color(20, 20, 20)
        self.multi_cell(0, 6, _txt(value), new_x="LMARGIN", new_y="NEXT")

    def section(self, title):
        self.ln(3)
        self.set_font("helvetica", "B", 12)
        self.set_text_color(88, 66, 155)
        self.cell(0, 8, _txt(title), new_x="LMARGIN", new_y="NEXT")

    def body(self, text):
        self.set_font("helvetica", "", 10)
        self.set_text_color(20, 20, 20)
        self.multi_cell(0, 5.5, _txt(text), new_x="LMARGIN", new_y="NEXT")


def render_report_pdf(report):
    """Report dict -> PDF bytes."""
    pdf = _ReportPDF()
    pdf.set_margins(_MARGIN, _MARGIN)
    pdf.set_auto_page_break(True, margin=18)
    pdf.add_page()

    user = report["user"]
    pdf.kv("Name", user.get("name"))
    pdf.kv("Email", user.get("email"))
    # Age is derived from date_of_birth at read time, so a stored report never
    # carries a stale number (see app/profile_utils.py).
    age, gender = user.get("age"), user.get("gender")
    pdf.kv("Age / gender", " / ".join([
        str(age) if age is not None else "-",
        # not gender_label(None): its em-dash placeholder isn't latin-1.
        gender_label(gender) if gender else "-",
    ]))
    pdf.kv("Phone", user.get("phone"))
    pdf.kv("Joined", (user.get("joinedAt") or "")[:10] or None)
    pdf.kv("Generated", (report.get("generatedAt") or "")[:16].replace("T", " ")
           + " UTC")
    pdf.kv("Coverage", f"{report.get('sessionCount', 0)} most recent session(s)")

    pdf.section("Analysis")
    pdf.body(report.get("analysis") or "(no analysis)")

    pdf.section("Sessions covered")
    for s in report.get("sessions", []):
        emotions = ", ".join(f"{k} x{v}" for k, v in (s.get("emotions") or {}).items())
        pdf.set_font("helvetica", "B", 10)
        pdf.set_text_color(20, 20, 20)
        pdf.multi_cell(0, 6, _txt(f"{s.get('title')}  ({(s.get('createdAt') or '')[:10]})"),
                       new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("helvetica", "", 9)
        pdf.set_text_color(80, 80, 80)
        pdf.multi_cell(0, 5,
                       _txt(f"{s.get('messageCount', 0)} messages | "
                            f"{s.get('escalations', 0)} escalation(s) | "
                            f"emotions: {emotions or 'none'}"),
                       new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    return bytes(pdf.output())
