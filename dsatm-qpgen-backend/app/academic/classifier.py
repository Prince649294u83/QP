"""
Academic metadata classifier for knowledge chunks.

Infers:
- Module number from syllabus context
- Bloom's taxonomy level from content patterns
- Course outcome mapping
- Topic name
- Confidence score
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger("app.academic.classifier")

# ---------------------------------------------------------------------------
# Bloom's Taxonomy keyword mapping
# ---------------------------------------------------------------------------

BLOOM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "L1": (
        "define", "list", "state", "name", "identify", "recall",
        "recognize", "label", "match", "select", "memorize",
    ),
    "L2": (
        "explain", "describe", "discuss", "summarize", "outline",
        "interpret", "classify", "illustrate", "paraphrase", "translate",
    ),
    "L3": (
        "solve", "calculate", "apply", "demonstrate", "implement",
        "compute", "execute", "use", "operate", "practice",
    ),
    "L4": (
        "analyze", "compare", "distinguish", "differentiate", "examine",
        "contrast", "categorize", "investigate", "break down", "organize",
    ),
    "L5": (
        "evaluate", "justify", "critique", "assess", "argue",
        "judge", "defend", "prioritize", "rate", "recommend",
    ),
    "L6": (
        "design", "develop", "construct", "create", "formulate",
        "propose", "synthesize", "compose", "invent", "plan",
    ),
}

# Reverse mapping: keyword -> level
_KEYWORD_TO_BLOOM: dict[str, str] = {}
for _level, _keywords in BLOOM_KEYWORDS.items():
    for _kw in _keywords:
        _KEYWORD_TO_BLOOM[_kw] = _level

# CO inference heuristics based on content type
CO_HEURISTICS: dict[str, list[str]] = {
    "CO1": ["definition", "concept", "introduction", "basics", "fundamental", "overview", "terminology"],
    "CO2": ["process", "method", "technique", "algorithm", "mechanism", "procedure"],
    "CO3": ["application", "implementation", "program", "code", "practical", "example", "experiment"],
    "CO4": ["analysis", "comparison", "performance", "efficiency", "complexity", "trade-off"],
    "CO5": ["design", "architecture", "system", "optimization", "improvement", "strategy"],
}

# Module detection patterns
MODULE_PATTERNS = [
    re.compile(r"\bmodule\s*[-:]?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bunit\s*[-:]?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bchapter\s*[-:]?\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bpart\s*[-:]?\s*(\d+)\b", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    """Result of classifying an academic chunk."""
    module_number: int | None
    topic_name: str | None
    bloom_level: str
    co_mapping: str
    confidence_score: float


def classify_chunk(
    chunk_text: str,
    source_section: str | None = None,
    syllabus_modules: list[dict] | None = None,
) -> ClassificationResult:
    """
    Classify a chunk of academic text.

    Args:
        chunk_text: The text content of the chunk.
        source_section: The section heading this chunk belongs to.
        syllabus_modules: Optional syllabus structure for topic matching.
            Format: [{"module": 1, "title": "...", "topics": ["...", ...]}]

    Returns:
        ClassificationResult with inferred metadata.
    """
    lowered = chunk_text.lower()
    confidence = 0.5  # Base confidence

    # --- Module Number ---
    module_number = _detect_module(chunk_text, source_section)
    if module_number is not None:
        confidence += 0.1

    # Try syllabus matching if no module found
    matched_topic = None
    if syllabus_modules:
        match_result = _match_to_syllabus(lowered, syllabus_modules)
        if match_result:
            if module_number is None:
                module_number = match_result["module"]
            matched_topic = match_result["topic"]
            confidence += 0.15

    # --- Topic Name ---
    topic_name = matched_topic or _extract_topic(chunk_text, source_section)
    if topic_name:
        confidence += 0.05

    # --- Bloom Level ---
    bloom_level = _infer_bloom_level(chunk_text)
    confidence += 0.05  # Always some signal from content type

    # --- CO Mapping ---
    co_mapping = _infer_co(lowered, bloom_level)
    confidence += 0.05

    # Clamp confidence
    confidence = min(1.0, max(0.0, confidence))

    return ClassificationResult(
        module_number=module_number,
        topic_name=topic_name,
        bloom_level=bloom_level,
        co_mapping=co_mapping,
        confidence_score=round(confidence, 3),
    )


def _detect_module(text: str, section: str | None) -> int | None:
    """Detect module number from text or section heading."""
    # Check section heading first
    if section:
        for pattern in MODULE_PATTERNS:
            match = pattern.search(section)
            if match:
                num = int(match.group(1))
                if 1 <= num <= 10:
                    return num

    # Then check chunk text
    for pattern in MODULE_PATTERNS:
        match = pattern.search(text)
        if match:
            num = int(match.group(1))
            if 1 <= num <= 10:
                return num

    return None


def _match_to_syllabus(
    lowered_text: str,
    syllabus_modules: list[dict],
) -> dict | None:
    """Match chunk content to syllabus topics using keyword overlap."""
    best_match = None
    best_score = 0

    for module_info in syllabus_modules:
        module_num = module_info.get("module", 0)
        module_title = str(module_info.get("title", "") or "")
        topics = module_info.get("topics", [])

        if module_title:
            title_words = set(re.findall(r"\w{3,}", module_title.lower()))
            text_words = set(re.findall(r"\w{3,}", lowered_text))
            title_overlap = len(title_words & text_words)
            if title_words:
                title_score = title_overlap / len(title_words)
                if title_score > best_score and title_score >= 0.35:
                    best_score = title_score
                    best_match = {"module": module_num, "topic": module_title}

        for topic in topics:
            topic_lower = topic.lower()
            # Simple keyword matching
            topic_words = set(re.findall(r"\w{3,}", topic_lower))
            text_words = set(re.findall(r"\w{3,}", lowered_text))

            overlap = len(topic_words & text_words)
            if topic_words:
                score = overlap / len(topic_words)
            else:
                score = 0

            if score > best_score and score >= 0.3:
                best_score = score
                best_match = {"module": module_num, "topic": topic}

    return best_match


def _extract_topic(text: str, section: str | None) -> str | None:
    """Extract a topic name from the chunk content."""
    # Use section heading if available
    if section:
        # Clean up section heading
        cleaned = re.sub(r"^(?:Module|Unit|Chapter)\s*[-:]?\s*\d+\s*[-:]?\s*", "", section, flags=re.IGNORECASE)
        cleaned = re.sub(r"^#{1,4}\s*", "", cleaned)
        cleaned = cleaned.strip()
        if cleaned and len(cleaned) < 200:
            return cleaned

    # Try to find a topic from the first line
    first_line = text.strip().split("\n")[0].strip()
    if first_line and len(first_line) < 200:
        # Remove numbering
        cleaned = re.sub(r"^\d+[\.\)]\s*", "", first_line)
        if cleaned and len(cleaned) > 5:
            return cleaned[:200]

    return None


def _infer_bloom_level(text: str) -> str:
    """Infer Bloom's taxonomy level from content patterns."""
    lowered = text.lower()
    
    # Count keyword matches for each level
    scores: dict[str, int] = {level: 0 for level in BLOOM_KEYWORDS}
    
    for keyword, level in _KEYWORD_TO_BLOOM.items():
        count = lowered.count(keyword)
        scores[level] += count

    # Content type heuristics
    if re.search(r"\b(?:theorem|proof|lemma|corollary)\b", lowered):
        scores["L4"] += 3
    if re.search(r"\b(?:example|e\.g\.|for instance)\b", lowered):
        scores["L3"] += 2
    if re.search(r"\b(?:code|program|function|class|def |import )\b", lowered):
        scores["L3"] += 3
    if re.search(r"[=+\-*/^].*\d", lowered):
        scores["L3"] += 2  # Mathematical content
    if re.search(r"\b(?:table|figure|diagram|fig\.|tab\.)\b", lowered):
        scores["L2"] += 1

    # Pick highest scoring level
    best_level = max(scores, key=lambda k: scores[k])
    if scores[best_level] == 0:
        return "L2"  # Default
    return best_level


def _infer_co(lowered_text: str, bloom_level: str) -> str:
    """Infer course outcome from content and bloom level."""
    # Score each CO based on keyword matches
    scores: dict[str, int] = {co: 0 for co in CO_HEURISTICS}

    for co, keywords in CO_HEURISTICS.items():
        for keyword in keywords:
            if keyword in lowered_text:
                scores[co] += 1

    # Bloom level hints
    bloom_to_co = {
        "L1": "CO1",
        "L2": "CO2",
        "L3": "CO3",
        "L4": "CO4",
        "L5": "CO5",
        "L6": "CO5",
    }
    default_co = bloom_to_co.get(bloom_level, "CO2")

    best_co = max(scores, key=lambda k: scores[k])
    if scores[best_co] == 0:
        return default_co
    return best_co
