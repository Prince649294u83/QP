"""
Concept Graph Extraction Engine (Stage 1 & Stage 2).
Uses LLM to process academic text into structured ConceptNodes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..config import settings
from ..llm_pipeline import LLMCall

logger = logging.getLogger("app.academic.concept_extraction")

EXTRACTION_SYSTEM_PROMPT = """
You are an expert academic knowledge extractor. Your task is to process academic text and extract a structured Concept Graph.
Identify Module Titles, Main Topics, Definitions, Algorithms, Examples, Diagrams, Theorems, Properties, Workflows, Numerical Problems, and Applications.

Return ONLY valid JSON in the following format:
{
  "concepts": [
    {
      "topic": "A* Search",
      "module_number": 3,
      "node_type": "algorithm",
      "difficulty": "medium",
      "content": "A* search is an informed search algorithm that uses an admissible heuristic...",
      "related_topics": ["Greedy Best First Search", "Heuristic Function"],
      "question_patterns": ["Explain", "Analyze", "Solve"]
    }
  ]
}

Rules:
- `node_type` must be one of: module_title, main_topic, subtopic, definition, algorithm, example, theorem, property, advantage_disadvantage, workflow, numerical_problem, application.
- `difficulty` must be: low, medium, or high.
- `module_number` should be an integer from 1 to 5. Try to infer it from context.
- Keep `content` concise but academically precise.
"""

def extract_concept_nodes(text: str) -> list[dict[str, Any]]:
    """Extract structured concept nodes from a block of text using LLM."""
    if not text or len(text.strip()) < 50:
        return []

    llm = LLMCall(
        model=settings.ollama_model,
        timeout=180.0,
    )

    if not llm.is_available():
        logger.error("LLM is not available for concept extraction.")
        return []

    prompt = f"Extract a structured Concept Graph from the following text:\n\n{text}"
    result_text = llm.generate_text(prompt, EXTRACTION_SYSTEM_PROMPT, temperature=0.2)

    if not result_text:
        return []

    # Clean up potential markdown JSON wrapping
    clean_text = result_text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    elif clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]

    try:
        parsed = json.loads(clean_text.strip())
        concepts = parsed.get("concepts", [])
        if isinstance(concepts, list):
            return concepts
    except json.JSONDecodeError as e:
        logger.error("Failed to parse concept extraction JSON: %s\nText: %s", e, clean_text[:200])

    return []
