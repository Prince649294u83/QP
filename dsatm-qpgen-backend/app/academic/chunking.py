"""
Semantic chunking engine for academic documents.

Strategy:
- 400-800 token chunks with 10-15% overlap
- Respects paragraph/section boundaries
- Preserves academic structure (headings, lists, formulas)
- Never splits mid-sentence
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger("app.academic.chunking")

# ---------------------------------------------------------------------------
# Token counting (lightweight, no external dependency required)
# ---------------------------------------------------------------------------

def count_tokens(text: str) -> int:
    """Approximate token count using whitespace splitting.
    
    For production accuracy, swap with tiktoken or the model's tokenizer.
    """
    return len(re.findall(r"\S+", text))


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class AcademicChunk:
    """A semantically meaningful chunk of academic text."""
    text: str
    chunk_index: int
    token_count: int
    page_number: int | None = None
    source_section: str | None = None
    # Inferred metadata (set by classifier)
    module_number: int | None = None
    topic_name: str | None = None
    bloom_level: str | None = None
    co_mapping: str | None = None
    confidence_score: float = 0.0


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------

# Patterns that indicate a new section/heading in academic text
_HEADING_PATTERNS = [
    re.compile(r"^#{1,4}\s+", re.MULTILINE),                          # Markdown headings
    re.compile(r"^(?:Module|MODULE|Unit|UNIT)\s*[-:]?\s*\d", re.MULTILINE),  # Module/Unit headers
    re.compile(r"^(?:Chapter|CHAPTER)\s+\d", re.MULTILINE),            # Chapter headers
    re.compile(r"^\d+\.\s+[A-Z]", re.MULTILINE),                      # Numbered sections
    re.compile(r"^(?:Introduction|Conclusion|Summary|References)\b", re.MULTILINE | re.IGNORECASE),
]


def _is_heading(line: str) -> bool:
    """Check if a line looks like a section heading."""
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) > 200:
        return False
    return any(pattern.match(stripped) for pattern in _HEADING_PATTERNS)


def _split_into_paragraphs(text: str) -> list[str]:
    """Split text into paragraphs respecting double newlines."""
    raw_blocks = re.split(r"\n\s*\n", text)
    paragraphs = []
    for block in raw_blocks:
        cleaned = block.strip()
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def _split_into_sentences(text: str) -> list[str]:
    """Split text into sentences, trying not to break on abbreviations."""
    # Simple sentence splitter that avoids common abbreviations
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [p.strip() for p in parts if p.strip()]


# ---------------------------------------------------------------------------
# Core chunking engine
# ---------------------------------------------------------------------------

def semantic_chunk(
    text: str,
    min_tokens: int = 400,
    max_tokens: int = 800,
    overlap_ratio: float = 0.12,
    page_numbers: dict[int, int] | None = None,
) -> list[AcademicChunk]:
    """
    Split academic text into semantically meaningful chunks.

    Args:
        text: Full extracted text from a document.
        min_tokens: Minimum chunk size in tokens.
        max_tokens: Maximum chunk size in tokens.
        overlap_ratio: Fraction of overlap between consecutive chunks (0.10-0.15).
        page_numbers: Optional mapping of character offset -> page number.

    Returns:
        List of AcademicChunk objects.
    """
    if not text or not text.strip():
        return []

    paragraphs = _split_into_paragraphs(text)
    if not paragraphs:
        return []

    overlap_tokens = int(max_tokens * overlap_ratio)
    chunks: list[AcademicChunk] = []
    current_parts: list[str] = []
    current_tokens = 0
    current_section: str | None = None
    chunk_index = 0

    def _flush_chunk(parts: list[str], section: str | None) -> None:
        nonlocal chunk_index
        if not parts:
            return
        chunk_text = "\n\n".join(parts).strip()
        if not chunk_text or count_tokens(chunk_text) < 20:
            return

        page_num = None
        if page_numbers:
            # Find the page number for the start of this chunk
            char_offset = text.find(parts[0][:50])
            if char_offset >= 0:
                for offset, page in sorted(page_numbers.items()):
                    if offset <= char_offset:
                        page_num = page
                    else:
                        break

        chunks.append(AcademicChunk(
            text=chunk_text,
            chunk_index=chunk_index,
            token_count=count_tokens(chunk_text),
            page_number=page_num,
            source_section=section,
        ))
        chunk_index += 1

    for paragraph in paragraphs:
        para_tokens = count_tokens(paragraph)

        # Track section headings
        if _is_heading(paragraph):
            current_section = paragraph.strip()

        # If a single paragraph exceeds max_tokens, split it into sentences
        if para_tokens > max_tokens:
            # Flush what we have first
            if current_parts:
                _flush_chunk(current_parts, current_section)
                # Keep overlap
                overlap_text = _get_overlap_text(current_parts, overlap_tokens)
                current_parts = [overlap_text] if overlap_text else []
                current_tokens = count_tokens(overlap_text) if overlap_text else 0

            # Split the large paragraph into sentence-level chunks
            sentences = _split_into_sentences(paragraph)
            sent_buffer: list[str] = []
            sent_tokens = 0
            for sentence in sentences:
                st = count_tokens(sentence)
                if sent_tokens + st > max_tokens and sent_buffer:
                    combined = " ".join(sent_buffer)
                    _flush_chunk([combined], current_section)
                    overlap_text = _get_overlap_text([combined], overlap_tokens)
                    sent_buffer = [overlap_text, sentence] if overlap_text else [sentence]
                    sent_tokens = count_tokens(overlap_text) + st if overlap_text else st
                else:
                    sent_buffer.append(sentence)
                    sent_tokens += st
            if sent_buffer:
                current_parts.append(" ".join(sent_buffer))
                current_tokens += sent_tokens
            continue

        # Would adding this paragraph exceed max?
        if current_tokens + para_tokens > max_tokens and current_parts:
            _flush_chunk(current_parts, current_section)
            # Create overlap from the end of previous chunk
            overlap_text = _get_overlap_text(current_parts, overlap_tokens)
            current_parts = [overlap_text] if overlap_text else []
            current_tokens = count_tokens(overlap_text) if overlap_text else 0

        current_parts.append(paragraph)
        current_tokens += para_tokens

        # If we're past the section heading and above min, consider flushing
        # at a natural break (heading boundary)
        if current_tokens >= min_tokens and _is_heading(paragraph):
            _flush_chunk(current_parts, current_section)
            overlap_text = _get_overlap_text(current_parts, overlap_tokens)
            current_parts = [overlap_text] if overlap_text else []
            current_tokens = count_tokens(overlap_text) if overlap_text else 0

    # Flush remainder
    if current_parts:
        _flush_chunk(current_parts, current_section)

    logger.info(
        "Chunked document into %d chunks (min=%d, max=%d tokens, overlap=%.0f%%)",
        len(chunks), min_tokens, max_tokens, overlap_ratio * 100,
    )
    return chunks


def _get_overlap_text(parts: list[str], overlap_tokens: int) -> str:
    """Extract the last N tokens worth of text for overlap."""
    if not parts or overlap_tokens <= 0:
        return ""
    
    combined = "\n\n".join(parts)
    words = combined.split()
    if len(words) <= overlap_tokens:
        return combined
    
    return " ".join(words[-overlap_tokens:])
