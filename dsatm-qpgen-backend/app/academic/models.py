"""
Database models for the Academic Knowledge Intelligence Layer.

Tables:
- AcademicDocument: Uploaded academic files (notes, PPTs, syllabus, previous papers)
- KnowledgeChunk: Semantically chunked content with embeddings
- SubjectSyllabus: Structured syllabus data per subject
- QuestionGenerationProfile: Per-subject generation configuration
- InstitutionalTemplateRecord: Persisted institutional template configs
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DocumentType(StrEnum):
    NOTES = "notes"
    QUESTION_BANK = "question_bank"
    PREVIOUS_PAPER = "previous_paper"
    SYLLABUS = "syllabus"
    LAB_MANUAL = "lab_manual"
    PPT = "ppt"
    OTHER = "other"


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    COMPLETED = "completed"
    FAILED = "failed"


class ChunkApprovalStatus(StrEnum):
    AUTO_APPROVED = "auto_approved"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


class JobStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# AcademicDocument
# ---------------------------------------------------------------------------

class AcademicDocument(Base):
    """Stores uploaded academic files and their processing status."""

    __tablename__ = "academic_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    file_name: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(50))  # pdf, docx, pptx, png, etc.
    document_type: Mapped[DocumentType] = mapped_column(
        Enum(DocumentType), default=DocumentType.NOTES
    )
    storage_path: Mapped[str] = mapped_column(String(1000))

    processing_status: Mapped[ProcessingStatus] = mapped_column(
        Enum(ProcessingStatus), default=ProcessingStatus.PENDING
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    concept_nodes: Mapped[list["ConceptNode"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    extracted_images: Mapped[list["ExtractedImage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# KnowledgeChunk — THE MOST IMPORTANT TABLE
# ---------------------------------------------------------------------------

class KnowledgeChunk(Base):
    """
    Semantically chunked academic content with embeddings.
    
    This is the core table that enables retrieval-constrained generation.
    Each chunk is 400-800 tokens with 10-15% overlap.
    """

    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("academic_documents.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)

    # Content
    chunk_text: Mapped[str] = mapped_column(Text)
    chunk_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer)  # position within document
    token_count: Mapped[int] = mapped_column(Integer, default=0)

    # Academic classification
    module_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    syllabus_unit: Mapped[str | None] = mapped_column(String(200), nullable=True)
    topic_name: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Bloom / CO mapping
    bloom_level: Mapped[str | None] = mapped_column(String(10), nullable=True)
    co_mapping: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Embedding — stored as JSON float array (pgvector can be added later)
    embedding_vector: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Provenance
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Review
    approval_status: Mapped[ChunkApprovalStatus] = mapped_column(
        Enum(ChunkApprovalStatus), default=ChunkApprovalStatus.PENDING_REVIEW
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    document: Mapped["AcademicDocument"] = relationship(back_populates="chunks")


# ---------------------------------------------------------------------------
# ConceptNode (Stage 1 & 2 Structured Understanding)
# ---------------------------------------------------------------------------

class ConceptNode(Base):
    """
    Structured concept extracted from academic documents.
    Captures semantic relationships (topic, module, type, difficulty).
    """

    __tablename__ = "concept_nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("academic_documents.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)

    # Core structured data
    topic: Mapped[str] = mapped_column(String(500))
    module_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    node_type: Mapped[str] = mapped_column(String(50))  # e.g., algorithm, definition, example, workflow
    difficulty: Mapped[str] = mapped_column(String(20)) # e.g., low, medium, high
    
    # Textual content and relationships
    content: Mapped[str] = mapped_column(Text)
    related_topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    question_patterns: Mapped[list[str]] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    document: Mapped["AcademicDocument"] = relationship(back_populates="concept_nodes")


# ---------------------------------------------------------------------------
# SubjectSyllabus
# ---------------------------------------------------------------------------

class SubjectSyllabus(Base):
    """Structured syllabus data for a subject."""

    __tablename__ = "subject_syllabi"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id"), unique=True, index=True
    )

    syllabus_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Structured JSON: [{"module": 1, "title": "...", "topics": [...]}]
    modules_json: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # CO definitions: {"CO1": "description...", ...}
    co_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # RBT rules per CO: {"CO1": ["L1", "L2"], "CO2": ["L3", "L4"]}
    rbt_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    uploaded_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# ExtractedImage
# ---------------------------------------------------------------------------

class ExtractedImage(Base):
    """Stores diagrams and figures extracted from academic documents with keywords."""

    __tablename__ = "extracted_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("academic_documents.id"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)

    image_path: Mapped[str] = mapped_column(String(1000))
    source_page: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    
    # Store list of keywords as JSON
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    ai_caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_hash: Mapped[str] = mapped_column(String(50), default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    document: Mapped["AcademicDocument"] = relationship(back_populates="extracted_images")


# ---------------------------------------------------------------------------
# QuestionGenerationProfile
# ---------------------------------------------------------------------------

class QuestionGenerationProfile(Base):
    """Per-subject generation configuration for retrieval-constrained generation."""

    __tablename__ = "question_generation_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(
        ForeignKey("subjects.id"), unique=True, index=True
    )

    # Source toggles
    use_notes: Mapped[bool] = mapped_column(Boolean, default=True)
    use_question_bank: Mapped[bool] = mapped_column(Boolean, default=True)
    use_previous_papers: Mapped[bool] = mapped_column(Boolean, default=False)
    use_syllabus: Mapped[bool] = mapped_column(Boolean, default=True)

    # Generation mode
    strict_vtu_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    strict_syllabus_mode: Mapped[bool] = mapped_column(Boolean, default=True)

    # Creativity: 0.0 = strict retrieval only, 1.0 = maximum creative
    creativity_level: Mapped[float] = mapped_column(Float, default=0.3)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# InstitutionalTemplateRecord
# ---------------------------------------------------------------------------

class InstitutionalTemplateRecord(Base):
    """Persisted custom template configurations."""

    __tablename__ = "institutional_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_id: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    template_name: Mapped[str] = mapped_column(String(255))
    institution_name: Mapped[str] = mapped_column(String(255), default="")
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# GenerationJob
# ---------------------------------------------------------------------------

class GenerationJob(Base):
    """Tracks background question generation tasks."""

    __tablename__ = "generation_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))

    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING)
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0-100
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Request params (stored as JSON)
    request_params: Mapped[dict] = mapped_column(JSON)
    
    # Result data (stored as JSON)
    result_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
