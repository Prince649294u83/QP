"""
CO/PO Attainment Calculator — Phase 5A.

Computes Course Outcome (CO) and Programme Outcome (PO) attainment levels
for a generated paper based on question mark allocations across Bloom levels.

Architecture:
  - Entirely rule-based, no LLM calls.
  - Takes a generated paper's question list and produces attainment metrics.
  - Supports configurable thresholds per institution.

Performance: <1ms per paper.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Defaults & Constants
# ---------------------------------------------------------------------------

# Standard PO ↔ CO mapping (rows = COs, cols = POs)
# Values: 3=High, 2=Medium, 1=Low, 0=No correlation
DEFAULT_CO_PO_MATRIX: dict[str, dict[str, int]] = {
    "CO1": {"PO1": 3, "PO2": 2, "PO3": 1, "PO4": 0, "PO5": 1, "PO6": 0, "PO7": 0, "PO8": 0, "PO9": 1, "PO10": 1, "PO11": 0, "PO12": 1},
    "CO2": {"PO1": 3, "PO2": 3, "PO3": 2, "PO4": 1, "PO5": 1, "PO6": 0, "PO7": 0, "PO8": 0, "PO9": 1, "PO10": 1, "PO11": 0, "PO12": 1},
    "CO3": {"PO1": 2, "PO2": 3, "PO3": 3, "PO4": 2, "PO5": 2, "PO6": 0, "PO7": 0, "PO8": 1, "PO9": 1, "PO10": 1, "PO11": 1, "PO12": 2},
    "CO4": {"PO1": 2, "PO2": 2, "PO3": 3, "PO4": 3, "PO5": 2, "PO6": 1, "PO7": 0, "PO8": 1, "PO9": 2, "PO10": 1, "PO11": 1, "PO12": 2},
    "CO5": {"PO1": 1, "PO2": 2, "PO3": 2, "PO4": 2, "PO5": 3, "PO6": 1, "PO7": 1, "PO8": 1, "PO9": 2, "PO10": 2, "PO11": 1, "PO12": 2},
}

# Attainment thresholds
ATTAINMENT_LEVELS = [
    (80, "High", 3),
    (60, "Medium", 2),
    (40, "Low", 1),
    (0, "Very Low", 0),
]


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class COAttainment:
    """Attainment metrics for a single Course Outcome."""
    co: str
    total_marks: int
    marks_in_paper: int
    percentage: float
    attainment_level: str
    attainment_value: int  # 0-3
    bloom_distribution: dict[str, int]  # L1-L6 → marks
    question_count: int


@dataclass
class POAttainment:
    """Attainment metrics for a single Programme Outcome."""
    po: str
    weighted_score: float
    attainment_level: str
    attainment_value: int
    contributing_cos: list[str]


@dataclass
class AttainmentReport:
    """Full attainment analysis for a paper."""
    paper_title: str
    total_marks: int
    co_attainments: list[COAttainment]
    po_attainments: list[POAttainment]
    overall_co_attainment: float  # Average attainment value
    overall_po_attainment: float
    bloom_summary: dict[str, int]  # L1-L6 → total marks
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core Engine
# ---------------------------------------------------------------------------

def _classify_attainment(percentage: float) -> tuple[str, int]:
    """Map a percentage to an attainment level and value."""
    for threshold, label, value in ATTAINMENT_LEVELS:
        if percentage >= threshold:
            return label, value
    return "Very Low", 0


def compute_co_attainment(
    questions: list[dict[str, Any]],
    total_marks: int,
) -> list[COAttainment]:
    """
    Compute CO attainment from a list of questions.

    Each question dict must have: course_outcome, marks, bloom_level.
    """
    co_data: dict[str, dict[str, Any]] = {}

    for q in questions:
        co = (q.get("course_outcome") or "CO1").upper().strip()
        marks = int(q.get("marks", 0) or q.get("custom_marks", 0) or 0)
        bloom = (q.get("bloom_level") or "L1").upper().strip()

        if co not in co_data:
            co_data[co] = {"marks": 0, "blooms": {}, "count": 0}

        co_data[co]["marks"] += marks
        co_data[co]["blooms"][bloom] = co_data[co]["blooms"].get(bloom, 0) + marks
        co_data[co]["count"] += 1

    # Ensure all 5 COs are present
    for co in ["CO1", "CO2", "CO3", "CO4", "CO5"]:
        if co not in co_data:
            co_data[co] = {"marks": 0, "blooms": {}, "count": 0}

    attainments = []
    for co in sorted(co_data.keys()):
        data = co_data[co]
        pct = (data["marks"] / total_marks * 100) if total_marks > 0 else 0
        level, value = _classify_attainment(pct)
        attainments.append(COAttainment(
            co=co,
            total_marks=total_marks,
            marks_in_paper=data["marks"],
            percentage=round(pct, 1),
            attainment_level=level,
            attainment_value=value,
            bloom_distribution=data["blooms"],
            question_count=data["count"],
        ))

    return attainments


def compute_po_attainment(
    co_attainments: list[COAttainment],
    co_po_matrix: dict[str, dict[str, int]] | None = None,
) -> list[POAttainment]:
    """
    Compute PO attainment from CO attainments using CO-PO mapping matrix.
    """
    matrix = co_po_matrix or DEFAULT_CO_PO_MATRIX

    # Determine all POs from the matrix
    all_pos: set[str] = set()
    for co_map in matrix.values():
        all_pos.update(co_map.keys())

    po_scores: dict[str, list[float]] = {po: [] for po in sorted(all_pos)}
    po_contributors: dict[str, list[str]] = {po: [] for po in sorted(all_pos)}

    for co_att in co_attainments:
        co_map = matrix.get(co_att.co, {})
        for po, correlation in co_map.items():
            if correlation > 0 and po in po_scores:
                # Weighted score = CO attainment × correlation weight
                weighted = co_att.attainment_value * (correlation / 3.0)
                po_scores[po].append(weighted)
                po_contributors[po].append(co_att.co)

    attainments = []
    for po in sorted(po_scores.keys()):
        scores = po_scores[po]
        avg = sum(scores) / len(scores) if scores else 0
        # Map 0-3 scale back to percentage for level classification
        pct_equiv = avg / 3.0 * 100
        level, value = _classify_attainment(pct_equiv)
        attainments.append(POAttainment(
            po=po,
            weighted_score=round(avg, 2),
            attainment_level=level,
            attainment_value=value,
            contributing_cos=list(set(po_contributors[po])),
        ))

    return attainments


def compute_attainment_report(
    paper_title: str,
    questions: list[dict[str, Any]],
    total_marks: int,
    co_po_matrix: dict[str, dict[str, int]] | None = None,
) -> AttainmentReport:
    """Generate a full attainment report for a paper."""
    co_atts = compute_co_attainment(questions, total_marks)
    po_atts = compute_po_attainment(co_atts, co_po_matrix)

    # Overall averages
    co_values = [a.attainment_value for a in co_atts if a.marks_in_paper > 0]
    po_values = [a.attainment_value for a in po_atts if a.weighted_score > 0]
    avg_co = sum(co_values) / len(co_values) if co_values else 0
    avg_po = sum(po_values) / len(po_values) if po_values else 0

    # Bloom summary
    bloom_summary: dict[str, int] = {}
    for co_att in co_atts:
        for bloom, marks in co_att.bloom_distribution.items():
            bloom_summary[bloom] = bloom_summary.get(bloom, 0) + marks

    # Warnings
    warnings: list[str] = []
    zero_cos = [a.co for a in co_atts if a.marks_in_paper == 0]
    if zero_cos:
        warnings.append(f"No questions mapped to: {', '.join(zero_cos)}")

    if not bloom_summary.get("L4") and not bloom_summary.get("L5") and not bloom_summary.get("L6"):
        warnings.append("No higher-order thinking (L4-L6) questions detected")

    hot_marks = sum(bloom_summary.get(f"L{i}", 0) for i in range(4, 7))
    if total_marks > 0 and hot_marks / total_marks < 0.2:
        warnings.append("Less than 20% marks from higher-order thinking levels (L4-L6)")

    return AttainmentReport(
        paper_title=paper_title,
        total_marks=total_marks,
        co_attainments=co_atts,
        po_attainments=po_atts,
        overall_co_attainment=round(avg_co, 2),
        overall_po_attainment=round(avg_po, 2),
        bloom_summary=bloom_summary,
        warnings=warnings,
    )


def attainment_to_dict(report: AttainmentReport) -> dict[str, Any]:
    """Convert AttainmentReport to JSON-serializable dict."""
    return {
        "paper_title": report.paper_title,
        "total_marks": report.total_marks,
        "overall_co_attainment": report.overall_co_attainment,
        "overall_po_attainment": report.overall_po_attainment,
        "bloom_summary": report.bloom_summary,
        "warnings": report.warnings,
        "co_attainments": [
            {
                "co": a.co,
                "total_marks": a.total_marks,
                "marks_in_paper": a.marks_in_paper,
                "percentage": a.percentage,
                "attainment_level": a.attainment_level,
                "attainment_value": a.attainment_value,
                "bloom_distribution": a.bloom_distribution,
                "question_count": a.question_count,
            }
            for a in report.co_attainments
        ],
        "po_attainments": [
            {
                "po": a.po,
                "weighted_score": a.weighted_score,
                "attainment_level": a.attainment_level,
                "attainment_value": a.attainment_value,
                "contributing_cos": a.contributing_cos,
            }
            for a in report.po_attainments
        ],
    }
