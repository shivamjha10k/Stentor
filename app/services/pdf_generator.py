"""
PDF Generator — Produces formatted PDF reports for call documents.
Uses fpdf2 for lightweight PDF generation with no system dependencies.
"""

import io
import logging
from datetime import datetime

logger = logging.getLogger("rag.pdf")

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False
    logger.warning("fpdf2 not installed — PDF export will be unavailable. Install with: pip install fpdf2")


class CallDocumentPDF(FPDF if FPDF_AVAILABLE else object):
    """Custom PDF class with header/footer for call documents."""

    def __init__(self, call_id: str, generated_at: str):
        if not FPDF_AVAILABLE:
            raise RuntimeError("fpdf2 is required for PDF generation. Install with: pip install fpdf2")
        super().__init__()
        self._call_id = call_id
        self._generated_at = generated_at

    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(30, 58, 138)  # dark blue
        self.cell(0, 10, "Call Analysis Report", ln=True, align="C")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, f"Call ID: {self._call_id}  |  Generated: {self._generated_at}", ln=True, align="C")
        self.line(10, self.get_y() + 2, 200, self.get_y() + 2)
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Stentor RAG Pipeline  |  Page {self.page_no()}/{{nb}}", align="C")

    def _safe(self, text: str) -> str:
        """Sanitize text to latin-1 safe characters."""
        return str(text).encode("latin-1", "replace").decode("latin-1")

    def section_title(self, title: str):
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(30, 58, 138)
        self.cell(0, 9, self._safe(title), ln=True)
        self.set_draw_color(30, 58, 138)
        self.line(10, self.get_y(), 80, self.get_y())
        self.ln(3)

    def body_text(self, text: str):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        # Sanitize non-latin characters
        safe_text = text.encode("latin-1", "replace").decode("latin-1")
        self.multi_cell(0, 5, safe_text)
        self.ln(2)

    def label_value(self, label: str, value: str):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(60, 60, 60)
        self.cell(50, 6, f"{label}:")
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        safe_val = str(value).encode("latin-1", "replace").decode("latin-1")
        self.multi_cell(0, 6, safe_val)
        self.ln(1)

    def bullet_list(self, items: list[str]):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        for item in items:
            safe_item = str(item).encode("latin-1", "replace").decode("latin-1")
            self.multi_cell(0, 5, f"  - {safe_item}")
        self.ln(2)

    def add_badge(self, text: str, color: tuple = (30, 58, 138)):
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(*color)
        self.set_text_color(255, 255, 255)
        w = self.get_string_width(f"  {text}  ") + 4
        self.cell(w, 7, f"  {text}  ", fill=True)
        self.set_text_color(40, 40, 40)
        self.cell(3)  # spacing


def _risk_color(assessment: str) -> tuple:
    """Return RGB color for risk level badge."""
    mapping = {
        "high_risk": (220, 38, 38),    # red
        "medium_risk": (234, 179, 8),   # amber
        "low_risk": (34, 197, 94),      # green
    }
    return mapping.get(assessment, (100, 100, 100))


def generate_call_document_pdf(
    call_id: str,
    document: dict,
    call_data: dict | None = None,
) -> bytes:
    """
    Generate a formatted PDF for a call document.

    Args:
        call_id:   The call identifier
        document:  The extracted call document dict
        call_data: Optional original call_analyses row for extra context

    Returns:
        PDF file content as bytes
    """
    if not FPDF_AVAILABLE:
        raise RuntimeError("fpdf2 is required for PDF generation. Install with: pip install fpdf2")

    generated_at = document.get("generated_at", datetime.utcnow().isoformat())
    if isinstance(generated_at, datetime):
        generated_at = generated_at.strftime("%Y-%m-%d %H:%M UTC")

    pdf = CallDocumentPDF(call_id, str(generated_at))
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    # --- Risk badge row ---
    if call_data:
        ra = call_data.get("risk_assessment", {})
        ro = call_data.get("rag_output", {})
        assessment = ro.get("grounded_assessment", "unknown")
        risk_score = ra.get("risk_score", "?")
        fraud = ra.get("fraud_likelihood", "?")

        pdf.add_badge(f"Risk: {risk_score}/100", _risk_color(assessment))
        pdf.add_badge(f"Fraud: {fraud}", _risk_color(assessment))
        pdf.add_badge(assessment.replace("_", " ").upper(), _risk_color(assessment))
        pdf.ln(10)

    # --- Section 1: Executive Summary ---
    pdf.section_title("1. Executive Summary")
    pdf.body_text(document.get("call_summary", "No summary available."))
    pdf.label_value("Purpose", document.get("call_purpose", "unknown"))
    pdf.label_value("Outcome", document.get("call_outcome", "unknown"))

    # --- Section 2: Financial Data ---
    fd = document.get("financial_data", {})
    pdf.section_title("2. Financial Data")

    amounts = fd.get("amounts_mentioned", [])
    if amounts:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(60, 6, "Amount", border=1)
        pdf.cell(30, 6, "Currency", border=1)
        pdf.cell(0, 6, "Context", border=1, ln=True)
        pdf.set_font("Helvetica", "", 10)
        for a in amounts:
            val = pdf._safe(str(a.get("value", "?")))
            cur = pdf._safe(a.get("currency", "INR"))
            ctx = pdf._safe(a.get("context", ""))[:60]
            pdf.cell(60, 6, val, border=1)
            pdf.cell(30, 6, cur, border=1)
            pdf.cell(0, 6, ctx, border=1, ln=True)
        pdf.ln(3)

    if fd.get("total_outstanding") is not None:
        pdf.label_value("Total Outstanding", f"{fd['total_outstanding']}")
    if fd.get("settlement_offered") is not None:
        pdf.label_value("Settlement Offered", f"{fd['settlement_offered']}")

    emi = fd.get("emi_details")
    if emi:
        pdf.label_value("EMI", f"{emi.get('amount', '?')} / {emi.get('frequency', '?')} ({emi.get('remaining', '?')} remaining)")

    products = fd.get("financial_products", [])
    if products:
        pdf.label_value("Products", ", ".join(products))

    acct_refs = fd.get("account_references", [])
    if acct_refs:
        pdf.label_value("Account Refs", ", ".join(acct_refs))

    pc = fd.get("payment_commitments", [])
    if pc:
        pdf.set_font("Helvetica", "B", 10)
        pdf.ln(2)
        pdf.cell(0, 6, "Payment Commitments:", ln=True)
        pdf.set_font("Helvetica", "", 10)
        for p in pc:
            due = p.get("due_date", "not specified")
            line = pdf._safe(f"  - {p.get('amount', '?')} ({p.get('type', '?')}) due: {due}")
            pdf.multi_cell(0, 5, line)
        pdf.ln(2)

    if not amounts and not pc and fd.get("total_outstanding") is None:
        pdf.body_text("No financial data extracted from this call.")

    # --- Section 3: Commitments & Promises ---
    commitments = document.get("commitments", [])
    pdf.section_title("3. Commitments & Promises")
    if commitments:
        for c in commitments:
            speaker = c.get("speaker", "?")
            text = c.get("commitment", "?")
            ctype = c.get("type", "?")
            conf = c.get("confidence", 0)
            cond = " (CONDITIONAL)" if c.get("conditional") else ""
            pdf.body_text(f"[{speaker}] {text} - {ctype} (confidence: {conf:.0%}){cond}")
            if c.get("condition"):
                pdf.set_font("Helvetica", "I", 9)
                pdf.set_text_color(80, 80, 80)
                pdf.multi_cell(0, 5, pdf._safe(f"  Condition: {c['condition']}"))
                pdf.ln(1)
    else:
        pdf.body_text("No commitments identified in this call.")

    # --- Section 4: Key Discussion Points ---
    points = document.get("key_discussion_points", [])
    pdf.section_title("4. Key Discussion Points")
    if points:
        pdf.bullet_list(points)
    else:
        pdf.body_text("No key discussion points extracted.")

    # --- Section 5: Entities ---
    ent = document.get("entities", {})
    pdf.section_title("5. Extracted Entities")
    has_entities = False
    for key, label in [("persons", "Persons"), ("organizations", "Organizations"),
                        ("dates", "Dates"), ("locations", "Locations"),
                        ("phone_numbers", "Phone Numbers"), ("reference_numbers", "Reference Numbers")]:
        items = ent.get(key, [])
        if items:
            pdf.label_value(label, ", ".join(str(i) for i in items))
            has_entities = True
    if not has_entities:
        pdf.body_text("No named entities extracted.")

    # --- Section 6: Compliance & Risk ---
    pdf.section_title("6. Compliance & Risk Notes")
    compliance = document.get("compliance_notes", [])
    if compliance:
        pdf.bullet_list(compliance)
    else:
        pdf.body_text("No compliance issues noted.")

    risk_flags = document.get("risk_flags", [])
    if risk_flags:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, "Risk Flags:", ln=True)
        pdf.bullet_list(risk_flags)

    # --- Section 7: Call Timeline ---
    timeline = document.get("call_timeline", [])
    pdf.section_title("7. Call Timeline")
    if timeline:
        for ev in timeline:
            ts = ev.get("timestamp_approx", "?")
            event = ev.get("event", "?")
            speaker = ev.get("speaker", "?")
            sig = ev.get("significance", "medium")
            sig_marker = {"high": "[!]", "medium": "[-]", "low": "[ ]"}.get(sig, "[-]")
            pdf.body_text(f"{sig_marker} [{ts}] [{speaker}] {event}")
    else:
        pdf.body_text("No timeline events extracted.")

    # --- Section 8: Action Items ---
    actions = document.get("action_items", [])
    pdf.section_title("8. Action Items")
    if actions:
        pdf.bullet_list(actions)
    else:
        pdf.body_text("No action items identified.")

    # --- Extraction metadata ---
    pdf.ln(5)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(150, 150, 150)
    model = document.get("extraction_model", "unknown")
    tokens = document.get("extraction_tokens", 0)
    version = document.get("extraction_version", "v1")
    pdf.cell(0, 5, f"Extracted by: {model} | Tokens: {tokens} | Version: {version}", ln=True)

    # Output as bytes
    return bytes(pdf.output())
