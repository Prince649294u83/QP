"""
VTU Academic Style Engine for question generation.

Provides:
- University-specific question phrasing patterns
- Bloom-level constrained verb selection
- Creativity control based on Bloom/CO level
- Academic style profile management
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# VTU Style Profile
# ---------------------------------------------------------------------------

@dataclass
class AcademicStyleProfile:
    """University-specific academic style configuration."""

    university: str = "VTU"
    institution: str = "DSATM"

    # Bloom-level action verbs (VTU standard)
    verbs: dict[str, list[str]] = field(default_factory=lambda: {
        "L1": ["Define", "List", "State", "Name", "Identify", "Recall", "Mention"],
        "L2": ["Explain", "Describe", "Discuss", "Summarize", "Outline", "Illustrate", "Differentiate"],
        "L3": ["Solve", "Calculate", "Apply", "Demonstrate", "Implement", "Compute", "Write a program"],
        "L4": ["Analyze", "Compare", "Distinguish", "Examine", "Contrast", "Classify", "Break down"],
        "L5": ["Evaluate", "Justify", "Critique", "Assess", "Argue", "Judge", "Recommend"],
        "L6": ["Design", "Develop", "Construct", "Create", "Formulate", "Propose", "Synthesize"],
    })

    # Question patterns by Bloom level
    question_patterns: dict[str, list[str]] = field(default_factory=lambda: {
        "L1": [
            "{verb} {topic}.",
            "{verb} the following: {topic}.",
            "{verb} the terms: {topic}.",
            "What is {topic}? {verb} briefly.",
        ],
        "L2": [
            "{verb} {topic} with a neat diagram.",
            "{verb} {topic} in detail.",
            "{verb} the concept of {topic}.",
            "{verb} how {topic} works.",
            "{verb} {topic} with suitable examples.",
        ],
        "L3": [
            "{verb} {topic} using a suitable example.",
            "{verb} the following problem on {topic}.",
            "Using {topic}, {verb} the given scenario.",
            "{verb} {topic}. Show all steps.",
            "Write a program to {verb} {topic}.",
        ],
        "L4": [
            "{verb} {topic} with {topic_b}.",
            "{verb} the advantages and disadvantages of {topic}.",
            "{verb} the performance of {topic}.",
            "{verb} {topic} using a case study.",
            "{verb} the differences between {topic} and {topic_b}.",
        ],
        "L5": [
            "{verb} the effectiveness of {topic}.",
            "{verb} whether {topic} is suitable for the given scenario.",
            "Critically {verb} {topic} in the context of {topic_b}.",
            "{verb} the trade-offs involved in {topic}.",
        ],
        "L6": [
            "{verb} a {topic} for the given requirements.",
            "{verb} an algorithm/strategy for {topic}.",
            "{verb} a solution to {topic} considering {topic_b}.",
            "Propose and {verb} a system for {topic}.",
        ],
    })


# Global profile
VTU_PROFILE = AcademicStyleProfile()


# ---------------------------------------------------------------------------
# Creativity control
# ---------------------------------------------------------------------------

def get_creativity_level(bloom_level: str, co_mapping: str | None = None) -> float:
    """
    Determine creativity level based on Bloom/CO.

    Low creativity (0.1-0.3): L1/L2 — strict recall/understanding
    Medium creativity (0.3-0.6): L3/L4 — application/analysis
    High creativity (0.6-0.9): L5/L6 — evaluation/creation
    """
    bloom_creativity = {
        "L1": 0.1,
        "L2": 0.2,
        "L3": 0.4,
        "L4": 0.5,
        "L5": 0.7,
        "L6": 0.8,
    }
    base = bloom_creativity.get(bloom_level, 0.3)

    # CO can slightly adjust creativity
    if co_mapping:
        co_num = int(co_mapping.replace("CO", "")) if co_mapping.startswith("CO") else 3
        co_adjustment = (co_num - 3) * 0.05  # CO5/CO6 = slightly more creative
        base = max(0.0, min(1.0, base + co_adjustment))

    return round(base, 2)


def get_temperature(creativity_level: float) -> float:
    """Convert creativity level to LLM temperature parameter."""
    # Map 0.0-1.0 creativity to 0.1-0.8 temperature
    return round(0.1 + (creativity_level * 0.7), 2)


# ---------------------------------------------------------------------------
# Question phrasing
# ---------------------------------------------------------------------------

def get_vtu_verb(bloom_level: str, profile: AcademicStyleProfile | None = None) -> str:
    """Get a random VTU-appropriate verb for a Bloom level."""
    profile = profile or VTU_PROFILE
    verbs = profile.verbs.get(bloom_level, profile.verbs["L2"])
    return random.choice(verbs)


def get_vtu_pattern(bloom_level: str, profile: AcademicStyleProfile | None = None) -> str:
    """Get a random VTU question pattern for a Bloom level."""
    profile = profile or VTU_PROFILE
    patterns = profile.question_patterns.get(bloom_level, profile.question_patterns["L2"])
    return random.choice(patterns)


def format_vtu_question(
    topic: str,
    bloom_level: str,
    topic_b: str | None = None,
    profile: AcademicStyleProfile | None = None,
) -> str:
    """Generate a VTU-style question shell from a topic and Bloom level."""
    verb = get_vtu_verb(bloom_level, profile)
    pattern = get_vtu_pattern(bloom_level, profile)

    return pattern.format(
        verb=verb,
        topic=topic,
        topic_b=topic_b or "related concepts",
    )


# ---------------------------------------------------------------------------
# Style validation
# ---------------------------------------------------------------------------

def check_vtu_style(question_text: str, bloom_level: str) -> dict[str, bool | str]:
    """Check if a question follows VTU style conventions."""
    profile = VTU_PROFILE
    expected_verbs = [v.lower() for v in profile.verbs.get(bloom_level, [])]
    lowered = question_text.lower().strip()

    starts_with_verb = any(lowered.startswith(v) for v in expected_verbs)
    any_verb_present = any(v in lowered for v in expected_verbs)

    return {
        "starts_with_verb": starts_with_verb,
        "has_expected_verb": any_verb_present,
        "bloom_level": bloom_level,
        "suggested_verbs": ", ".join(profile.verbs.get(bloom_level, [])[:3]),
    }
