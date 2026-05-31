"""
API routes for the Academic Knowledge Intelligence Layer.

Provides endpoints for:
- Document upload and ingestion
- Knowledge chunk management (list, search, approve, edit)
- Syllabus management
- Generation profile configuration
- Topic coverage analytics
"""

from __future__ import annotations

import logging
import re
import io
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..auth import get_current_user, require_roles
from ..config import settings
from ..database import get_db
from ..models import PaperQuestion, Question, QuestionPaper, Role, Subject, TeacherSubject, User
from ..services import ensure_subject_access
from .embeddings import generate_embedding, generate_embeddings_batch
from .ingestion import create_document_record, process_document_background, process_syllabus_background
from .models import (
    AcademicDocument,
    ChunkApprovalStatus,
    DocumentType,
    ExtractedImage,
    KnowledgeChunk,
    ProcessingStatus,
    QuestionGenerationProfile,
    SubjectSyllabus,
)
from .schemas import (
    AcademicDocumentListResponse,
    AcademicDocumentResponse,
    ChunkApprovalRequest,
    ChunkEditRequest,
    ChunkSearchResponse,
    DocumentPreviewResponse,
    GenerationProfileResponse,
    GenerationProfileUpdate,
    KnowledgeChunkResponse,
    OverlapCheckItem,
    QuestionBankAnalyticsResponse,
    QuestionOverlapCheckRequest,
    QuestionOverlapCheckResponse,
    QuestionUsageItem,
    RAGGeneratedQuestionResponse,
    RAGGenerationRequest,
    RAGGenerationResponse,
    RegenerateSlotRequest,
    BloomHeatmapItem,
    SubjectSyllabusResponse,
    SyllabusUploadRequest,
    TopicCoverageItem,
    TopicCoverageResponse,
)

logger = logging.getLogger("app.academic.routes")

router = APIRouter(prefix="/api/v1/academic", tags=["academic"])

_INLINE_INGEST_EXTENSIONS = {".txt", ".md", ".csv"}
_INLINE_INGEST_MAX_BYTES = 512 * 1024


def _get_subject_or_404(db: Session, subject_id: int) -> Subject:
    subject = db.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return subject


def _ensure_subject_route_access(db: Session, user: User, subject_id: int) -> Subject:
    subject = _get_subject_or_404(db, subject_id)
    ensure_subject_access(user, subject, db)
    return subject


def _get_accessible_subject_ids(db: Session, user: User) -> list[int] | None:
    if user.role == Role.ADMIN:
        return None
    if user.role == Role.HOD and user.dept_id is not None:
        return list(db.scalars(select(Subject.id).where(Subject.dept_id == user.dept_id)))
    if user.role == Role.TEACHER:
        return list(
            db.scalars(
                select(TeacherSubject.subject_id).where(TeacherSubject.teacher_id == user.id)
            )
        )
    return []


def _apply_subject_scope(stmt, subject_column, accessible_subject_ids: list[int] | None):
    if accessible_subject_ids is None:
        return stmt
    if not accessible_subject_ids:
        return stmt.where(False)
    return stmt.where(subject_column.in_(accessible_subject_ids))


def _should_process_inline(filename: str, content_size: int) -> bool:
    suffix = Path(filename).suffix.lower()
    return suffix in _INLINE_INGEST_EXTENSIONS and content_size <= _INLINE_INGEST_MAX_BYTES


def _normalize_overlap_text(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", str(text or "").lower())
        if len(token) > 2
    ]


def _question_similarity(left: str, right: str) -> float:
    left_tokens = set(_normalize_overlap_text(left))
    right_tokens = set(_normalize_overlap_text(right))
    if not left_tokens or not right_tokens:
        return 0.0
    shared = len(left_tokens & right_tokens)
    return shared / max(min(len(left_tokens), len(right_tokens)), 1)


def _preview_excerpt(text: str | None, limit: int = 700) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    return f"{cleaned[: limit - 1].rstrip()}..."


def _resolve_image_path(image_path: str) -> Path | None:
    path = Path(image_path)
    candidates = [path]
    if not path.is_absolute():
        candidates.extend(
            [
                settings.storage_path / path,
                Path(__file__).resolve().parents[3] / path,
                Path(__file__).resolve().parents[2] / path,
            ]
        )
    path_text = str(path)
    if f"{Path('backend')}\\{Path('storage')}" in path_text:
        candidates.append(Path(path_text.replace(f"{Path('backend')}\\{Path('storage')}", "storage")))

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _fallback_image_svg(image: ExtractedImage) -> str:
    caption = re.sub(r"[<>&]", " ", image.ai_caption or "Extracted figure preview")
    keywords = ", ".join((image.keywords or [])[:4]) or "academic figure"
    keywords = re.sub(r"[<>&]", " ", keywords)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
  <rect width="640" height="360" rx="24" fill="#111827"/>
  <rect x="24" y="24" width="592" height="312" rx="18" fill="#1f2937" stroke="#334155"/>
  <circle cx="320" cy="128" r="42" fill="#3b82f6" opacity="0.22"/>
  <path d="M287 148h66l-19-25-14 17-10-12-23 20z" fill="#93c5fd"/>
  <rect x="206" y="202" width="228" height="14" rx="7" fill="#64748b" opacity="0.65"/>
  <rect x="154" y="232" width="332" height="12" rx="6" fill="#475569" opacity="0.65"/>
  <text x="320" y="282" fill="#cbd5e1" font-family="Arial, sans-serif" font-size="20" font-weight="700" text-anchor="middle">{caption[:54]}</text>
  <text x="320" y="310" fill="#94a3b8" font-family="Arial, sans-serif" font-size="16" text-anchor="middle">Page {image.source_page or 1} • {keywords[:58]}</text>
</svg>"""


# ---------------------------------------------------------------------------
# Document Upload
# ---------------------------------------------------------------------------

@router.post("/documents/upload", response_model=AcademicDocumentResponse)
async def upload_academic_document(
    background_tasks: BackgroundTasks,
    subject_id: int = Form(...),
    document_type: str = Form("notes"),
    file: UploadFile = File(...),
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> AcademicDocumentResponse:
    """Upload and ingest an academic document."""
    _ensure_subject_route_access(db, user, subject_id)

    # Validate file type
    filename = file.filename or "upload"
    suffix = Path(filename).suffix.lower()
    allowed = {".pdf", ".docx", ".pptx", ".txt", ".md", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {suffix}. Allowed: {', '.join(sorted(allowed))}",
        )

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    # Parse document type
    try:
        doc_type = DocumentType(document_type)
    except ValueError:
        doc_type = DocumentType.NOTES

    # Create the record immediately and return
    doc = create_document_record(
        db=db,
        subject_id=subject_id,
        user_id=user.id,
        file_name=filename,
        content=content,
        document_type=doc_type,
    )

    is_syllabus = (doc_type == DocumentType.SYLLABUS)
    processor = process_syllabus_background if is_syllabus else process_document_background

    if _should_process_inline(filename, len(content)):
        processor(doc.id)
        db.refresh(doc)
        logger.info(
            "Processed lightweight document %d inline for faster knowledge-base feedback",
            doc.id,
        )
    else:
        background_tasks.add_task(processor, doc.id)
        logger.info(
            "Queued background processing for document %d (%d bytes)",
            doc.id,
            len(content),
        )

    return AcademicDocumentResponse.model_validate(doc)


@router.post("/previous-papers/import")
async def import_previous_year_paper(
    subject_id: int = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """Extract questions from a previous year paper into the indexed question bank."""
    from ..ai_service import process_question_bank

    _ensure_subject_route_access(db, user, subject_id)
    result = await process_question_bank(
        file,
        subject_id,
        user.id,
        db,
        source_type="previous_paper",
    )
    return {
        "success": result.success,
        "document_id": result.document_id,
        "filename": result.filename,
        "total_extracted": result.total_extracted,
        "auto_approved": result.auto_approved,
        "processing_time": round(result.processing_time, 2),
        "ai_model": result.ai_model,
        "ai_mode": result.ai_mode,
        "summary": result.summary,
        "error": result.error,
        "source_type": "previous_paper",
    }


def _generate_chunk_embeddings_bg(document_id: int) -> None:
    """Generate embeddings for all chunks of a document (background task).
    
    Creates its own database session since this runs outside the request context.
    """
    from ..database import SessionLocal
    
    db = SessionLocal()
    try:
        _generate_chunk_embeddings(db, document_id)
    finally:
        db.close()


def _generate_chunk_embeddings(db: Session, document_id: int) -> None:
    """Generate embeddings for all chunks of a document."""
    chunks = list(
        db.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document_id)
            .order_by(KnowledgeChunk.chunk_index)
        )
    )
    if not chunks:
        return

    texts = [c.chunk_text for c in chunks]
    embeddings = generate_embeddings_batch(texts)

    for chunk, embedding in zip(chunks, embeddings):
        if embedding is not None:
            chunk.embedding_vector = embedding

    db.commit()
    logger.info("Generated embeddings for %d chunks (doc=%d)", len(chunks), document_id)


# ---------------------------------------------------------------------------
# Document Listing
# ---------------------------------------------------------------------------

@router.get("/documents", response_model=AcademicDocumentListResponse)
def list_academic_documents(
    subject_id: int | None = None,
    document_type: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """List academic documents with optional filters."""
    stmt = select(AcademicDocument).order_by(AcademicDocument.created_at.desc())
    accessible_subject_ids = _get_accessible_subject_ids(db, user)

    if subject_id:
        _ensure_subject_route_access(db, user, subject_id)
        stmt = stmt.where(AcademicDocument.subject_id == subject_id)
    if document_type:
        try:
            stmt = stmt.where(AcademicDocument.document_type == DocumentType(document_type))
        except ValueError:
            pass
    if subject_id is None:
        stmt = _apply_subject_scope(stmt, AcademicDocument.subject_id, accessible_subject_ids)

    # Access control
    if user.role == Role.TEACHER:
        stmt = stmt.where(AcademicDocument.uploaded_by == user.id)

    docs = list(db.scalars(stmt))
    return {"documents": docs, "total": len(docs)}


@router.delete("/documents/{document_id}", status_code=200)
def delete_academic_document(
    document_id: int,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """Delete an academic document and its chunks."""
    doc = db.get(AcademicDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_subject_route_access(db, user, doc.subject_id)
    if user.role == Role.TEACHER and doc.uploaded_by != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this document")

    db.delete(doc)
    db.commit()
    return {"deleted": True, "document_id": document_id}


@router.get("/documents/{document_id}/preview", response_model=DocumentPreviewResponse)
def preview_academic_document(
    document_id: int,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """Return extracted chunks and images for teacher-side extraction review."""
    stmt = (
        select(AcademicDocument)
        .options(
            selectinload(AcademicDocument.chunks),
            selectinload(AcademicDocument.extracted_images),
        )
        .where(AcademicDocument.id == document_id)
    )
    document = db.scalar(stmt)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_subject_route_access(db, user, document.subject_id)
    if user.role == Role.TEACHER and document.uploaded_by != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to preview this document")

    chunks = sorted(document.chunks, key=lambda item: item.chunk_index)
    chunks_by_page: dict[int, list[KnowledgeChunk]] = {}
    for chunk in chunks:
        page = int(chunk.page_number or 1)
        chunks_by_page.setdefault(page, []).append(chunk)

    images = []
    for image in sorted(document.extracted_images, key=lambda item: (item.source_page, item.id)):
        image_file = _resolve_image_path(image.image_path)
        page_chunks = chunks_by_page.get(int(image.source_page or 1), [])
        before_text = page_chunks[0].chunk_text if page_chunks else ""
        after_text = page_chunks[1].chunk_text if len(page_chunks) > 1 else before_text
        caption = image.ai_caption or (
            f"Extracted figure related to {', '.join(image.keywords[:4])}"
            if image.keywords
            else "Extracted figure"
        )
        images.append(
            {
                "id": image.id,
                "image_path": image.image_path,
                "image_available": True,
                "source_page": image.source_page,
                "keywords": image.keywords or [],
                "context_before": _preview_excerpt(before_text),
                "context_after": _preview_excerpt(after_text),
                "ai_caption": caption,
                "width": image.width,
                "height": image.height,
            }
        )

    return {
        "id": document.id,
        "filename": document.file_name,
        "parsed_text": document.extracted_text or "",
        "chunks": [
            {
                "id": chunk.id,
                "page": int(chunk.page_number or 1),
                "text": chunk.chunk_text,
                "source_type": document.document_type.value,
                "block_index": chunk.chunk_index,
            }
            for chunk in chunks
        ],
        "images": images,
    }


@router.get("/documents/images/{image_id}")
def get_academic_document_image(
    image_id: int,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    """Serve an extracted academic image after normal subject access checks."""
    image = db.get(ExtractedImage, image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    document = db.get(AcademicDocument, image.document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    _ensure_subject_route_access(db, user, document.subject_id)
    if user.role == Role.TEACHER and document.uploaded_by != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this image")

    image_path = _resolve_image_path(image.image_path)
    if image_path is None:
        logger.warning(
            "Extracted image file missing for image_id=%s path=%s",
            image.id,
            image.image_path,
        )
        raise HTTPException(status_code=404, detail="Image file not found on disk")
    return FileResponse(image_path)


# ---------------------------------------------------------------------------
# Knowledge Chunks
# ---------------------------------------------------------------------------

@router.get("/chunks", response_model=list[KnowledgeChunkResponse])
def list_knowledge_chunks(
    document_id: int | None = None,
    subject_id: int | None = None,
    module_number: int | None = None,
    approval_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list:
    """List knowledge chunks with filtering."""
    stmt = select(KnowledgeChunk).order_by(
        KnowledgeChunk.document_id, KnowledgeChunk.chunk_index
    )
    accessible_subject_ids = _get_accessible_subject_ids(db, user)

    if document_id:
        document = db.get(AcademicDocument, document_id)
        if document is None:
            raise HTTPException(status_code=404, detail="Document not found")
        _ensure_subject_route_access(db, user, document.subject_id)
        stmt = stmt.where(KnowledgeChunk.document_id == document_id)
    if subject_id:
        _ensure_subject_route_access(db, user, subject_id)
        stmt = stmt.where(KnowledgeChunk.subject_id == subject_id)
    if document_id is None and subject_id is None:
        stmt = _apply_subject_scope(stmt, KnowledgeChunk.subject_id, accessible_subject_ids)
    if module_number:
        stmt = stmt.where(KnowledgeChunk.module_number == module_number)
    if approval_status:
        try:
            stmt = stmt.where(
                KnowledgeChunk.approval_status == ChunkApprovalStatus(approval_status)
            )
        except ValueError:
            pass

    stmt = stmt.limit(limit).offset(offset)
    return list(db.scalars(stmt))


@router.get("/chunks/search", response_model=ChunkSearchResponse)
def search_knowledge_chunks(
    query: str,
    subject_id: int | None = None,
    module_number: int | None = None,
    limit: int = 20,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Semantic search across knowledge chunks."""
    # Generate query embedding
    query_embedding = generate_embedding(query)
    accessible_subject_ids = _get_accessible_subject_ids(db, user)

    # Build base filter
    stmt = select(KnowledgeChunk)
    if subject_id:
        _ensure_subject_route_access(db, user, subject_id)
        stmt = stmt.where(KnowledgeChunk.subject_id == subject_id)
    else:
        stmt = _apply_subject_scope(stmt, KnowledgeChunk.subject_id, accessible_subject_ids)
    if module_number:
        stmt = stmt.where(KnowledgeChunk.module_number == module_number)

    # Only search approved/auto-approved chunks
    stmt = stmt.where(
        KnowledgeChunk.approval_status.in_([
            ChunkApprovalStatus.AUTO_APPROVED,
            ChunkApprovalStatus.APPROVED,
            ChunkApprovalStatus.EDITED,
        ])
    )

    all_chunks = list(db.scalars(stmt))

    if query_embedding and all_chunks:
        # Semantic search using embeddings
        from .embeddings import cosine_similarity

        scored = []
        for chunk in all_chunks:
            if chunk.embedding_vector:
                score = cosine_similarity(query_embedding, chunk.embedding_vector)
                scored.append((chunk, score))
            else:
                # Fallback: text matching
                if query.lower() in chunk.chunk_text.lower():
                    scored.append((chunk, 0.5))

        scored.sort(key=lambda x: x[1], reverse=True)
        results = [c for c, _ in scored[:limit]]
    else:
        # Text-based fallback search
        stmt = stmt.where(KnowledgeChunk.chunk_text.ilike(f"%{query}%"))
        results = list(db.scalars(stmt.limit(limit)))

    return {"chunks": results, "total": len(results), "query": query}


@router.put("/chunks/{chunk_id}/approve")
def approve_chunk(
    chunk_id: int,
    payload: ChunkApprovalRequest,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> KnowledgeChunkResponse:
    """Approve or reject a knowledge chunk."""
    chunk = db.get(KnowledgeChunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    _ensure_subject_route_access(db, user, chunk.subject_id)

    document = db.get(AcademicDocument, chunk.document_id)
    if user.role == Role.TEACHER and document is not None and document.uploaded_by != user.id:
        raise HTTPException(status_code=403, detail="Only the owning teacher can approve this chunk")

    chunk.approval_status = payload.approval_status
    chunk.reviewed_by = user.id
    chunk.review_notes = payload.review_notes
    db.commit()
    db.refresh(chunk)
    return KnowledgeChunkResponse.model_validate(chunk)


@router.put("/chunks/{chunk_id}/edit")
def edit_chunk(
    chunk_id: int,
    payload: ChunkEditRequest,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> KnowledgeChunkResponse:
    """Edit a knowledge chunk's content or metadata."""
    chunk = db.get(KnowledgeChunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    _ensure_subject_route_access(db, user, chunk.subject_id)

    document = db.get(AcademicDocument, chunk.document_id)
    if user.role == Role.TEACHER and document is not None and document.uploaded_by != user.id:
        raise HTTPException(status_code=403, detail="Only the owning teacher can edit this chunk")

    if payload.chunk_text is not None:
        chunk.chunk_text = payload.chunk_text
        # Re-generate embedding
        new_embedding = generate_embedding(payload.chunk_text)
        if new_embedding:
            chunk.embedding_vector = new_embedding
    if payload.module_number is not None:
        chunk.module_number = payload.module_number
    if payload.topic_name is not None:
        chunk.topic_name = payload.topic_name
    if payload.bloom_level is not None:
        chunk.bloom_level = payload.bloom_level
    if payload.co_mapping is not None:
        chunk.co_mapping = payload.co_mapping

    chunk.approval_status = ChunkApprovalStatus.EDITED
    chunk.reviewed_by = user.id
    db.commit()
    db.refresh(chunk)
    return KnowledgeChunkResponse.model_validate(chunk)


# ---------------------------------------------------------------------------
# Syllabus Management
# ---------------------------------------------------------------------------

@router.post("/syllabus", response_model=SubjectSyllabusResponse)
def upload_syllabus(
    payload: SyllabusUploadRequest,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> SubjectSyllabus:
    """Create or update a subject syllabus."""
    _ensure_subject_route_access(db, user, payload.subject_id)

    existing = db.scalar(
        select(SubjectSyllabus).where(SubjectSyllabus.subject_id == payload.subject_id)
    )

    if existing:
        if payload.syllabus_text is not None:
            existing.syllabus_text = payload.syllabus_text
        if payload.modules is not None:
            existing.modules_json = [m.model_dump() for m in payload.modules]
        if payload.co_definitions is not None:
            existing.co_json = payload.co_definitions
        if payload.rbt_rules is not None:
            existing.rbt_rules = payload.rbt_rules
        db.commit()
        db.refresh(existing)
        return existing

    syllabus = SubjectSyllabus(
        subject_id=payload.subject_id,
        syllabus_text=payload.syllabus_text,
        modules_json=[m.model_dump() for m in payload.modules] if payload.modules else None,
        co_json=payload.co_definitions,
        rbt_rules=payload.rbt_rules,
        uploaded_by=user.id,
    )
    db.add(syllabus)
    db.commit()
    db.refresh(syllabus)
    return syllabus


@router.get("/syllabus/{subject_id}", response_model=SubjectSyllabusResponse)
def get_syllabus(
    subject_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubjectSyllabus:
    """Get syllabus for a subject."""
    _ensure_subject_route_access(db, user, subject_id)
    syllabus = db.scalar(
        select(SubjectSyllabus).where(SubjectSyllabus.subject_id == subject_id)
    )
    if not syllabus:
        raise HTTPException(status_code=404, detail="Syllabus not found for this subject")
    return syllabus


# ---------------------------------------------------------------------------
# Generation Profile
# ---------------------------------------------------------------------------

@router.get("/profile/{subject_id}", response_model=GenerationProfileResponse)
def get_generation_profile(
    subject_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QuestionGenerationProfile:
    """Get or create generation profile for a subject."""
    _ensure_subject_route_access(db, user, subject_id)
    profile = db.scalar(
        select(QuestionGenerationProfile).where(
            QuestionGenerationProfile.subject_id == subject_id
        )
    )
    if not profile:
        profile = QuestionGenerationProfile(subject_id=subject_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.put("/profile/{subject_id}", response_model=GenerationProfileResponse)
def update_generation_profile(
    subject_id: int,
    payload: GenerationProfileUpdate,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> QuestionGenerationProfile:
    """Update generation profile for a subject."""
    _ensure_subject_route_access(db, user, subject_id)
    profile = db.scalar(
        select(QuestionGenerationProfile).where(
            QuestionGenerationProfile.subject_id == subject_id
        )
    )
    if not profile:
        profile = QuestionGenerationProfile(subject_id=subject_id)
        db.add(profile)
        db.flush()

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Topic Coverage Analytics
# ---------------------------------------------------------------------------

@router.get("/coverage/{subject_id}", response_model=TopicCoverageResponse)
def get_topic_coverage(
    subject_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Get topic coverage analysis for a subject."""
    _ensure_subject_route_access(db, user, subject_id)
    # Total counts
    total_chunks = db.scalar(
        select(func.count(KnowledgeChunk.id)).where(
            KnowledgeChunk.subject_id == subject_id
        )
    ) or 0

    total_docs = db.scalar(
        select(func.count(AcademicDocument.id)).where(
            AcademicDocument.subject_id == subject_id
        )
    ) or 0

    # Coverage by module and topic
    coverage_query = (
        select(
            KnowledgeChunk.module_number,
            KnowledgeChunk.topic_name,
            func.count(KnowledgeChunk.id).label("chunk_count"),
            func.count(func.distinct(KnowledgeChunk.document_id)).label("doc_count"),
            func.avg(KnowledgeChunk.confidence_score).label("avg_conf"),
        )
        .where(KnowledgeChunk.subject_id == subject_id)
        .group_by(KnowledgeChunk.module_number, KnowledgeChunk.topic_name)
        .order_by(KnowledgeChunk.module_number)
    )

    rows = db.execute(coverage_query).all()
    coverage = [
        TopicCoverageItem(
            module_number=row.module_number or 0,
            topic_name=row.topic_name or "Unclassified",
            chunk_count=row.chunk_count,
            document_count=row.doc_count,
            avg_confidence=round(float(row.avg_conf or 0), 3),
        )
        for row in rows
    ]

    # Gap detection
    gaps: list[str] = []
    covered_modules = {item.module_number for item in coverage if item.module_number}
    for module in range(1, 6):
        if module not in covered_modules:
            gaps.append(f"Module {module} has no content chunks")
    
    low_coverage = [
        item for item in coverage if item.chunk_count < 3
    ]
    for item in low_coverage:
        gaps.append(f"Module {item.module_number} topic '{item.topic_name}' has only {item.chunk_count} chunk(s)")

    return {
        "subject_id": subject_id,
        "total_chunks": total_chunks,
        "total_documents": total_docs,
        "coverage": coverage,
        "gaps": gaps,
    }


@router.get("/question-bank/analytics", response_model=QuestionBankAnalyticsResponse)
def get_question_bank_analytics(
    subject_id: int | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Question-bank usage, freshness, and overlap analytics."""
    accessible_subject_ids = _get_accessible_subject_ids(db, user)
    question_stmt = select(Question)

    if subject_id is not None:
        _ensure_subject_route_access(db, user, subject_id)
        question_stmt = question_stmt.where(Question.subject_id == subject_id)
    else:
        question_stmt = _apply_subject_scope(question_stmt, Question.subject_id, accessible_subject_ids)

    questions = list(db.scalars(question_stmt.order_by(Question.created_at.desc())))
    question_ids = [question.id for question in questions]

    usage_rows = []
    if question_ids:
        usage_rows = list(
            db.execute(
                select(
                    PaperQuestion.question_id,
                    func.count(PaperQuestion.id).label("usage_count"),
                    func.max(QuestionPaper.created_at).label("last_used_at"),
                )
                .join(QuestionPaper, QuestionPaper.id == PaperQuestion.paper_id)
                .where(PaperQuestion.question_id.in_(question_ids))
                .group_by(PaperQuestion.question_id)
            )
        )

    usage_map = {
        int(row.question_id): {
            "usage_count": int(row.usage_count or 0),
            "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        }
        for row in usage_rows
    }

    now = datetime.now(timezone.utc)
    freshness_buckets = {"recent": 0, "aging": 0, "stale": 0, "unused": 0}
    heatmap: dict[tuple[int, str], int] = {}
    usage_items: list[QuestionUsageItem] = []
    stale_items: list[QuestionUsageItem] = []
    previous_paper_questions = 0

    for question in questions:
        usage = usage_map.get(question.id, {"usage_count": 0, "last_used_at": None})
        freshness_days = max(0, (now - question.created_at).days)
        usage_count = int(usage["usage_count"])

        if usage_count == 0:
            freshness_buckets["unused"] += 1
        elif freshness_days <= 90:
            freshness_buckets["recent"] += 1
        elif freshness_days <= 180:
            freshness_buckets["aging"] += 1
        else:
            freshness_buckets["stale"] += 1

        heatmap[(int(question.module_number or 1), str(question.bloom_level or "L1"))] = (
            heatmap.get((int(question.module_number or 1), str(question.bloom_level or "L1")), 0) + 1
        )

        tags = {str(tag).lower() for tag in (question.tags or [])}
        if "source_type:previous_paper" in tags or "previous-paper" in tags:
            previous_paper_questions += 1

        usage_item = QuestionUsageItem(
            question_id=question.id,
            text=question.text,
            module_number=int(question.module_number or 1),
            bloom_level=str(question.bloom_level or "L1"),
            course_outcome=str(question.course_outcome or "CO1"),
            usage_count=usage_count,
            last_used_at=usage["last_used_at"],
            freshness_days=freshness_days,
        )
        usage_items.append(usage_item)
        if usage_count == 0 or freshness_days > 180:
            stale_items.append(usage_item)

    overlap_pairs: list[OverlapCheckItem] = []
    for index, question in enumerate(questions):
        for other in questions[index + 1 :]:
            if question.subject_id != other.subject_id:
                continue
            similarity = _question_similarity(question.text, other.text)
            if similarity < 0.72:
                continue
            overlap_pairs.append(
                OverlapCheckItem(
                    question_id=question.id,
                    text=question.text,
                    compared_text=other.text,
                    similarity=round(similarity, 3),
                    source="question_bank",
                )
            )
    overlap_pairs.sort(key=lambda item: item.similarity, reverse=True)

    heatmap_items = [
        BloomHeatmapItem(module_number=module, bloom_level=bloom, count=count)
        for (module, bloom), count in sorted(heatmap.items())
    ]

    usage_items.sort(key=lambda item: (item.usage_count, -(item.freshness_days or 0)), reverse=True)
    stale_items.sort(key=lambda item: ((item.freshness_days or 0), item.usage_count), reverse=True)
    average_usage = round(
        sum(item.usage_count for item in usage_items) / max(len(usage_items), 1),
        2,
    )

    return {
        "total_questions": len(questions),
        "verified_questions": sum(1 for question in questions if question.is_verified),
        "pending_questions": sum(1 for question in questions if not question.is_verified),
        "previous_paper_questions": previous_paper_questions,
        "average_usage": average_usage,
        "freshness_buckets": freshness_buckets,
        "bloom_heatmap": heatmap_items,
        "high_overlap_pairs": overlap_pairs[:12],
        "most_used_questions": usage_items[:8],
        "stale_questions": stale_items[:8],
    }


@router.post("/question-bank/overlap-check", response_model=QuestionOverlapCheckResponse)
def question_bank_overlap_check(
    payload: QuestionOverlapCheckRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Check new or generated questions against the indexed bank for overlap risk."""
    accessible_subject_ids = _get_accessible_subject_ids(db, user)
    stmt = select(Question)

    if payload.subject_id is not None:
        _ensure_subject_route_access(db, user, payload.subject_id)
        stmt = stmt.where(Question.subject_id == payload.subject_id)
    else:
        stmt = _apply_subject_scope(stmt, Question.subject_id, accessible_subject_ids)

    candidates = list(db.scalars(stmt))
    if payload.previous_papers_only:
        candidates = [
            question
            for question in candidates
            if any(
                marker in {str(tag).lower() for tag in (question.tags or [])}
                for marker in ("source_type:previous_paper", "previous-paper")
            )
        ]

    matches: list[OverlapCheckItem] = []
    for text in payload.questions:
        for question in candidates:
            similarity = _question_similarity(text, question.text)
            if similarity < payload.threshold:
                continue
            matches.append(
                OverlapCheckItem(
                    question_id=question.id,
                    text=text,
                    compared_text=question.text,
                    similarity=round(similarity, 3),
                    source="previous_paper" if payload.previous_papers_only else "question_bank",
                )
            )

    matches.sort(key=lambda item: item.similarity, reverse=True)
    return {"threshold": payload.threshold, "matches": matches[:25]}


# ---------------------------------------------------------------------------
# Retrieval-Constrained Generation (Phase 6)
# ---------------------------------------------------------------------------

@router.post("/generate", response_model=None)
async def generate_questions_rag(
    payload: RAGGenerationRequest,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """
    Generate questions using retrieval-constrained generation.

    The LLM NEVER generates from memory. All output is:
    1. Sourced from retrieved academic chunks
    2. Validated against the knowledge base
    3. Traced back to source documents

    Returns questions with full traceability and validation results.
    """
    from .generation import generate_questions_from_retrieval

    # Validate subject exists
    _ensure_subject_route_access(db, user, payload.subject_id)

    # Check we have content to generate from
    chunk_count = db.scalar(
        select(func.count(KnowledgeChunk.id)).where(
            KnowledgeChunk.subject_id == payload.subject_id,
            KnowledgeChunk.approval_status.in_([
                ChunkApprovalStatus.AUTO_APPROVED,
                ChunkApprovalStatus.APPROVED,
                ChunkApprovalStatus.EDITED,
            ]),
        )
        .join(AcademicDocument, AcademicDocument.id == KnowledgeChunk.document_id)
        .where(AcademicDocument.document_type != DocumentType.SYLLABUS)
    ) or 0

    if chunk_count == 0:
        raise HTTPException(
            status_code=400,
            detail="No approved knowledge chunks found for this subject. Upload and approve academic materials first.",
        )

    result = await generate_questions_from_retrieval(
        db=db,
        subject_id=payload.subject_id,
        num_questions=payload.num_questions,
        marks_distribution=payload.marks_distribution,
        bloom_levels=payload.bloom_levels,
        co_targets=payload.co_targets,
        question_types=payload.question_types,
        module_filter=payload.module_filter,
        additional_instructions=payload.additional_instructions,
        creativity_override=payload.creativity_override,
        existing_questions=payload.existing_question_texts,
    )

    # Build response — serialize ValidationIssue objects to strings
    questions_out = []
    for q in result.questions:
        questions_out.append(
            RAGGeneratedQuestionResponse(
                text=q.text,
                marks=q.marks,
                bloom_level=q.bloom_level,
                co_mapping=q.co_mapping,
                module_number=q.module_number,
                question_type=q.question_type,
                topic_name=q.topic_name,
                source_chunk_ids=q.source_chunk_ids,
                source_documents=q.source_documents,
                attached_images=q.attached_images,
                confidence=q.confidence,
                is_valid=q.validation.is_valid if q.validation else True,
                validation_errors=[i.message for i in q.validation.errors] if q.validation else [],
                validation_warnings=[i.message for i in q.validation.warnings] if q.validation else [],
            )
        )

    return RAGGenerationResponse(
        questions=questions_out,
        retrieval_summary=result.retrieval_summary,
        validation_summary=result.validation_summary,
        generation_time=result.generation_time,
        model_used=result.model_used,
        creativity_level=result.creativity_level,
        temperature=result.temperature,
    ).model_dump()


# ---------------------------------------------------------------------------
# Pedagogical Analysis (Phase 1)
# ---------------------------------------------------------------------------

@router.post("/pedagogical/analyze")
def analyze_question_pedagogical(
    payload: dict,
    user: User = Depends(get_current_user),
) -> dict:
    """
    Analyze a question for pedagogical metadata.

    Entirely rule-based — no LLM calls, <1ms response.

    Payload: { "text": str, "bloom_level": str|null, "marks": int }
    """
    from .pedagogical_engine import analyze_question

    intel = analyze_question(
        text=payload.get("text", ""),
        bloom_level=payload.get("bloom_level"),
        marks=int(payload.get("marks", 5)),
    )
    return {
        "bloom_level": intel.bloom_level,
        "bloom_label": intel.bloom_label,
        "difficulty": intel.difficulty,
        "difficulty_index": intel.difficulty_index,
        "marks": intel.marks,
        "time_estimate_min": intel.time_estimate_min,
        "cognitive_load": intel.cognitive_load,
        "expected_answer_depth": intel.expected_answer_depth,
        "question_family": intel.question_family,
        "is_numerical": intel.is_numerical,
        "solution_steps_estimate": intel.solution_steps_estimate,
        "marks_valid": intel.marks_valid,
        "marks_suggestion": intel.marks_suggestion,
    }


@router.post("/pedagogical/analyze-paper")
def analyze_paper_time_budget(
    payload: dict,
    user: User = Depends(get_current_user),
) -> dict:
    """
    Analyze whether a paper's total time fits the exam duration.

    Payload: { "questions": [...], "exam_duration_min": int }
    """
    from .pedagogical_engine import analyze_paper_time

    result = analyze_paper_time(
        questions=payload.get("questions", []),
        exam_duration_min=int(payload.get("exam_duration_min", 90)),
    )
    return {
        "total_estimated_min": result.total_estimated_min,
        "exam_duration_min": result.exam_duration_min,
        "time_surplus_min": result.time_surplus_min,
        "is_balanced": result.is_balanced,
        "per_question": result.per_question,
        "warnings": result.warnings,
    }


# ---------------------------------------------------------------------------
# Mark Strategies (Phase 1)
# ---------------------------------------------------------------------------

@router.get("/mark-strategies")
def list_mark_strategies(
    user: User = Depends(get_current_user),
) -> list[dict]:
    """List all available mark distribution strategies."""
    from .mark_engine import list_strategies
    return list_strategies()


@router.post("/mark-strategies/allocate")
def allocate_marks_endpoint(
    payload: dict,
    user: User = Depends(get_current_user),
) -> dict:
    """
    Allocate marks across Bloom levels using a strategy.

    Payload: { "total_marks": int, "strategy": str }
    """
    from .mark_engine import allocate_marks

    result = allocate_marks(
        total_marks=int(payload.get("total_marks", 50)),
        strategy_name=str(payload.get("strategy", "balanced")),
    )
    return {
        "strategy": result.strategy,
        "total_marks": result.total_marks,
        "bloom_allocation": result.bloom_allocation,
        "bloom_question_counts": result.bloom_question_counts,
        "warnings": result.warnings,
    }


# ---------------------------------------------------------------------------
# Institutional Templates (Phase 2)
# ---------------------------------------------------------------------------

@router.get("/templates")
def list_templates(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List all available institutional templates."""
    from .templates import get_template_manager
    return get_template_manager().list_templates(db)


@router.get("/templates/{template_id}")
def get_template(
    template_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """Get full configuration of a template."""
    from .templates import get_template_manager
    return get_template_manager().get_template(template_id, db).to_dict()


@router.post("/templates")
def create_custom_template(
    payload: dict,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """Create a custom institutional template."""
    from .templates import InstitutionalTemplate, get_template_manager

    template = InstitutionalTemplate.from_dict(payload)
    saved = get_template_manager().save_custom_template(
        template,
        db=db,
        owner_user_id=user.id,
    )
    return saved.to_dict()


@router.put("/templates/{template_id}")
def update_custom_template(
    template_id: str,
    payload: dict,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """Update a custom institutional template."""
    from .templates import InstitutionalTemplate, get_template_manager

    body = dict(payload)
    body["template_id"] = template_id
    template = InstitutionalTemplate.from_dict(body)
    saved = get_template_manager().save_custom_template(
        template,
        db=db,
        owner_user_id=user.id,
    )
    return saved.to_dict()


@router.delete("/templates/{template_id}")
def delete_template(
    template_id: str,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """Delete a custom template. Cannot delete presets."""
    from .templates import get_template_manager

    deleted = get_template_manager().delete_custom_template(template_id, db)
    if not deleted:
        raise HTTPException(status_code=400, detail="Cannot delete preset templates")
    return {"deleted": True, "template_id": template_id}


@router.post("/templates/{template_id}/logo")
async def upload_template_logo(
    template_id: str,
    position: str = Form(...),  # "left" or "right"
    file: UploadFile = File(...),
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
) -> dict:
    """Upload a logo/seal for a template."""
    from .templates import get_template_manager

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Logo file too large (max 5MB)")

    manager = get_template_manager()
    rel_path = manager.save_logo(
        template_id, position, content, file.filename or "logo.png"
    )
    return {"path": rel_path, "position": position, "template_id": template_id}


# ---------------------------------------------------------------------------
# Rubric Generation (Phase 4)
# ---------------------------------------------------------------------------

@router.post("/rubric/generate")
def generate_rubric(
    payload: dict,
    user: User = Depends(get_current_user),
) -> dict:
    """
    Generate marking rubrics for a paper.

    Payload: { "paper_title": str, "questions": [...] }
    Each question: { "text": str, "marks": int, "bloom_level": str }
    """
    from .rubric_engine import generate_paper_rubric, rubric_to_dict

    rubric = generate_paper_rubric(
        paper_title=payload.get("paper_title", "Untitled Paper"),
        questions=payload.get("questions", []),
    )
    return rubric_to_dict(rubric)


# ---------------------------------------------------------------------------
# CO/PO Attainment (Phase 5)
# ---------------------------------------------------------------------------

@router.post("/attainment/analyze")
def analyze_attainment(
    payload: dict,
    user: User = Depends(get_current_user),
) -> dict:
    """
    Compute CO/PO attainment for a paper.

    Payload: {
        "paper_title": str,
        "total_marks": int,
        "questions": [{"text": str, "marks": int, "course_outcome": str, "bloom_level": str}],
        "co_po_matrix": optional dict
    }
    """
    from .attainment import compute_attainment_report, attainment_to_dict

    report = compute_attainment_report(
        paper_title=payload.get("paper_title", "Untitled"),
        questions=payload.get("questions", []),
        total_marks=int(payload.get("total_marks", 50)),
        co_po_matrix=payload.get("co_po_matrix"),
    )
    return attainment_to_dict(report)


# ---------------------------------------------------------------------------
# Answer Key (Phase 4B)
# ---------------------------------------------------------------------------

@router.post("/answer-key/generate")
def generate_answer_key_endpoint(
    payload: dict,
    user: User = Depends(get_current_user),
) -> dict:
    """
    Generate model answers for a paper.

    Payload: {
        "paper_title": str,
        "questions": [{"text": str, "marks": int, "bloom_level": str}],
        "include_rubric": bool (default true)
    }
    """
    from .answer_key import generate_answer_key, answer_key_to_dict

    questions = payload.get("questions", [])
    paper_title = payload.get("paper_title", "Untitled")

    # Optionally generate rubric first for structured steps
    rubrics = None
    if payload.get("include_rubric", True):
        from .rubric_engine import generate_paper_rubric, rubric_to_dict
        rubric = generate_paper_rubric(paper_title, questions)
        rubrics = rubric_to_dict(rubric)

    key = generate_answer_key(
        paper_title=paper_title,
        questions=questions,
        rubrics=rubrics,
    )
    return answer_key_to_dict(key)


# ---------------------------------------------------------------------------
# PDF Export (Phase 6B)
# ---------------------------------------------------------------------------

@router.post("/export/pdf")
def export_paper_pdf_endpoint(
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Export a question paper as PDF.

    Payload: {
        "questions": [...],
        "paper_meta": {exam_type, department, subject_name, ...},
        "template_id": optional str,
        "co_descriptions": optional dict,
        "co_percentages": optional dict,
        "module_percentages": optional dict,
    }
    """
    from fastapi.responses import Response
    from .pdf_export import export_paper_pdf

    template_config = None
    template_id = payload.get("template_id")
    if template_id:
        from .templates import get_template_manager
        try:
            tmpl = get_template_manager().get_template(template_id, db)
            template_config = tmpl.to_dict()
        except Exception:
            pass

    pdf_bytes = export_paper_pdf(
        questions=payload.get("questions", []),
        paper_meta=payload.get("paper_meta", {}),
        template_config=template_config,
        co_descriptions=payload.get("co_descriptions"),
        co_percentages=payload.get("co_percentages"),
        module_percentages=payload.get("module_percentages"),
    )

    content_type = "application/pdf" if pdf_bytes[:4] == b"%PDF" else "text/html"
    filename = f"{payload.get('paper_meta', {}).get('subject_name', 'paper')}_paper.pdf"

    return Response(
        content=pdf_bytes,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export/docx")
def export_paper_docx_endpoint(
    payload: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export a question paper as a template-aware DOCX document."""
    from fastapi.responses import Response
    from ..generator import PaperConfig, docx_generator
    from .templates import get_template_manager

    template_config = None
    template_id = payload.get("template_id")
    if template_id:
        try:
            template_config = get_template_manager().get_template(template_id, db).to_dict()
        except Exception:
            template_config = None

    paper_meta = payload.get("paper_meta", {})
    co_descriptions = payload.get("co_descriptions") or {}
    questions = payload.get("questions", [])
    modules = sorted(
        {
            int(question.get("module_number") or 1)
            for question in questions
            if question.get("module_number") is not None
        }
    ) or [1, 2, 3, 4, 5]

    config = PaperConfig(
        department=str(paper_meta.get("department", "")),
        subject=str(paper_meta.get("subject_name", "")),
        subject_code=str(paper_meta.get("subject_code", "")),
        semester=str(paper_meta.get("semester", "")),
        max_marks=int(paper_meta.get("max_marks", 50) or 50),
        duration=str(paper_meta.get("duration", "")),
        date=str(paper_meta.get("date", "To be announced")),
        batch=str(paper_meta.get("batch", "")),
        teaching_department=str(
            paper_meta.get("teaching_dept", paper_meta.get("teaching_department", ""))
        ),
        exam_type=str(paper_meta.get("exam_type", "Question Paper")),
        modules=modules,
        rbt_levels=["L1", "L2", "L3", "L4", "L5", "L6"],
        co_targets=sorted(co_descriptions.keys()),
        instructions=str(
            paper_meta.get("instructions", "Instruction: Answer the following questions")
        ),
        co_descriptions={str(key): str(value) for key, value in co_descriptions.items()},
        co_percentages={
            str(key): int(value) for key, value in (payload.get("co_percentages") or {}).items()
        },
        module_percentages={
            str(key): int(value)
            for key, value in (payload.get("module_percentages") or {}).items()
        },
        template_note=paper_meta.get("template_note"),
        template_config=template_config or {},
    )

    document = docx_generator.generate(config, questions)
    buffer = io.BytesIO()
    document.save(buffer)
    filename = f"{paper_meta.get('subject_name', 'paper')}_paper.docx"
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/export/answer-key-pdf")
def export_answer_key_pdf_endpoint(
    payload: dict,
    user: User = Depends(get_current_user),
):
    """
    Export answer key as PDF.

    Payload: {
        "paper_title": str,
        "questions": [...],
        "paper_meta": {...},
    }
    """
    from fastapi.responses import Response
    from .answer_key import generate_answer_key, answer_key_to_dict
    from .rubric_engine import generate_paper_rubric, rubric_to_dict
    from .pdf_export import export_answer_key_pdf

    questions = payload.get("questions", [])
    paper_title = payload.get("paper_title", "Untitled")

    rubric = generate_paper_rubric(paper_title, questions)
    rubrics = rubric_to_dict(rubric)
    key = generate_answer_key(paper_title, questions, rubrics)
    key_dict = answer_key_to_dict(key)

    pdf_bytes = export_answer_key_pdf(key_dict, payload.get("paper_meta", {}))

    content_type = "application/pdf" if pdf_bytes[:4] == b"%PDF" else "text/html"
    filename = f"{payload.get('paper_meta', {}).get('subject_name', 'paper')}_answer_key.pdf"

    return Response(
        content=pdf_bytes,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.post("/regenerate-slot")
def regenerate_slot(
    payload: RegenerateSlotRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from .generation import generate_questions_from_retrieval
    from .pedagogical_engine import enrich_candidates_with_intelligence

    _ensure_subject_route_access(db, user, payload.subject_id)

    result = generate_questions_from_retrieval(
        db=db,
        subject_id=payload.subject_id,
        num_questions=1,
        marks_distribution={payload.marks: 1},
        bloom_levels=[payload.bloom_level],
        co_targets=[payload.course_outcome],
        module_filter=payload.module_number,
        module_plan=[payload.module_number],
        existing_questions=payload.existing_questions,
    )

    if not result.candidates:
        raise HTTPException(status_code=500, detail="Failed to regenerate question slot.")

    candidates = result.candidates
    enrich_candidates_with_intelligence(candidates)

    return candidates[0]


# ---------------------------------------------------------------------------
# Paper Variants (Phase 6A)
# ---------------------------------------------------------------------------

@router.post("/variants/generate")
def generate_paper_variants(
    payload: dict,
    user: User = Depends(get_current_user),
) -> dict:
    """
    Generate Set A/B variants from a paper.

    Payload: {
        "paper_title": str,
        "total_marks": int,
        "questions": [...],
        "num_variants": int (default 2, max 5)
    }
    """
    from .variants import generate_variants, variant_set_to_dict

    result = generate_variants(
        questions=payload.get("questions", []),
        paper_title=payload.get("paper_title", "Untitled"),
        total_marks=int(payload.get("total_marks", 50)),
        num_variants=int(payload.get("num_variants", 2)),
    )
    return variant_set_to_dict(result)


# ---------------------------------------------------------------------------
# Batch Paper Generation (Phase 6C)
# ---------------------------------------------------------------------------

@router.post("/batch/generate")
def batch_generate_papers(
    payload: dict,
    user: User = Depends(require_roles(Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    """
    Generate multiple papers in batch.

    Payload: {
        "items": [
            {
                "subject_id": int,
                "title": str,
                "exam_type": str,
                "max_marks": int,
                ...
            }
        ]
    }
    """
    from .batch_generation import (
        validate_batch_request,
        generate_batch_papers,
        batch_result_to_dict,
        BatchItem,
    )

    items_data = payload.get("items", [])
    parsed_items, errors = validate_batch_request(items_data)

    if errors:
        raise HTTPException(status_code=400, detail="; ".join(errors))

    def single_paper_generator(item: BatchItem) -> dict:
        """Generate a single paper for the batch."""
        subject = db.get(Subject, item.subject_id)
        if not subject:
            raise ValueError(f"Subject {item.subject_id} not found")

        from ..generator import build_question_blueprint
        from ..ai_service import select_questions_for_paper

        import asyncio

        rbt_dict = {rbt: 100 // len(item.rbt_levels) for rbt in item.rbt_levels}
        co_targets = {f"CO{i}": 20 for i in range(1, 6)}
        blueprint = build_question_blueprint(item.max_marks)

        loop = asyncio.new_event_loop()
        try:
            selection = loop.run_until_complete(select_questions_for_paper(
                db, item.subject_id, item.max_marks,
                item.module_numbers, rbt_dict, co_targets,
                item.difficulty, item.prompt,
            ))
        finally:
            loop.close()

        questions = selection.questions
        if not questions:
            raise ValueError("No suitable questions found")

        return {
            "paper_id": None,
            "question_count": len(questions),
            "variant_count": item.num_variants if item.generate_variants else 0,
        }

    result = generate_batch_papers(parsed_items, single_paper_generator)
    return batch_result_to_dict(result)


# ---------------------------------------------------------------------------
# Question Bank Analytics (Phase 6D-G)
# ---------------------------------------------------------------------------

@router.get("/qb-analytics/{subject_id}")
def get_question_bank_analytics(
    subject_id: int,
    overlap_threshold: float = 0.72,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Get comprehensive question bank analytics for a subject.

    Returns usage frequency, Bloom heatmap, freshness, and overlap detection.
    """
    from ..models import Question, PaperQuestion
    from .qb_analytics import compute_question_bank_analytics, analytics_to_dict

    _ensure_subject_route_access(db, user, subject_id)

    # Fetch all questions for this subject
    questions = list(db.scalars(
        select(Question).where(Question.subject_id == subject_id)
    ))
    question_dicts = [
        {
            "id": q.id,
            "text": q.text,
            "module_number": q.module_number,
            "bloom_level": q.bloom_level,
            "course_outcome": q.course_outcome,
            "is_verified": q.is_verified,
        }
        for q in questions
    ]

    # Fetch paper_question associations for usage tracking
    paper_question_dicts = []
    if questions:
        q_ids = [q.id for q in questions]
        paper_qs = list(db.scalars(
            select(PaperQuestion).where(PaperQuestion.question_id.in_(q_ids))
        ))
        paper_question_dicts = [
            {"question_id": pq.question_id}
            for pq in paper_qs
        ]

    report = compute_question_bank_analytics(
        questions=question_dicts,
        paper_questions=paper_question_dicts,
        overlap_threshold=overlap_threshold,
    )
    return analytics_to_dict(report)


@router.post("/qb-analytics/overlap-check")
def check_question_overlap(
    payload: QuestionOverlapCheckRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """
    Check overlap between provided questions and existing question bank.

    Use before finalizing a paper to detect repeated questions.
    """
    from ..models import Question
    from .qb_analytics import compute_text_similarity, OverlapPair

    # Get existing questions
    stmt = select(Question)
    if payload.subject_id:
        _ensure_subject_route_access(db, user, payload.subject_id)
        stmt = stmt.where(Question.subject_id == payload.subject_id)

    existing = list(db.scalars(stmt))
    matches: list[dict] = []

    for new_text in payload.questions:
        for eq in existing:
            sim = compute_text_similarity(new_text, eq.text)
            if sim >= payload.threshold:
                matches.append({
                    "question_id": eq.id,
                    "text": new_text[:200],
                    "compared_text": eq.text[:200],
                    "similarity": round(sim, 3),
                    "source": "question_bank",
                })

    # Sort by similarity
    matches.sort(key=lambda m: m["similarity"], reverse=True)

    return {
        "threshold": payload.threshold,
        "matches": matches[:30],
    }


@router.get("/qb-analytics/{subject_id}/bloom-heatmap")
def get_bloom_heatmap(
    subject_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Get Bloom's taxonomy × Module heatmap data for a subject."""
    from ..models import Question
    from .qb_analytics import compute_bloom_heatmap

    _ensure_subject_route_access(db, user, subject_id)

    questions = list(db.scalars(
        select(Question).where(Question.subject_id == subject_id)
    ))
    question_dicts = [
        {
            "module_number": q.module_number,
            "bloom_level": q.bloom_level,
        }
        for q in questions
    ]

    heatmap = compute_bloom_heatmap(question_dicts)
    return [
        {
            "module_number": c.module_number,
            "bloom_level": c.bloom_level,
            "count": c.count,
        }
        for c in heatmap
    ]
