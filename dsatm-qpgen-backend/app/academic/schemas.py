"""Pydantic schemas for the Academic Knowledge Intelligence Layer."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import ChunkApprovalStatus, DocumentType, ProcessingStatus


# ---------------------------------------------------------------------------
# Upload / Ingestion
# ---------------------------------------------------------------------------

class AcademicUploadRequest(BaseModel):
    subject_id: int
    document_type: DocumentType = DocumentType.NOTES


class AcademicDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    uploaded_by: int
    file_name: str
    file_type: str
    document_type: DocumentType
    processing_status: ProcessingStatus
    processing_error: str | None = None
    page_count: int | None = None
    total_chunks: int
    created_at: datetime


class AcademicDocumentListResponse(BaseModel):
    documents: list[AcademicDocumentResponse]
    total: int


class DocumentChunkPreviewResponse(BaseModel):
    id: int
    page: int
    text: str
    source_type: str
    block_index: int


class DocumentImagePreviewResponse(BaseModel):
    id: int
    image_path: str
    image_available: bool = True
    source_page: int
    keywords: list[str] = Field(default_factory=list)
    context_before: str = ""
    context_after: str = ""
    ai_caption: str = ""
    width: int | None = None
    height: int | None = None


class DocumentPreviewResponse(BaseModel):
    id: int
    filename: str
    parsed_text: str
    chunks: list[DocumentChunkPreviewResponse]
    images: list[DocumentImagePreviewResponse]


# ---------------------------------------------------------------------------
# Knowledge Chunks
# ---------------------------------------------------------------------------

class KnowledgeChunkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    subject_id: int
    chunk_text: str
    chunk_summary: str | None = None
    chunk_index: int
    token_count: int
    module_number: int | None = None
    syllabus_unit: str | None = None
    topic_name: str | None = None
    bloom_level: str | None = None
    co_mapping: str | None = None
    page_number: int | None = None
    confidence_score: float
    approval_status: ChunkApprovalStatus
    reviewed_by: int | None = None
    review_notes: str | None = None
    created_at: datetime


class ChunkApprovalRequest(BaseModel):
    approval_status: ChunkApprovalStatus
    review_notes: str | None = None


class ChunkEditRequest(BaseModel):
    chunk_text: str | None = None
    module_number: int | None = None
    topic_name: str | None = None
    bloom_level: str | None = None
    co_mapping: str | None = None


class ChunkSearchRequest(BaseModel):
    query: str
    subject_id: int | None = None
    module_number: int | None = None
    document_type: DocumentType | None = None
    limit: int = Field(default=20, ge=1, le=100)


class ChunkSearchResponse(BaseModel):
    chunks: list[KnowledgeChunkResponse]
    total: int
    query: str


# ---------------------------------------------------------------------------
# Subject Syllabus
# ---------------------------------------------------------------------------

class SyllabusModuleItem(BaseModel):
    module: int
    title: str
    topics: list[str]


class SubjectSyllabusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    syllabus_text: str | None = None
    modules_json: list[dict] | None = None
    co_json: dict | None = None
    rbt_rules: dict | None = None
    created_at: datetime


class SyllabusUploadRequest(BaseModel):
    subject_id: int
    syllabus_text: str | None = None
    modules: list[SyllabusModuleItem] | None = None
    co_definitions: dict[str, str] | None = None
    rbt_rules: dict[str, list[str]] | None = None


# ---------------------------------------------------------------------------
# Question Generation Profile
# ---------------------------------------------------------------------------

class GenerationProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    subject_id: int
    use_notes: bool
    use_question_bank: bool
    use_previous_papers: bool
    use_syllabus: bool
    strict_vtu_mode: bool
    strict_syllabus_mode: bool
    creativity_level: float
    created_at: datetime


class GenerationProfileUpdate(BaseModel):
    use_notes: bool | None = None
    use_question_bank: bool | None = None
    use_previous_papers: bool | None = None
    use_syllabus: bool | None = None
    strict_vtu_mode: bool | None = None
    strict_syllabus_mode: bool | None = None
    creativity_level: float | None = Field(default=None, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Retrieval Source Selection (used during generation)
# ---------------------------------------------------------------------------

class RetrievalSourceSelection(BaseModel):
    """Teacher toggles for choosing generation sources."""
    use_notes: bool = True
    use_question_bank: bool = True
    use_previous_papers: bool = False
    use_syllabus: bool = True


# ---------------------------------------------------------------------------
# Topic Coverage
# ---------------------------------------------------------------------------

class TopicCoverageItem(BaseModel):
    module_number: int
    topic_name: str
    chunk_count: int
    document_count: int
    avg_confidence: float


class TopicCoverageResponse(BaseModel):
    subject_id: int
    total_chunks: int
    total_documents: int
    coverage: list[TopicCoverageItem]
    gaps: list[str]


class QuestionUsageItem(BaseModel):
    question_id: int
    text: str
    module_number: int
    bloom_level: str
    course_outcome: str
    usage_count: int
    last_used_at: str | None = None
    freshness_days: int | None = None


class BloomHeatmapItem(BaseModel):
    module_number: int
    bloom_level: str
    count: int


class OverlapCheckItem(BaseModel):
    question_id: int
    text: str
    compared_text: str
    similarity: float
    source: str


class QuestionBankAnalyticsResponse(BaseModel):
    total_questions: int
    verified_questions: int
    pending_questions: int
    previous_paper_questions: int
    average_usage: float
    freshness_buckets: dict[str, int]
    bloom_heatmap: list[BloomHeatmapItem]
    high_overlap_pairs: list[OverlapCheckItem]
    most_used_questions: list[QuestionUsageItem]
    stale_questions: list[QuestionUsageItem]


class QuestionOverlapCheckRequest(BaseModel):
    subject_id: int | None = None
    questions: list[str]
    previous_papers_only: bool = False
    threshold: float = Field(default=0.72, ge=0.3, le=1.0)


class QuestionOverlapCheckResponse(BaseModel):
    threshold: float
    matches: list[OverlapCheckItem]


class RegenerateSlotRequest(BaseModel):
    subject_id: int
    marks: int
    bloom_level: str
    course_outcome: str
    module_number: int
    topic_name: str | None = None
    existing_questions: list[str] | None = None


# ---------------------------------------------------------------------------
# Retrieval-Constrained Generation (Phase 6)
# ---------------------------------------------------------------------------

class RAGGenerationRequest(BaseModel):
    """Request for retrieval-constrained question generation."""
    subject_id: int
    num_questions: int = Field(default=10, ge=1, le=50)
    marks_distribution: dict[int, int] | None = None  # {2: 5, 5: 3, 10: 2}
    bloom_levels: list[str] | None = None  # ["L1", "L2", "L3"]
    co_targets: list[str] | None = None  # ["CO1", "CO2"]
    question_types: list[str] | None = None  # ["theory", "numerical"]
    module_filter: int | None = Field(default=None, ge=1, le=5)
    additional_instructions: str | None = None
    creativity_override: float | None = Field(default=None, ge=0.0, le=1.0)
    existing_question_texts: list[str] | None = None  # For dedup


class RAGGeneratedQuestionResponse(BaseModel):
    """A single generated question with source traceability."""
    text: str
    marks: int
    bloom_level: str
    co_mapping: str
    module_number: int | None = None
    question_type: str
    topic_name: str | None = None
    source_chunk_ids: list[int] = []
    source_documents: list[str] = []
    attached_images: list[dict[str, Any]] = []
    confidence: float
    is_valid: bool
    validation_errors: list[str] = []
    validation_warnings: list[str] = []


class RAGGenerationResponse(BaseModel):
    """Full response from retrieval-constrained generation."""
    model_config = ConfigDict(protected_namespaces=())

    questions: list[RAGGeneratedQuestionResponse]
    retrieval_summary: dict
    validation_summary: dict
    generation_time: float
    model_used: str
    creativity_level: float
    temperature: float
