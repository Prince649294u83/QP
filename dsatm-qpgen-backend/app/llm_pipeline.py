"""
Optimized LLM pipeline for QPGen.

Roles:
- Vision: ONLY extraction (structured questions from images/PDFs)
- Text: ONLY generation and validation (no vision)
- Embeddings: Duplicate filtering using sentence transformers
"""

import json
import logging
from typing import Any

import httpx
import numpy as np

from .config import settings

logger = logging.getLogger(__name__)


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


class LLMCall:
    """Unified low-level Ollama interface."""

    def __init__(self, base_url: str = None, model: str = None, timeout: float = 60.0):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout = timeout or settings.ollama_request_timeout_seconds

    def is_available(self, timeout: float | None = None) -> bool:
        try:
            response = httpx.get(
                f"{self.base_url}/api/tags",
                timeout=timeout or settings.ollama_health_timeout_seconds,
            )
            return response.status_code == 200
        except Exception:
            return False

    def _request(
        self,
        prompt: str,
        system: str,
        images: list[str] | None = None,
        *,
        expect_json: bool,
        model: str | None = None,
        timeout: float | None = None,
    ) -> str | None:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
        }
        if expect_json:
            payload["format"] = "json"
        if images:
            payload["images"] = images

        try:
            response = httpx.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=timeout or self.timeout,
            )
            response.raise_for_status()
            return str(response.json().get("response", "")).strip()
        except Exception as exc:
            logger.error("LLMCall failed for model=%s: %s", model or self.model, exc)
            return None

    def generate_text(
        self,
        prompt: str,
        system: str,
        images: list[str] | None = None,
        *,
        model: str | None = None,
        timeout: float | None = None,
    ) -> str | None:
        return self._request(
            prompt,
            system,
            images,
            expect_json=False,
            model=model,
            timeout=timeout,
        )

    def __call__(
        self,
        prompt: str,
        system: str,
        images: list[str] | None = None,
        *,
        model: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Generic LLM call (sync). Returns parsed JSON or None."""
        raw = self._request(
            prompt,
            system,
            images,
            expect_json=True,
            model=model,
            timeout=timeout,
        )
        if not raw:
            return None
        parsed = _extract_json_object(raw)
        if parsed is None:
            logger.warning("Could not parse JSON response from model=%s: %s", model or self.model, raw[:300])
        return parsed

    async def _async_request(
        self,
        prompt: str,
        system: str,
        images: list[str] | None = None,
        *,
        expect_json: bool,
        model: str | None = None,
        timeout: float | None = None,
    ) -> str | None:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
        }
        if expect_json:
            payload["format"] = "json"
        if images:
            payload["images"] = images

        try:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                response.raise_for_status()
                return str(response.json().get("response", "")).strip()
        except Exception as exc:
            logger.error("LLMCall async request failed for model=%s: %s", model or self.model, exc)
            return None

    async def async_call(
        self,
        prompt: str,
        system: str,
        images: list[str] | None = None,
        *,
        model: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any] | None:
        """Generic LLM call (async). Returns parsed JSON or None."""
        raw = await self._async_request(
            prompt,
            system,
            images,
            expect_json=True,
            model=model,
            timeout=timeout,
        )
        if not raw:
            return None
        parsed = _extract_json_object(raw)
        if parsed is None:
            logger.warning("Could not parse JSON response from model=%s: %s", model or self.model, raw[:300])
        return parsed


# ============================================================================
# EXTRACTION (Vision mode - ONLY for understanding/OCR)
# ============================================================================


EXTRACTION_PROMPT_TEMPLATE = """
You are extracting questions from an exam paper image or document.

Return STRICT JSON format with NO extra text:
{{
  "questions": [
    {{
      "text": "...",
      "marks": number,
      "topic": "...",
      "type": "theory|numerical|definition",
      "module": number (1-5),
      "confidence": 0.0-1.0
    }}
  ]
}}

Focus on clarity. Do not add explanation.
"""


class VisionExtractor:
    """Extract questions from images/PDFs using Vision."""

    def __init__(self, llm_call: LLMCall = None):
        self.llm = llm_call or LLMCall()

    def from_image(self, image_b64: str) -> list[dict[str, Any]]:
        """Extract questions from base64 image."""
        system = (
            "You are an expert academic parser. "
            "Extract all questions from this exam paper image. "
            "Be precise and maintain academic rigor."
        )
        prompt = EXTRACTION_PROMPT_TEMPLATE + "\n\nExtract all questions now."
        
        result = self.llm(prompt, system, images=[image_b64])
        
        if isinstance(result, dict) and isinstance(result.get("questions"), list):
            logger.info(f"Extracted {len(result['questions'])} questions from image")
            return result["questions"]
        
        logger.warning("Vision extraction failed")
        return []

    def from_text(self, text: str) -> list[dict[str, Any]]:
        """Extract questions from raw text."""
        system = (
            "You are an expert academic parser for engineering question banks. "
            "Extract exam questions from the text provided."
        )
        prompt = (
            EXTRACTION_PROMPT_TEMPLATE
            + f"\n\nInput text:\n{text[:8000]}"
        )
        
        result = self.llm(prompt, system)
        
        if isinstance(result, dict) and isinstance(result.get("questions"), list):
            logger.info(f"Extracted {len(result['questions'])} questions from text")
            return result["questions"]
        
        logger.warning("Text extraction failed")
        return []


# ============================================================================
# GENERATION (Text mode - ONLY for creating new questions)
# ============================================================================


def _difficulty_rules(difficulty: str) -> str:
    """Hard constraints for difficulty levels."""
    rules = {
        "easy": (
            "Definition or direct concept. No problem solving. "
            "One sentence answer. Can be recalled from textbook."
        ),
        "medium": (
            "Concept + explanation or small example. "
            "Requires understanding but straightforward reasoning. "
            "2-3 sentences. Mix of recall and application."
        ),
        "hard": (
            "Numerical problem, derivation, or multi-step reasoning. "
            "Requires synthesis of multiple concepts. "
            "Complex analysis or design task."
        ),
    }
    return rules.get(difficulty.lower(), "Concept-based question")


class QuestionGenerator:
    """Generate exam questions at specific difficulty levels."""

    def __init__(self, llm_call: LLMCall = None):
        self.llm = llm_call or LLMCall()

    def generate(
        self,
        base_question: str,
        topic: str,
        difficulty: str,
        subject_code: str = "N/A",
        existing_questions: list[str] = None,
        bloom_level: str = "L2",
    ) -> str | None:
        """Generate a new question from a base question."""
        import random
        from .academic.validation import VTU_VERBS
        
        existing_questions = existing_questions or []
        rules = _difficulty_rules(difficulty)
        
        available_verbs = VTU_VERBS.get(bloom_level.upper(), ["Explain", "Describe"])
        chosen_verb = random.choice(available_verbs)
        
        system = (
            "You are an expert exam question designer for engineering students. "
            "Generate high-quality exam questions that are clear and unambiguous."
        )
        
        avoid_str = ""
        if existing_questions:
            avoid_str = "Do NOT generate any question similar to these:\n" + "\n".join(f"- {q}" for q in existing_questions[-5:])
        
        prompt = f"""
Generate a NEW exam question based on the original.

Topic: {topic}
Subject Code: {subject_code}
Difficulty: {difficulty}
Bloom's Level: {bloom_level} (Start the question with the verb '{chosen_verb.capitalize()}')

Difficulty Rules:
{rules}

Original Question:
{base_question}

{avoid_str}

Requirements:
- Do NOT repeat wording from original
- Stay within same topic
- Follow difficulty rules strictly
- The question must be concrete and domain-specific (e.g. use specific algorithms, derivations, tracing). Avoid vague AI templates.
- Return ONLY valid JSON: {{"question":"..."}}

Generate the new question:
"""
        
        response = self.llm(prompt, system)
        
        if isinstance(response, dict) and isinstance(response.get("question"), str):
            new_q = response["question"].strip()
            if new_q and len(new_q) > 10:
                logger.info(f"Generated {difficulty} question: {new_q[:50]}...")
                return new_q
        
        logger.warning(f"Generation failed for {difficulty} question")
        return None


# ============================================================================
# VALIDATION (Text mode - ensure quality)
# ============================================================================


class QuestionValidator:
    """Validate questions for quality and relevance."""

    def __init__(self, llm_call: LLMCall = None):
        self.llm = llm_call or LLMCall()

    def validate(self, question: str, topic: str, difficulty: str = None) -> bool:
        """Check if question is valid for topic."""
        
        system = (
            "You are a strict academic quality evaluator. "
            "Answer ONLY YES or NO."
        )
        
        conditions = [
            f"- Is the question relevant to topic '{topic}'?",
            "- Is it grammatically correct and clear?",
            "- Is it an exam-appropriate question?",
        ]
        
        if difficulty:
            rules = _difficulty_rules(difficulty)
            conditions.append(f"- Does it follow {difficulty} difficulty rules? {rules}")
        
        prompt = f"""
Validate this question strictly.

Question: {question}
Topic: {topic}
Difficulty: {difficulty or 'any'}

Conditions:
{chr(10).join(conditions)}

Return ONLY valid JSON: {{"answer":"YES"}} or {{"answer":"NO"}}
"""
        
        response = self.llm(prompt, system)
        
        if isinstance(response, dict):
            answer = str(response.get("answer", "")).upper()
            is_valid = "YES" in answer
            logger.info(f"Question validation: {is_valid}")
            return is_valid
        
        return False


# ============================================================================
# DUPLICATE FILTERING (Using embeddings)
# ============================================================================


class DuplicateFilter:
    """Detect duplicate/similar questions using semantic embeddings."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", threshold: float = 0.85):
        try:
            from sentence_transformers import SentenceTransformer

            self.embedder = SentenceTransformer(model_name, device="cpu")
            self.threshold = threshold
            self.cache: dict[str, np.ndarray] = {}
            logger.info(f"DuplicateFilter initialized with {model_name}")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            self.embedder = None

    def is_duplicate(self, new_question: str, existing_questions: list[str]) -> bool:
        """Check if new_question is a duplicate of any existing question."""
        
        if not self.embedder:
            return False
        
        try:
            new_vec = self._get_embedding(new_question)
            
            for existing_q in existing_questions:
                existing_vec = self._get_embedding(existing_q)
                similarity = self._cosine_similarity(new_vec, existing_vec)
                
                if similarity > self.threshold:
                    logger.warning(
                        f"Duplicate detected (similarity={similarity:.2f}): "
                        f"{existing_q[:50]}..."
                    )
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Duplicate check failed: {e}")
            return False

    def _get_embedding(self, text: str) -> np.ndarray:
        """Get cached embedding or compute new."""
        if text not in self.cache:
            self.cache[text] = self.embedder.encode(text)
        return self.cache[text]

    def _cosine_similarity(self, vec_a: np.ndarray, vec_b: np.ndarray) -> float:
        """Compute cosine similarity."""
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return np.dot(vec_a, vec_b) / (norm_a * norm_b)

    def clear_cache(self):
        """Clear embedding cache."""
        self.cache.clear()


# ============================================================================
# INTEGRATED PIPELINE
# ============================================================================


class QPGenPipeline:
    """Complete question generation pipeline."""

    def __init__(
        self,
        llm_call: LLMCall = None,
        embedding_model: str = "all-MiniLM-L6-v2",
    ):
        self.llm = llm_call or LLMCall()
        self.extractor = VisionExtractor(self.llm)
        self.generator = QuestionGenerator(self.llm)
        self.validator = QuestionValidator(self.llm)
        self.deduplicator = DuplicateFilter(model_name=embedding_model)

    def generate_variants(
        self,
        base_question: str,
        topic: str,
        difficulties: list[str] = None,
        subject_code: str = "N/A",
        existing_questions: list[str] = None,
        bloom_level: str = "L2",
    ) -> list[dict[str, Any]]:
        """
        Generate question variants at different difficulty levels.
        
        Returns list of validated, non-duplicate questions.
        """
        if not difficulties:
            difficulties = ["easy", "medium", "hard"]
        
        existing_questions = existing_questions or []
        generated = []
        
        for difficulty in difficulties:
            # Generate
            new_q = self.generator.generate(
                base_question, topic, difficulty, subject_code, existing_questions, bloom_level
            )
            if not new_q:
                continue
            
            # Check for duplicates
            if self.deduplicator.is_duplicate(new_q, existing_questions + [q["text"] for q in generated]):
                logger.info(f"Skipped duplicate: {difficulty}")
                continue
            
            # Validate
            if not self.validator.validate(new_q, topic, difficulty):
                logger.info(f"Failed validation: {difficulty}")
                continue
            
            generated.append({
                "text": new_q,
                "topic": topic,
                "difficulty": difficulty,
                "subject_code": subject_code,
                "source": "generated",
            })
        
        return generated


# Global singleton for easy access
_pipeline = None


def get_pipeline() -> QPGenPipeline:
    """Get or create the global pipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = QPGenPipeline()
    return _pipeline
