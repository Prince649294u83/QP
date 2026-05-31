"""
Pedagogical Intelligence Engine — QPGen v2.

Rule-based engine (zero LLM calls, <1ms per question) that infers:
  - Difficulty from Bloom level + solution steps + keywords
  - Time estimates from marks (1.5-2 min/mark)
  - Cognitive load classification
  - Expected answer depth
  - Question family detection

All mapping tables sourced from Revised Bloom's Taxonomy and
VTU/DSATM examination standards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class BloomLevel(IntEnum):
    L1 = 1  # Remember
    L2 = 2  # Understand
    L3 = 3  # Apply
    L4 = 4  # Analyze
    L5 = 5  # Evaluate
    L6 = 6  # Create


BLOOM_LABELS = {
    1: "Remember",
    2: "Understand",
    3: "Apply",
    4: "Analyze",
    5: "Evaluate",
    6: "Create",
}

# Marks range per Bloom level (min, max, typical)
BLOOM_MARKS_TABLE: dict[int, tuple[int, int, int]] = {
    1: (1, 2, 2),
    2: (2, 5, 4),
    3: (4, 6, 5),
    4: (6, 10, 8),
    5: (8, 12, 10),
    6: (10, 15, 12),
}

# Time per mark: (min_factor, max_factor) in minutes
TIME_PER_MARK = (1.5, 2.0)

# Cognitive load per Bloom level
COGNITIVE_LOAD_TABLE: dict[int, str] = {
    1: "Very Low",
    2: "Low",
    3: "Moderate",
    4: "High",
    5: "High",
    6: "Very High",
}

# Expected answer depth per Bloom level
ANSWER_DEPTH_TABLE: dict[int, str] = {
    1: "One-line, definition, or single fact",
    2: "Conceptual explanation (2-3 sentences)",
    3: "Step-by-step application or worked example",
    4: "Multi-step reasoning with analysis",
    5: "Justified evaluation with tradeoff analysis",
    6: "Original design methodology or creative synthesis",
}

# Difficulty keywords (patterns that push difficulty higher)
HARD_KEYWORDS = re.compile(
    r"\b(derive|prove|design|synthesize|formulate|critique|evaluate\s+and|"
    r"compare\s+and\s+contrast|justify|optimize|architect)\b",
    re.IGNORECASE,
)
MEDIUM_KEYWORDS = re.compile(
    r"\b(explain|solve|demonstrate|apply|illustrate|implement|compute|"
    r"calculate|classify|differentiate)\b",
    re.IGNORECASE,
)
EASY_KEYWORDS = re.compile(
    r"\b(define|list|state|name|identify|recall|mention|enumerate|write)\b",
    re.IGNORECASE,
)

# Numerical / formula indicators
NUMERICAL_PATTERN = re.compile(
    r"(\bcalculate\b|\bcompute\b|\bnumerical\b|\bsolve\b|\bfind\s+the\s+value\b|"
    r"\bgiven\s+that\b|\bif\s+\w+\s*=\s*\d+)",
    re.IGNORECASE,
)

# Question family patterns
FAMILY_PATTERNS: dict[str, re.Pattern] = {
    "core-concept": re.compile(
        r"\b(define|what\s+is|state|explain\s+the\s+concept)\b", re.I
    ),
    "workflow": re.compile(
        r"\b(steps|procedure|process|algorithm|how\s+to|describe\s+the\s+process)\b", re.I
    ),
    "comparison": re.compile(
        r"\b(compare|contrast|differentiate|distinguish|difference\s+between|"
        r"advantages\s+and\s+disadvantages)\b", re.I
    ),
    "application": re.compile(
        r"\b(solve|calculate|compute|apply|demonstrate|implement|find\s+the)\b", re.I
    ),
    "analysis": re.compile(
        r"\b(analyze|examine|investigate|why\s+does|reason|identify\s+the\s+cause)\b", re.I
    ),
    "design": re.compile(
        r"\b(design|propose|architect|formulate|create|develop|build)\b", re.I
    ),
    "evaluation": re.compile(
        r"\b(evaluate|assess|judge|critique|justify|recommend|argue)\b", re.I
    ),
}

# Difficulty levels ordered by severity
DIFFICULTY_LEVELS = ("Very Easy", "Easy", "Medium", "Hard", "Very Hard")


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuestionIntelligence:
    """Complete pedagogical metadata for a single question."""

    bloom_level: str               # "L1" .. "L6"
    bloom_label: str               # "Remember" .. "Create"
    bloom_numeric: int             # 1-6
    difficulty: str                # "Very Easy" .. "Very Hard"
    difficulty_index: int          # 0-4
    marks: int                     # Declared or inferred marks
    time_estimate_min: float       # Estimated solving time in minutes
    cognitive_load: str            # "Very Low" .. "Very High"
    expected_answer_depth: str     # Description of expected depth
    question_family: str           # "core-concept", "application", etc.
    is_numerical: bool             # Contains numerical computation
    solution_steps_estimate: int   # Rough estimate of solution steps
    marks_valid: bool              # Whether marks are in expected range for Bloom
    marks_suggestion: int | None   # Suggested marks if current marks are off


@dataclass
class PaperTimeAnalysis:
    """Time budget analysis for a complete paper."""

    total_estimated_min: float
    exam_duration_min: int
    time_surplus_min: float        # Positive = students have extra time
    is_balanced: bool              # Within ±5% of exam duration
    per_question: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Core Engine
# ---------------------------------------------------------------------------

def _parse_bloom(raw: str | int | None) -> int:
    """Normalize Bloom level to integer 1-6."""
    if isinstance(raw, int):
        return max(1, min(6, raw))
    if not raw:
        return 2  # default to Understand
    text = str(raw).upper().strip()
    if text.startswith("L") and text[1:].isdigit():
        return max(1, min(6, int(text[1:])))
    return 2


def infer_question_family(text: str) -> str:
    """Detect question family from text patterns."""
    if not text:
        return "core-concept"

    for family, pattern in FAMILY_PATTERNS.items():
        if pattern.search(text):
            return family
    return "core-concept"


def infer_difficulty(
    bloom_level: int,
    marks: int,
    text: str = "",
) -> tuple[str, int]:
    """
    Infer difficulty from Bloom level, marks, and text keywords.

    Returns (difficulty_label, difficulty_index 0-4).
    """
    # Base difficulty from Bloom
    base = {1: 0, 2: 1, 3: 2, 4: 3, 5: 3, 6: 4}.get(bloom_level, 2)

    # Adjust by marks relative to Bloom expectation
    expected_min, expected_max, _ = BLOOM_MARKS_TABLE.get(bloom_level, (2, 5, 4))
    if marks > expected_max:
        base = min(4, base + 1)
    elif marks < expected_min:
        base = max(0, base - 1)

    # Adjust by text keywords
    if HARD_KEYWORDS.search(text):
        base = min(4, base + 1)
    elif EASY_KEYWORDS.search(text) and not MEDIUM_KEYWORDS.search(text):
        base = max(0, base - 1)

    # Numerical problems are inherently harder
    if NUMERICAL_PATTERN.search(text) and base < 3:
        base = min(4, base + 1)

    return DIFFICULTY_LEVELS[base], base


def estimate_time(marks: int) -> float:
    """Estimate solving time in minutes from marks (1.5-2 min/mark rule)."""
    avg_factor = (TIME_PER_MARK[0] + TIME_PER_MARK[1]) / 2.0
    return round(marks * avg_factor, 1)


def estimate_solution_steps(bloom_level: int, marks: int) -> int:
    """Rough estimate of solution steps required."""
    base_steps = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6}.get(bloom_level, 2)
    marks_factor = max(1, marks // 3)
    return base_steps + marks_factor - 1


def validate_marks_for_bloom(bloom_level: int, marks: int) -> tuple[bool, int | None]:
    """Check if marks are in expected range for Bloom level."""
    expected_min, expected_max, typical = BLOOM_MARKS_TABLE.get(bloom_level, (2, 5, 4))
    if expected_min <= marks <= expected_max:
        return True, None
    return False, typical


def analyze_question(
    text: str,
    bloom_level: str | int | None = None,
    marks: int = 5,
) -> QuestionIntelligence:
    """
    Perform complete pedagogical analysis of a single question.

    All computation is rule-based — no LLM calls.
    Executes in <1ms per question.
    """
    bloom_num = _parse_bloom(bloom_level)
    bloom_label = BLOOM_LABELS.get(bloom_num, "Understand")

    difficulty, diff_idx = infer_difficulty(bloom_num, marks, text)
    time_min = estimate_time(marks)
    cognitive = COGNITIVE_LOAD_TABLE.get(bloom_num, "Moderate")
    depth = ANSWER_DEPTH_TABLE.get(bloom_num, "Moderate explanation")
    family = infer_question_family(text)
    is_numerical = bool(NUMERICAL_PATTERN.search(text))
    steps = estimate_solution_steps(bloom_num, marks)
    marks_ok, marks_suggest = validate_marks_for_bloom(bloom_num, marks)

    return QuestionIntelligence(
        bloom_level=f"L{bloom_num}",
        bloom_label=bloom_label,
        bloom_numeric=bloom_num,
        difficulty=difficulty,
        difficulty_index=diff_idx,
        marks=marks,
        time_estimate_min=time_min,
        cognitive_load=cognitive,
        expected_answer_depth=depth,
        question_family=family,
        is_numerical=is_numerical,
        solution_steps_estimate=steps,
        marks_valid=marks_ok,
        marks_suggestion=marks_suggest,
    )


def analyze_paper_time(
    questions: list[dict[str, Any]],
    exam_duration_min: int = 90,
) -> PaperTimeAnalysis:
    """
    Analyze whether the paper's total estimated time fits the exam duration.

    Each question dict should have at least: text, bloom_level, marks.
    """
    per_q: list[dict[str, Any]] = []
    total_time = 0.0

    for i, q in enumerate(questions):
        intel = analyze_question(
            text=str(q.get("text", "")),
            bloom_level=q.get("bloom_level"),
            marks=int(q.get("marks", 5)),
        )
        entry = {
            "index": i,
            "bloom_level": intel.bloom_level,
            "marks": intel.marks,
            "time_estimate_min": intel.time_estimate_min,
            "difficulty": intel.difficulty,
            "cognitive_load": intel.cognitive_load,
        }
        per_q.append(entry)
        total_time += intel.time_estimate_min

    surplus = exam_duration_min - total_time
    tolerance = exam_duration_min * 0.05  # 5% tolerance
    is_balanced = abs(surplus) <= tolerance

    warnings: list[str] = []
    if surplus < -tolerance:
        warnings.append(
            f"Paper is overloaded: estimated {total_time:.0f} min "
            f"for a {exam_duration_min} min exam (surplus: {surplus:+.0f} min). "
            f"Consider removing {abs(surplus / 1.75):.0f} marks worth of questions."
        )
    elif surplus > tolerance * 3:
        warnings.append(
            f"Paper is underloaded: estimated {total_time:.0f} min "
            f"for a {exam_duration_min} min exam. Students may finish early."
        )

    return PaperTimeAnalysis(
        total_estimated_min=round(total_time, 1),
        exam_duration_min=exam_duration_min,
        time_surplus_min=round(surplus, 1),
        is_balanced=is_balanced,
        per_question=per_q,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Batch utility
# ---------------------------------------------------------------------------

def enrich_candidates_with_intelligence(
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Enrich a list of question candidates with pedagogical metadata.

    Mutates candidates in-place and returns them. Used in the
    paper generation pipeline to annotate questions before assembly.
    """
    for candidate in candidates:
        intel = analyze_question(
            text=str(candidate.get("text", "")),
            bloom_level=candidate.get("bloom_level"),
            marks=int(candidate.get("marks", 5)),
        )
        candidate["difficulty"] = intel.difficulty.lower()
        candidate["time_estimate_min"] = intel.time_estimate_min
        candidate["cognitive_load"] = intel.cognitive_load
        candidate["expected_answer_depth"] = intel.expected_answer_depth
        candidate["question_family"] = intel.question_family
        candidate["is_numerical"] = intel.is_numerical
        candidate["solution_steps"] = intel.solution_steps_estimate

        if not intel.marks_valid and intel.marks_suggestion:
            candidate.setdefault("pedagogical_warnings", []).append(
                f"Marks ({intel.marks}) unusual for {intel.bloom_level}; "
                f"typical is {intel.marks_suggestion}."
            )

    return candidates
