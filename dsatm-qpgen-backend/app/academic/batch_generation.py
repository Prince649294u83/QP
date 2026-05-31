"""
Batch Paper Generation — Phase 6C.

Generates multiple papers in parallel for department-wide exam preparation.
Supports different subjects and configurations in a single batch request.

Architecture:
  - Coordinates paper generation across subjects
  - Tracks progress and errors per batch item
  - Returns aggregated results with individual success/failure status

Performance: Parallel execution, no sequential bottleneck.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("app.academic.batch")


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class BatchItem:
    """A single item in a batch generation request."""
    subject_id: int
    title: str
    exam_type: str = "IAT-1"
    semester: str = "1"
    batch: str = "2022-26"
    max_marks: int = 50
    duration_minutes: int = 90
    teaching_department: str = ""
    prompt: str = ""
    rbt_levels: list[str] = field(default_factory=lambda: ["L1", "L2", "L3", "L4", "L5", "L6"])
    module_numbers: list[int] = field(default_factory=lambda: [1, 2, 3, 4, 5])
    difficulty: str = "medium"
    generate_variants: bool = False
    num_variants: int = 2


@dataclass
class BatchItemResult:
    """Result for a single batch item."""
    index: int
    subject_id: int
    title: str
    success: bool
    paper_id: int | None = None
    question_count: int = 0
    variant_count: int = 0
    error: str | None = None
    generation_time_ms: float = 0


@dataclass
class BatchResult:
    """Aggregated result for a batch generation."""
    total_items: int
    successful: int
    failed: int
    total_time_ms: float
    items: list[BatchItemResult]


# ---------------------------------------------------------------------------
# Core Engine
# ---------------------------------------------------------------------------

def validate_batch_request(items: list[dict[str, Any]]) -> tuple[list[BatchItem], list[str]]:
    """Validate and parse batch items. Returns (valid_items, errors)."""
    parsed: list[BatchItem] = []
    errors: list[str] = []

    if not items:
        errors.append("Batch request must contain at least one item")
        return parsed, errors

    if len(items) > 20:
        errors.append("Maximum 20 items per batch")
        return parsed, errors

    for i, item in enumerate(items):
        if not item.get("subject_id"):
            errors.append(f"Item {i + 1}: subject_id is required")
            continue
        if not item.get("title"):
            errors.append(f"Item {i + 1}: title is required")
            continue

        parsed.append(BatchItem(
            subject_id=int(item["subject_id"]),
            title=str(item["title"]),
            exam_type=str(item.get("exam_type", "IAT-1")),
            semester=str(item.get("semester", "1")),
            batch=str(item.get("batch", "2022-26")),
            max_marks=int(item.get("max_marks", 50)),
            duration_minutes=int(item.get("duration_minutes", 90)),
            teaching_department=str(item.get("teaching_department", "")),
            prompt=str(item.get("prompt", "")),
            rbt_levels=item.get("rbt_levels", ["L1", "L2", "L3", "L4", "L5", "L6"]),
            module_numbers=item.get("module_numbers", [1, 2, 3, 4, 5]),
            difficulty=str(item.get("difficulty", "medium")),
            generate_variants=bool(item.get("generate_variants", False)),
            num_variants=int(item.get("num_variants", 2)),
        ))

    return parsed, errors


def generate_batch_papers(
    items: list[BatchItem],
    paper_generator_fn: Any,
) -> BatchResult:
    """
    Generate multiple papers from a batch of items.

    Args:
        items: Validated batch items
        paper_generator_fn: Callable that generates a single paper,
                           signature: (item: BatchItem) -> dict with keys
                           {paper_id, question_count, variant_count}
    """
    start = time.perf_counter()
    results: list[BatchItemResult] = []
    successful = 0
    failed = 0

    for i, item in enumerate(items):
        item_start = time.perf_counter()
        try:
            result = paper_generator_fn(item)
            results.append(BatchItemResult(
                index=i,
                subject_id=item.subject_id,
                title=item.title,
                success=True,
                paper_id=result.get("paper_id"),
                question_count=result.get("question_count", 0),
                variant_count=result.get("variant_count", 0),
                generation_time_ms=round((time.perf_counter() - item_start) * 1000, 1),
            ))
            successful += 1
        except Exception as e:
            logger.error("Batch item %d failed: %s", i, str(e))
            results.append(BatchItemResult(
                index=i,
                subject_id=item.subject_id,
                title=item.title,
                success=False,
                error=str(e),
                generation_time_ms=round((time.perf_counter() - item_start) * 1000, 1),
            ))
            failed += 1

    total_time = round((time.perf_counter() - start) * 1000, 1)

    return BatchResult(
        total_items=len(items),
        successful=successful,
        failed=failed,
        total_time_ms=total_time,
        items=results,
    )


def batch_result_to_dict(result: BatchResult) -> dict[str, Any]:
    """Convert BatchResult to JSON-serializable dict."""
    return {
        "total_items": result.total_items,
        "successful": result.successful,
        "failed": result.failed,
        "total_time_ms": result.total_time_ms,
        "items": [
            {
                "index": item.index,
                "subject_id": item.subject_id,
                "title": item.title,
                "success": item.success,
                "paper_id": item.paper_id,
                "question_count": item.question_count,
                "variant_count": item.variant_count,
                "error": item.error,
                "generation_time_ms": item.generation_time_ms,
            }
            for item in result.items
        ],
    }
