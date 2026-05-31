"""
PDF Export Engine — Phase 6B.

Renders question papers, answer keys, and rubrics as print-ready PDFs
using WeasyPrint (HTML→PDF). Falls back to basic HTML if WeasyPrint
is not installed.

Architecture:
  - Generates styled HTML using institutional template config
  - Converts to PDF via WeasyPrint
  - Supports custom logos, headers, and metadata fields

Performance target: <3s for a complete paper PDF.
"""

from __future__ import annotations

import base64
import io
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.academic.pdf_export")


# ---------------------------------------------------------------------------
# HTML Templates
# ---------------------------------------------------------------------------

_CSS = """
@page {
    size: A4;
    margin: 18mm 15mm 18mm 15mm;
}
body {
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-size: 11px;
    line-height: 1.45;
    color: #000;
    margin: 0;
    padding: 0;
}
.header {
    display: flex;
    align-items: center;
    gap: 12px;
    border-bottom: 2px solid #000;
    padding-bottom: 10px;
    margin-bottom: 8px;
}
.header-logo {
    width: 56px;
    height: 56px;
    object-fit: contain;
}
.header-center {
    flex: 1;
    border-right: 1px solid #000;
    padding-right: 12px;
}
.header-center h1 {
    font-size: 13px;
    margin: 0;
    font-weight: 700;
}
.header-center p {
    font-size: 10px;
    margin: 2px 0 0 0;
}
.header-right {
    min-width: 200px;
    font-size: 10px;
    line-height: 1.5;
}
.header-right .accent {
    color: #c00;
    font-weight: 600;
}
.usn-row {
    text-align: right;
    margin: 8px 0;
    font-size: 11px;
}
.usn-box {
    display: inline-block;
    width: 18px;
    height: 20px;
    border: 1px solid #000;
    margin-left: 2px;
    vertical-align: middle;
}
.dept-title {
    text-align: center;
    font-size: 14px;
    font-weight: 700;
    margin: 8px 0;
}
.exam-banner {
    border: 1px solid #000;
    text-align: center;
    font-size: 13px;
    font-weight: 700;
    padding: 5px 10px;
    margin: 8px 0;
}
table.meta {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
    margin: 8px 0;
}
table.meta td {
    border: 1px solid #000;
    padding: 4px 8px;
}
table.meta .label {
    font-weight: 700;
    width: 18%;
}
.instructions {
    text-align: center;
    font-style: italic;
    font-size: 11px;
    margin: 10px 0;
}
.note {
    font-weight: 700;
    font-size: 11px;
    margin: 6px 0;
}
table.questions {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
    margin-top: 6px;
    table-layout: fixed;
}
table.questions th,
table.questions td {
    border: 1px solid #000;
    padding: 4px 6px;
    vertical-align: top;
    word-wrap: break-word;
}
table.questions th {
    text-align: center;
    font-weight: 700;
    background: #f8f8f8;
}
table.questions col.qno { width: 8%; }
table.questions col.text { width: 66%; }
table.questions col.marks { width: 10%; }
table.questions col.co { width: 8%; }
table.questions col.rbtl { width: 8%; }
.module-row td {
    text-align: center;
    font-weight: 700;
    background: #f0f0f0;
}
.or-row td {
    text-align: center;
    font-weight: 600;
}
table.co-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
    margin-top: 6px;
}
table.co-table td {
    border: 1px solid #000;
    padding: 3px 6px;
}
table.co-table .co-label {
    font-weight: 700;
    width: 50px;
}
.section-title {
    font-weight: 700;
    text-align: center;
    font-size: 11px;
    margin: 20px 0 4px 0;
}
table.coverage {
    width: 100%;
    border-collapse: collapse;
    font-size: 11px;
}
table.coverage td {
    border: 1px solid #000;
    padding: 3px 6px;
    text-align: center;
}
table.coverage .label {
    font-weight: 700;
}
/* Answer key specific */
.answer-section {
    page-break-before: always;
}
.answer-block {
    margin: 12px 0;
    padding: 8px;
    border: 1px solid #ddd;
    border-radius: 4px;
}
.answer-block h3 {
    font-size: 12px;
    margin: 0 0 6px 0;
    border-bottom: 1px solid #eee;
    padding-bottom: 4px;
}
.step {
    margin: 4px 0;
    padding-left: 20px;
}
.step-marks {
    color: #666;
    font-size: 10px;
}
"""


def _img_to_data_uri(path: str) -> str:
    """Convert an image file path to a data URI for embedding in HTML."""
    try:
        p = Path(path)
        if not p.exists():
            return ""
        data = p.read_bytes()
        suffix = p.suffix.lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "svg": "image/svg+xml"}.get(suffix.lstrip("."), "image/png")
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# HTML Rendering
# ---------------------------------------------------------------------------

def render_paper_html(
    questions: list[dict[str, Any]],
    paper_meta: dict[str, Any],
    template_config: dict[str, Any] | None = None,
    co_descriptions: dict[str, str] | None = None,
    co_percentages: dict[str, float] | None = None,
    module_percentages: dict[str, float] | None = None,
) -> str:
    """
    Render a question paper as a complete HTML document.

    Args:
        questions: List of question dicts (text, marks, course_outcome, bloom_level, section_label, module_number).
        paper_meta: Dict with exam_type, department, subject_name, subject_code, semester, max_marks, batch, duration, date, teaching_dept, instructions.
        template_config: Optional institutional template config.
        co_descriptions: Optional CO description mapping.
        co_percentages: Optional CO coverage percentages.
        module_percentages: Optional module coverage percentages.
    """
    tc = template_config or {}
    meta = paper_meta

    # Institution info
    inst_name = tc.get("institution_name", meta.get("institution_name", "Dayananda Sagar Academy of Technology & Management"))
    inst_sub = tc.get("affiliation_text", tc.get("institution_subtitle", meta.get("institution_subtitle", "(Autonomous Institute under VTU)")))

    # Logos
    left_logo = tc.get("left_logo_path", tc.get("left_seal_path", ""))
    right_logo = tc.get("right_logo_path", tc.get("right_seal_path", ""))
    left_uri = _img_to_data_uri(left_logo) if left_logo else ""
    right_uri = _img_to_data_uri(right_logo) if right_logo else ""

    # Build question rows HTML
    q_rows = []
    max_marks = int(meta.get("max_marks", 50))
    prev_module = None

    for i, q in enumerate(questions):
        module = q.get("module_number")
        label = q.get("section_label", f"Q{i+1}")

        # Module header for 100-mark papers
        if max_marks > 50 and module and module != prev_module:
            q_rows.append(f'<tr class="module-row"><td colspan="5">Module - {module}</td></tr>')
            prev_module = module

        # OR separator (for alternate questions)
        qnum = i + 1
        if max_marks > 50 and qnum % 2 == 0 and q.get("subpart", "a") == "a":
            q_rows.append('<tr class="or-row"><td colspan="5">OR</td></tr>')

        text = q.get("text", "")
        marks = q.get("marks") or q.get("custom_marks", "")
        co = q.get("course_outcome", "")
        bloom = q.get("bloom_level", "")

        # Parse diagram placeholder if present
        import re
        match = re.search(r'\[DIAGRAM:\s*(.*?)\]', text)
        img_html = ""
        if match:
            img_path = match.group(1).strip()
            text = text.replace(match.group(0), "").strip()
            
            resolved_path = img_path
            if not os.path.isabs(resolved_path):
                resolved_path = os.path.abspath(resolved_path)
            
            data_uri = _img_to_data_uri(resolved_path)
            if data_uri:
                img_html = f'<br/><img class="question-diagram" src="{data_uri}" style="max-width: 400px; max-height: 250px; display: block; margin-top: 8px; border: 1px solid #ddd; padding: 4px;" />'

        q_rows.append(f"""<tr>
            <td style="text-align:center">{label}</td>
            <td>{text}{img_html}</td>
            <td style="text-align:center">{marks}</td>
            <td style="text-align:center">{co}</td>
            <td style="text-align:center">{bloom}</td>
        </tr>""")

    q_table_html = "\n".join(q_rows)

    # CO descriptions table
    co_desc_html = ""
    if co_descriptions:
        co_rows = "\n".join(
            f'<tr><td class="co-label">{co}</td><td>{desc}</td></tr>'
            for co, desc in sorted(co_descriptions.items())
        )
        co_desc_html = f"""
        <p class="section-title">Course Outcomes (COs): At the end of the Course, the Student will be able to:</p>
        <table class="co-table"><tbody>{co_rows}</tbody></table>
        """

    # Coverage tables
    coverage_html = ""
    if co_percentages:
        co_headers = "".join(f'<td class="label">{co}</td>' for co in sorted(co_percentages.keys()))
        co_values = "".join(f'<td>{v}</td>' for v in [co_percentages[k] for k in sorted(co_percentages.keys())])
        coverage_html += f"""
        <p class="section-title" style="margin-top:24px">Percentage of CO Coverage</p>
        <table class="coverage"><tbody>
            <tr><td class="label">Course Outcomes</td>{co_headers}</tr>
            <tr><td class="label">Percentage</td>{co_values}</tr>
        </tbody></table>
        """

    if module_percentages:
        m_headers = "".join(f'<td class="label">{m}</td>' for m in sorted(module_percentages.keys()))
        m_values = "".join(f'<td>{v}</td>' for v in [module_percentages[k] for k in sorted(module_percentages.keys())])
        coverage_html += f"""
        <p class="section-title" style="margin-top:12px">Percentage of Syllabus Coverage</p>
        <table class="coverage"><tbody>
            <tr><td class="label">Modules Covered</td>{m_headers}</tr>
            <tr><td class="label">Percentage</td>{m_values}</tr>
        </tbody></table>
        """

    # USN boxes
    usn_boxes = "".join('<span class="usn-box"></span>' for _ in range(10))

    # Template note
    template_note = meta.get("template_note", "")
    if not template_note and max_marks >= 100:
        template_note = "Answer any FIVE full questions, choosing at least ONE question from each MODULE"
    note_html = f'<p class="note">Note: {template_note}</p>' if template_note else ""

    # Accreditation info
    accreditation_lines = tc.get("accreditation_lines") or []
    if accreditation_lines:
        formatted_lines = []
        for line in accreditation_lines:
            text = str(line.get("text", ""))
            for part in line.get("highlighted_parts", []) or []:
                text = text.replace(part, f'<span class="accent">{part}</span>')
            formatted_lines.append(f"<p>{text}</p>")
        accreditation_html = "".join(formatted_lines)
    else:
        accreditation_html = tc.get("accreditation_html", """
            <p>Affiliated to <span class="accent">VTU</span></p>
            <p>Approved by <span class="accent">AICTE</span></p>
            <p>Accredited by <span class="accent">NAAC</span> with <span class="accent">A+</span> Grade</p>
            <p>6 Programs Accredited by <span class="accent">NBA</span></p>
        """)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><style>{_CSS}</style></head>
<body>
    <div class="header">
        {"<img class='header-logo' src='" + left_uri + "'/>" if left_uri else ""}
        <div class="header-center">
            <h1>{inst_name}</h1>
            <p>{inst_sub}</p>
        </div>
        <div class="header-right">{accreditation_html}</div>
        {"<img class='header-logo' src='" + right_uri + "'/>" if right_uri else ""}
    </div>

    <div class="usn-row">USN: {usn_boxes}</div>

    <p class="dept-title">Department of {meta.get("department", "")}</p>
    <div class="exam-banner">{meta.get("exam_type", "")}</div>

    <table class="meta"><tbody>
        <tr>
            <td class="label">Subject:</td><td>{meta.get("subject_name", "")}</td>
            <td class="label">Subject Code:</td><td>{meta.get("subject_code", "")}</td>
        </tr>
        <tr>
            <td class="label">Semester:</td><td>{meta.get("semester", "")}</td>
            <td class="label">Max. Marks:</td><td>{max_marks}</td>
        </tr>
        <tr>
            <td class="label">Batch:</td><td>{meta.get("batch", "")}</td>
            <td class="label">Duration:</td><td>{meta.get("duration", "")}</td>
        </tr>
        <tr>
            <td class="label">Date:</td><td>{meta.get("date", "To be announced")}</td>
            <td class="label">Teaching Dept:</td><td>{meta.get("teaching_dept", "")}</td>
        </tr>
        <tr>
            <td class="label">RBT Levels:</td>
            <td colspan="3">L1-Remember, L2-Understand, L3-Apply, L4-Analyze, L5-Evaluate, L6-Create</td>
        </tr>
    </tbody></table>

    <p class="instructions">{meta.get("instructions", "Answer the following questions")}</p>
    {note_html}

    <table class="questions">
        <colgroup>
            <col class="qno"><col class="text"><col class="marks"><col class="co"><col class="rbtl">
        </colgroup>
        <thead><tr>
            <th>Q No</th><th>Questions</th><th>Marks</th><th>COs</th><th>RBTL</th>
        </tr></thead>
        <tbody>{q_table_html}</tbody>
    </table>

    {co_desc_html}
    {coverage_html}
</body>
</html>"""

    return html


def render_answer_key_html(
    answer_key: dict[str, Any],
    paper_meta: dict[str, Any],
) -> str:
    """Render an answer key as HTML."""
    answers_html = []
    for ans in answer_key.get("answers", []):
        steps_html = "\n".join(
            f'<div class="step">'
            f'<strong>Step {s["step_number"]}:</strong> {s["content"]} '
            f'<span class="step-marks">[{s["marks"]} mark{"s" if s["marks"] != 1 else ""}]</span>'
            f'</div>'
            for s in ans.get("steps", [])
        )
        kp_html = ""
        if ans.get("key_points"):
            kp_items = "".join(f"<li>{kp}</li>" for kp in ans["key_points"])
            kp_html = f'<p style="margin-top:6px;font-size:10px;color:#666"><strong>Key Points:</strong></p><ul style="font-size:10px;color:#666">{kp_items}</ul>'

        answers_html.append(f"""
        <div class="answer-block">
            <h3>Q{ans["question_index"]}. {ans["question_text"][:100]}{"..." if len(ans.get("question_text","")) > 100 else ""} [{ans["marks"]} marks, {ans["bloom_level"]}]</h3>
            {steps_html}
            {kp_html}
        </div>
        """)

    body = "\n".join(answers_html)

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><style>{_CSS}</style></head>
<body>
    <h2 style="text-align:center;font-size:16px;margin-bottom:4px">Answer Key / Model Answers</h2>
    <p style="text-align:center;font-size:12px;color:#666;margin-bottom:16px">{paper_meta.get("subject_name", "")} — {paper_meta.get("exam_type", "")}</p>
    <p style="font-size:11px;margin-bottom:12px"><strong>General Instructions:</strong> {answer_key.get("general_instructions", "")}</p>
    {body}
</body>
</html>"""


# ---------------------------------------------------------------------------
# PDF Generation
# ---------------------------------------------------------------------------

def html_to_pdf(html: str) -> bytes:
    """Convert HTML string to PDF bytes using WeasyPrint."""
    try:
        from weasyprint import HTML
        doc = HTML(string=html)
        return doc.write_pdf()
    except ImportError:
        logger.warning("WeasyPrint not installed. Falling back to raw HTML.")
        return html.encode("utf-8")
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return html.encode("utf-8")


def export_paper_pdf(
    questions: list[dict[str, Any]],
    paper_meta: dict[str, Any],
    template_config: dict[str, Any] | None = None,
    co_descriptions: dict[str, str] | None = None,
    co_percentages: dict[str, float] | None = None,
    module_percentages: dict[str, float] | None = None,
) -> bytes:
    """Generate a complete paper PDF."""
    html = render_paper_html(
        questions, paper_meta, template_config,
        co_descriptions, co_percentages, module_percentages,
    )
    return html_to_pdf(html)


def export_answer_key_pdf(
    answer_key: dict[str, Any],
    paper_meta: dict[str, Any],
) -> bytes:
    """Generate an answer key PDF."""
    html = render_answer_key_html(answer_key, paper_meta)
    return html_to_pdf(html)
