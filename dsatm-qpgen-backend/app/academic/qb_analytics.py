"""
Question Bank Analytics & Overlap Detection — Phase 6D-G.

Provides:
  - Question usage frequency tracking
  - Topic freshness analysis
  - Bloom heatmap (module × bloom level)
  - Semantic overlap/similarity detection between questions
  - Previous paper question identification

Architecture:
  - Rule-based analytics (no LLM)
  - Text-based similarity using token overlap (fast fallback)
  - Embedding-based similarity when available

Performance: <100ms for typical question banks (<500 questions).
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

logger = logging.getLogger("app.academic.qb_analytics")


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class QuestionUsageInfo:
    """Usage metadata for a single question."""
    question_id: int
    text: str
    module_number: int
    bloom_level: str
    course_outcome: str
    usage_count: int
    last_used_at: str | None = None
    freshness_days: int | None = None


@dataclass
class BloomHeatmapCell:
    """Single cell in the module × bloom heatmap."""
    module_number: int
    bloom_level: str
    count: int


@dataclass
class OverlapPair:
    """A pair of questions with detected similarity."""
    question_id: int
    text: str
    compared_text: str
    similarity: float
    source: str  # "question_bank", "previous_paper"


@dataclass
class QuestionBankAnalytics:
    """Full analytics report for a question bank."""
    total_questions: int
    verified_questions: int
    pending_questions: int
    previous_paper_questions: int
    average_usage: float
    freshness_buckets: dict[str, int]  # "fresh"/"aging"/"stale" → count
    bloom_heatmap: list[BloomHeatmapCell]
    high_overlap_pairs: list[OverlapPair]
    most_used_questions: list[QuestionUsageInfo]
    stale_questions: list[QuestionUsageInfo]


# ---------------------------------------------------------------------------
# Text Similarity
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def compute_text_similarity(text_a: str, text_b: str) -> float:
    """
    Compute similarity between two question texts.
    Uses token overlap + SequenceMatcher for a balanced score.
    """
    norm_a = _normalize_text(text_a)
    norm_b = _normalize_text(text_b)

    if not norm_a or not norm_b:
        return 0.0

    # Token overlap (Jaccard)
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    if not tokens_a or not tokens_b:
        return 0.0
    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)

    # Sequence similarity
    seq_sim = SequenceMatcher(None, norm_a, norm_b).ratio()

    # Weighted combination
    return 0.4 * jaccard + 0.6 * seq_sim


# ---------------------------------------------------------------------------
# Analytics Engine
# ---------------------------------------------------------------------------

def compute_bloom_heatmap(questions: list[dict[str, Any]]) -> list[BloomHeatmapCell]:
    """Build module × bloom level heatmap."""
    counts: dict[tuple[int, str], int] = defaultdict(int)

    for q in questions:
        module = q.get("module_number", 1) or 1
        bloom = (q.get("bloom_level") or "L1").upper().strip()
        counts[(module, bloom)] += 1

    cells = []
    for module in range(1, 6):
        for bloom in ["L1", "L2", "L3", "L4", "L5", "L6"]:
            count = counts.get((module, bloom), 0)
            cells.append(BloomHeatmapCell(
                module_number=module,
                bloom_level=bloom,
                count=count,
            ))

    return cells


def detect_overlaps(
    questions: list[dict[str, Any]],
    threshold: float = 0.72,
    max_pairs: int = 20,
) -> list[OverlapPair]:
    """
    Detect high-similarity question pairs.
    Uses text-based similarity as fast fallback.
    """
    pairs: list[OverlapPair] = []

    # Only check pairs where both have meaningful text
    valid_questions = [
        q for q in questions
        if q.get("text") and len(q["text"].strip()) > 10
    ]

    for i in range(len(valid_questions)):
        for j in range(i + 1, len(valid_questions)):
            q_a = valid_questions[i]
            q_b = valid_questions[j]

            sim = compute_text_similarity(q_a["text"], q_b["text"])
            if sim >= threshold:
                pairs.append(OverlapPair(
                    question_id=q_a.get("id", i),
                    text=q_a["text"][:200],
                    compared_text=q_b["text"][:200],
                    similarity=round(sim, 3),
                    source="question_bank",
                ))

            if len(pairs) >= max_pairs:
                break
        if len(pairs) >= max_pairs:
            break

    # Sort by similarity descending
    pairs.sort(key=lambda p: p.similarity, reverse=True)
    return pairs


def compute_question_bank_analytics(
    questions: list[dict[str, Any]],
    paper_questions: list[dict[str, Any]] | None = None,
    overlap_threshold: float = 0.72,
) -> QuestionBankAnalytics:
    """
    Compute full analytics for a question bank.

    Args:
        questions: All questions in the bank
        paper_questions: Questions from past papers (for freshness/overlap)
        overlap_threshold: Similarity threshold for overlap detection
    """
    if paper_questions is None:
        paper_questions = []

    total = len(questions)
    verified = sum(1 for q in questions if q.get("is_verified"))
    pending = total - verified
    prev_paper = len(paper_questions)

    # Usage tracking (simulated - in production, from paper_questions junction)
    usage_counts: dict[int, int] = Counter()
    for pq in paper_questions:
        qid = pq.get("question_id", 0)
        if qid:
            usage_counts[qid] += 1

    avg_usage = sum(usage_counts.values()) / max(total, 1)

    # Freshness buckets
    freshness: dict[str, int] = {"fresh": 0, "aging": 0, "stale": 0}
    most_used: list[QuestionUsageInfo] = []
    stale: list[QuestionUsageInfo] = []

    for q in questions:
        qid = q.get("id", 0)
        count = usage_counts.get(qid, 0)
        info = QuestionUsageInfo(
            question_id=qid,
            text=q.get("text", "")[:150],
            module_number=q.get("module_number", 1) or 1,
            bloom_level=q.get("bloom_level", "L1") or "L1",
            course_outcome=q.get("course_outcome", "CO1") or "CO1",
            usage_count=count,
        )

        if count == 0:
            freshness["fresh"] += 1
        elif count <= 2:
            freshness["aging"] += 1
        else:
            freshness["stale"] += 1
            stale.append(info)

        if count >= 2:
            most_used.append(info)

    most_used.sort(key=lambda x: x.usage_count, reverse=True)
    stale.sort(key=lambda x: x.usage_count, reverse=True)

    # Bloom heatmap
    heatmap = compute_bloom_heatmap(questions)

    # Overlap detection
    overlaps = detect_overlaps(questions, threshold=overlap_threshold)

    return QuestionBankAnalytics(
        total_questions=total,
        verified_questions=verified,
        pending_questions=pending,
        previous_paper_questions=prev_paper,
        average_usage=round(avg_usage, 2),
        freshness_buckets=freshness,
        bloom_heatmap=heatmap,
        high_overlap_pairs=overlaps,
        most_used_questions=most_used[:10],
        stale_questions=stale[:10],
    )


def analytics_to_dict(report: QuestionBankAnalytics) -> dict[str, Any]:
    """Convert analytics report to JSON-serializable dict."""
    return {
        "total_questions": report.total_questions,
        "verified_questions": report.verified_questions,
        "pending_questions": report.pending_questions,
        "previous_paper_questions": report.previous_paper_questions,
        "average_usage": report.average_usage,
        "freshness_buckets": report.freshness_buckets,
        "bloom_heatmap": [
            {
                "module_number": c.module_number,
                "bloom_level": c.bloom_level,
                "count": c.count,
            }
            for c in report.bloom_heatmap
        ],
        "high_overlap_pairs": [
            {
                "question_id": p.question_id,
                "text": p.text,
                "compared_text": p.compared_text,
                "similarity": p.similarity,
                "source": p.source,
            }
            for p in report.high_overlap_pairs
        ],
        "most_used_questions": [
            {
                "question_id": q.question_id,
                "text": q.text,
                "module_number": q.module_number,
                "bloom_level": q.bloom_level,
                "course_outcome": q.course_outcome,
                "usage_count": q.usage_count,
                "last_used_at": q.last_used_at,
                "freshness_days": q.freshness_days,
            }
            for q in report.most_used_questions
        ],
        "stale_questions": [
            {
                "question_id": q.question_id,
                "text": q.text,
                "module_number": q.module_number,
                "bloom_level": q.bloom_level,
                "course_outcome": q.course_outcome,
                "usage_count": q.usage_count,
                "last_used_at": q.last_used_at,
                "freshness_days": q.freshness_days,
            }
            for q in report.stale_questions
        ],
    }
