"""
Mark Distribution Engine — QPGen v2.

Provides configurable mark-allocation strategies for different
course types and validates paper-level time balance.

Three built-in strategies:
  - Conservative: Heavy on L1/L2 (fundamentals courses)
  - Balanced: Standard engineering distribution
  - Rigorous: Heavy on L4-L6 (advanced/elective courses)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MarkStrategy:
    """Defines the percentage allocation of marks across Bloom levels."""

    name: str
    description: str
    # Percentage of total marks allocated to each Bloom tier
    l1_l2_percent: int   # Remember + Understand
    l3_percent: int       # Apply
    l4_percent: int       # Analyze
    l5_l6_percent: int   # Evaluate + Create

    def validate(self) -> bool:
        return (
            self.l1_l2_percent + self.l3_percent +
            self.l4_percent + self.l5_l6_percent
        ) == 100


CONSERVATIVE = MarkStrategy(
    name="conservative",
    description="Heavy on fundamentals (L1/L2). Suitable for introductory courses.",
    l1_l2_percent=40,
    l3_percent=30,
    l4_percent=20,
    l5_l6_percent=10,
)

BALANCED = MarkStrategy(
    name="balanced",
    description="Standard engineering distribution. Default for most courses.",
    l1_l2_percent=20,
    l3_percent=40,
    l4_percent=30,
    l5_l6_percent=10,
)

RIGOROUS = MarkStrategy(
    name="rigorous",
    description="Heavy on analysis/evaluation (L4-L6). For advanced courses.",
    l1_l2_percent=10,
    l3_percent=30,
    l4_percent=40,
    l5_l6_percent=20,
)

STRATEGIES: dict[str, MarkStrategy] = {
    "conservative": CONSERVATIVE,
    "balanced": BALANCED,
    "rigorous": RIGOROUS,
}


# ---------------------------------------------------------------------------
# Mark Allocation
# ---------------------------------------------------------------------------

@dataclass
class MarkAllocation:
    """Result of mark allocation for a paper."""

    strategy: str
    total_marks: int
    bloom_allocation: dict[str, int]  # {"L1": 5, "L2": 5, "L3": 20, ...}
    bloom_question_counts: dict[str, int]  # Approximate question counts
    warnings: list[str] = field(default_factory=list)


def allocate_marks(
    total_marks: int,
    strategy_name: str = "balanced",
    custom_strategy: MarkStrategy | None = None,
) -> MarkAllocation:
    """
    Allocate marks across Bloom levels based on a strategy.

    Returns a MarkAllocation with per-level marks and approximate
    question counts.
    """
    strategy = custom_strategy or STRATEGIES.get(
        strategy_name.lower(), BALANCED
    )

    # Split L1/L2 and L5/L6 tiers evenly
    l1_l2_marks = round(total_marks * strategy.l1_l2_percent / 100)
    l3_marks = round(total_marks * strategy.l3_percent / 100)
    l4_marks = round(total_marks * strategy.l4_percent / 100)
    l5_l6_marks = total_marks - l1_l2_marks - l3_marks - l4_marks  # remainder

    l1_marks = l1_l2_marks // 2
    l2_marks = l1_l2_marks - l1_marks
    l5_marks = l5_l6_marks // 2
    l6_marks = l5_l6_marks - l5_marks

    allocation = {
        "L1": l1_marks,
        "L2": l2_marks,
        "L3": l3_marks,
        "L4": l4_marks,
        "L5": l5_marks,
        "L6": l6_marks,
    }

    # Typical marks per question by Bloom level
    typical_marks = {"L1": 2, "L2": 4, "L3": 5, "L4": 8, "L5": 10, "L6": 12}
    counts = {
        level: max(1, round(marks / typical_marks[level]))
        for level, marks in allocation.items()
        if marks > 0
    }

    warnings: list[str] = []
    allocated_sum = sum(allocation.values())
    if allocated_sum != total_marks:
        # Fix rounding error
        diff = total_marks - allocated_sum
        allocation["L3"] += diff
        warnings.append(
            f"Rounding adjustment: {diff:+d} marks added to L3."
        )

    return MarkAllocation(
        strategy=strategy.name,
        total_marks=total_marks,
        bloom_allocation=allocation,
        bloom_question_counts=counts,
        warnings=warnings,
    )


def validate_time_balance(
    total_estimated_min: float,
    exam_duration_min: int,
    tolerance_percent: float = 5.0,
) -> tuple[bool, str]:
    """
    Check if total estimated time is within tolerance of exam duration.

    Returns (is_balanced, message).
    """
    tolerance = exam_duration_min * tolerance_percent / 100
    surplus = exam_duration_min - total_estimated_min

    if abs(surplus) <= tolerance:
        return True, (
            f"Time is balanced: ~{total_estimated_min:.0f} min "
            f"for {exam_duration_min} min exam."
        )
    elif surplus < 0:
        return False, (
            f"Paper is overloaded: ~{total_estimated_min:.0f} min estimated "
            f"for {exam_duration_min} min exam ({abs(surplus):.0f} min over)."
        )
    else:
        return False, (
            f"Paper may be underloaded: ~{total_estimated_min:.0f} min estimated "
            f"for {exam_duration_min} min exam ({surplus:.0f} min surplus)."
        )


def get_strategy(name: str) -> MarkStrategy:
    """Get a strategy by name. Defaults to balanced."""
    return STRATEGIES.get(name.lower(), BALANCED)


def list_strategies() -> list[dict[str, Any]]:
    """List all available mark strategies as dicts."""
    return [
        {
            "name": s.name,
            "description": s.description,
            "l1_l2_percent": s.l1_l2_percent,
            "l3_percent": s.l3_percent,
            "l4_percent": s.l4_percent,
            "l5_l6_percent": s.l5_l6_percent,
        }
        for s in STRATEGIES.values()
    ]
