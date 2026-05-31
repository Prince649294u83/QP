"""
Rubric & Answer Key Generation Engine — QPGen v2.

Generates:
  - Stepwise mark allocation rubrics per question
  - Model answer outlines (from RAG context + LLM synthesis)
  - Exportable answer key documents
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .pedagogical_engine import _parse_bloom, infer_question_family


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class RubricStep:
    """A single step in a marking rubric."""

    step_number: int
    description: str
    marks_allocated: int
    partial_marking: str = ""       # Guidance for partial marks


@dataclass
class QuestionRubric:
    """Complete rubric for a single question."""

    question_index: int
    question_text: str
    total_marks: int
    bloom_level: str
    steps: list[RubricStep] = field(default_factory=list)
    answer_outline: str = ""        # Model answer outline
    key_terms: list[str] = field(default_factory=list)
    diagram_required: bool = False
    formula_required: bool = False


@dataclass
class PaperRubric:
    """Complete rubric for an entire paper."""

    paper_title: str
    total_marks: int
    questions: list[QuestionRubric] = field(default_factory=list)
    general_instructions: str = ""


# ---------------------------------------------------------------------------
# Rubric Generation (Rule-Based)
# ---------------------------------------------------------------------------

def _generate_l1_rubric(marks: int, text: str) -> list[RubricStep]:
    """Rubric for L1 (Remember): full marks for correct recall."""
    return [
        RubricStep(
            step_number=1,
            description="Correct definition/fact/term recalled",
            marks_allocated=marks,
            partial_marking=(
                f"Award {marks - 1} mark(s) for partially correct answer "
                f"with minor omissions." if marks > 1 else
                "Full marks for correct answer only."
            ),
        )
    ]


def _generate_l2_rubric(marks: int, text: str) -> list[RubricStep]:
    """Rubric for L2 (Understand): concept + example split."""
    concept_marks = max(1, round(marks * 0.6))
    example_marks = marks - concept_marks

    steps = [
        RubricStep(
            step_number=1,
            description="Clear explanation of the concept with key terminology",
            marks_allocated=concept_marks,
            partial_marking=f"Award {concept_marks - 1} for incomplete but relevant explanation.",
        ),
    ]

    if example_marks > 0:
        steps.append(
            RubricStep(
                step_number=2,
                description="Relevant example or illustration",
                marks_allocated=example_marks,
                partial_marking="Award partial marks for related but imprecise example.",
            )
        )

    return steps


def _generate_l3_rubric(marks: int, text: str) -> list[RubricStep]:
    """Rubric for L3 (Apply): step-by-step allocation."""
    import re
    is_numerical = bool(re.search(
        r"\b(calculate|compute|solve|find|determine)\b", text, re.I
    ))

    if is_numerical:
        formula_marks = max(1, round(marks * 0.25))
        substitution_marks = max(1, round(marks * 0.35))
        answer_marks = max(1, round(marks * 0.30))
        units_marks = marks - formula_marks - substitution_marks - answer_marks

        steps = [
            RubricStep(1, "Correct formula/equation identified", formula_marks,
                       "Award marks even if final answer is wrong."),
            RubricStep(2, "Correct substitution of values", substitution_marks,
                       "Partial marks for correct approach with minor errors."),
            RubricStep(3, "Correct final answer", answer_marks,
                       "Full marks only for numerically correct answer."),
        ]
        if units_marks > 0:
            steps.append(
                RubricStep(4, "Correct units and rounding", units_marks,
                           "Deduct if units are missing or incorrect.")
            )
        return steps

    # Non-numerical application
    approach_marks = max(1, round(marks * 0.30))
    execution_marks = max(1, round(marks * 0.50))
    conclusion_marks = marks - approach_marks - execution_marks

    steps = [
        RubricStep(1, "Correct approach/method identified", approach_marks,
                   "Award marks for mentioning correct technique."),
        RubricStep(2, "Step-by-step execution with logical flow", execution_marks,
                   "Partial marks for each correct intermediate step."),
    ]
    if conclusion_marks > 0:
        steps.append(
            RubricStep(3, "Final result and interpretation", conclusion_marks,
                       "Award for correct conclusion even with minor calculation errors.")
        )
    return steps


def _generate_l4_l5_rubric(marks: int, text: str, bloom: int) -> list[RubricStep]:
    """Rubric for L4 (Analyze) / L5 (Evaluate)."""
    intro_marks = max(1, round(marks * 0.10))
    analysis_marks = max(1, round(marks * 0.50))
    conclusion_marks = max(1, round(marks * 0.30))
    diagram_marks = marks - intro_marks - analysis_marks - conclusion_marks

    label = "Analysis" if bloom == 4 else "Evaluation/Justification"

    steps = [
        RubricStep(1, "Introduction and problem statement", intro_marks,
                   "Award for correctly identifying what is being analyzed."),
        RubricStep(2, f"{label} with structured reasoning", analysis_marks,
                   f"Award partial marks for each valid analytical point."),
        RubricStep(3, "Conclusion with justified reasoning", conclusion_marks,
                   "Must include evidence-backed conclusion."),
    ]
    if diagram_marks > 0:
        steps.append(
            RubricStep(4, "Diagram/table/comparison chart (if applicable)", diagram_marks,
                       "Award for well-labeled, relevant diagram.")
        )
    return steps


def _generate_l6_rubric(marks: int, text: str) -> list[RubricStep]:
    """Rubric for L6 (Create): design methodology."""
    design_marks = max(1, round(marks * 0.20))
    implementation_marks = max(1, round(marks * 0.40))
    justification_marks = max(1, round(marks * 0.25))
    innovation_marks = marks - design_marks - implementation_marks - justification_marks

    steps = [
        RubricStep(1, "Design approach and methodology", design_marks,
                   "Award for clear problem decomposition."),
        RubricStep(2, "Implementation details/architecture", implementation_marks,
                   "Partial marks for partially correct design."),
        RubricStep(3, "Justification of design choices", justification_marks,
                   "Must explain why this approach was chosen."),
    ]
    if innovation_marks > 0:
        steps.append(
            RubricStep(4, "Originality and completeness", innovation_marks,
                       "Award for creative, well-rounded solution.")
        )
    return steps


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_rubric_for_question(
    question_text: str,
    marks: int,
    bloom_level: str | int = "L2",
    course_outcome: str = "",
) -> QuestionRubric:
    """
    Generate a complete marking rubric for a single question.

    Entirely rule-based — no LLM calls.
    """
    import re

    bloom_num = _parse_bloom(bloom_level)
    family = infer_question_family(question_text)

    # Generate steps based on Bloom level
    generators = {
        1: _generate_l1_rubric,
        2: _generate_l2_rubric,
        3: _generate_l3_rubric,
    }

    if bloom_num in generators:
        steps = generators[bloom_num](marks, question_text)
    elif bloom_num in (4, 5):
        steps = _generate_l4_l5_rubric(marks, question_text, bloom_num)
    else:
        steps = _generate_l6_rubric(marks, question_text)

    # Detect diagram/formula requirements
    diagram_required = bool(re.search(
        r"\b(diagram|figure|sketch|draw|illustrate|flowchart|block\s+diagram)\b",
        question_text, re.I
    ))
    formula_required = bool(re.search(
        r"\b(derive|prove|formula|equation|expression)\b",
        question_text, re.I
    ))

    # Extract key terms (simple keyword extraction)
    key_terms = list({
        word.lower()
        for word in re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b", question_text)
        if len(word) > 3
    })[:10]

    return QuestionRubric(
        question_index=0,
        question_text=question_text,
        total_marks=marks,
        bloom_level=f"L{bloom_num}",
        steps=steps,
        key_terms=key_terms,
        diagram_required=diagram_required,
        formula_required=formula_required,
    )


def generate_paper_rubric(
    paper_title: str,
    questions: list[dict[str, Any]],
) -> PaperRubric:
    """
    Generate rubrics for all questions in a paper.

    Each question dict should have: text, marks, bloom_level.
    """
    rubrics: list[QuestionRubric] = []

    for i, q in enumerate(questions):
        rubric = generate_rubric_for_question(
            question_text=str(q.get("text", "")),
            marks=int(q.get("marks", 5)),
            bloom_level=q.get("bloom_level", "L2"),
            course_outcome=str(q.get("course_outcome", "")),
        )
        rubric.question_index = i + 1
        rubrics.append(rubric)

    return PaperRubric(
        paper_title=paper_title,
        total_marks=sum(r.total_marks for r in rubrics),
        questions=rubrics,
        general_instructions=(
            "Award partial marks as specified per step. "
            "Diagram marks should be awarded only for well-labeled, relevant diagrams. "
            "Minor arithmetic errors should not result in full deduction."
        ),
    )


def rubric_to_dict(rubric: PaperRubric) -> dict[str, Any]:
    """Serialize a paper rubric to JSON-compatible dict."""
    return {
        "paper_title": rubric.paper_title,
        "total_marks": rubric.total_marks,
        "general_instructions": rubric.general_instructions,
        "questions": [
            {
                "question_index": qr.question_index,
                "question_text": qr.question_text,
                "total_marks": qr.total_marks,
                "bloom_level": qr.bloom_level,
                "diagram_required": qr.diagram_required,
                "formula_required": qr.formula_required,
                "key_terms": qr.key_terms,
                "answer_outline": qr.answer_outline,
                "steps": [
                    {
                        "step_number": s.step_number,
                        "description": s.description,
                        "marks_allocated": s.marks_allocated,
                        "partial_marking": s.partial_marking,
                    }
                    for s in qr.steps
                ],
            }
            for qr in rubric.questions
        ],
    }
