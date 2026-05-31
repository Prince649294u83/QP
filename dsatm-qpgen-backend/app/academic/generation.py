"""
Retrieval-constrained VTU question generation.

The generator follows a strict pipeline:
  1. Retrieve bounded academic evidence.
  2. Clean and normalize concepts before planning.
  3. Plan each question slot with module, Bloom level, CO, and intent.
  4. Generate polished VTU-style stems from slot-specific evidence only.
  5. Validate uniqueness, structure, and source grounding before returning.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..llm_pipeline import LLMCall
from ..models import Question
from .retrieval import RetrievedContext, get_generation_sources, retrieve_for_generation
from .style_profiles import VTU_PROFILE, get_creativity_level, get_temperature
from .validation import ValidationResult, validate_question

logger = logging.getLogger("app.academic.generation")

_PLAN_PROMPT_BUDGET_TOKENS = 2400
_GENERIC_TOPIC_LABELS = {
    "artificial intelligence",
    "introduction to artificial intelligence",
    "module",
    "unit",
    "chapter",
    "topic",
    "section",
    "subject",
    "notes",
}
_GENERIC_DETAIL_PHRASES = {
    "the retrieved material",
    "the academic content",
    "the uploaded academic material",
    "the uploaded notes",
    "the given content",
}
_BANNED_TOPIC_PHRASES = (
    "as expected",
    "homo sapiens",
    "given percept",
    "representation revisited",
    "problem-solving agents",
    "problem-solving",
)
_RAW_ARTIFACT_PATTERN = re.compile(
    r"(?:\b[A-Z]{2,}\d{2,}\b|[•]|^\d+\.\s*[A-Z]|defi\s+in\s+nition|as expected, neither|"
    r"solve history of|apply foundations of|analyze define|explain application of example)",
    flags=re.IGNORECASE,
)
_FLOW_HINTS = (
    "architecture",
    "workflow",
    "process",
    "steps",
    "pipeline",
    "life cycle",
    "lifecycle",
)
_NUMERICAL_HINTS = (
    "heuristic",
    "distance",
    "cost",
    "search",
    "algorithm",
    "resolution",
    "proof",
    "inference",
    "graph",
    "classification",
    "regression",
    "probability",
)
_QUESTION_FAMILIES = (
    "core-concept",
    "workflow",
    "comparison",
    "application",
    "analysis",
    "design",
)


@dataclass
class GeneratedQuestion:
    text: str
    marks: int
    bloom_level: str
    co_mapping: str
    module_number: int | None
    question_type: str
    topic_name: str | None
    source_chunk_ids: list[int] = field(default_factory=list)
    source_documents: list[str] = field(default_factory=list)
    attached_images: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    validation: ValidationResult | None = None


@dataclass
class GenerationResult:
    questions: list[GeneratedQuestion]
    retrieval_summary: dict[str, Any]
    validation_summary: dict[str, Any]
    generation_time: float
    model_used: str
    creativity_level: float
    temperature: float


@dataclass
class PlannedQuestionSlot:
    slot_id: int
    marks: int
    bloom_level: str
    co_mapping: str
    question_type: str
    module_number: int | None
    topic_name: str
    detail: str | None
    intent: str
    family: str
    source_indices: list[int]


SYSTEM_PROMPT = """You are an expert VTU question paper setter.
You will receive question slots with one or two short evidence snippets per slot.
Write one novel, completely unique, polished university exam question for each slot securely grounded in the provided notes/context.

Rules for Question Generation:
- Provide strict Chain-of-Thought (cot) reasoning first to evaluate alignment with Bloom's level, explicit CO Mapping, evidence grounding, and perform Self-Validation check.
- Produce completely novel, highly specific, sensible questions for every request. Do not reuse basic, common phrasing. Eliminate any vague hallucinations.
- Use only the supplied evidence for that slot.
- Do not copy raw notes, headings, module labels, file names, or subject codes.
- Do not mention "module", "unit", "chapter", document names, or chunk identifiers.
- Keep each question grammatically complete and semantically precise.
- Preserve slot intent, marks, Bloom level, CO, and module alignment.
- MARKS-BASED INTELLIGENCE:
  - For low marks (2-5), favor Definitions, Properties, or brief Explanations.
  - For medium marks (6-8), favor Compare/Contrast, Analysis, or Workflows.
  - For high marks (8-10+), favor Algorithms, Architectures, comprehensive Design questions, or complex numericals.

Return ONLY valid JSON in the exact format shown below:
{"questions":[{"slot_id":1,"cot":"Reasoning about bloom, CO mapping, and evaluating validation...", "is_valid": true, "text":"...", "source_indices":[0]}]}"""


def _estimate_tokens(text: str) -> int:
    return max(1, int(len(re.findall(r"\S+", text)) * 1.35))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _clean_topic_label(label: str | None) -> str:
    if not label:
        return ""

    cleaned = _normalize_text(label)
    cleaned = cleaned.replace("•", " ")
    cleaned = re.sub(r"\b[A-Z]{2,}\d{2,}\s*[-:]\s*", "", cleaned)
    cleaned = re.sub(r"\b(module|unit|chapter|topic|section)\s*[-:]?\s*\d+\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[A-Z]{2,}\d{2,}\b", " ", cleaned)
    cleaned = re.sub(r"^\d+[\).:-]?\s*", "", cleaned)
    cleaned = re.sub(r"\((?:\d{4}[-–]\d{4}|\d{4})\)", " ", cleaned)
    cleaned = re.sub(r"[_*~`]+", " ", cleaned)
    cleaned = re.sub(r"\s*[:;,-]\s*$", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;-")

    if not cleaned:
        return ""

    lowered = cleaned.lower()
    if lowered in _GENERIC_TOPIC_LABELS or re.fullmatch(r"module\s*\d+", lowered):
        return ""
    if any(phrase in lowered for phrase in _BANNED_TOPIC_PHRASES):
        return ""
    if len(cleaned.split()) < 2:
        return ""
    if len(re.findall(r"[A-Za-z]", cleaned)) < 6:
        return ""
    if sum(char.isdigit() for char in cleaned) > max(2, len(cleaned) // 8):
        return ""

    if cleaned.isupper():
        cleaned = cleaned.title()
    return cleaned[:120]


def _extract_topic_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    normalized = _normalize_text(text)
    if not normalized:
        return candidates

    segments = re.split(r"[.:\n;]", normalized)
    for segment in segments:
        cleaned = _clean_topic_label(segment)
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    return candidates


def _derive_topic_from_context(context: RetrievedContext) -> str:
    for seed in (
        context.topic_name,
        context.concept_summary,
        context.clean_text,
    ):
        for candidate in _extract_topic_candidates(seed or ""):
            lowered = candidate.lower()
            if any(word in lowered for word in ("given percept at the given time", "as expected, neither", "module")):
                continue
            return candidate

    fallback = _clean_topic_label(context.document_name.replace(".pdf", "").replace("-", " "))
    return fallback or "the given concept"


def _question_text_has_raw_artifacts(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return True
    if _RAW_ARTIFACT_PATTERN.search(normalized):
        return True
    if len(normalized.split()) < 6:
        return True
    return False


def _extract_detail(context: RetrievedContext, topic_name: str) -> str | None:
    summary = _normalize_text(context.concept_summary or context.clean_text)
    if not summary:
        return None

    lowered_topic_tokens = set(re.findall(r"[a-z0-9]+", topic_name.lower()))
    pieces = re.split(r"(?<=[.!?])\s+", summary)
    for piece in pieces:
        candidate = _normalize_text(piece)
        if not candidate:
            continue
        candidate = re.sub(re.escape(topic_name), "", candidate, flags=re.IGNORECASE)
        words = re.findall(r"[A-Za-z0-9]+", candidate.lower())
        remaining = [word for word in words if word not in lowered_topic_tokens]
        if len(remaining) < 4:
            continue
        detail = " ".join(remaining[:12]).strip()
        if detail and detail not in _GENERIC_DETAIL_PHRASES:
            return detail
    return None


def _normalize_marks_distribution(
    marks_distribution: dict[int, int] | None,
    num_questions: int,
) -> list[int]:
    if not marks_distribution:
        return [5] * num_questions

    marks_plan: list[int] = []
    for raw_marks, raw_count in marks_distribution.items():
        try:
            marks = max(1, int(raw_marks))
            count = max(0, int(raw_count))
        except (TypeError, ValueError):
            continue
        marks_plan.extend([marks] * count)

    if not marks_plan:
        marks_plan = [5] * num_questions
    if len(marks_plan) < num_questions:
        marks_plan.extend([marks_plan[-1]] * (num_questions - len(marks_plan)))
    return marks_plan[:num_questions]


def _choose_family(context: RetrievedContext, bloom_level: str, marks: int, slot_id: int) -> str:
    summary = f"{context.concept_summary} {context.clean_text}".lower()
    if bloom_level == "L6":
        return "design"
    if bloom_level in {"L4", "L5"}:
        return "analysis"
    if any(hint in summary for hint in _FLOW_HINTS):
        return "workflow"
    if any(hint in summary for hint in _NUMERICAL_HINTS) or marks >= 8 and bloom_level == "L3":
        return "application"
    if slot_id % 4 == 0:
        return "comparison"
    return "core-concept"


def _build_slot_intent(family: str, bloom_level: str, marks: int) -> str:
    if family == "workflow":
        return "Explain the workflow clearly with appropriate academic framing."
    if family == "comparison":
        return "Compare or differentiate key aspects using professional VTU phrasing."
    if family == "application":
        return "Frame the question around application, problem solving, or procedural reasoning."
    if family == "analysis":
        return "Require analytical discussion, justification, or structured reasoning."
    if family == "design":
        return "Require a design-oriented or solution-construction response."
    if bloom_level in {"L1", "L2"}:
        return "Test conceptual understanding with precise academic wording."
    if marks >= 8:
        return "Use sufficient scope for a long-answer question."
    return "Keep the question focused and academically complete."


def _select_context_for_slot(
    contexts: list[RetrievedContext],
    topic_usage: Counter[str],
    used_chunks: set[int],
    desired_module: int | None,
    slot_bloom: str,
    slot_co: str,
) -> tuple[int, RetrievedContext]:
    ranked: list[tuple[float, int, RetrievedContext]] = []
    candidate_contexts = contexts

    if desired_module is not None:
        exact_matches = [
            context for context in contexts if context.module_number == desired_module
        ]
        if exact_matches:
            candidate_contexts = exact_matches

    for index, context in enumerate(contexts):
        if context not in candidate_contexts:
            continue
        topic_name = _derive_topic_from_context(context)
        if topic_name == "the given concept":
            continue

        score = float(context.relevance_score) + (context.quality_score * 0.25)
        if desired_module is not None:
            if context.module_number == desired_module:
                score += 0.55
            elif context.module_number is not None:
                score -= 0.4
        if context.co_mapping and context.co_mapping.upper() == slot_co.upper():
            score += 0.1
        if context.bloom_level and context.bloom_level.upper() == slot_bloom.upper():
            score += 0.08
        if context.chunk_id in used_chunks:
            score -= 0.08
        score -= topic_usage[context.topic_key or topic_name.lower()] * 0.45
        ranked.append((score, index, context))

    if not ranked:
        return 0, contexts[0]

    ranked.sort(key=lambda item: item[0], reverse=True)
    _, selected_index, selected_context = ranked[0]
    return selected_index, selected_context


def _build_question_plan(
    contexts: list[RetrievedContext],
    *,
    num_questions: int,
    marks_distribution: dict[int, int] | None,
    bloom_levels: list[str] | None,
    co_targets: list[str] | None,
    question_types: list[str] | None,
    module_filter: int | None,
    module_plan: list[int] | None,
    module_co_mapping: dict[int, list[str]] | None = None,
    module_bloom_mapping: dict[int, list[str]] | None = None,
) -> list[PlannedQuestionSlot]:
    marks_plan = _normalize_marks_distribution(marks_distribution, num_questions)
    bloom_plan = bloom_levels or ["L2", "L3", "L4"]
    co_plan = co_targets or ["CO1", "CO2", "CO3"]
    qtype_plan = question_types or ["theory"]
    explicit_module_plan = module_plan[:num_questions] if module_plan else []

    slots: list[PlannedQuestionSlot] = []
    topic_usage: Counter[str] = Counter()
    module_co_usage: Counter[int] = Counter()
    used_chunks: set[int] = set()

    for slot_index in range(num_questions):
        desired_module = (
            explicit_module_plan[slot_index]
            if slot_index < len(explicit_module_plan)
            else module_filter
        )
        
        if desired_module is not None and module_bloom_mapping:
            b_mapping = module_bloom_mapping.get(desired_module) or module_bloom_mapping.get(str(desired_module))
            if b_mapping:
                mapped_blooms = [
                    str(b).strip().upper()
                    for b in b_mapping
                    if str(b).strip()
                ]
                if mapped_blooms:
                    bloom_level = mapped_blooms[module_co_usage.get(desired_module, 0) % len(mapped_blooms)]
                else:
                    bloom_level = str(bloom_plan[slot_index % len(bloom_plan)]).upper()
            else:
                bloom_level = str(bloom_plan[slot_index % len(bloom_plan)]).upper()
        else:
            bloom_level = str(bloom_plan[slot_index % len(bloom_plan)]).upper()

        # Incorporate dynamic module-to-CO mapping
        if desired_module is not None and module_co_mapping:
            c_mapping = module_co_mapping.get(desired_module) or module_co_mapping.get(str(desired_module))
            if c_mapping:
                mapped_cos = [
                    str(co).strip().upper()
                    for co in c_mapping
                    if str(co).strip()
                ]
                if mapped_cos:
                    co_mapping = mapped_cos[module_co_usage[desired_module] % len(mapped_cos)]
                    module_co_usage[desired_module] += 1
                else:
                    co_mapping = str(co_plan[slot_index % len(co_plan)]).upper()
            else:
                co_mapping = str(co_plan[slot_index % len(co_plan)]).upper()
        else:
            co_mapping = str(co_plan[slot_index % len(co_plan)]).upper()

        # Iron-clad rule: strictly bound Bloom levels to CO mapping
        if co_mapping == "CO1":
            bloom_level = "L1" if slot_index % 2 == 0 else "L2"
        elif co_mapping == "CO2":
            bloom_level = "L3"
        elif co_mapping == "CO3":
            bloom_level = "L4"
        elif co_mapping == "CO4":
            bloom_level = "L5"
        elif co_mapping in {"CO5", "CO6"}:
            bloom_level = "L6"

        question_type = str(qtype_plan[slot_index % len(qtype_plan)]).lower()
        marks = int(marks_plan[slot_index])

        context_index, context = _select_context_for_slot(
            contexts,
            topic_usage,
            used_chunks,
            desired_module,
            bloom_level,
            co_mapping,
        )
        topic_name = _derive_topic_from_context(context)
        detail = _extract_detail(context, topic_name)
        family = _choose_family(context, bloom_level, marks, slot_index + 1)
        topic_usage[context.topic_key or topic_name.lower()] += 1
        used_chunks.add(context.chunk_id)

        secondary_index = None
        if len(contexts) > 1:
            for candidate_index, candidate in enumerate(contexts):
                if candidate_index == context_index:
                    continue
                if desired_module is not None and candidate.module_number not in {None, desired_module}:
                    continue
                if candidate.topic_key == context.topic_key:
                    continue
                secondary_index = candidate_index
                break

        source_indices = [context_index]
        if secondary_index is not None and detail is None:
            source_indices.append(secondary_index)
            detail = _extract_detail(contexts[secondary_index], _derive_topic_from_context(contexts[secondary_index]))

        slots.append(
            PlannedQuestionSlot(
                slot_id=slot_index + 1,
                marks=marks,
                bloom_level=bloom_level,
                co_mapping=co_mapping,
                question_type=question_type,
                module_number=desired_module or context.module_number,
                topic_name=topic_name,
                detail=detail,
                intent=_build_slot_intent(family, bloom_level, marks),
                family=family,
                source_indices=source_indices,
            )
        )

    return slots


def _build_heuristic_question_text(slot: PlannedQuestionSlot) -> str:
    verbs = VTU_PROFILE.verbs.get(slot.bloom_level, VTU_PROFILE.verbs["L2"])
    verb = verbs[0]
    topic = slot.topic_name
    
    if slot.family == "workflow":
        return f"{verb} the steps involved in {topic}."
    if slot.family == "comparison":
        return f"{verb} the significance of {topic}."
    if slot.family == "application":
        return f"{verb} the application of {topic}."
    if slot.family == "analysis":
        return f"{verb} the impact of {topic}."
    if slot.family == "design":
        return f"{verb} the design of {topic}."
    if slot.bloom_level in {"L1", "L2"}:
        return f"{verb} {topic}."
    return f"{verb} {topic} in detail."


def _build_batch_prompt(
    contexts: list[RetrievedContext],
    slots: list[PlannedQuestionSlot],
    semantic_variance: float = 0.5,
    structural_variance: float = 0.5,
    context_variance: float = 0.5,
    difficulty_variance: float = 0.5,
    diagram_variance: float = 0.5,
) -> str:
    lines = ["QUESTION SLOTS:"]
    used_tokens = _estimate_tokens(lines[0]) + 20

    for slot in slots:
        evidence_lines: list[str] = []
        for source_index in slot.source_indices:
            if not 0 <= source_index < len(contexts):
                continue
            context = contexts[source_index]
            evidence = _normalize_text(context.concept_summary or context.clean_text)[:320]
            evidence_lines.append(f"  - [{source_index}] {evidence}")

        slot_block = (
            f"Slot {slot.slot_id} | Module {slot.module_number or 'NA'} | {slot.marks} marks | "
            f"{slot.bloom_level} | {slot.co_mapping} | family={slot.family}\n"
            f"Topic: {slot.topic_name}\n"
            f"Intent: {slot.intent}\n"
            f"Evidence:\n" + "\n".join(evidence_lines)
        )
        slot_tokens = _estimate_tokens(slot_block)
        if lines and used_tokens + slot_tokens > _PLAN_PROMPT_BUDGET_TOKENS:
            break
        lines.append(slot_block)
        used_tokens += slot_tokens

    lines.append(
        "Write one final exam question per slot. The question must be complete, professional, and free from raw note fragments."
    )
    return "\n\n".join(lines)


def _batched(items: list[PlannedQuestionSlot], batch_size: int) -> list[list[PlannedQuestionSlot]]:
    return [items[index:index + batch_size] for index in range(0, len(items), batch_size)]


async def _generate_llm_questions_async(
    llm: LLMCall,
    contexts: list[RetrievedContext],
    slots: list[PlannedQuestionSlot],
    semantic_variance: float = 0.5,
    structural_variance: float = 0.5,
    context_variance: float = 0.5,
    difficulty_variance: float = 0.5,
    diagram_variance: float = 0.5,
) -> tuple[dict[int, dict[str, Any]], str | None]:
    generated: dict[int, dict[str, Any]] = {}
    llm_error: str | None = None

    # Group by module to execute concurrent requests per module
    module_slots: dict[int, list[PlannedQuestionSlot]] = {}
    for slot in slots:
        mod = slot.module_number or 0
        if mod not in module_slots:
            module_slots[mod] = []
        module_slots[mod].append(slot)

    async def process_batch(batch: list[PlannedQuestionSlot]) -> tuple[dict[int, dict[str, Any]], str | None]:
        batch_gen = {}
        err = None
        prompt = _build_batch_prompt(
            contexts,
            batch,
            semantic_variance=semantic_variance,
            structural_variance=structural_variance,
            context_variance=context_variance,
            difficulty_variance=difficulty_variance,
            diagram_variance=diagram_variance,
        )
        raw_result = await llm.async_call(
            prompt=prompt,
            system=SYSTEM_PROMPT,
            timeout=settings.ollama_generation_timeout_seconds,
        )
        if not raw_result or "questions" not in raw_result:
            return batch_gen, "Invalid LLM response"

        for item in raw_result.get("questions", []):
            if not isinstance(item, dict):
                continue
            try:
                slot_id = int(item.get("slot_id"))
            except (TypeError, ValueError):
                continue
            text = _normalize_text(str(item.get("text", "")))
            if len(text.split()) < 5:
                continue
            source_indices = [
                int(index)
                for index in item.get("source_indices", [])
                if isinstance(index, int) or (isinstance(index, str) and index.isdigit())
            ]
            batch_gen[slot_id] = {"text": text, "source_indices": source_indices}
        return batch_gen, err

    tasks = []
    # Send one request per module. If a module has many slots, batch them in 3s.
    for mod_slots in module_slots.values():
        for batch in _batched(mod_slots, 3):
            tasks.append(process_batch(batch))

    if not tasks:
        return generated, llm_error

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for res in results:
        if isinstance(res, Exception):
            llm_error = f"Concurrency error: {res}"
            continue
        batch_generated, batch_error = res
        generated.update(batch_generated)
        if batch_error and not llm_error:
            llm_error = batch_error

    return generated, llm_error


async def _regenerate_llm_question_slot_async(
    llm: LLMCall,
    contexts: list[RetrievedContext],
    slot: PlannedQuestionSlot,
    failed_text: str,
    issues: list[Any],
) -> str | None:
    feedback = []
    for issue in issues:
        feedback.append(f"- [{issue.category}] {issue.message}. Suggestion: {issue.suggestion}")

    evidence_lines: list[str] = []
    for source_index in slot.source_indices:
        if not 0 <= source_index < len(contexts):
            continue
        context = contexts[source_index]
        evidence = _normalize_text(context.concept_summary or context.clean_text)[:320]
        evidence_lines.append(f"  - [{source_index}] {evidence}")

    feedback_text = "\n".join(feedback)
    evidence_text = "\n".join(evidence_lines)

    prompt = f"""You previously wrote this university exam question:
"{failed_text}"

However, it FAILED strict academic validation with the following issues:
{feedback_text}

Task:
Please rewrite this exam question so that it strictly adheres to all validation rules and remains fully within the syllabus topic '{slot.topic_name}'.
The slot metadata is:
Module: {slot.module_number or 'NA'} | Marks: {slot.marks} | Bloom Level: {slot.bloom_level} | CO: {slot.co_mapping}
Topic: {slot.topic_name}
Intent: {slot.intent}

Evidence Reference:
{evidence_text}

Important Instructions:
- Avoid the exact wording of the failed text.
- Rectify every validation failure.
- Ensure the question is written in formal VTU style starting with appropriate Bloom verbs (e.g. {", ".join(VTU_PROFILE.verbs.get(slot.bloom_level, []))}).
- Return a JSON object with a single key "text" containing the rewritten question.

Example JSON output:
{{"text": "Your polished and corrected question here"}}
"""

    system = "You are an expert VTU question reviewer and editor. Output only valid JSON with the key 'text'."

    try:
        raw_result = await llm.async_call(
            prompt=prompt,
            system=system,
            timeout=settings.ollama_generation_timeout_seconds,
        )
        if raw_result and "text" in raw_result:
            return _normalize_text(str(raw_result["text"]))
    except Exception as exc:
        logger.error("Regeneration LLM call failed for slot %s: %s", slot.slot_id, exc)
    return None


def _build_generated_question(
    slot: PlannedQuestionSlot,
    contexts: list[RetrievedContext],
    candidate_text: str,
    *,
    existing_questions: list[str],
    syllabus_topics: list[str] | None,
    module_syllabus_topics: list[str] | None,
    strict_syllabus: bool,
) -> GeneratedQuestion:
    source_contexts = [
        contexts[index]
        for index in slot.source_indices
        if 0 <= index < len(contexts)
    ] or [contexts[0]]

    validation = validate_question(
        question_text=candidate_text,
        marks=slot.marks,
        bloom_level=slot.bloom_level,
        co_mapping=slot.co_mapping,
        retrieved_contexts=source_contexts,
        existing_questions=existing_questions,
        syllabus_topics=module_syllabus_topics or syllabus_topics,
        topic_name=slot.topic_name,
        module_number=slot.module_number,
        strict_syllabus=strict_syllabus,
    )

    confidence_base = sum(
        (context.relevance_score * 0.55) + (context.quality_score * 0.45)
        for context in source_contexts
    ) / max(len(source_contexts), 1)
    confidence = round(max(0.0, min(1.0, (confidence_base * 0.55) + (validation.confidence * 0.45))), 3)

    documents: list[str] = []
    chunk_ids: list[int] = []
    for context in source_contexts:
        chunk_ids.append(context.chunk_id)
        if context.document_name not in documents:
            documents.append(context.document_name)

    return GeneratedQuestion(
        text=candidate_text,
        marks=slot.marks,
        bloom_level=slot.bloom_level,
        co_mapping=slot.co_mapping,
        module_number=slot.module_number,
        question_type=slot.question_type,
        topic_name=slot.topic_name,
        source_chunk_ids=chunk_ids,
        source_documents=documents,
        confidence=confidence,
        validation=validation,
    )


def _is_publishable_question(question: GeneratedQuestion, min_confidence: float = 0.60) -> bool:
    if question.validation is None or not question.validation.is_valid:
        return False
    # Only reject on critical warning categories — structure/marks produce
    # false positives on valid academic topics and Bloom mismatches.
    critical_warning_categories = {issue.category for issue in question.validation.warnings} & {
        "phrasing", "syllabus",
    }
    if critical_warning_categories:
        return False
    if question.confidence < min_confidence:
        return False
    if _question_text_has_raw_artifacts(question.text):
        return False
    return True



def _build_alternative_slot_candidates(
    slot: PlannedQuestionSlot,
    contexts: list[RetrievedContext],
) -> list[PlannedQuestionSlot]:
    alternatives: list[PlannedQuestionSlot] = []
    seen_topics = {slot.topic_name.lower()}

    for index, context in enumerate(contexts):
        if slot.module_number is not None and context.module_number != slot.module_number:
            continue
        topic_name = _derive_topic_from_context(context)
        if topic_name == "the given concept":
            continue
        topic_key = topic_name.lower()
        if topic_key in seen_topics:
            continue
        seen_topics.add(topic_key)
        alternatives.append(
            PlannedQuestionSlot(
                slot_id=slot.slot_id,
                marks=slot.marks,
                bloom_level=slot.bloom_level,
                co_mapping=slot.co_mapping,
                question_type=slot.question_type,
                module_number=slot.module_number or context.module_number,
                topic_name=topic_name,
                detail=_extract_detail(context, topic_name),
                intent=slot.intent,
                family=_choose_family(context, slot.bloom_level, slot.marks, slot.slot_id),
                source_indices=[index],
            )
        )
        if len(alternatives) >= 4:
            break
    return alternatives


async def generate_questions_from_retrieval(
    db: Session,
    subject_id: int,
    *,
    num_questions: int = 10,
    marks_distribution: dict[int, int] | None = None,
    bloom_levels: list[str] | None = None,
    co_targets: list[str] | None = None,
    question_types: list[str] | None = None,
    module_filter: int | None = None,
    module_plan: list[int] | None = None,
    additional_instructions: str | None = None,
    creativity_override: float | None = None,
    semantic_variance: float | None = None,
    structural_variance: float | None = None,
    context_variance: float | None = None,
    difficulty_variance: float | None = None,
    diagram_variance: float | None = None,
    existing_questions: list[str] | None = None,
    use_notes: bool | None = None,
    use_question_bank: bool | None = None,
    use_previous_papers: bool | None = None,
    use_syllabus: bool | None = None,
    module_co_mapping: dict[int, list[str]] | None = None,
    module_bloom_mapping: dict[int, list[str]] | None = None,
    strict_syllabus_override: bool | None = None,
) -> GenerationResult:
    start = time.time()

    profile_sources = get_generation_sources(db, subject_id)
    sources = {
        "use_notes": profile_sources["use_notes"] if use_notes is None else use_notes,
        "use_question_bank": (
            profile_sources["use_question_bank"]
            if use_question_bank is None
            else use_question_bank
        ),
        "use_previous_papers": (
            profile_sources["use_previous_papers"]
            if use_previous_papers is None
            else use_previous_papers
        ),
        "use_syllabus": profile_sources["use_syllabus"] if use_syllabus is None else use_syllabus,
    }

    query_parts: list[str] = ["professional VTU exam questions"]
    if bloom_levels:
        query_parts.append(f"Bloom levels: {', '.join(bloom_levels)}")
    if co_targets:
        query_parts.append(f"Course outcomes: {', '.join(co_targets)}")
    if module_filter:
        query_parts.append(f"Module {module_filter}")
    if module_plan:
        query_parts.append("Modules: " + ", ".join(str(module) for module in sorted(set(module_plan))))
    if question_types:
        query_parts.append(f"Question types: {', '.join(question_types)}")
    if additional_instructions:
        query_parts.append(_normalize_text(additional_instructions)[:240])

    retrieval = retrieve_for_generation(
        db,
        subject_id,
        " ".join(query_parts),
        use_notes=sources.get("use_notes", True),
        use_question_bank=sources.get("use_question_bank", True),
        use_previous_papers=sources.get("use_previous_papers", False),
        use_syllabus=sources.get("use_syllabus", True),
        module_filter=module_filter,
        module_allowlist=module_plan,
        module_co_mapping=module_co_mapping,
        top_k=min(18, max(10, num_questions * 3)),
    )

    if not retrieval.contexts:
        return GenerationResult(
            questions=[],
            retrieval_summary={
                "total_retrieved": 0,
                "error": "No relevant content found",
                "syllabus_topics": retrieval.syllabus_topics,
                "module_topic_map": retrieval.module_topic_map,
                "planned_slots": [],
            },
            validation_summary={"total": 0, "valid": 0, "errors": 0},
            generation_time=time.time() - start,
            model_used="retrieval-empty",
            creativity_level=0.0,
            temperature=0.1,
        )

    target_bloom = bloom_levels[0] if bloom_levels else "L3"
    creativity = creativity_override if creativity_override is not None else get_creativity_level(target_bloom)
    temperature = get_temperature(creativity)
    strict_syllabus = strict_syllabus_override if strict_syllabus_override is not None else bool(retrieval.syllabus_topics)

    slots = _build_question_plan(
        retrieval.contexts,
        num_questions=num_questions,
        marks_distribution=marks_distribution,
        bloom_levels=bloom_levels,
        co_targets=co_targets,
        question_types=question_types,
        module_filter=module_filter,
        module_plan=module_plan,
        module_co_mapping=module_co_mapping,
        module_bloom_mapping=module_bloom_mapping,
    )

    llm = LLMCall(
        model=settings.ollama_model,
        timeout=settings.ollama_generation_timeout_seconds,
    )
    llm_generated: dict[int, dict[str, Any]] = {}
    llm_error: str | None = None
    model_used = "heuristic-planner"

    if llm.is_available():
        llm_slots = [s for s in slots if s.bloom_level not in {"L1", "L2"}]
        llm_generated, llm_error = await _generate_llm_questions_async(
            llm,
            retrieval.contexts,
            llm_slots,
            semantic_variance=semantic_variance or 0.5,
            structural_variance=structural_variance or 0.5,
            context_variance=context_variance or 0.5,
            difficulty_variance=difficulty_variance or 0.5,
            diagram_variance=diagram_variance or 0.5,
        )
        if llm_generated:
            model_used = settings.ollama_model
    else:
        llm_error = "Ollama is unavailable"
        logger.warning("Skipping LLM generation because Ollama is unavailable")

    generated_questions: list[GeneratedQuestion] = []
    rejected_count = 0
    seen_questions = _collect_existing_question_texts(
        db,
        subject_id,
        existing_questions or [],
    )

    for slot in slots:
        llm_candidate = llm_generated.get(slot.slot_id, {})
        llm_text = _normalize_text(str(llm_candidate.get("text", "")))

        is_llm_slot = bool(llm_text)
        candidate_text = llm_text if is_llm_slot else _build_heuristic_question_text(slot)

        if is_llm_slot:
            source_indices = [
                index for index in llm_candidate.get("source_indices", [])
                if isinstance(index, int) and 0 <= index < len(retrieval.contexts)
            ]
            if source_indices:
                slot = PlannedQuestionSlot(
                    slot_id=slot.slot_id,
                    marks=slot.marks,
                    bloom_level=slot.bloom_level,
                    co_mapping=slot.co_mapping,
                    question_type=slot.question_type,
                    module_number=slot.module_number,
                    topic_name=slot.topic_name,
                    detail=slot.detail,
                    intent=slot.intent,
                    family=slot.family,
                    source_indices=source_indices,
                )

        # 1. Initial build & validate
        question = _build_generated_question(
            slot,
            retrieval.contexts,
            candidate_text,
            existing_questions=seen_questions,
            syllabus_topics=retrieval.syllabus_topics,
            module_syllabus_topics=retrieval.module_topic_map.get(slot.module_number or -1),
            strict_syllabus=strict_syllabus,
        )

        # 2. Self-correcting LLM Regeneration Loop (up to 2 retries)
        if is_llm_slot and not _is_publishable_question(question) and llm.is_available():
            logger.info("Slot %s failed initial validation. Triggering Self-Correction Regeneration Loop.", slot.slot_id)
            for attempt in range(1, 3):
                validation_errors = question.validation.issues if question.validation else []
                retried_text = await _regenerate_llm_question_slot_async(
                    llm,
                    retrieval.contexts,
                    slot,
                    candidate_text,
                    validation_errors,
                )
                if retried_text:
                    logger.info("Slot %s retry %s: got candidate '%s'", slot.slot_id, attempt, retried_text)
                    candidate_text = retried_text
                    question = _build_generated_question(
                        slot,
                        retrieval.contexts,
                        candidate_text,
                        existing_questions=seen_questions,
                        syllabus_topics=retrieval.syllabus_topics,
                        module_syllabus_topics=retrieval.module_topic_map.get(slot.module_number or -1),
                        strict_syllabus=strict_syllabus,
                    )
                    if _is_publishable_question(question):
                        logger.info("Slot %s successfully self-corrected on retry %s!", slot.slot_id, attempt)
                        break
                else:
                    logger.warning("Slot %s retry %s returned empty generation", slot.slot_id, attempt)

        # 3. Heuristic / Alternative Fallback if still invalid
        if not _is_publishable_question(question):
            fallback_text = _build_heuristic_question_text(slot)
            if fallback_text != candidate_text:
                fallback_question = _build_generated_question(
                    slot,
                    retrieval.contexts,
                    fallback_text,
                    existing_questions=seen_questions,
                    syllabus_topics=retrieval.syllabus_topics,
                    module_syllabus_topics=retrieval.module_topic_map.get(slot.module_number or -1),
                    strict_syllabus=strict_syllabus,
                )
                if _is_publishable_question(fallback_question):
                    question = fallback_question

        if not _is_publishable_question(question):
            for alternative_slot in _build_alternative_slot_candidates(slot, retrieval.contexts):
                alternative_question = _build_generated_question(
                    alternative_slot,
                    retrieval.contexts,
                    _build_heuristic_question_text(alternative_slot),
                    existing_questions=seen_questions,
                    syllabus_topics=retrieval.syllabus_topics,
                    module_syllabus_topics=retrieval.module_topic_map.get(alternative_slot.module_number or -1),
                    strict_syllabus=strict_syllabus,
                )
                if _is_publishable_question(alternative_question):
                    question = alternative_question
                    break

        if not _is_publishable_question(question):
            rejected_count += 1

        if question.topic_name:
            from .retrieval import retrieve_diagrams_for_question

            question.attached_images = retrieve_diagrams_for_question(
                db,
                subject_id,
                question.text,
                topic=question.topic_name,
                module_number=question.module_number,
                source_documents=question.source_documents,
                limit=1,
            )

        seen_questions.append(question.text.lower().strip())
        generated_questions.append(question)

    valid_count = sum(1 for question in generated_questions if question.validation and question.validation.is_valid)
    error_count = sum(1 for question in generated_questions if question.validation and not question.validation.is_valid)

    return GenerationResult(
        questions=generated_questions,
        retrieval_summary={
            "total_retrieved": retrieval.total_retrieved,
            "sources_used": retrieval.sources_used,
            "topics_covered": retrieval.topics_covered,
            "syllabus_topics": retrieval.syllabus_topics,
            "module_topic_map": retrieval.module_topic_map,
            "planned_slots": [
                {
                    "slot_id": slot.slot_id,
                    "module_number": slot.module_number,
                    "topic_name": slot.topic_name,
                    "family": slot.family,
                    "source_indices": slot.source_indices,
                }
                for slot in slots
            ],
        },
        validation_summary={
            "total": len(generated_questions),
            "valid": valid_count,
            "errors": error_count,
            "publishable": sum(1 for question in generated_questions if _is_publishable_question(question)),
            "rejected_for_publish": rejected_count,
            "warnings": sum(1 for q in generated_questions if q.validation and q.validation.warnings),
            **({"llm_error": llm_error} if llm_error else {}),
        },
        generation_time=time.time() - start,
        model_used=model_used,
        creativity_level=creativity,
        temperature=temperature,
    )


def _collect_existing_question_texts(
    db: Session,
    subject_id: int,
    provided_questions: list[str],
) -> list[str]:
    normalized_questions: list[str] = []
    seen: set[str] = set()

    for question in provided_questions:
        cleaned = _normalize_text(question).lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            normalized_questions.append(cleaned)

    subject_questions = db.scalars(
        select(Question.text).where(Question.subject_id == subject_id).limit(400)
    )
    for question_text in subject_questions:
        cleaned = _normalize_text(question_text).lower()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            normalized_questions.append(cleaned)

    return normalized_questions
