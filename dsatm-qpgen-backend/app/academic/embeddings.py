"""
Embedding service for semantic search and deduplication.

Uses sentence-transformers with BAAI/bge-small-en-v1.5 (or all-MiniLM-L6-v2 fallback).
Embeddings stored as JSON arrays in the KnowledgeChunk table.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger("app.academic.embeddings")

# ---------------------------------------------------------------------------
# Singleton embedding model
# ---------------------------------------------------------------------------

_model = None
_model_name: str = ""


def _get_model():
    """Lazy-load the embedding model."""
    global _model, _model_name
    if _model is not None:
        return _model

    try:
        from sentence_transformers import SentenceTransformer

        # Use lighter/faster model first for better performance
        preferred_models = [
            "all-MiniLM-L6-v2",  # Faster, 22MB
            "BAAI/bge-small-en-v1.5",  # Accurate, 133MB
        ]
        for name in preferred_models:
            try:
                _model = SentenceTransformer(name, device="cpu")
                _model_name = name
                logger.info("Loaded embedding model: %s", name)
                return _model
            except Exception:
                continue

        logger.warning("No embedding model available")
        return None
    except ImportError:
        logger.warning("sentence-transformers not installed")
        return None


def get_model_name() -> str:
    """Return the name of the loaded model."""
    _get_model()
    return _model_name


# ---------------------------------------------------------------------------
# Embedding generation
# ---------------------------------------------------------------------------

def generate_embedding(text: str) -> list[float] | None:
    """Generate an embedding vector for a single text."""
    model = _get_model()
    if model is None:
        return None
    try:
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()
    except Exception as e:
        logger.error("Embedding generation failed: %s", e)
        return None


def generate_embeddings_batch(texts: list[str]) -> list[list[float] | None]:
    """Generate embeddings for a batch of texts."""
    model = _get_model()
    if model is None:
        return [None] * len(texts)
    try:
        vectors = model.encode(texts, normalize_embeddings=True, batch_size=32)
        return [v.tolist() for v in vectors]
    except Exception as e:
        logger.error("Batch embedding failed: %s", e)
        return [None] * len(texts)


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------

def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(vec_a)
    b = np.array(vec_b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


def find_similar_chunks(
    query_embedding: list[float],
    chunk_embeddings: list[tuple[int, list[float]]],  # (chunk_id, embedding)
    top_k: int = 10,
    threshold: float = 0.3,
) -> list[tuple[int, float]]:
    """
    Find the most similar chunks to a query embedding.

    Returns: List of (chunk_id, similarity_score) sorted by score desc.
    """
    results: list[tuple[int, float]] = []
    for chunk_id, embedding in chunk_embeddings:
        if embedding is None:
            continue
        score = cosine_similarity(query_embedding, embedding)
        if score >= threshold:
            results.append((chunk_id, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

def is_duplicate(
    new_embedding: list[float],
    existing_embeddings: list[list[float]],
    threshold: float = 0.85,
) -> bool:
    """Check if new content is semantically duplicate of existing content."""
    if not new_embedding or not existing_embeddings:
        return False
    for existing in existing_embeddings:
        if existing is None:
            continue
        sim = cosine_similarity(new_embedding, existing)
        if sim >= threshold:
            return True
    return False
