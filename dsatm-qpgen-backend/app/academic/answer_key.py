"""
Answer Key Engine — Phase 4B.

Generates model answers for a paper by combining:
  1. Rubric step structure (from rubric_engine.py)
  2. RAG-retrieved academic context (from the knowledge base)
  3. Bloom-level-appropriate answer depth guidelines

Architecture:
  - Rule-based template for L1/L2 answers (no LLM needed)
  - LLM synthesis for L3+ answers using retrieved context
  - Falls back gracefully when LLM is unavailable

Performance target: <15s for a full 50-mark paper answer key.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from ..llm_pipeline import LLMCall

logger = logging.getLogger("app.academic.answer_key")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLOOM_ANSWER_DEPTH = {
    "L1": {"style": "direct_recall", "min_words": 20, "max_words": 80, "guidance": "State the definition/fact directly. No elaboration needed."},
    "L2": {"style": "explain", "min_words": 50, "max_words": 200, "guidance": "Explain the concept with an example. Show understanding."},
    "L3": {"style": "apply", "min_words": 80, "max_words": 300, "guidance": "Demonstrate application with a worked example or procedure."},
    "L4": {"style": "analyze", "min_words": 100, "max_words": 400, "guidance": "Break down into components. Compare/contrast. Show relationships."},
    "L5": {"style": "evaluate", "min_words": 120, "max_words": 500, "guidance": "Justify a position. Critique strengths and weaknesses."},
    "L6": {"style": "create", "min_words": 150, "max_words": 600, "guidance": "Propose a novel solution or design. Synthesize from multiple sources."},
}


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class AnswerStep:
    """A single step in a model answer."""
    step_number: int
    content: str
    marks: int
    is_diagram: bool = False
    is_formula: bool = False


@dataclass
class QuestionAnswer:
    """Complete model answer for a single question."""
    question_index: int
    question_text: str
    marks: int
    bloom_level: str
    answer_steps: list[AnswerStep]
    key_points: list[str]
    total_words: int
    source_context: str = ""  # RAG context used
    answer_quality: str = "template"  # "template" | "rag_enhanced" | "llm_generated"


@dataclass
class AnswerKey:
    """Complete answer key for a paper."""
    paper_title: str
    total_marks: int
    answers: list[QuestionAnswer]
    general_instructions: str
    generation_mode: str  # "rule_based" | "rag_enhanced" | "hybrid"


# ---------------------------------------------------------------------------
# Rule-Based Answer Generation (no LLM)
# ---------------------------------------------------------------------------

def _generate_template_answer(
    question_text: str,
    marks: int,
    bloom_level: str,
    rubric_steps: list[dict] | None = None,
) -> QuestionAnswer:
    """
    Generate a template-based model answer using rubric structure.

    This is the fast path — pure rule-based, <1ms per question.
    """
    bl = bloom_level.upper().strip() if bloom_level else "L1"
    depth = BLOOM_ANSWER_DEPTH.get(bl, BLOOM_ANSWER_DEPTH["L2"])

    steps: list[AnswerStep] = []
    key_points: list[str] = []

    if rubric_steps:
        for rs in rubric_steps:
            steps.append(AnswerStep(
                step_number=rs.get("step_number", len(steps) + 1),
                content=rs.get("description", ""),
                marks=rs.get("marks_allocated", 1),
                is_diagram="diagram" in rs.get("description", "").lower(),
                is_formula="formula" in rs.get("description", "").lower() or "equation" in rs.get("description", "").lower(),
            ))
            key_points.append(rs.get("description", ""))
    else:
        # Generate placeholder steps based on marks
        marks_per_step = max(1, marks // max(1, _estimate_step_count(marks, bl)))
        step_count = max(1, marks // marks_per_step)

        for i in range(step_count):
            step_marks = marks_per_step if i < step_count - 1 else marks - marks_per_step * (step_count - 1)
            steps.append(AnswerStep(
                step_number=i + 1,
                content=f"[Answer step {i + 1}: {depth['guidance']}]",
                marks=step_marks,
            ))

    total_words = sum(len(s.content.split()) for s in steps)

    return QuestionAnswer(
        question_index=0,
        question_text=question_text,
        marks=marks,
        bloom_level=bl,
        answer_steps=steps,
        key_points=key_points[:5],
        total_words=total_words,
        answer_quality="template",
    )


def _estimate_step_count(marks: int, bloom_level: str) -> int:
    """Estimate the number of answer steps based on marks and Bloom level."""
    base = max(1, marks // 2)
    bl_num = int(bloom_level[1]) if len(bloom_level) == 2 and bloom_level[1].isdigit() else 2
    if bl_num <= 2:
        return min(base, 3)
    elif bl_num <= 4:
        return min(base + 1, 5)
    else:
        return min(base + 2, 7)


# ---------------------------------------------------------------------------
# RAG-Enhanced Answer Generation
# ---------------------------------------------------------------------------

def _enhance_answer_with_context(
    answer: QuestionAnswer,
    context_chunks: list[str],
) -> QuestionAnswer:
    """
    Enhance a template answer with RAG-retrieved context.

    This adds real content from the knowledge base to the answer steps.
    """
    if not context_chunks:
        return answer

    combined_context = "\n\n".join(context_chunks[:3])  # Top 3 chunks
    answer.source_context = combined_context[:500]
    answer.answer_quality = "rag_enhanced"

    # Enhance key points from context
    sentences = [s.strip() for s in combined_context.split(".") if len(s.strip()) > 20]
    if sentences:
        answer.key_points = sentences[:5]

    return answer


def _synthesize_higher_order_answer(
    answer: QuestionAnswer,
    context_chunks: list[str],
) -> QuestionAnswer:
    """
    Use the local Ollama text model for L3+ answers when available.

    This is best-effort only and always falls back to the structured rule-based
    answer if the model is unavailable or returns unusable output.
    """
    if answer.bloom_level not in {"L3", "L4", "L5", "L6"}:
        return answer

    llm = LLMCall(timeout=12.0)
    if not llm.is_available(timeout=2.0):
        return answer

    context = "\n".join(context_chunks[:3]).strip()
    prompt = (
        "Create a concise, academically correct model answer.\n"
        f"Question: {answer.question_text}\n"
        f"Bloom level: {answer.bloom_level}\n"
        f"Marks: {answer.marks}\n"
        f"Context:\n{context or 'No external context available.'}\n\n"
        "Return plain text with short numbered steps. Keep it factual, compact, and aligned to marks."
    )
    response = llm.generate_text(
        prompt,
        "You are an academic examiner preparing model answers. Avoid filler and return only the answer body.",
    )
    if not response:
        return answer

    steps = []
    chunks = [segment.strip() for segment in re.split(r"\n+|\d+\.", response) if segment.strip()]
    if not chunks:
        return answer

    remaining_marks = max(answer.marks, 1)
    marks_per_step = max(1, remaining_marks // max(len(chunks), 1))
    for index, chunk in enumerate(chunks, start=1):
        if remaining_marks <= 0:
            break
        allocated = marks_per_step if index < len(chunks) else remaining_marks
        allocated = min(max(allocated, 1), remaining_marks)
        steps.append(
            AnswerStep(
                step_number=index,
                content=chunk,
                marks=allocated,
                is_diagram="diagram" in chunk.lower(),
                is_formula="formula" in chunk.lower() or "=" in chunk,
            )
        )
        remaining_marks -= allocated

    if not steps:
        return answer

    answer.answer_steps = steps
    answer.total_words = sum(len(step.content.split()) for step in steps)
    answer.key_points = [step.content for step in steps[:5]]
    answer.source_context = context[:500]
    answer.answer_quality = "llm_generated" if context else "hybrid"
    return answer


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_answer_key(
    paper_title: str,
    questions: list[dict[str, Any]],
    rubrics: dict[str, Any] | None = None,
    context_map: dict[int, list[str]] | None = None,
) -> AnswerKey:
    """
    Generate a complete answer key for a paper.

    Args:
        paper_title: Title of the paper.
        questions: List of question dicts with text, marks, bloom_level.
        rubrics: Optional pre-generated rubric dict (from rubric_engine).
        context_map: Optional mapping of question index → RAG context chunks.

    Returns:
        AnswerKey with model answers for each question.
    """
    answers: list[QuestionAnswer] = []
    total_marks = 0

    rubric_questions = rubrics.get("questions", []) if rubrics else []

    for i, q in enumerate(questions):
        text = q.get("text", "")
        marks = int(q.get("marks") or q.get("custom_marks") or 5)
        bloom = q.get("bloom_level", "L2")
        total_marks += marks

        # Find matching rubric
        rubric_steps = None
        for rq in rubric_questions:
            if rq.get("question_index") == i + 1:
                rubric_steps = rq.get("steps", [])
                break

        # Generate template answer
        answer = _generate_template_answer(text, marks, bloom, rubric_steps)
        answer.question_index = i + 1

        # Enhance with RAG context if available
        if context_map and i in context_map:
            answer = _enhance_answer_with_context(answer, context_map[i])
            answer = _synthesize_higher_order_answer(answer, context_map[i])

        answers.append(answer)

    modes = {a.answer_quality for a in answers}
    if "llm_generated" in modes or "hybrid" in modes:
        mode = "hybrid"
    elif "rag_enhanced" in modes:
        mode = "rag_enhanced"
    else:
        mode = "rule_based"

    return AnswerKey(
        paper_title=paper_title,
        total_marks=total_marks,
        answers=answers,
        general_instructions="Award marks for each step independently. Accept alternative valid approaches.",
        generation_mode=mode,
    )


def answer_key_to_dict(key: AnswerKey) -> dict[str, Any]:
    """Convert AnswerKey to JSON-serializable dict."""
    return {
        "paper_title": key.paper_title,
        "total_marks": key.total_marks,
        "general_instructions": key.general_instructions,
        "generation_mode": key.generation_mode,
        "answers": [
            {
                "question_index": a.question_index,
                "question_text": a.question_text,
                "marks": a.marks,
                "bloom_level": a.bloom_level,
                "answer_quality": a.answer_quality,
                "total_words": a.total_words,
                "key_points": a.key_points,
                "source_context_preview": a.source_context[:200] if a.source_context else "",
                "steps": [
                    {
                        "step_number": s.step_number,
                        "content": s.content,
                        "marks": s.marks,
                        "is_diagram": s.is_diagram,
                        "is_formula": s.is_formula,
                    }
                    for s in a.answer_steps
                ],
            }
            for a in key.answers
        ],
    }
