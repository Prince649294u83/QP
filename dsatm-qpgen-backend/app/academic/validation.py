"""
Academic validation engine for generated questions.

Validates:
- Syllabus compliance (topic must exist in syllabus)
- Bloom level compliance
- CO alignment
- Topic presence in retrieved context (anti-hallucination)
- VTU phrasing patterns
- Marks distribution
- Semantic deduplication
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .embeddings import cosine_similarity, generate_embedding
from .retrieval import RetrievedContext

logger = logging.getLogger("app.academic.validation")

_GENERIC_TOPIC_PATTERN = re.compile(
    r"\b(module|unit|chapter|topic|section)\s*[-:]?\s*\d+\b",
    flags=re.IGNORECASE,
)
_SUBJECT_CODE_PATTERN = re.compile(r"\b[A-Z]{2,}\d{2,}\b")
_ARITHMETIC_FRAGMENT_PATTERN = re.compile(r"(?:\d+\s*[+\-=/]\s*){2,}\d+")
_RAW_HEADING_PATTERN = re.compile(r"^\s*\d+[\.)]\s*[A-Z]")
_UPPERCASE_BURST_PATTERN = re.compile(r"\b[A-Z][A-Z\s\-]{8,}\b")
_YEAR_RANGE_PATTERN = re.compile(r"\(\d{4}\s*[–-]\s*\d{4}\)")
_BULLET_ARTIFACT_PATTERN = re.compile(r"[•â€¢]")
_SOURCE_ARTIFACT_PATTERN = re.compile(
    (
        r"\b("
        r"given percept at the given time|"
        r"as expected, neither|"
        r"the key to power|"
        r"representation revisited|"
        r"homo sapiens|"
        r"make-action-query|"
        r"the name is latin for|"
        r"most accurate on the node|"
        r"the left legs of richard|"
        r"cannot tell whether the written|"
        r"q is true in m"
        r")\b"
    ),
    flags=re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# VTU Academic Style
# ---------------------------------------------------------------------------

VTU_VERBS: dict[str, tuple[str, ...]] = {
    "L1": ("define", "list", "state", "name", "identify", "recall", "mention"),
    "L2": ("explain", "describe", "discuss", "summarize", "outline", "differentiate"),
    "L3": ("solve", "calculate", "apply", "demonstrate", "implement", "compute", "write"),
    "L4": ("analyze", "compare", "distinguish", "examine", "contrast", "classify"),
    "L5": ("evaluate", "justify", "critique", "assess", "argue", "judge"),
    "L6": ("design", "develop", "construct", "create", "formulate", "propose"),
}

# Flatten for quick lookup
_ALL_VTU_VERBS = set()
for _verbs in VTU_VERBS.values():
    _ALL_VTU_VERBS.update(_verbs)


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

@dataclass
class ValidationIssue:
    """A single validation issue."""
    category: str  # syllabus, bloom, co, topic, phrasing, marks, duplicate
    severity: str  # error, warning, info
    message: str
    suggestion: str | None = None


@dataclass
class ValidationResult:
    """Result of validating a generated question."""
    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    confidence: float = 1.0

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]


# ---------------------------------------------------------------------------
# Individual validators
# ---------------------------------------------------------------------------

def validate_topic_in_context(
    question_text: str,
    retrieved_contexts: list[RetrievedContext],
    threshold: float = 0.3,
) -> ValidationIssue | None:
    """
    CRITICAL: Ensure the question topic exists in retrieved context.
    This is the primary anti-hallucination check.
    """
    if not retrieved_contexts:
        return ValidationIssue(
            category="topic",
            severity="error",
            message="No retrieved context available — question may be hallucinated",
            suggestion="Upload relevant notes/materials before generating questions",
        )

    q_embedding = generate_embedding(question_text)
    if not q_embedding:
        # Fallback to text matching
        q_lower = question_text.lower()
        for ctx in retrieved_contexts:
            # Check if significant words overlap
            ctx_words = set(re.findall(r"\w{4,}", (ctx.clean_text or ctx.text).lower()))
            q_words = set(re.findall(r"\w{4,}", q_lower))
            overlap = len(q_words & ctx_words)
            if overlap >= 3 or (q_words and overlap / len(q_words) >= 0.3):
                return None
        return ValidationIssue(
            category="topic",
            severity="error",
            message="Question topic not found in any retrieved context",
            suggestion="This question may contain hallucinated content",
        )

    # Check semantic similarity with retrieved chunks
    best_score = 0.0
    for ctx in retrieved_contexts:
        ctx_embedding = generate_embedding(ctx.clean_text or ctx.text)
        if ctx_embedding:
            score = cosine_similarity(q_embedding, ctx_embedding)
            best_score = max(best_score, score)

    if best_score < threshold:
        return ValidationIssue(
            category="topic",
            severity="error",
            message=f"Question has low relevance to retrieved context (best match: {best_score:.2f})",
            suggestion="Question may be outside the scope of uploaded materials",
        )
    return None


def validate_bloom_level(
    question_text: str,
    declared_bloom: str,
) -> ValidationIssue | None:
    """Check if the question text matches its declared Bloom level."""
    lowered = question_text.lower()
    expected_verbs = VTU_VERBS.get(declared_bloom, ())

    if not expected_verbs:
        return ValidationIssue(
            category="bloom",
            severity="warning",
            message=f"Unknown Bloom level: {declared_bloom}",
            suggestion="Use L1-L6",
        )

    has_expected = any(verb in lowered for verb in expected_verbs)
    if not has_expected:
        # Check if it matches a different level
        detected_level = None
        for level, verbs in VTU_VERBS.items():
            if any(v in lowered for v in verbs):
                detected_level = level
                break

        if detected_level and detected_level != declared_bloom:
            return ValidationIssue(
                category="bloom",
                severity="warning",
                message=f"Question appears to be {detected_level} but declared as {declared_bloom}",
                suggestion=f"Consider changing to {detected_level} or rephrasing with {declared_bloom} verbs: {', '.join(expected_verbs[:3])}",
            )
    return None


def validate_co_alignment(
    question_text: str,
    declared_co: str,
    bloom_level: str,
    co_definitions: dict[str, str] | None = None,
) -> ValidationIssue | None:
    """Check if CO assignment is reasonable."""
    if not declared_co or not declared_co.startswith("CO"):
        return ValidationIssue(
            category="co",
            severity="warning",
            message=f"Invalid CO format: {declared_co}",
            suggestion="Use CO1-CO6",
        )

    # Basic bloom-CO consistency check
    bloom_to_typical_co = {
        "L1": {"CO1", "CO2"},
        "L2": {"CO1", "CO2", "CO3"},
        "L3": {"CO2", "CO3", "CO4"},
        "L4": {"CO3", "CO4", "CO5"},
        "L5": {"CO4", "CO5"},
        "L6": {"CO4", "CO5", "CO6"},
    }
    typical_cos = bloom_to_typical_co.get(bloom_level, set())
    if typical_cos and declared_co not in typical_cos:
        return ValidationIssue(
            category="co",
            severity="info",
            message=f"{declared_co} is unusual for {bloom_level} questions (typical: {', '.join(sorted(typical_cos))})",
        )
    return None


def validate_vtu_phrasing(question_text: str) -> list[ValidationIssue]:
    """Check if question follows VTU academic phrasing patterns."""
    issues: list[ValidationIssue] = []
    lowered = question_text.lower().strip()

    # Should start with an action verb or question word
    starts_with_verb = any(lowered.startswith(verb) for verb in _ALL_VTU_VERBS)
    starts_with_question_word = any(
        lowered.startswith(w) for w in ("what", "how", "why", "when", "where", "which", "who")
    )

    if not starts_with_verb and not starts_with_question_word:
        issues.append(ValidationIssue(
            category="phrasing",
            severity="info",
            message="Question doesn't start with a standard VTU action verb",
            suggestion="Consider starting with: Define, Explain, Describe, Solve, Analyze, Design, etc.",
        ))

    # Should have reasonable length
    word_count = len(question_text.split())
    if word_count < 5:
        issues.append(ValidationIssue(
            category="phrasing",
            severity="warning",
            message="Question is too short for academic use",
            suggestion="Expand with more context or specificity",
        ))
    elif word_count > 200:
        issues.append(ValidationIssue(
            category="phrasing",
            severity="info",
            message="Question is unusually long",
            suggestion="Consider splitting into sub-parts or simplifying",
        ))

    return issues


def validate_structural_integrity(
    question_text: str,
    topic_name: str | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    normalized = re.sub(r"\s+", " ", question_text).strip()
    lowered = normalized.lower()

    if _GENERIC_TOPIC_PATTERN.search(normalized):
        issues.append(ValidationIssue(
            category="structure",
            severity="error",
            message="Question contains a raw module/unit heading instead of an academic topic",
            suggestion="Replace the heading with the actual concept from the syllabus",
        ))

    if _SUBJECT_CODE_PATTERN.search(normalized):
        issues.append(ValidationIssue(
            category="structure",
            severity="error",
            message="Question leaks the subject code into the stem",
            suggestion="Use only the concept name, not the course code",
        ))

    if _RAW_HEADING_PATTERN.search(normalized):
        issues.append(ValidationIssue(
            category="structure",
            severity="error",
            message="Question begins with a raw numbered heading fragment",
            suggestion="Rewrite the stem as a complete VTU question",
        ))

    if _BULLET_ARTIFACT_PATTERN.search(normalized):
        issues.append(ValidationIssue(
            category="structure",
            severity="error",
            message="Question contains OCR or bullet artifacts from the source material",
            suggestion="Remove bullet symbols and rewrite the topic as a clean academic stem",
        ))

    if _ARITHMETIC_FRAGMENT_PATTERN.search(normalized) and not lowered.startswith(("solve", "calculate", "compute", "apply")):
        issues.append(ValidationIssue(
            category="structure",
            severity="error",
            message="Question contains a worked-solution arithmetic fragment",
            suggestion="Use the underlying concept and frame a complete problem statement",
        ))

    if _UPPERCASE_BURST_PATTERN.search(normalized):
        issues.append(ValidationIssue(
            category="structure",
            severity="info",
            message="Question contains an unformatted uppercase heading fragment",
            suggestion="Convert raw headings into normal academic phrasing",
        ))

    if _YEAR_RANGE_PATTERN.search(normalized):
        issues.append(ValidationIssue(
            category="structure",
            severity="error",
            message="Question contains a textbook year-range fragment instead of a clean academic topic",
            suggestion="Remove textbook-era headings and use the underlying concept name only",
        ))

    if _SOURCE_ARTIFACT_PATTERN.search(lowered):
        issues.append(ValidationIssue(
            category="structure",
            severity="error",
            message="Question contains a raw source fragment rather than a professionally authored topic",
            suggestion="Rewrite the stem using the underlying academic concept in proper VTU phrasing",
        ))

    repeated_phrase = re.search(r"\b(\w+\s+\w+\s+\w+\s+\w+)\b.*\b\1\b", lowered)
    if repeated_phrase:
        issues.append(ValidationIssue(
            category="structure",
            severity="info",
            message="Question repeats the same phrase, which suggests stitched source text",
            suggestion="Use a single concise phrasing for the concept",
        ))

    if topic_name:
        topic_lower = topic_name.lower().strip()
        if topic_lower in {"module", "topic", "unit"} or re.fullmatch(r"module\s*\d+", topic_lower):
            issues.append(ValidationIssue(
                category="structure",
                severity="error",
                message="Question uses a generic topic label instead of a real syllabus concept",
                suggestion="Select a specific concept before generating the final question",
            ))

    return issues


def validate_marks_appropriateness(
    marks: int,
    bloom_level: str,
    question_text: str,
) -> ValidationIssue | None:
    """Check if marks allocation is reasonable for the question type."""
    word_count = len(question_text.split())

    if bloom_level in {"L1", "L2"} and marks > 10:
        return ValidationIssue(
            category="marks",
            severity="info",
            message=f"{marks} marks is high for an {bloom_level} question",
            suggestion="L1/L2 questions typically carry 2-10 marks",
        )

    if marks >= 15 and word_count < 15:
        return ValidationIssue(
            category="marks",
            severity="warning",
            message="High marks but very short question text",
            suggestion="A 15+ mark question should have more detail or sub-parts",
        )
    return None


def validate_module_alignment(
    retrieved_contexts: list[RetrievedContext],
    module_number: int | None,
) -> ValidationIssue | None:
    if module_number is None or not retrieved_contexts:
        return None

    explicit_modules = {
        context.module_number
        for context in retrieved_contexts
        if context.module_number is not None
    }
    if not explicit_modules:
        return ValidationIssue(
            category="module",
            severity="warning",
            message="Question could not be verified against a classified module boundary",
            suggestion="Review the source chunk metadata before using this question",
        )

    if explicit_modules == {module_number}:
        return None

    return ValidationIssue(
        category="module",
        severity="error",
        message=(
            f"Retrieved evidence crosses module boundaries for a Module {module_number} question "
            f"(found: {', '.join(f'Module {value}' for value in sorted(explicit_modules))})"
        ),
        suggestion="Restrict retrieval and generation to chunks from the requested module only",
    )


def _normalized_shingles(text: str, width: int = 8) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    if len(tokens) < width:
        return set()
    return {" ".join(tokens[index:index + width]) for index in range(len(tokens) - width + 1)}


def validate_source_leakage(
    question_text: str,
    retrieved_contexts: list[RetrievedContext],
) -> ValidationIssue | None:
    if not retrieved_contexts:
        return None

    question_shingles = _normalized_shingles(question_text, width=8)
    if not question_shingles:
        return None

    max_overlap = 0
    for context in retrieved_contexts:
        context_shingles = _normalized_shingles(context.clean_text or context.text, width=8)
        if not context_shingles:
            continue
        overlap = len(question_shingles & context_shingles)
        max_overlap = max(max_overlap, overlap)

    if max_overlap >= 2:
        return ValidationIssue(
            category="source-leakage",
            severity="error",
            message="Question wording appears to copy a long phrase from the source material",
            suggestion="Rephrase the stem so it reads like an authored VTU question, not a note fragment",
        )
    return None


def validate_duplicate(
    question_text: str,
    existing_questions: list[str],
    threshold: float = 0.85,
) -> ValidationIssue | None:
    """Check for semantic duplication against existing questions."""
    if not existing_questions:
        return None

    q_embedding = generate_embedding(question_text)
    normalized_question = " ".join(re.findall(r"[a-z0-9]+", question_text.lower()))
    if not q_embedding:
        for existing in existing_questions:
            normalized_existing = " ".join(re.findall(r"[a-z0-9]+", existing.lower()))
            if normalized_existing and normalized_existing == normalized_question:
                return ValidationIssue(
                    category="duplicate",
                    severity="error",
                    message="Question is an exact duplicate of an existing question",
                    suggestion="Use a different concept or reframe the question intent",
                )
        return None

    for existing in existing_questions:
        normalized_existing = " ".join(re.findall(r"[a-z0-9]+", existing.lower()))
        if normalized_existing and normalized_existing == normalized_question:
            return ValidationIssue(
                category="duplicate",
                severity="error",
                message="Question is an exact duplicate of an existing question",
                suggestion="Use a different concept or reframe the question intent",
            )
        existing_embedding = generate_embedding(existing)
        if existing_embedding:
            similarity = cosine_similarity(q_embedding, existing_embedding)
            if similarity >= threshold:
                return ValidationIssue(
                    category="duplicate",
                    severity="error",
                    message=f"Question is semantically similar to an existing question (similarity: {similarity:.2f})",
                    suggestion="Rephrase significantly or use a different topic",
                )
    return None


def validate_syllabus_compliance(
    question_text: str,
    topic_name: str | None,
    module_number: int | None,
    syllabus_topics: list[str] | None,
    *,
    strict: bool = False,
) -> ValidationIssue | None:
    """Check if the question aligns with the syllabus."""
    if not syllabus_topics:
        return None  # Can't validate without syllabus

    q_lower = question_text.lower()
    
    # 1. Check topic name match first
    if topic_name:
        topic_lower = topic_name.lower().strip()
        for syllabus_topic in syllabus_topics:
            s_topic_lower = syllabus_topic.lower().strip()
            if topic_lower in s_topic_lower or s_topic_lower in topic_lower:
                return None  # Direct match

    # 2. Check question text against syllabus topics using smart overlap and boundaries
    for syllabus_topic in syllabus_topics:
        s_topic_lower = syllabus_topic.lower().strip()
        # Direct phrase match in question text
        if s_topic_lower in q_lower:
            return None
            
        # Check for word boundaries of short acronyms/terms (e.g., DFS, RAG, NLP)
        short_words = [w for w in re.findall(r"\b\w{3,}\b", s_topic_lower) if w not in {"the", "and", "for", "with", "out"}]
        if short_words:
            # Check if all words in a multi-word short phrase appear in the question
            if all(f"\\b{re.escape(w)}\\b" for w in short_words):
                pattern = r".*?".join(rf"\b{re.escape(w)}\b" for w in short_words)
                if re.search(pattern, q_lower):
                    return None
            
            # General overlap count for longer terms
            topic_words = set(re.findall(r"\w{3,}", s_topic_lower)) - {"the", "and", "for", "with", "out", "from", "each", "both", "their"}
            q_words = set(re.findall(r"\w{3,}", q_lower))
            overlap = topic_words & q_words
            # If the topic is short (1-2 words), we need high overlap. If longer, 2 words overlap is usually sufficient.
            min_overlap = min(len(topic_words), 2)
            if len(overlap) >= min_overlap:
                return None

    # Topic mapping/explanation suggestion
    suggested_topic = syllabus_topics[0] if syllabus_topics else "a valid syllabus topic"
    module_suffix = f" for Module {module_number}" if module_number is not None else ""
    return ValidationIssue(
        category="syllabus",
        severity="error" if strict else "warning",
        message=f"Question topic may not align with the subject syllabus{module_suffix}",
        suggestion=f"Ensure the question strictly addresses syllabus topics such as: '{suggested_topic}'",
    )


def validate_semantic_uniqueness(
    question_text: str,
    existing_questions: list[str],
    threshold: float = 0.85,
) -> ValidationIssue | None:
    """Check if the question is semantically too similar to existing questions."""
    if not existing_questions:
        return None

    q_embedding = generate_embedding(question_text)
    if not q_embedding:
        return None

    best_score = 0.0
    for existing in existing_questions:
        e_embedding = generate_embedding(existing)
        if e_embedding:
            score = cosine_similarity(q_embedding, e_embedding)
            if score > best_score:
                best_score = score

    if best_score >= threshold:
        return ValidationIssue(
            category="duplicate",
            severity="error",
            message=f"Question is too similar to an existing question (similarity: {best_score:.2f})",
            suggestion="Rephrase the question to test a different aspect or use a different context.",
        )
    return None

# ---------------------------------------------------------------------------
# Complete validation pipeline
# ---------------------------------------------------------------------------

def validate_question(
    question_text: str,
    marks: int,
    bloom_level: str,
    co_mapping: str,
    *,
    retrieved_contexts: list[RetrievedContext] | None = None,
    existing_questions: list[str] | None = None,
    syllabus_topics: list[str] | None = None,
    co_definitions: dict[str, str] | None = None,
    topic_name: str | None = None,
    module_number: int | None = None,
    strict_syllabus: bool = False,
) -> ValidationResult:
    """
    Run the complete validation pipeline on a generated question.

    Returns ValidationResult with is_valid=False if any errors are found.
    """
    issues: list[ValidationIssue] = []

    # 1. Topic in context (CRITICAL anti-hallucination)
    if retrieved_contexts is not None:
        issue = validate_topic_in_context(question_text, retrieved_contexts)
        if issue:
            issues.append(issue)
        issue = validate_module_alignment(retrieved_contexts, module_number)
        if issue:
            issues.append(issue)
        issue = validate_source_leakage(question_text, retrieved_contexts)
        if issue:
            issues.append(issue)

    # 1.5 Semantic Uniqueness Check
    if existing_questions:
        issue = validate_semantic_uniqueness(question_text, existing_questions)
        if issue:
            issues.append(issue)

    # 2. Bloom level compliance
    issue = validate_bloom_level(question_text, bloom_level)
    if issue:
        issues.append(issue)

    # 3. CO alignment
    issue = validate_co_alignment(question_text, co_mapping, bloom_level, co_definitions)
    if issue:
        issues.append(issue)

    # 4. VTU phrasing
    phrasing_issues = validate_vtu_phrasing(question_text)
    issues.extend(phrasing_issues)

    # 5. Structural integrity / anti-leakage
    structural_issues = validate_structural_integrity(question_text, topic_name)
    issues.extend(structural_issues)

    # 6. Marks appropriateness
    issue = validate_marks_appropriateness(marks, bloom_level, question_text)
    if issue:
        issues.append(issue)

    # 7. Duplicate check
    if existing_questions:
        issue = validate_duplicate(question_text, existing_questions)
        if issue:
            issues.append(issue)

    # 8. Syllabus compliance
    if syllabus_topics:
        issue = validate_syllabus_compliance(
            question_text,
            topic_name,
            module_number,
            syllabus_topics,
            strict=strict_syllabus,
        )
        if issue:
            issues.append(issue)

    # Determine validity
    has_errors = any(i.severity == "error" for i in issues)
    warning_count = sum(1 for i in issues if i.severity == "warning")
    confidence = 1.0 - (0.3 * len([i for i in issues if i.severity == "error"])) - (0.1 * warning_count)
    confidence = max(0.0, min(1.0, confidence))

    return ValidationResult(
        is_valid=not has_errors,
        issues=issues,
        confidence=round(confidence, 3),
    )
