"""
Multi-source retrieval system for retrieval-constrained generation.

Retrieves relevant academic chunks from:
- Notes
- Question Banks
- Previous Papers

Syllabus content is used only as a constraint source for module and topic
boundaries. It is never passed as direct generation evidence.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .embeddings import cosine_similarity, generate_embedding
from .models import (
    AcademicDocument,
    ChunkApprovalStatus,
    DocumentType,
    KnowledgeChunk,
    QuestionGenerationProfile,
    SubjectSyllabus,
    ExtractedImage,
    ConceptNode,
)

logger = logging.getLogger("app.academic.retrieval")

_TOPIC_MATCH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "for",
    "from",
    "how",
    "into",
    "its",
    "of",
    "the",
    "their",
    "this",
    "with",
}


def _normalize_chunk_key(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return normalized[:220]


@lru_cache(maxsize=128)
def _cached_query_embedding(query: str) -> tuple[float, ...] | None:
    embedding = generate_embedding(query)
    if embedding is None:
        return None
    return tuple(float(value) for value in embedding)


def _normalize_topic_key(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9\s-]", " ", text.lower())
    normalized = re.sub(r"\b(module|unit|chapter|topic|section)\b", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized[:120]


def _clean_context_text(text: str) -> str:
    lines: list[str] = []
    seen: set[str] = set()

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            continue
        if re.fullmatch(r"page \d+(\s+of\s+\d+)?", line, flags=re.IGNORECASE):
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if re.fullmatch(r"(module|unit|chapter)\s*[-:]?\s*\d+", line, flags=re.IGNORECASE):
            continue
        if re.fullmatch(r"[A-Z0-9\s\-\.:]{3,}", line) and len(line.split()) > 6:
            line = line.title()

        line = re.sub(r"\bfig(?:ure)?\.?\s*\d+\b", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\btable\s*\d+\b", "", line, flags=re.IGNORECASE)
        line = re.sub(r"[_*~`]+", " ", line)
        line = re.sub(r"\s+", " ", line).strip(" -:;,.")
        if len(line) < 12:
            continue

        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        lines.append(line)

    cleaned = " ".join(lines)
    cleaned = re.sub(r"\b(?:module|unit|chapter)\s*\d+\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[a-z]{1,3}\d{2,}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _summarize_context_text(clean_text: str) -> str:
    if not clean_text:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", clean_text)
    informative: list[str] = []
    for sentence in sentences:
        snippet = sentence.strip()
        if len(snippet.split()) < 4:
            continue
        informative.append(snippet)
        if len(informative) == 2:
            break

    summary = " ".join(informative) if informative else clean_text
    words = summary.split()
    if len(words) > 42:
        summary = " ".join(words[:42]).strip()
    return summary


def _context_quality_score(clean_text: str) -> float:
    if not clean_text:
        return 0.0

    words = clean_text.split()
    if len(words) < 6:
        return 0.1

    alpha_chars = sum(1 for char in clean_text if char.isalpha())
    digit_chars = sum(1 for char in clean_text if char.isdigit())
    upper_words = sum(1 for word in words if len(word) > 2 and word.isupper())
    weird_tokens = sum(1 for word in words if re.search(r"[^A-Za-z0-9(),.%/-]", word))

    alpha_ratio = alpha_chars / max(len(clean_text), 1)
    digit_penalty = min(0.18, digit_chars / max(len(clean_text), 1))
    upper_penalty = min(0.2, upper_words / max(len(words), 1))
    weird_penalty = min(0.16, weird_tokens / max(len(words), 1))
    score = 0.45 + (alpha_ratio * 0.6) - digit_penalty - upper_penalty - weird_penalty
    return max(0.0, min(1.0, round(score, 3)))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RetrievedContext:
    """A ranked chunk with source metadata for generation."""
    chunk_id: int
    text: str
    clean_text: str
    concept_summary: str
    relevance_score: float
    quality_score: float
    source_type: str  # notes, question_bank, previous_paper, syllabus
    document_name: str
    module_number: int | None = None
    topic_name: str | None = None
    bloom_level: str | None = None
    co_mapping: str | None = None
    topic_key: str = ""


@dataclass
class RetrievalResult:
    """Complete retrieval result for a generation request."""
    contexts: list[RetrievedContext]
    total_retrieved: int
    sources_used: list[str]
    topics_covered: list[str]
    syllabus_topics: list[str] = field(default_factory=list)
    module_topic_map: dict[int, list[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Source type mapping
# ---------------------------------------------------------------------------

_DOC_TYPE_TO_SOURCE = {
    DocumentType.NOTES: "notes",
    DocumentType.QUESTION_BANK: "question_bank",
    DocumentType.PREVIOUS_PAPER: "previous_paper",
    DocumentType.SYLLABUS: "syllabus",
    DocumentType.LAB_MANUAL: "notes",
    DocumentType.PPT: "notes",
    DocumentType.OTHER: "notes",
}


# ---------------------------------------------------------------------------
# Multi-source retrieval
# ---------------------------------------------------------------------------

def _is_chunk_syllabus_compliant(
    chunk_text: str,
    chunk_topic: str | None,
    allowed_topics: list[str],
) -> bool:
    if not allowed_topics:
        return True
        
    text_lower = chunk_text.lower()
    topic_lower = chunk_topic.lower().strip() if chunk_topic else ""
    
    for s_topic in allowed_topics:
        s_topic_lower = s_topic.lower().strip()
        if s_topic_lower in text_lower:
            return True
        if topic_lower and (topic_lower in s_topic_lower or s_topic_lower in topic_lower):
            return True
            
        # Word boundary overlap match for short acronyms/phrases
        topic_words = set(re.findall(r"\w{3,}", s_topic_lower)) - {"the", "and", "for", "with", "out", "from", "each", "both", "their"}
        text_words = set(re.findall(r"\w{3,}", text_lower))
        overlap = topic_words & text_words
        min_overlap = min(len(topic_words), 2)
        if len(overlap) >= min_overlap:
            return True
            
    return False


def retrieve_for_generation(
    db: Session,
    subject_id: int,
    query: str,
    *,
    use_notes: bool = True,
    use_question_bank: bool = True,
    use_previous_papers: bool = False,
    use_syllabus: bool = True,
    module_filter: int | None = None,
    module_allowlist: list[int] | None = None,
    module_co_mapping: dict[int, list[str]] | None = None,
    bloom_filter: str | None = None,
    co_filter: str | None = None,
    top_k: int = 30,
    min_relevance: float = 0.25,
    strict_syllabus: bool = False,
) -> RetrievalResult:
    """
    Retrieve relevant academic chunks for question generation.

    This is the core retrieval function that feeds the constrained LLM.

    Args:
        db: Database session.
        subject_id: Subject to retrieve from.
        query: Generation prompt / topic query.
        use_notes: Include notes chunks.
        use_question_bank: Include question bank chunks.
        use_previous_papers: Include previous paper chunks.
        use_syllabus: Load syllabus constraints for validation and topic bounds.
        module_filter: Optional module number filter.
        module_allowlist: Optional module whitelist for multi-module paper plans.
        bloom_filter: Optional Bloom level filter.
        co_filter: Optional CO filter.
        top_k: Max number of chunks to return.
        min_relevance: Minimum relevance score threshold.

    Returns:
        RetrievalResult with ranked contexts.
    """
    # Determine which document types to include
    allowed_types: set[DocumentType] = set()
    if use_notes:
        allowed_types.update({DocumentType.NOTES, DocumentType.LAB_MANUAL, DocumentType.PPT})
    if use_question_bank:
        allowed_types.add(DocumentType.QUESTION_BANK)
    if use_previous_papers:
        allowed_types.add(DocumentType.PREVIOUS_PAPER)

    # Load syllabus early if requested so we can filter chunks
    syllabus_topics, module_topic_map = _load_syllabus_topics(db, subject_id) if use_syllabus else ([], {})

    normalized_module_allowlist = sorted(
        {
            int(module)
            for module in (module_allowlist or [])
            if isinstance(module, int) or (isinstance(module, str) and str(module).isdigit())
        }
    )
    if module_filter is not None and module_filter not in normalized_module_allowlist:
        normalized_module_allowlist.append(module_filter)

    if not allowed_types:
        return RetrievalResult(
            contexts=[],
            total_retrieved=0,
            sources_used=[],
            topics_covered=[],
            syllabus_topics=syllabus_topics,
            module_topic_map=module_topic_map,
        )

    # Get document IDs for allowed types
    doc_ids_stmt = (
        select(AcademicDocument.id, AcademicDocument.document_type, AcademicDocument.file_name)
        .where(
            AcademicDocument.subject_id == subject_id,
            AcademicDocument.document_type.in_(allowed_types),
        )
    )
    doc_rows = db.execute(doc_ids_stmt).all()
    doc_info = {row.id: (row.document_type, row.file_name) for row in doc_rows}

    if not doc_info:
        return RetrievalResult(
            contexts=[],
            total_retrieved=0,
            sources_used=[],
            topics_covered=[],
            syllabus_topics=syllabus_topics,
            module_topic_map=module_topic_map,
        )

    # Fetch approved chunks from allowed documents
    chunks_stmt = (
        select(KnowledgeChunk)
        .where(
            KnowledgeChunk.subject_id == subject_id,
            KnowledgeChunk.document_id.in_(doc_info.keys()),
            KnowledgeChunk.approval_status.in_([
                ChunkApprovalStatus.AUTO_APPROVED,
                ChunkApprovalStatus.APPROVED,
                ChunkApprovalStatus.EDITED,
            ]),
        )
    )

    if bloom_filter:
        chunks_stmt = chunks_stmt.where(KnowledgeChunk.bloom_level == bloom_filter)
    if co_filter:
        chunks_stmt = chunks_stmt.where(KnowledgeChunk.co_mapping == co_filter)
    if normalized_module_allowlist:
        chunks_stmt = chunks_stmt.where(
            KnowledgeChunk.module_number.in_(normalized_module_allowlist)
        )
    if module_filter is not None:
        chunks_stmt = chunks_stmt.where(KnowledgeChunk.module_number == module_filter)

    chunks = list(db.scalars(chunks_stmt))

    # --- CO Firewall (Stage 1): Strict Global Filtering ---
    if module_co_mapping:
        filtered_chunks_by_co = []
        for chunk in chunks:
            chunk_mod = chunk.module_number
            if chunk_mod is None:
                # If chunk has no module, it can't be mapped. Keep it if it has no CO, or if its CO is in ANY of the allowed COs across all modules
                if not chunk.co_mapping:
                    filtered_chunks_by_co.append(chunk)
                else:
                    all_allowed_cos = {co.upper() for cos in module_co_mapping.values() for co in cos}
                    if chunk.co_mapping.upper() in all_allowed_cos:
                        filtered_chunks_by_co.append(chunk)
                continue
            
            allowed_cos = module_co_mapping.get(chunk_mod, [])
            if allowed_cos:
                # Chunk must match the allowed COs for its module
                if chunk.co_mapping and chunk.co_mapping.upper() not in [co.upper() for co in allowed_cos]:
                    continue
            filtered_chunks_by_co.append(chunk)
            
        logger.info(
            "CO Firewall: Reduced chunks from %s to %s for subject %s",
            len(chunks), len(filtered_chunks_by_co), subject_id
        )
        chunks = filtered_chunks_by_co

    # Apply strict Syllabus-Aware Filtering if syllabus is available and strict mode is on
    allowed_topics_for_scoring: list[str] = []
    if use_syllabus and syllabus_topics:
        # Determine allowed topics for the target modules
        if module_filter is not None:
            allowed_topics_for_scoring.extend(module_topic_map.get(module_filter, []))
        elif normalized_module_allowlist:
            for m in normalized_module_allowlist:
                allowed_topics_for_scoring.extend(module_topic_map.get(m, []))
        else:
            allowed_topics_for_scoring.extend(syllabus_topics)
            
        if allowed_topics_for_scoring and strict_syllabus:
            filtered_chunks = []
            for chunk in chunks:
                if _is_chunk_syllabus_compliant(chunk.chunk_text, chunk.topic_name, allowed_topics_for_scoring):
                    filtered_chunks.append(chunk)
            
            logger.info(
                "Syllabus-Aware Filtering: Reduced target chunks from %s to %s for subject %s",
                len(chunks), len(filtered_chunks), subject_id
            )
            chunks = filtered_chunks

    # --- Marks-Based Question Intelligence (Stage 3): Fetch ConceptNodes ---
    concept_stmt = (
        select(ConceptNode)
        .where(
            ConceptNode.subject_id == subject_id,
            ConceptNode.document_id.in_(doc_info.keys()),
        )
    )
    if normalized_module_allowlist:
        concept_stmt = concept_stmt.where(ConceptNode.module_number.in_(normalized_module_allowlist))
    if module_filter is not None:
        concept_stmt = concept_stmt.where(ConceptNode.module_number == module_filter)
        
    concept_nodes = list(db.scalars(concept_stmt))

    # --- CO Firewall (Stage 2): Filter Concept Nodes ---
    if module_co_mapping:
        filtered_concepts_by_co = []
        for node in concept_nodes:
            node_mod = node.module_number
            if node_mod is None:
                filtered_concepts_by_co.append(node)
                continue
            
            allowed_cos = module_co_mapping.get(node_mod, [])
            # For concept nodes we don't have a direct co_mapping field, but we assume they map to the module's target CO
            filtered_concepts_by_co.append(node)
        # concept_nodes = filtered_concepts_by_co # Concept nodes don't inherently have a CO, they belong to a module. Module filtering is sufficient.

    if not chunks and not concept_nodes:
        return RetrievalResult(
            contexts=[],
            total_retrieved=0,
            sources_used=[],
            topics_covered=[],
            syllabus_topics=syllabus_topics,
            module_topic_map=module_topic_map,
        )

    query_embedding = None
    if any(chunk.embedding_vector for chunk in chunks):
        normalized_query = re.sub(r"\s+", " ", query).strip().lower()[:600]
        cached_embedding = _cached_query_embedding(normalized_query)
        if cached_embedding is not None:
            query_embedding = list(cached_embedding)

    # Score and rank chunks
    scored_contexts: list[RetrievedContext] = []

    for chunk in chunks:
        doc_type, doc_name = doc_info.get(chunk.document_id, (DocumentType.NOTES, "Unknown"))
        source_type = _DOC_TYPE_TO_SOURCE.get(doc_type, "notes")
        clean_text = _clean_context_text(chunk.chunk_text)
        if not clean_text:
            continue

        quality_score = _context_quality_score(clean_text)
        if quality_score < 0.38:
            continue

        concept_summary = _summarize_context_text(clean_text)
        topic_label = (chunk.topic_name or concept_summary or doc_name).strip()
        topic_key = _normalize_topic_key(topic_label or clean_text[:120])

        # Compute relevance score
        score = 0.0
        if query_embedding and chunk.embedding_vector:
            score = cosine_similarity(query_embedding, chunk.embedding_vector)
        else:
            # Text-based fallback
            query_lower = query.lower()
            chunk_lower = clean_text.lower()
            query_words = set(query_lower.split())
            chunk_words = set(chunk_lower.split())
            overlap = len(query_words & chunk_words)
            score = min(1.0, overlap / max(len(query_words), 1) * 0.8)

        # Boost scores
        if chunk.confidence_score >= 0.7:
            score *= 1.1
        if source_type == "notes":
            score *= 1.08
        if source_type == "question_bank":
            score *= 1.02
        if source_type == "previous_paper":
            score *= 0.98
        score *= 0.85 + (quality_score * 0.25)
        if module_filter is not None:
            if chunk.module_number == module_filter:
                score *= 1.25
        
        # Syllabus bonus if not in strict mode but matches
        if not strict_syllabus and allowed_topics_for_scoring:
            if _is_chunk_syllabus_compliant(clean_text, chunk.topic_name, allowed_topics_for_scoring):
                score *= 1.15

        if score < min_relevance:
            continue

        scored_contexts.append(RetrievedContext(
            chunk_id=chunk.id,
            text=chunk.chunk_text,
            clean_text=clean_text,
            concept_summary=concept_summary,
            relevance_score=round(score, 4),
            quality_score=quality_score,
            source_type=source_type,
            document_name=doc_name,
            module_number=chunk.module_number,
            topic_name=chunk.topic_name,
            bloom_level=chunk.bloom_level,
            co_mapping=chunk.co_mapping,
            topic_key=topic_key,
        ))

    # Incorporate ConceptNodes into scored_contexts
    for cnode in concept_nodes:
        doc_type, doc_name = doc_info.get(cnode.document_id, (DocumentType.NOTES, "Unknown"))
        clean_text = _clean_context_text(cnode.content)
        if not clean_text:
            continue
            
        topic_label = (cnode.topic or doc_name).strip()
        topic_key = _normalize_topic_key(topic_label)
        
        # Base relevance for ConceptNodes is very high because they are curated
        score = 0.95
        if module_filter is not None and cnode.module_number == module_filter:
            score *= 1.25
            
        # Prioritize based on requested properties if possible, else just add them
        scored_contexts.append(RetrievedContext(
            chunk_id=cnode.id + 1000000, # Offset ID to avoid conflicts with KnowledgeChunk
            text=f"CONCEPT: {cnode.topic} ({cnode.node_type})\n{cnode.content}",
            clean_text=clean_text,
            concept_summary=cnode.topic,
            relevance_score=round(score, 4),
            quality_score=0.9,
            source_type="concept_graph",
            document_name=doc_name,
            module_number=cnode.module_number,
            topic_name=cnode.topic,
            bloom_level=None,
            co_mapping=None,
            topic_key=topic_key,
        ))

    # Sort by relevance, then diversify by topic to reduce repeated concept selection.
    scored_contexts.sort(key=lambda c: c.relevance_score, reverse=True)
    deduped_contexts: list[RetrievedContext] = []
    seen_keys: set[str] = set()
    seen_topics: set[str] = set()

    for context in scored_contexts:
        key = _normalize_chunk_key(context.clean_text)
        if key in seen_keys:
            continue
        if context.topic_key and context.topic_key in seen_topics:
            continue
        seen_keys.add(key)
        if context.topic_key:
            seen_topics.add(context.topic_key)
        deduped_contexts.append(context)
        if len(deduped_contexts) >= top_k:
            break

    if len(deduped_contexts) < top_k:
        for context in scored_contexts:
            key = _normalize_chunk_key(context.clean_text)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped_contexts.append(context)
            if len(deduped_contexts) >= top_k:
                break

    top_contexts = deduped_contexts

    # Collect metadata
    sources_used = sorted(set(c.source_type for c in top_contexts))
    topics_covered = sorted(set(c.topic_name for c in top_contexts if c.topic_name))

    return RetrievalResult(
        contexts=top_contexts,
        total_retrieved=len(top_contexts),
        sources_used=sources_used,
        topics_covered=topics_covered,
        syllabus_topics=syllabus_topics,
        module_topic_map=module_topic_map,
    )


def get_generation_sources(
    db: Session, subject_id: int
) -> dict[str, bool]:
    """Get the configured source toggles for a subject."""
    profile = db.scalar(
        select(QuestionGenerationProfile).where(
            QuestionGenerationProfile.subject_id == subject_id
        )
    )
    if profile:
        return {
            "use_notes": profile.use_notes,
            "use_question_bank": profile.use_question_bank,
            "use_previous_papers": profile.use_previous_papers,
            "use_syllabus": profile.use_syllabus,
        }
    return {
        "use_notes": True,
        "use_question_bank": True,
        "use_previous_papers": False,
        "use_syllabus": True,
    }


def _load_syllabus_topics(db: Session, subject_id: int) -> tuple[list[str], dict[int, list[str]]]:
    flat_topics: list[str] = []
    module_map: dict[int, list[str]] = {}

    syllabus = db.scalar(
        select(SubjectSyllabus).where(SubjectSyllabus.subject_id == subject_id)
    )
    if syllabus is not None:
        for module_entry in syllabus.modules_json or []:
            if not isinstance(module_entry, dict):
                continue
            module_number = module_entry.get("module") or module_entry.get("module_number")
            topics = [
                re.sub(r"\s+", " ", str(topic)).strip()
                for topic in (module_entry.get("topics") or [])
                if str(topic).strip()
            ]
            for topic in topics:
                if topic not in flat_topics:
                    flat_topics.append(topic)
            if isinstance(module_number, (int, str)) and topics:
                try:
                    module_map[int(module_number)] = topics
                except ValueError:
                    pass

        if not flat_topics and syllabus.syllabus_text:
            flat_topics.extend(_extract_topics_from_text(syllabus.syllabus_text))

    syllabus_doc_rows = db.execute(
        select(KnowledgeChunk.module_number, KnowledgeChunk.topic_name)
        .join(AcademicDocument, AcademicDocument.id == KnowledgeChunk.document_id)
        .where(
            KnowledgeChunk.subject_id == subject_id,
            AcademicDocument.document_type == DocumentType.SYLLABUS,
            KnowledgeChunk.approval_status.in_([
                ChunkApprovalStatus.AUTO_APPROVED,
                ChunkApprovalStatus.APPROVED,
                ChunkApprovalStatus.EDITED,
            ]),
        )
    ).all()

    for module_number, topic_name in syllabus_doc_rows:
        topic = re.sub(r"\s+", " ", str(topic_name or "")).strip()
        if not topic:
            continue
        if topic not in flat_topics:
            flat_topics.append(topic)
        if isinstance(module_number, int):
            module_map.setdefault(module_number, [])
            if topic not in module_map[module_number]:
                module_map[module_number].append(topic)

    return flat_topics, module_map


def _extract_topics_from_text(text: str) -> list[str]:
    topics: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip(" -:;,.")
        if len(line.split()) < 2:
            continue
        if len(line) > 120:
            line = " ".join(line.split()[:16])
        if line.lower() not in {topic.lower() for topic in topics}:
            topics.append(line)
        if len(topics) >= 40:
            break
    return topics


def retrieve_diagrams_for_topic(
    db: Session,
    subject_id: int,
    topic: str,
    limit: int = 5,
) -> list[ExtractedImage]:
    """
    Search ExtractedImage database records for diagrams matching a topic or its keywords.
    """
    # Query all images for the subject
    images = list(
        db.scalars(
            select(ExtractedImage)
            .where(ExtractedImage.subject_id == subject_id)
            .order_by(ExtractedImage.created_at.desc())
        )
    )
    if not images:
        return []
        
    topic_lower = topic.lower().strip()
    topic_words = set(re.findall(r"\w{3,}", topic_lower)) - {"the", "and", "for", "with", "out", "from", "each", "both", "their"}
    
    scored: list[tuple[ExtractedImage, float]] = []
    for img in images:
        # Check keyword overlaps
        score = 0.0
        # If the direct caption or keywords match
        if img.ai_caption and topic_lower in img.ai_caption.lower():
            score += 0.8
            
        # Match keywords list
        img_keywords = [str(kw).lower() for kw in (img.keywords or [])]
        overlap_count = 0
        for kw in img_keywords:
            if kw in topic_lower:
                score += 0.4
            # Check word boundary overlap
            kw_words = set(re.findall(r"\w{3,}", kw))
            overlap = kw_words & topic_words
            if overlap:
                score += 0.25 * len(overlap)
                
        if score > 0.0:
            scored.append((img, score))
            
    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)
    return [img for img, _ in scored[:limit]]


def _image_attachment_payload(
    image: ExtractedImage,
    *,
    document_name: str | None = None,
    score: float | None = None,
) -> dict[str, Any]:
    return {
        "image_id": image.id,
        "image_path": image.image_path,
        "caption": image.ai_caption or "Extracted academic diagram",
        "keywords": list(image.keywords or []),
        "source_page": image.source_page,
        "width": image.width,
        "height": image.height,
        "document_name": document_name or "",
        "relevance_score": round(float(score or 0.0), 4),
    }


def list_subject_image_pool(
    db: Session,
    subject_id: int,
    *,
    limit: int = 24,
) -> list[dict[str, Any]]:
    image_rows = db.execute(
        select(ExtractedImage, AcademicDocument.file_name)
        .join(AcademicDocument, AcademicDocument.id == ExtractedImage.document_id)
        .where(ExtractedImage.subject_id == subject_id)
        .order_by(ExtractedImage.created_at.desc())
        .limit(limit)
    ).all()
    return [
        _image_attachment_payload(image, document_name=file_name)
        for image, file_name in image_rows
    ]


def retrieve_diagrams_for_question(
    db: Session,
    subject_id: int,
    question_text: str,
    *,
    topic: str | None = None,
    module_number: int | None = None,
    source_documents: list[str] | None = None,
    limit: int = 2,
) -> list[dict[str, Any]]:
    """
    Match extracted diagrams to a generated question using topic, caption, keyword,
    and source-document hints. Returns lightweight attachment payloads.
    """
    image_rows = db.execute(
        select(ExtractedImage, AcademicDocument.file_name)
        .join(AcademicDocument, AcademicDocument.id == ExtractedImage.document_id)
        .where(ExtractedImage.subject_id == subject_id)
        .order_by(ExtractedImage.created_at.desc())
    ).all()
    if not image_rows:
        return []

    question_lower = re.sub(r"\s+", " ", str(question_text or "").lower()).strip()
    topic_lower = re.sub(r"\s+", " ", str(topic or "").lower()).strip()
    question_terms = set(re.findall(r"\w{3,}", question_lower)) - _TOPIC_MATCH_STOPWORDS
    topic_terms = set(re.findall(r"\w{3,}", topic_lower)) - _TOPIC_MATCH_STOPWORDS
    desired_documents = {str(name).lower().strip() for name in (source_documents or []) if str(name).strip()}
    visual_trigger = any(
        token in question_lower
        for token in (
            "diagram",
            "figure",
            "flow",
            "workflow",
            "architecture",
            "block",
            "illustrate",
            "sketch",
            "draw",
            "label",
        )
    )

    scored: list[tuple[float, ExtractedImage, str]] = []
    for image, file_name in image_rows:
        score = 0.0
        caption_lower = str(image.ai_caption or "").lower()
        keyword_terms = {
            term
            for keyword in (image.keywords or [])
            for term in re.findall(r"\w{3,}", str(keyword).lower())
        } - _TOPIC_MATCH_STOPWORDS

        if topic_lower and topic_lower in caption_lower:
            score += 0.95
        if topic_terms:
            overlap = topic_terms & keyword_terms
            if overlap:
                score += 0.3 + (0.15 * min(len(overlap), 3))
        if question_terms:
            overlap = question_terms & keyword_terms
            if overlap:
                score += 0.2 + (0.08 * min(len(overlap), 4))
        if caption_lower:
            caption_terms = set(re.findall(r"\w{3,}", caption_lower)) - _TOPIC_MATCH_STOPWORDS
            if topic_terms:
                score += 0.12 * min(len(topic_terms & caption_terms), 3)
            if question_terms:
                score += 0.06 * min(len(question_terms & caption_terms), 4)

        file_name_lower = str(file_name or "").lower().strip()
        if desired_documents and file_name_lower in desired_documents:
            score += 0.2
        if module_number is not None and str(module_number) in file_name_lower:
            score += 0.05
        if visual_trigger:
            score += 0.12

        if score >= (0.65 if visual_trigger else 0.95):
            scored.append((score, image, file_name))

    scored.sort(key=lambda item: item[0], reverse=True)
    seen_ids: set[int] = set()
    attachments: list[dict[str, Any]] = []
    for score, image, file_name in scored:
        if image.id in seen_ids:
            continue
        seen_ids.add(image.id)
        attachments.append(
            _image_attachment_payload(image, document_name=file_name, score=score)
        )
        if len(attachments) >= limit:
            break
    return attachments
