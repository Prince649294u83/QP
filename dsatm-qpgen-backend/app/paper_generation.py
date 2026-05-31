from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .academic.generation import generate_questions_from_retrieval
from .academic.pedagogical_engine import enrich_candidates_with_intelligence
from .academic.retrieval import list_subject_image_pool, retrieve_diagrams_for_question
from .academic.validation import VTU_VERBS, validate_question, validate_structural_integrity
from .ai_service import OllamaClient, select_questions_for_paper
from .generator import build_question_blueprint
from .models import PaperQuestion, PaperStatus, Question, QuestionPaper, Subject, User
from .schemas import GeneratePaperRequest
from .services import ensure_subject_access, serialize_paper

logger = logging.getLogger("app.paper_generation")

ProgressCallback = Callable[[int, str, str], None]

_TOKEN_OVERHEAD = 180
_PROMPT_TOKEN_BUDGET = 320
_PUBLISHABLE_CONFIDENCE_THRESHOLD = 0.72
_OVERLAP_THRESHOLD = 0.72
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
    "question",
}
_QUESTION_VERBS = tuple(
    sorted({verb for verbs in VTU_VERBS.values() for verb in verbs}, key=len, reverse=True)
)
_TRAILING_SCAFFOLD_PATTERNS = (
    r"\bwith suitable examples?\b.*$",
    r"\bwith a neat diagram(?: and suitable example)?\b.*$",
    r"\band (?:its|their) role in\b.*$",
    r"\bin the context of\b.*$",
    r"\bto solve a suitable problem(?: and show the major steps involved)?\b.*$",
    r"\band show the major steps involved\b.*$",
    r"\band propose suitable improvements\b.*$",
    r"\band discuss (?:its|their) significance\b.*$",
)
_CANONICAL_TOPIC_OVERRIDES = (
    ("given percept at the given time", "agent function"),
    ("manhattan distance", "heuristic search"),
    ("heuristic accuracy", "heuristic search"),
    ("the key to power", "knowledge-based systems"),
    ("representation revisited", "first-order logic"),
    ("problem-solving agents", "problem-solving agents"),
)
_WORKFLOW_HINTS = ("workflow", "steps", "pipeline", "architecture", "stages", "process")
_APPLICATION_HINTS = ("solve", "apply", "heuristic", "distance", "algorithm", "classification")
_TOPIC_MATCH_STOPWORDS = {
    "a",
    "an",
    "and",
    "artificial",
    "basic",
    "basics",
    "by",
    "for",
    "from",
    "in",
    "intelligence",
    "introduction",
    "of",
    "on",
    "the",
    "to",
    "with",
}
_CORRUPTED_SOURCE_HINTS = (
    "homo sapiens",
    "make-action-query",
    "cannot tell whether the written",
    "the name is latin for",
    "the left legs of richard",
    "most accurate on the node",
    "q is true in m",
)
_OVERLAP_STOPWORDS = {
    "define",
    "explain",
    "describe",
    "discuss",
    "solve",
    "apply",
    "analyze",
    "compare",
    "evaluate",
    "justify",
    "design",
    "develop",
    "construct",
    "create",
    "suitable",
    "example",
    "examples",
    "proper",
    "academic",
    "workflow",
    "context",
    "problem",
    "representative",
    "major",
    "steps",
    "involved",
    "diagram",
    "show",
    "using",
    "role",
    "significance",
    "important",
    "aspects",
    "solution",
    "based",
    "with",
    "their",
    "into",
    "from",
    "this",
    "that",
}
# --- Intelligent image gating constants ---
# Visual NOUNS: question must reference a visual artifact to warrant an image
_DIAGRAM_REQUIRED_NOUNS = (
    "diagram",
    "block diagram",
    "flowchart",
    "flow chart",
    "state space tree",
    "search tree",
    "decision tree",
    "parse tree",
    "syntax tree",
    "game tree",
    "architecture",
    "workflow",
    "figure",
    "neural network architecture",
    "bayesian network",
    "semantic net",
    "graph",
)
# Visual VERBS: question explicitly asks to produce a visual
_DIAGRAM_REQUIRED_VERBS = (
    "illustrate",
    "draw",
    "sketch",
    "depict",
    "represent diagrammatically",
    "label the",
    "show the architecture",
    "show the workflow",
    "show the flow",
)
# Questions starting with these verbs NEVER get images
_DIAGRAM_NEVER_VERBS = (
    "define",
    "list",
    "state",
    "name",
    "mention",
    "enumerate",
    "recall",
    "write short note",
    "what is",
    "what are",
)
# Legacy alias kept for any external references
_QUESTION_IMAGE_HINTS = _DIAGRAM_REQUIRED_NOUNS + _DIAGRAM_REQUIRED_VERBS


def _emit_progress(
    callback: ProgressCallback | None, progress: int, stage: str, message: str
) -> None:
    if callback is not None:
        callback(progress, stage, message)


def _estimate_tokens(text: str) -> int:
    words = re.findall(r"\S+", text)
    return max(1, int(len(words) * 1.35))


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _compress_prompt_text(text: str | None, max_tokens: int = _PROMPT_TOKEN_BUDGET) -> str:
    if not text:
        return ""

    normalized = _normalize_text(text)
    if not normalized:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    chosen: list[str] = []
    seen: set[str] = set()
    used_tokens = 0

    for sentence in sentences:
        cleaned = sentence.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)

        sentence_tokens = _estimate_tokens(cleaned)
        if chosen and used_tokens + sentence_tokens > max_tokens:
            break

        chosen.append(cleaned)
        used_tokens += sentence_tokens

    compressed = " ".join(chosen) if chosen else normalized
    if _estimate_tokens(compressed) <= max_tokens:
        return compressed

    words = compressed.split()
    target_words = max(20, max_tokens - _TOKEN_OVERHEAD)
    return " ".join(words[:target_words]).strip()


def _build_coverage_stats(
    question_items: list[dict[str, Any]],
    blueprint: list[dict[str, int | str]],
    requested_modules: list[int],
    requested_rbt: dict[str, int],
    requested_co: dict[str, int],
) -> dict[str, Any]:
    slot_marks = [int(slot["marks"]) for slot in blueprint[: len(question_items)]]
    total = sum(slot_marks) or 1
    by_module = {str(module): 0 for module in (requested_modules or [1, 2, 3, 4, 5])}
    by_rbt = {f"L{level}": 0 for level in range(1, 7)}
    by_co = {f"CO{level}": 0 for level in range(1, 7)}

    for question, marks in zip(question_items, slot_marks):
        module_number = int(question.get("module_number") or 1)
        bloom_level = str(question.get("bloom_level") or "L2").upper()
        course_outcome = str(question.get("course_outcome") or "CO1").upper()

        by_module[str(module_number)] = by_module.get(str(module_number), 0) + marks
        by_rbt[bloom_level] = by_rbt.get(bloom_level, 0) + marks
        by_co[course_outcome] = by_co.get(course_outcome, 0) + marks

    return {
        "question_count": len(question_items),
        "by_module": by_module,
        "by_rbt": by_rbt,
        "by_co": by_co,
        "requested": {
            "modules": requested_modules,
            "rbt": requested_rbt,
            "co": requested_co,
        },
        "percentages": {
            "co": {
                key: round((value / total) * 100)
                for key, value in by_co.items()
                if key in requested_co or value
            },
            "modules": {
                key: round((value / total) * 100)
                for key, value in by_module.items()
                if int(key) in requested_modules or value
            },
        },
    }


def _candidate_from_row(row: Question) -> dict[str, Any]:
    return {
        "id": row.id,
        "row": row,
        "text": row.text,
        "marks": row.marks,
        "course_outcome": row.course_outcome,
        "bloom_level": row.bloom_level,
        "difficulty": row.difficulty,
        "module_number": row.module_number,
        "confidence": 0.86 if row.is_verified else 0.72,
        "source_documents": [],
        "validation_errors": [],
        "validation_warnings": [],
    }


def _candidate_text_key(candidate: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(candidate.get("text", "")).strip()).lower()


def _normalize_phrase(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _topic_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2 and token not in _TOPIC_MATCH_STOPWORDS
    }


def _match_syllabus_topic(text: str, syllabus_topics: list[str]) -> str | None:
    if not text or not syllabus_topics:
        return None

    question_tokens = _topic_tokens(text)
    if not question_tokens:
        return None

    best_topic: str | None = None
    best_score = 0.0

    for topic in syllabus_topics:
        cleaned_topic = _clean_topic_seed(topic)
        if not cleaned_topic:
            continue

        topic_tokens = _topic_tokens(cleaned_topic)
        if not topic_tokens:
            continue

        overlap = len(question_tokens & topic_tokens)
        if not overlap:
            continue

        if cleaned_topic.lower() in text.lower():
            score = 1.0
        else:
            score = overlap / max(len(topic_tokens), 1)

        if score > best_score and (score >= 0.45 or overlap >= 2):
            best_score = score
            best_topic = cleaned_topic

    return best_topic


def _clean_topic_seed(text: str) -> str:
    cleaned = _normalize_text(text)
    cleaned = cleaned.replace("â€¢", " ")
    cleaned = cleaned.replace("A*", "A_STAR")
    cleaned = re.sub(r"\b[A-Z]{2,}\d{2,}\s*[-:]\s*", " ", cleaned)
    cleaned = re.sub(r"\b(module|unit|chapter|section|topic)\s*[-:]?\s*\d+\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\d+[\).:-]?\s*", "", cleaned)
    cleaned = re.sub(r"\(\d{4}\s*[-–]\s*\d{4}\)", " ", cleaned)
    cleaned = re.sub(r"[_*~`]+", " ", cleaned)
    cleaned = cleaned.replace("A_STAR", "A*")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;-")
    if not cleaned:
        return ""
    if cleaned.isupper():
        cleaned = cleaned.title()
    return cleaned[:120]


def _default_family_for_bloom(bloom_level: str, marks: int) -> str:
    if bloom_level == "L6":
        return "design"
    if bloom_level in {"L4", "L5"}:
        return "analysis"
    if bloom_level == "L3" or marks >= 8:
        return "application"
    return "core-concept"


def _harmonize_family_for_bloom(family: str | None, bloom_level: str, marks: int) -> str:
    if not family:
        return _default_family_for_bloom(bloom_level, marks)
    if bloom_level in {"L1", "L2"} and family in {"analysis", "design"}:
        return "core-concept"
    if bloom_level == "L3" and family == "design":
        return "application"
    if bloom_level in {"L4", "L5"} and family == "design":
        return "analysis"
    if bloom_level == "L6" and family in {"analysis", "core-concept"}:
        return "design"
    return family


def _looks_corrupted_question_text(text: str, topic_name: str | None = None) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return True

    lowered = normalized.lower()
    if any(fragment in lowered for fragment in _CORRUPTED_SOURCE_HINTS):
        return True

    issues = validate_structural_integrity(normalized, topic_name)
    return any(issue.severity == "error" for issue in issues)


def _extract_topic_from_question_text(
    text: str,
    subject: Subject,
    planned_topic: str | None = None,
) -> str | None:
    normalized = _normalize_text(text)
    lowered = normalized.lower()

    for artifact, replacement in _CANONICAL_TOPIC_OVERRIDES:
        if artifact in lowered:
            return replacement

    cleaned = normalized
    if subject.code:
        cleaned = re.sub(re.escape(subject.code), " ", cleaned, flags=re.IGNORECASE)
    if subject.name:
        cleaned = re.sub(re.escape(subject.name), " ", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(
        rf"^(?:{'|'.join(re.escape(verb) for verb in _QUESTION_VERBS)})\b",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b(?:the workflow of|workflow of|the application of|application of)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(?:\d+\s*[+\-=/]\s*){2,}\d+", " ", cleaned)
    for pattern in _TRAILING_SCAFFOLD_PATTERNS:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.split("?")[0]

    candidates = [cleaned, *re.split(r"[:;/,-]\s*", cleaned)]

    for candidate in candidates:
        topic = _clean_topic_seed(candidate)
        normalized_topic = _normalize_phrase(topic)
        if not topic or not normalized_topic:
            continue
        if normalized_topic in _GENERIC_TOPIC_LABELS:
            continue
        if len(normalized_topic.split()) > 10:
            continue
        if len(re.findall(r"[A-Za-z]", topic)) < 4:
            continue
        return topic

    if planned_topic:
        fallback = _clean_topic_seed(planned_topic)
        return fallback or None
    return None


def _strip_diagram_placeholders(text: str) -> tuple[str, list[str]]:
    placeholders = re.findall(r"\[DIAGRAM:\s*(.*?)\]", str(text or ""), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\[DIAGRAM:\s*.*?\]\s*", " ", str(text or ""), flags=re.IGNORECASE)
    return _normalize_text(cleaned), [path.strip() for path in placeholders if path.strip()]


def _candidate_needs_diagram(text: str, attached_images: list[dict[str, Any]] | None = None) -> bool:
    """Determine if a question TEXT explicitly requires a visual diagram.

    The decision is based ONLY on the question text — not on whether images
    happen to exist in the database.  This prevents the old circular logic
    where 'images were found → attach them → question has images → attach more'.
    """
    lowered = _normalize_text(text).lower()

    # NEVER attach images for pure definition / listing questions
    if any(lowered.startswith(verb) for verb in _DIAGRAM_NEVER_VERBS):
        return False

    # STRICT IMAGE GATING: Only attach if text EXPLICITLY depends on visual content
    explicit_visual_cues = [
        "based on the figure",
        "in the figure",
        "given figure",
        "given circuit",
        "given diagram",
        "following figure",
        "following diagram",
        "shown in figure",
        "shown below",
        "referring to the figure",
    ]
    
    if any(cue in lowered for cue in explicit_visual_cues):
        return True

    # Catch explicit requests for drawing
    if re.search(r"\b(draw|sketch|plot)\b", lowered) and re.search(r"\b(diagram|graph|circuit|architecture)\b", lowered):
        # Even if they ask to draw, it doesn't mean we need to provide a reference image unless they say "given".
        # But if they say "draw the diagram for", maybe they want the reference image attached.
        # Actually, the user rule is "ONLY trigger on 'Based on the figure below' tags."
        pass

    return False


def _attach_images_to_candidates(
    db: Session,
    subject_id: int,
    candidates: list[dict[str, Any]],
    subject: Subject,
    planned_slots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Attach images to candidates using intelligent gating.

    Only retrieves and attaches images when the question TEXT explicitly
    requires a diagram.  Questions like 'Define X' or 'List the types of Y'
    will NEVER receive images, regardless of what's in the image pool.
    """
    image_pool = list_subject_image_pool(db, subject_id)
    image_lookup_by_path = {
        str(image.get("image_path")): image
        for image in image_pool
        if str(image.get("image_path") or "").strip()
    }

    for index, candidate in enumerate(candidates):
        planned_slot = planned_slots[index] if index < len(planned_slots) else {}
        cleaned_text, placeholder_paths = _strip_diagram_placeholders(str(candidate.get("text", "")))
        candidate["text"] = cleaned_text

        # ── Gate: skip image retrieval entirely for non-diagram questions ──
        if not _candidate_needs_diagram(cleaned_text):
            candidate["attached_images"] = []
            continue

        # ── Only reach here for questions that explicitly require visuals ──
        attached_images: list[dict[str, Any]] = []

        # Resolve explicit [DIAGRAM: path] placeholders
        for path in placeholder_paths:
            image = image_lookup_by_path.get(path)
            if image:
                attached_images.append(dict(image))

        # Auto-match from the image pool
        topic_name = _extract_topic_from_question_text(
            cleaned_text,
            subject,
            str(planned_slot.get("topic_name") or "").strip() or None,
        )

        auto_matches = retrieve_diagrams_for_question(
            db,
            subject_id,
            cleaned_text,
            topic=topic_name,
            module_number=int(candidate.get("module_number") or 0) or None,
            source_documents=list(candidate.get("source_documents") or []),
            limit=1,
        )
        for image in auto_matches:
            if any(existing.get("image_id") == image.get("image_id") for existing in attached_images):
                continue
            attached_images.append(image)

        candidate["attached_images"] = attached_images[:2]

    return image_pool


def _topic_matches_syllabus(topic: str, syllabus_topics: list[str]) -> bool:
    cleaned_topic = _clean_topic_seed(topic)
    if not cleaned_topic:
        return False

    lowered = cleaned_topic.lower()
    if any(fragment in lowered for fragment in _CORRUPTED_SOURCE_HINTS):
        return False
    if any(char in cleaned_topic for char in ('"', "?", "“", "”")):
        return False
    if len(cleaned_topic.split()) > 8:
        return False

    if not syllabus_topics:
        return True

    topic_tokens = _topic_tokens(cleaned_topic)
    if not topic_tokens:
        return False

    for syllabus_topic in syllabus_topics:
        cleaned_syllabus = _clean_topic_seed(syllabus_topic)
        if not cleaned_syllabus:
            continue

        if cleaned_topic.lower() == cleaned_syllabus.lower():
            return True
        if cleaned_topic.lower() in cleaned_syllabus.lower() or cleaned_syllabus.lower() in cleaned_topic.lower():
            return True

        syllabus_tokens = _topic_tokens(cleaned_syllabus)
        overlap = len(topic_tokens & syllabus_tokens)
        if overlap >= 2:
            return True
        if overlap and overlap == len(topic_tokens) and overlap >= max(1, len(syllabus_tokens) - 1):
            return True

    return False


def _resolve_candidate_topic(
    text: str,
    subject: Subject,
    planned_topic: str | None,
    syllabus_topics: list[str],
) -> str | None:
    planned = _clean_topic_seed(planned_topic or "")
    safe_planned = planned if _topic_matches_syllabus(planned, syllabus_topics) else None
    syllabus_match = _match_syllabus_topic(text, syllabus_topics)
    extracted = _extract_topic_from_question_text(text, subject, None)

    if syllabus_match:
        return syllabus_match
    if extracted and _topic_matches_syllabus(extracted, syllabus_topics):
        return extracted
    if safe_planned:
        return safe_planned
    if syllabus_topics and not _question_is_within_syllabus_scope(text, syllabus_topics):
        return None
    if extracted and not syllabus_topics:
        return extracted
    return None


def _infer_question_family(
    raw_text: str,
    bloom_level: str,
    planned_family: str | None = None,
) -> str:
    if planned_family in {"workflow", "comparison", "application", "analysis", "design", "core-concept"}:
        return planned_family

    lowered = raw_text.lower()
    if any(lowered.startswith(prefix) for prefix in ("compare", "contrast", "differentiate", "distinguish")):
        return "comparison"
    if any(lowered.startswith(prefix) for prefix in ("analyze", "evaluate", "justify", "assess", "critique")):
        return "analysis"
    if any(lowered.startswith(prefix) for prefix in ("design", "develop", "construct", "create", "formulate")):
        return "design"
    if any(lowered.startswith(prefix) for prefix in ("solve", "apply", "demonstrate", "implement", "compute")):
        return "application"
    if any(hint in lowered for hint in _WORKFLOW_HINTS):
        return "workflow"
    if bloom_level in {"L4", "L5"}:
        return "analysis"
    if bloom_level == "L6":
        return "design"
    if any(hint in lowered for hint in _APPLICATION_HINTS):
        return "application"
    return "core-concept"


def _extract_question_detail(text: str, topic: str) -> str | None:
    normalized = _normalize_text(text)
    if not normalized or not topic:
        return None

    for marker in (
        " and its role in ",
        " with respect to ",
        " using ",
        " for ",
        " in ",
    ):
        index = normalized.lower().find(marker)
        if index == -1:
            continue
        detail = _clean_topic_seed(normalized[index + len(marker):])
        if not detail:
            continue
        detail_key = _normalize_phrase(detail)
        if detail_key in _GENERIC_TOPIC_LABELS or len(detail_key.split()) > 8:
            continue
        if detail_key == _normalize_phrase(topic):
            continue
        return detail
    return None


def _build_clean_question_text(
    *,
    topic: str,
    bloom_level: str,
    marks: int,
    family: str,
    detail: str | None = None,
) -> str:
    verb = VTU_VERBS.get(bloom_level, VTU_VERBS["L2"])[0].capitalize()
    if family == "workflow":
        return f"{verb} the workflow of {topic} with a neat diagram and suitable example."
    if family == "comparison":
        if detail:
            return f"{verb} {topic} with respect to {detail}."
        return f"{verb} the important aspects of {topic}."
    if family == "application":
        if bloom_level == "L3":
            return f"{verb} {topic} to solve a suitable problem and show the major steps involved."
        if detail:
            return f"{verb} the application of {topic} in {detail}."
        return f"{verb} {topic} in a suitable problem-solving context."
    if family == "analysis":
        if detail:
            return f"{verb} {topic} and discuss its significance in {detail}."
        return f"{verb} {topic} with proper justification."
    if family == "design":
        if detail:
            return f"{verb} a solution based on {topic} for {detail}."
        return f"{verb} a suitable solution using {topic}."
    if bloom_level == "L1":
        return f"{verb} {topic} with a suitable example."
    if bloom_level == "L2":
        if detail:
            return f"{verb} {topic} and its role in {detail}."
        return f"{verb} {topic} with suitable examples."
    if marks >= 10 and detail:
        return f"{verb} {topic} in the context of {detail}."
    return f"{verb} {topic} with proper academic justification."


def _validation_is_publishable(validation: Any) -> bool:
    if not validation or not validation.is_valid:
        return False
    # Only reject on critical warning categories. Structural and marks
    # warnings create false positives (e.g., uppercase topic names like
    # "BEST FIRST SEARCH" or legitimate Bloom-marks edge cases) and should
    # not block publishability.
    critical_warnings = [
        issue for issue in (validation.warnings or [])
        if issue.category in ("syllabus", "phrasing")
    ]
    return len(critical_warnings) == 0


def _validate_final_candidate_text(
    *,
    text: str,
    slot: dict[str, Any],
    candidate: dict[str, Any],
    topic_name: str | None,
    existing_questions: list[str],
    syllabus_topics: list[str],
) -> Any:
    return validate_question(
        question_text=text,
        marks=int(slot["marks"]),
        bloom_level=str(candidate.get("bloom_level") or "L2").upper(),
        co_mapping=str(candidate.get("course_outcome") or "CO1").upper(),
        existing_questions=existing_questions,
        syllabus_topics=syllabus_topics,
        topic_name=topic_name,
        module_number=int(candidate.get("module_number") or slot["module_number"] or 1),
        strict_syllabus=bool(syllabus_topics),
    )


def _build_bank_candidate(
    *,
    question: Question,
    slot: dict[str, Any],
    subject: Subject,
    accepted_candidates: list[dict[str, Any]],
    planned_topic: str | None,
    planned_family: str | None,
    syllabus_topics: list[str],
) -> dict[str, Any] | None:
    candidate = _candidate_from_row(question)
    existing_questions = [str(existing.get("text", "")) for existing in accepted_candidates if existing.get("text")]
    topic_name = _resolve_candidate_topic(question.text, subject, planned_topic, syllabus_topics)
    raw_text = _normalize_text(question.text)
    raw_is_corrupted = _looks_corrupted_question_text(raw_text, topic_name) or not _question_is_within_syllabus_scope(
        raw_text,
        syllabus_topics,
    )
    family = _infer_question_family(question.text, str(candidate["bloom_level"]).upper(), planned_family)
    if raw_is_corrupted and not planned_family:
        family = _default_family_for_bloom(
            str(candidate["bloom_level"]).upper(),
            int(slot["marks"]),
        )
    family = _harmonize_family_for_bloom(
        family,
        str(candidate["bloom_level"]).upper(),
        int(slot["marks"]),
    )
    detail = _extract_question_detail(question.text, topic_name or planned_topic or "")

    attempts: list[tuple[str, str | None]] = []
    if raw_text and not raw_is_corrupted:
        attempts.append((raw_text, topic_name))

    diversified_text = _diversify_bank_question_text(raw_text)
    if diversified_text and diversified_text != raw_text and not raw_is_corrupted:
        attempts.append((diversified_text, topic_name))

    if topic_name:
        synthesized_text = _build_clean_question_text(
            topic=topic_name,
            bloom_level=str(candidate["bloom_level"]).upper(),
            marks=int(slot["marks"]),
            family=family,
            detail=detail,
        )
        if synthesized_text not in {text for text, _ in attempts}:
            attempts.append((synthesized_text, topic_name))

    if not attempts and planned_topic:
        planned_clean = _clean_topic_seed(planned_topic)
        if planned_clean:
            attempts.append(
                (
                    _build_clean_question_text(
                        topic=planned_clean,
                        bloom_level=str(candidate["bloom_level"]).upper(),
                        marks=int(slot["marks"]),
                        family=_default_family_for_bloom(
                            str(candidate["bloom_level"]).upper(),
                            int(slot["marks"]),
                        ),
                    ),
                    planned_clean,
                )
            )

    for candidate_text, candidate_topic in attempts:
        if _has_high_overlap(candidate_text, accepted_candidates):
            continue
        validation = _validate_final_candidate_text(
            text=candidate_text,
            slot=slot,
            candidate=candidate,
            topic_name=candidate_topic,
            existing_questions=existing_questions,
            syllabus_topics=syllabus_topics,
        )
        if not _validation_is_publishable(validation):
            continue
        candidate["text"] = candidate_text
        candidate["validation_errors"] = []
        candidate["validation_warnings"] = []
        return candidate

    return None


def _normalize_for_overlap(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return [
        token
        for token in tokens
        if len(token) > 2 and token not in _OVERLAP_STOPWORDS
    ]


def _question_scope_tokens(text: str) -> set[str]:
    return set(_normalize_for_overlap(text)) - _TOPIC_MATCH_STOPWORDS


def _question_is_within_syllabus_scope(text: str, syllabus_topics: list[str]) -> bool:
    if not syllabus_topics:
        return True

    question_tokens = _question_scope_tokens(text)
    if not question_tokens:
        return True

    syllabus_tokens: set[str] = set()
    for topic in syllabus_topics:
        syllabus_tokens.update(_question_scope_tokens(topic))

    if not syllabus_tokens:
        return True

    overlap = len(question_tokens & syllabus_tokens)
    return overlap >= 2 and (overlap / max(len(question_tokens), 1)) >= 0.45


def _question_overlap_score(left: str, right: str) -> float:
    left_tokens = set(_normalize_for_overlap(left))
    right_tokens = set(_normalize_for_overlap(right))
    if not left_tokens or not right_tokens:
        return 0.0
    shared = len(left_tokens & right_tokens)
    return shared / max(len(left_tokens), len(right_tokens), 1)


def _has_high_overlap(candidate_text: str, accepted_candidates: list[dict[str, Any]]) -> bool:
    return any(
        _question_overlap_score(candidate_text, str(existing.get("text", ""))) >= _OVERLAP_THRESHOLD
        for existing in accepted_candidates
    )


def _is_publishable_rag_candidate(question: Any, accepted_candidates: list[dict[str, Any]]) -> bool:
    if not question.text:
        return False
    if question.validation is None or not question.validation.is_valid:
        return False
    if question.validation.warnings:
        return False
    if float(question.confidence or 0.0) < _PUBLISHABLE_CONFIDENCE_THRESHOLD:
        return False
    if _has_high_overlap(question.text, accepted_candidates):
        return False
    return True


def _diversify_bank_question_text(text: str) -> str:
    rewritten = text.strip()
    replacements = (
        (r"^Explain (.+) and its role in (.+)\.$", r"Discuss the significance of \1 in \2."),
        (r"^Compare (.+) and (.+) for (.+) tasks\.$", r"Differentiate between \1 and \2 with reference to \3 tasks."),
        (r"^Justify how (.+) improves reliability or accuracy in (.+)\.$", r"Examine how \1 contributes to reliability or accuracy in \2."),
        (r"^Apply (.+) to solve a representative problem in (.+)\.$", r"Demonstrate the use of \1 to solve a representative problem in \2."),
        (r"^Evaluate the limitations of (.+) and propose suitable improvements\.$", r"Critically assess the limitations of \1 and suggest suitable improvements."),
        (r"^Design an end-to-end (.+) solution using (.+)\.$", r"Develop an end-to-end \1 solution using \2."),
        (r"^Illustrate the workflow of (.+) with a neat diagram and suitable example\.$", r"With a neat diagram, explain the workflow of \1 using a suitable example."),
    )
    for pattern, replacement in replacements:
        updated = re.sub(pattern, replacement, rewritten, flags=re.IGNORECASE)
        if updated != rewritten:
            return updated
    return rewritten


def _topic_usage_count(topic: str, accepted_candidates: list[dict[str, Any]]) -> int:
    cleaned_topic = _clean_topic_seed(topic)
    if not cleaned_topic:
        return 0
    return sum(
        1
        for existing in accepted_candidates
        if _match_syllabus_topic(str(existing.get("text", "")), [cleaned_topic]) == cleaned_topic
    )


def _rank_syllabus_topics(
    syllabus_topics: list[str],
    accepted_candidates: list[dict[str, Any]],
    planned_topic: str | None,
) -> list[str]:
    cleaned_topics: list[str] = []
    seen_topics: set[str] = set()

    for topic in syllabus_topics:
        cleaned = _clean_topic_seed(topic)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen_topics:
            continue
        seen_topics.add(key)
        cleaned_topics.append(cleaned)

    planned_clean = _clean_topic_seed(planned_topic or "")
    if planned_clean and _topic_matches_syllabus(planned_clean, cleaned_topics):
        planned_key = planned_clean.lower()
        if planned_key not in seen_topics:
            cleaned_topics.append(planned_clean)

    return sorted(
        cleaned_topics,
        key=lambda topic: (
            _topic_usage_count(topic, accepted_candidates),
            0 if topic.lower() == planned_clean.lower() else 1,
            len(topic.split()),
            topic.lower(),
        ),
    )


def _preferred_bloom_levels_for_family(family: str | None, marks: int) -> tuple[str, ...]:
    if family == "design":
        return ("L6", "L5", "L4", "L3", "L2", "L1")
    if family in {"analysis", "comparison"}:
        return ("L5", "L4", "L3", "L2", "L1", "L6")
    if family == "application":
        return ("L3", "L4", "L5", "L2", "L1", "L6")
    if family == "workflow":
        return ("L2", "L3", "L1", "L4", "L5", "L6")
    if marks >= 8:
        return ("L3", "L4", "L2", "L5", "L1", "L6")
    return ("L2", "L1", "L3", "L4", "L5", "L6")


def _default_co_for_bloom(bloom_level: str) -> str:
    """Fallback CO assignment when user hasn't provided module_co_mapping.

    Aligns CO with Bloom's taxonomy bands:
    CO1 (L1-L2): Remember / Understand
    CO2 (L2-L3): Understand / Apply
    CO3 (L3-L4): Apply / Analyze
    CO4 (L4-L5): Analyze / Evaluate
    CO5 (L5-L6): Evaluate / Create
    """
    return {
        "L1": "CO1",
        "L2": "CO2",
        "L3": "CO3",
        "L4": "CO4",
        "L5": "CO5",
        "L6": "CO5",
    }.get(bloom_level, "CO1")


def _co_for_module_slot(
    module_co_mapping: dict[int, list[str]],
    module_number: int,
    module_slot_index: int,
) -> str | None:
    mapped_cos = [
        str(co).strip().upper()
        for co in module_co_mapping.get(module_number, [])
        if str(co).strip()
    ]
    if not mapped_cos:
        return None
    return mapped_cos[module_slot_index % len(mapped_cos)]


def _syllabus_template_priority(
    question: Question,
    *,
    family: str | None,
    target_marks: int,
    subject: Subject,
    syllabus_topics: list[str],
) -> tuple[int, int, int, int, int, int]:
    preferred_blooms = _preferred_bloom_levels_for_family(family, target_marks)
    question_bloom = str(question.bloom_level or "L2").upper()
    bloom_rank = (
        preferred_blooms.index(question_bloom)
        if question_bloom in preferred_blooms
        else len(preferred_blooms)
    )
    topic_name = _resolve_candidate_topic(question.text, subject, None, syllabus_topics)
    corrupted_rank = 1 if (
        _looks_corrupted_question_text(question.text, topic_name)
        or not _question_is_within_syllabus_scope(question.text, syllabus_topics)
    ) else 0
    verification_rank = 0 if question.is_verified else 1
    tag_rank = 2 if "rag-generated" in (question.tags or []) else 0
    marks_rank = abs((question.marks or target_marks) - target_marks)
    return (bloom_rank, corrupted_rank, verification_rank, tag_rank, marks_rank, int(question.id or 0))


def _build_syllabus_fallback_candidate(
    *,
    slot: dict[str, Any],
    pool: list[Question],
    subject: Subject,
    accepted_candidates: list[dict[str, Any]],
    planned_topic: str | None,
    planned_family: str | None,
    syllabus_topics: list[str],
    temp_id: int,
    slot_co: str | None = None,
) -> dict[str, Any] | None:
    if not syllabus_topics:
        return None

    target_module = int(slot["module_number"])
    module_pool = [question for question in pool if question.module_number == target_module]
    if not module_pool:
        return None

    ranked_topics = _rank_syllabus_topics(syllabus_topics, accepted_candidates, planned_topic)
    if not ranked_topics:
        return None

    family = (
        planned_family
        if planned_family in {"workflow", "comparison", "application", "analysis", "design", "core-concept"}
        else None
    )
    template_pool = sorted(
        module_pool,
        key=lambda question: _syllabus_template_priority(
            question,
            family=family,
            target_marks=int(slot["marks"]),
            subject=subject,
            syllabus_topics=syllabus_topics,
        ),
    )
    existing_questions = [
        str(existing.get("text", ""))
        for existing in accepted_candidates
        if existing.get("text")
    ]

    for topic in ranked_topics:
        for template in template_pool:
            bloom_level = str(template.bloom_level or "L2").upper()
            candidate_family = _harmonize_family_for_bloom(
                family,
                bloom_level,
                int(slot["marks"]),
            )
            candidate_text = _build_clean_question_text(
                topic=topic,
                bloom_level=bloom_level,
                marks=int(slot["marks"]),
                family=candidate_family,
            )
            if _has_high_overlap(candidate_text, accepted_candidates):
                continue

            validation = _validate_final_candidate_text(
                text=candidate_text,
                slot=slot,
                candidate={
                    "bloom_level": bloom_level,
                    "course_outcome": str(template.course_outcome or _default_co_for_bloom(bloom_level)).upper(),
                    "module_number": target_module,
                },
                topic_name=topic,
                existing_questions=existing_questions,
                syllabus_topics=syllabus_topics,
            )
            if not _validation_is_publishable(validation):
                continue

            # Use slot_co from module_co_mapping, otherwise fall back to template or bloom default
            effective_co = slot_co or str(template.course_outcome or _default_co_for_bloom(bloom_level)).upper()

            return {
                "id": temp_id,
                "row": None,
                "text": candidate_text,
                "marks": int(slot["marks"]),
                "course_outcome": effective_co,
                "bloom_level": bloom_level,
                "difficulty": str(template.difficulty or "medium").lower(),
                "module_number": target_module,
                "confidence": 0.84,
                "source_documents": ["official syllabus"],
                "validation_errors": [],
                "validation_warnings": [],
            }

    return None


def _question_bank_priority(
    question: Question,
    target_marks: int,
    subject: Subject,
    planned_topic: str | None,
    syllabus_topics: list[str],
) -> tuple[int, int, int, int]:
    topic_name = _resolve_candidate_topic(question.text, subject, planned_topic, syllabus_topics)
    corrupted_rank = 1 if (
        _looks_corrupted_question_text(question.text, topic_name)
        or not _question_is_within_syllabus_scope(question.text, syllabus_topics)
    ) else 0
    verification_rank = 0 if question.is_verified else 1
    tag_rank = 2 if "rag-generated" in (question.tags or []) else 0
    marks_rank = abs((question.marks or target_marks) - target_marks)
    return (corrupted_rank, verification_rank, tag_rank, marks_rank)


def _choose_bank_candidate_for_slot(
    slot: dict[str, Any],
    pool: list[Question],
    subject: Subject,
    accepted_candidates: list[dict[str, Any]],
    used_question_ids: set[int],
    planned_topic: str | None,
    planned_family: str | None,
    syllabus_topics: list[str],
    slot_co: str | None = None,
) -> dict[str, Any] | None:
    target_module = int(slot["module_number"])
    target_marks = int(slot["marks"])
    module_pool = [question for question in pool if question.module_number == target_module]
    if not module_pool:
        return None

    prioritized = sorted(
        module_pool,
        key=lambda question: _question_bank_priority(
            question,
            target_marks,
            subject,
            planned_topic,
            syllabus_topics,
        ),
    )

    for question in prioritized:
        if question.id in used_question_ids:
            continue
        candidate = _build_bank_candidate(
            question=question,
            slot=slot,
            subject=subject,
            accepted_candidates=accepted_candidates,
            planned_topic=planned_topic,
            planned_family=planned_family,
            syllabus_topics=syllabus_topics,
        )
        if candidate is not None:
            # Override CO to match slot's module_co_mapping
            if slot_co:
                candidate["course_outcome"] = slot_co
            return candidate
    return None


def _persist_generated_candidates(
    db: Session, subject_id: int, teacher_id: int, candidates: list[dict[str, Any]]
) -> None:
    for candidate in candidates:
        if candidate.get("row") is not None:
            continue

        row = Question(
            subject_id=subject_id,
            teacher_id=teacher_id,
            text=str(candidate.get("text", "")).strip(),
            marks=int(candidate.get("marks") or 5),
            course_outcome=str(candidate.get("course_outcome") or "CO1").upper(),
            bloom_level=str(candidate.get("bloom_level") or "L2").upper(),
            difficulty=str(candidate.get("difficulty") or "medium").lower(),
            module_number=int(candidate.get("module_number") or 1),
            tags=["rag-generated"],
            is_verified=float(candidate.get("confidence") or 0.0) >= 0.8,
        )
        db.add(row)
        db.flush()
        candidate["row"] = row
        candidate["id"] = row.id


async def generate_ai_paper(
    db: Session,
    user: User,
    payload: GeneratePaperRequest,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    _emit_progress(progress_callback, 5, "validating", "Validating paper request")

    subject = db.get(Subject, payload.subject_id)
    if not subject:
        raise ValueError("Subject not found")
    ensure_subject_access(user, subject, db)

    modules = payload.model_dump().get("module_numbers") or [1, 2, 3, 4, 5]
    rbt_dist = payload.model_dump().get("rbt_levels") or [
        "L1",
        "L2",
        "L3",
        "L4",
        "L5",
        "L6",
    ]
    rbt_dict = {rbt: 100 // len(rbt_dist) for rbt in rbt_dist}
    co_targets = payload.model_dump().get("co_targets", {}) or {
        f"CO{i}": 100 // 5 for i in range(1, 6)
    }
    difficulty = payload.model_dump().get("difficulty", "medium")
    module_co_mapping = payload.model_dump().get("module_co_mapping", {}) or {}
    # Normalise keys to int
    module_co_mapping = {
        int(k): [str(co).strip().upper() for co in v if str(co).strip()]
        for k, v in module_co_mapping.items()
        if str(k).isdigit() and v
    }
    
    module_bloom_mapping = payload.model_dump().get("module_bloom_mapping", {}) or {}
    module_bloom_mapping = {
        int(k): [str(b).strip().upper() for b in v if str(b).strip()]
        for k, v in module_bloom_mapping.items()
        if str(k).isdigit() and v
    }
    
    blueprint = build_question_blueprint(payload.max_marks)

    # ── Phase 2a: Stamp each blueprint slot with its CO from module_co_mapping ──
    module_slot_counts: dict[int, int] = {}
    for slot in blueprint:
        module_num = int(slot["module_number"])
        module_index = module_slot_counts.get(module_num, 0)
        module_slot_counts[module_num] = module_index + 1
        slot["slot_co"] = _co_for_module_slot(
            module_co_mapping,
            module_num,
            module_index,
        )

    manual_question_ids = list(dict.fromkeys(payload.manual_question_ids))
    excluded_question_ids = {
        int(question_id)
        for question_id in payload.exclude_question_ids
        if isinstance(question_id, int) and question_id > 0
    }
    excluded_text_keys = {
        _normalize_text(text).lower()
        for text in payload.exclude_question_texts
        if _normalize_text(text)
    }
    compact_prompt = _compress_prompt_text(payload.prompt)
    use_rag = (
        not manual_question_ids
        and any(
            (
                payload.use_notes,
                payload.use_question_bank,
                payload.use_previous_papers,
                payload.use_syllabus,
            )
        )
    )

    def is_question_excluded(question: Question) -> bool:
        return question.id in excluded_question_ids or _normalize_text(question.text).lower() in excluded_text_keys

    slot_candidates: list[dict[str, Any] | None] = [None] * len(blueprint)
    temp_id_seed = -1
    rag_result = None
    planned_slots: list[dict[str, Any]] = []
    syllabus_topics: list[str] = []
    module_topic_map: dict[int, list[str]] = {}
    question_bank_pool: list[Question] = []

    _emit_progress(
        progress_callback,
        18,
        "planning",
        "Building the paper blueprint and selection plan",
    )

    if manual_question_ids:
        question_rows = list(
            db.scalars(
                select(Question).where(
                    Question.subject_id == payload.subject_id,
                    Question.id.in_(manual_question_ids),
                )
            )
        )
        question_by_id = {question.id: question for question in question_rows}
        ordered_manual_candidates = [
            _candidate_from_row(question_by_id[question_id])
            for question_id in manual_question_ids
            if question_id in question_by_id and not is_question_excluded(question_by_id[question_id])
        ]
        for index, candidate in enumerate(ordered_manual_candidates[: len(slot_candidates)]):
            slot_candidates[index] = candidate
    else:
        if use_rag:
            _emit_progress(
                progress_callback,
                34,
                "retrieving",
                "Retrieving the strongest academic evidence",
            )

            marks_dist: dict[int, int] = {}
            for slot in blueprint:
                marks_dist[int(slot["marks"])] = marks_dist.get(int(slot["marks"]), 0) + 1

            rag_result = await generate_questions_from_retrieval(
                db=db,
                subject_id=payload.subject_id,
                num_questions=len(blueprint),
                marks_distribution=marks_dist,
                bloom_levels=payload.model_dump().get("rbt_levels", []),
                co_targets=list(co_targets.keys()),
                module_filter=modules[0] if len(modules) == 1 else None,
                module_plan=[int(slot["module_number"]) for slot in blueprint],
                module_co_mapping=module_co_mapping,
                module_bloom_mapping=module_bloom_mapping,
                additional_instructions=compact_prompt,
                creativity_override=payload.creativity,
                semantic_variance=payload.semantic_variance,
                structural_variance=payload.structural_variance,
                context_variance=payload.context_variance,
                difficulty_variance=payload.difficulty_variance,
                diagram_variance=payload.diagram_variance,
                use_notes=payload.use_notes,
                use_question_bank=payload.use_question_bank,
                use_previous_papers=payload.use_previous_papers,
                use_syllabus=payload.use_syllabus,
                strict_syllabus_override=payload.strict_syllabus_mode,
                existing_questions=list(excluded_text_keys),
            )
            planned_slots = list(rag_result.retrieval_summary.get("planned_slots", []))
            syllabus_topics = list(rag_result.retrieval_summary.get("syllabus_topics", []))
            raw_module_topic_map = rag_result.retrieval_summary.get("module_topic_map", {})
            if isinstance(raw_module_topic_map, dict):
                module_topic_map = {
                    int(key): list(value or [])
                    for key, value in raw_module_topic_map.items()
                    if str(key).isdigit()
                }

            accepted_rag_candidates: list[dict[str, Any]] = []
            for index, generated_question in enumerate(rag_result.questions[: len(blueprint)]):
                if not _is_publishable_rag_candidate(generated_question, accepted_rag_candidates):
                    continue
                candidate = {
                    "id": temp_id_seed,
                    "row": None,
                    "text": generated_question.text,
                    "marks": generated_question.marks,
                    "course_outcome": generated_question.co_mapping,
                    "bloom_level": generated_question.bloom_level,
                    "difficulty": "medium",
                    "module_number": generated_question.module_number or int(blueprint[index]["module_number"]),
                    "confidence": generated_question.confidence,
                    "source_documents": list(generated_question.source_documents),
                    "attached_images": list(generated_question.attached_images),
                    "validation_errors": [
                        issue.message for issue in (generated_question.validation.errors if generated_question.validation else [])
                    ],
                    "validation_warnings": [
                        issue.message for issue in (generated_question.validation.warnings if generated_question.validation else [])
                    ],
                }
                if _normalize_text(candidate["text"]).lower() in excluded_text_keys:
                    continue
                slot_candidates[index] = candidate
                accepted_rag_candidates.append(candidate)
                temp_id_seed -= 1

        if any(candidate is None for candidate in slot_candidates):
            _emit_progress(
                progress_callback,
                48,
                "selecting",
                "Balancing coverage with the indexed question bank",
            )

            selection = await select_questions_for_paper(
                db,
                payload.subject_id,
                payload.max_marks,
                modules,
                rbt_dict,
                co_targets,
                difficulty,
                compact_prompt,
            )

            accepted_candidates = [candidate for candidate in slot_candidates if candidate is not None]
            used_question_ids = {
                int(candidate["id"])
                for candidate in accepted_candidates
                if isinstance(candidate.get("id"), int) and int(candidate["id"]) > 0
            }
            selection_pool = list(selection.questions)
            broader_pool = list(
                db.scalars(select(Question).where(Question.subject_id == payload.subject_id))
            )
            combined_pool: list[Question] = []
            seen_pool_ids: set[int] = set()
            for question in selection_pool + broader_pool:
                if question.id in seen_pool_ids or is_question_excluded(question):
                    continue
                seen_pool_ids.add(question.id)
                combined_pool.append(question)
            question_bank_pool = list(combined_pool)

            for index, slot in enumerate(blueprint):
                if slot_candidates[index] is not None:
                    continue
                planned_slot = planned_slots[index] if index < len(planned_slots) else {}
                slot_syllabus_topics = module_topic_map.get(int(slot["module_number"])) or syllabus_topics
                slot_co = slot.get("slot_co")  # CO from module_co_mapping
                bank_pick = _choose_bank_candidate_for_slot(
                    slot,
                    combined_pool,
                    subject,
                    accepted_candidates,
                    used_question_ids,
                    str(planned_slot.get("topic_name") or "").strip() or None,
                    str(planned_slot.get("family") or "").strip() or None,
                    slot_syllabus_topics,
                    slot_co=slot_co,
                )
                if bank_pick is None:
                    bank_pick = _build_syllabus_fallback_candidate(
                        slot=slot,
                        pool=combined_pool,
                        subject=subject,
                        accepted_candidates=accepted_candidates,
                        planned_topic=str(planned_slot.get("topic_name") or "").strip() or None,
                        planned_family=str(planned_slot.get("family") or "").strip() or None,
                        syllabus_topics=slot_syllabus_topics,
                        temp_id=temp_id_seed,
                        slot_co=slot_co,
                    )
                    if bank_pick is not None:
                        temp_id_seed -= 1
                if bank_pick is None:
                    continue
                slot_candidates[index] = bank_pick
                accepted_candidates.append(bank_pick)
                if isinstance(bank_pick.get("id"), int) and int(bank_pick["id"]) > 0:
                    used_question_ids.add(int(bank_pick["id"]))

    selected_candidates = [candidate for candidate in slot_candidates if candidate is not None]
    if not selected_candidates:
        logger.warning("No AI or bank candidates found — synthesizing from syllabus blueprint")

    # Graceful degradation: fill remaining empty slots with synthesised questions
    # built from the blueprint's module/marks structure instead of raising errors.
    for index, slot in enumerate(blueprint):
        if slot_candidates[index] is not None:
            continue
        planned_slot = planned_slots[index] if index < len(planned_slots) else {}
        topic = str(planned_slot.get("topic_name") or "").strip()
        if not topic:
            slot_syllabus = module_topic_map.get(int(slot["module_number"]))
            topic = slot_syllabus[0] if slot_syllabus else f"Module {slot['module_number']} concept"
        bloom_level = str(planned_slot.get("bloom_level") or "L2").upper()
        # Use module_co_mapping first, then planned slot, then default
        slot_co = slot.get("slot_co")
        co_mapping = slot_co or str(planned_slot.get("co_mapping") or "CO1").upper()
        family = _harmonize_family_for_bloom(
            str(planned_slot.get("family") or "").strip() or None,
            bloom_level,
            int(slot["marks"]),
        )
        fallback_text = _build_clean_question_text(
            topic=topic,
            bloom_level=bloom_level,
            marks=int(slot["marks"]),
            family=family,
        )
        temp_id_seed -= 1
        slot_candidates[index] = {
            "id": temp_id_seed,
            "row": None,
            "text": fallback_text,
            "marks": int(slot["marks"]),
            "course_outcome": co_mapping,
            "bloom_level": bloom_level,
            "difficulty": "medium",
            "module_number": int(slot["module_number"]),
            "confidence": 0.65,
            "source_documents": ["syllabus-generated"],
            "validation_errors": [],
            "validation_warnings": ["Auto-generated from syllabus due to insufficient source material"],
        }
        logger.info(
            "Synthesised fallback question for slot %s (Module %s): %s",
            slot["label"], slot["module_number"], fallback_text[:80],
        )

    _emit_progress(
        progress_callback,
        64,
        "refining",
        "Refining final question wording and ordering",
    )

    final_candidates = [dict(candidate) for candidate in slot_candidates]
    client = OllamaClient()
    if payload.allow_ai_rewrite and await client.is_available():
        rewritten = await client.rephrase_questions(
            [
                {
                    "id": candidate["id"],
                    "text": candidate["text"],
                    "marks": blueprint[index]["marks"],
                    "course_outcome": candidate["course_outcome"],
                    "bloom_level": candidate["bloom_level"],
                    "module_number": candidate["module_number"],
                    "difficulty": candidate["difficulty"],
                }
                for index, candidate in enumerate(final_candidates)
            ],
            subject.name or "Subject",
            subject.code or "N/A",
            payload.semester,
            payload.exam_type,
            compact_prompt,
        )
        if rewritten:
            rewritten_by_id = {item["id"]: item for item in rewritten}
            accepted_rewrites: list[dict[str, Any]] = []
            for index, candidate in enumerate(final_candidates):
                updated = rewritten_by_id.get(candidate["id"])
                if not updated:
                    accepted_rewrites.append(candidate)
                    continue
                rewritten_text = str(updated.get("text", candidate["text"])).strip()
                planned_slot = planned_slots[index] if index < len(planned_slots) else {}
                slot_syllabus_topics = module_topic_map.get(int(blueprint[index]["module_number"])) or syllabus_topics
                rewritten_topic = _extract_topic_from_question_text(
                    rewritten_text,
                    subject,
                    str(planned_slot.get("topic_name") or "").strip() or None,
                )
                rewritten_validation = _validate_final_candidate_text(
                    text=rewritten_text,
                    slot=blueprint[index],
                    candidate=candidate,
                    topic_name=rewritten_topic,
                    existing_questions=[str(existing.get("text", "")) for existing in accepted_rewrites],
                    syllabus_topics=slot_syllabus_topics,
                )
                if (
                    rewritten_text
                    and not _has_high_overlap(rewritten_text, accepted_rewrites)
                    and _validation_is_publishable(rewritten_validation)
                ):
                    candidate["text"] = rewritten_text
                    candidate["difficulty"] = updated.get("difficulty", candidate["difficulty"])
                    candidate["validation_errors"] = []
                    candidate["validation_warnings"] = []
                accepted_rewrites.append(candidate)

    if not manual_question_ids:
        validated_candidates: list[dict[str, Any]] = []
        for index, candidate in enumerate(final_candidates):
            planned_slot = planned_slots[index] if index < len(planned_slots) else {}
            slot_syllabus_topics = module_topic_map.get(int(blueprint[index]["module_number"])) or syllabus_topics
            topic_name = _extract_topic_from_question_text(
                str(candidate.get("text", "")),
                subject,
                str(planned_slot.get("topic_name") or "").strip() or None,
            )
            validation = _validate_final_candidate_text(
                text=str(candidate.get("text", "")),
                slot=blueprint[index],
                candidate=candidate,
                topic_name=topic_name,
                existing_questions=[str(existing.get("text", "")) for existing in validated_candidates],
                syllabus_topics=slot_syllabus_topics,
            )
            if _has_high_overlap(str(candidate.get("text", "")), validated_candidates) or not _validation_is_publishable(validation):
                fallback_candidate = _build_syllabus_fallback_candidate(
                    slot=blueprint[index],
                    pool=question_bank_pool or list(
                        db.scalars(select(Question).where(Question.subject_id == payload.subject_id))
                    ),
                    subject=subject,
                    accepted_candidates=validated_candidates,
                    planned_topic=str(planned_slot.get("topic_name") or "").strip() or None,
                    planned_family=str(planned_slot.get("family") or "").strip() or None,
                    syllabus_topics=slot_syllabus_topics,
                    temp_id=temp_id_seed,
                    slot_co=blueprint[index].get("slot_co"),
                )
                if fallback_candidate is not None:
                    temp_id_seed -= 1
                    final_candidates[index] = fallback_candidate
                    candidate = fallback_candidate
                    validation = _validate_final_candidate_text(
                        text=str(candidate.get("text", "")),
                        slot=blueprint[index],
                        candidate=candidate,
                        topic_name=_extract_topic_from_question_text(
                            str(candidate.get("text", "")),
                            subject,
                            str(planned_slot.get("topic_name") or "").strip() or None,
                        ),
                        existing_questions=[str(existing.get("text", "")) for existing in validated_candidates],
                        syllabus_topics=slot_syllabus_topics,
                    )
            if _has_high_overlap(str(candidate.get("text", "")), validated_candidates) or not _validation_is_publishable(validation):
                # Graceful degradation: instead of raising ValueError, include
                # the best-effort candidate with validation warnings attached.
                logger.warning(
                    "Slot %s failed final validation but will be included with warnings (graceful degradation)",
                    blueprint[index]["label"],
                )
                candidate["validation_errors"] = []
                candidate["validation_warnings"] = [
                    f"{issue.category}: {issue.message}"
                    for issue in (getattr(validation, 'issues', []) or [])
                ]
            else:
                candidate["validation_errors"] = []
                candidate["validation_warnings"] = []
            validated_candidates.append(candidate)

    # ── Phase 2e: Final CO enforcement pass ──
    # Ensure every candidate's CO strictly matches the user's module_co_mapping.
    # This catches any CO that leaked through bank selection, RAG generation, or AI rewrite.
    if module_co_mapping:
        for index, candidate in enumerate(final_candidates[: len(blueprint)]):
            expected_co = blueprint[index].get("slot_co")
            if expected_co and str(candidate.get("course_outcome", "")).upper() != expected_co:
                logger.info(
                    "CO enforcement: overriding %s → %s for slot %s (Module %s)",
                    candidate.get("course_outcome"), expected_co,
                    blueprint[index].get("label", index + 1), blueprint[index].get("module_number"),
                )
                candidate["course_outcome"] = expected_co

    coverage_stats = _build_coverage_stats(
        final_candidates[: len(blueprint)],
        blueprint,
        modules,
        rbt_dict,
        co_targets,
    )

    enrich_candidates_with_intelligence(final_candidates[: len(blueprint)])
    image_pool = _attach_images_to_candidates(
        db,
        payload.subject_id,
        final_candidates[: len(blueprint)],
        subject,
        planned_slots,
    )

    _emit_progress(
        progress_callback,
        82,
        "saving",
        "Saving the generated paper and traceability data",
    )

    _persist_generated_candidates(db, payload.subject_id, user.id, final_candidates)

    traceability = [
        {
            "order_index": index + 1,
            "question_id": int(candidate["id"]),
            "confidence": candidate.get("confidence"),
            "source_documents": list(candidate.get("source_documents") or []),
            "attached_images": list(candidate.get("attached_images") or []),
            "validation_errors": list(candidate.get("validation_errors") or []),
            "validation_warnings": list(candidate.get("validation_warnings") or []),
            "pedagogical_intel": {
                "difficulty": candidate.get("difficulty"),
                "time_estimate_min": candidate.get("time_estimate_min"),
                "cognitive_load": candidate.get("cognitive_load"),
                "expected_answer_depth": candidate.get("expected_answer_depth"),
                "question_family": candidate.get("question_family"),
                "is_numerical": candidate.get("is_numerical"),
            }
        }
        for index, candidate in enumerate(final_candidates[: len(blueprint)])
    ]

    paper = QuestionPaper(
        subject_id=payload.subject_id,
        teacher_id=user.id,
        title=payload.title,
        exam_type=payload.exam_type,
        semester=payload.semester,
        batch=payload.batch,
        max_marks=payload.max_marks,
        duration_minutes=payload.duration_minutes,
        exam_date=payload.exam_date,
        teaching_department=payload.teaching_department,
        prompt_used=payload.prompt,
        generated_summary=(
            f"{'Manually selected' if manual_question_ids else 'AI selected'} "
            f"{len(final_candidates[: len(blueprint)])} slot-aligned questions for {subject.code} across "
            f"{len({int(candidate.get('module_number') or 1) for candidate in final_candidates[: len(blueprint)]})} modules."
        ),
        ai_config_json={
            "rbt_levels": rbt_dist,
            "module_numbers": modules,
            "module_co_mapping": module_co_mapping,
            "co_targets": co_targets,
            "co_descriptions": payload.co_descriptions,
            "difficulty": difficulty,
            "manual_question_ids": manual_question_ids,
            "template_id": payload.template_id,
            "variant_label": payload.variant_label,
            "instructions": payload.instructions,
            "template_note": (
                "Answer any FIVE full questions, choosing at least ONE question from each MODULE"
                if payload.max_marks >= 100
                else None
            ),
            "coverage_stats": coverage_stats,
            "image_pool": image_pool,
            "traceability": traceability,
            "rag_summary": {
                "used": bool(use_rag),
                "retrieval_summary": rag_result.retrieval_summary if rag_result is not None else {},
                "validation_summary": rag_result.validation_summary if rag_result is not None else {},
            },
            "generation_prompt": compact_prompt,
        },
        status=PaperStatus.DRAFT,
        download_path=None,
    )
    db.add(paper)
    db.flush()

    for index, candidate in enumerate(final_candidates[: len(blueprint)], 1):
        slot = blueprint[index - 1]
        db.add(
            PaperQuestion(
                paper_id=paper.id,
                question_id=int(candidate["id"]),
                order_index=index,
                section_label=str(slot["label"]),
                option_group=f"CHOICE-{((int(slot['question_number']) - 1) // 2) + 1}",
                custom_marks=int(slot["marks"]),
                question_text_snapshot=str(candidate["text"]),
            )
        )

    db.commit()

    stored_paper = db.scalar(
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.id == paper.id)
    )
    if stored_paper is None:
        raise ValueError("Generated paper could not be reloaded")

    _emit_progress(progress_callback, 96, "finalizing", "Paper is ready for preview")
    return serialize_paper(db, stored_paper)
