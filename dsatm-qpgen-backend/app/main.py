from __future__ import annotations
import logging
import random

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("app")

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, File, HTTPException, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .auth import create_auth_tokens, decode_token, get_current_user, require_roles
from .config import settings
from .database import Base, engine, get_db, SessionLocal
from .models import (
    AuditLog,
    Department,
    DocumentImage,
    PaperStatus,
    Question,
    QuestionPaper,
    ReviewDecision,
    Role,
    Subject,
    TeacherSubject,
    User,
)
from .schemas import (
    AdminUserCreate,
    AuditLogResponse,
    BatchPaperGenerationRequest,
    BatchPaperGenerationResponse,
    DashboardResponse,
    DocumentPreviewResponse,
    GeneratePaperRequest,
    LoginRequest,
    PaperGenerationJobResponse,
    PaperResponse,
    PaperUpdateRequest,
    QuestionCreate,
    QuestionBankSummaryResponse,
    QuestionResponse,
    RefreshRequest,
    ReviewActionRequest,
    SubjectCreate,
    SubjectResponse,
    TokenResponse,
    UploadResponse,
    UserSummary,
)
from .services import (
    authenticate_user,
    create_admin_user,
    create_question,
    dashboard_stats,
    delete_paper,
    delete_question,
    ensure_paper_access,
    ensure_subject_access,
    export_paper_docx,
    generate_paper,
    get_paper_or_404,
    list_papers_for_user,
    list_questions_for_user,
    parse_uploaded_document,
    review_paper,
    seed_demo_data,
    serialize_paper,
    submit_paper,
    update_question,
    update_paper,
)

from .ai_service import (
    OllamaClient,
    process_question_bank,
    select_questions_for_paper,
    summarize_question_bank,
)
from .generator import PaperConfig, build_question_blueprint, generate_question_paper
from .paper_generation import generate_ai_paper

# Import academic models so they are registered with Base.metadata
from .academic.models import (  # noqa: F401
    AcademicDocument,
    GenerationJob,
    JobStatus,
    KnowledgeChunk,
    SubjectSyllabus,
    QuestionGenerationProfile,
    ExtractedImage,
)
from .academic.routes import router as academic_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        seed_demo_data(session)
    
    if settings.prewarm_embeddings_on_startup:
        try:
            from .academic.embeddings import _get_model

            logger.info("Pre-warming embedding model...")
            _get_model()
            logger.info("Embedding model pre-warmed and ready")
        except Exception as e:
            logger.warning("Could not pre-warm embedding model: %s", e)
    
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(academic_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _build_coverage_stats(
    questions: list[Question],
    blueprint: list[dict[str, int | str]],
    requested_modules: list[int],
    requested_rbt: dict[str, int],
    requested_co: dict[str, int],
) -> dict:
    slot_marks = [int(slot["marks"]) for slot in blueprint[: len(questions)]]
    total = sum(slot_marks) or 1
    by_module = {str(module): 0 for module in (requested_modules or [1, 2, 3, 4, 5])}
    by_rbt = {f"L{level}": 0 for level in range(1, 7)}
    by_co = {f"CO{level}": 0 for level in range(1, 7)}

    for question, marks in zip(questions, slot_marks):
        by_module[str(question.module_number)] = (
            by_module.get(str(question.module_number), 0) + marks
        )
        by_rbt[question.bloom_level] = by_rbt.get(question.bloom_level, 0) + marks
        by_co[question.course_outcome.upper()] = (
            by_co.get(question.course_outcome.upper(), 0) + marks
        )

    return {
        "question_count": len(questions),
        "by_module": by_module,
        "by_rbt": by_rbt,
        "by_co": by_co,
        "requested": {
            "modules": requested_modules,
            "rbt": requested_rbt,
            "co": requested_co,
        },
        "percentages": {
            "co": {
                key: round((value / total) * 100)
                for key, value in by_co.items()
                if key in requested_co or value
            },
            "modules": {
                key: round((value / total) * 100)
                for key, value in by_module.items()
                if int(key) in requested_modules or value
            },
        },
    }


def _job_payload(job: GenerationJob) -> dict:
    return dict(job.result_data or {})


def _serialize_generation_job(job: GenerationJob) -> dict:
    payload = _job_payload(job)
    return {
        "id": job.id,
        "subject_id": job.subject_id,
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "progress": int(job.progress or 0),
        "error_message": job.error_message,
        "stage": payload.get("stage"),
        "message": payload.get("message"),
        "paper_id": payload.get("paper_id"),
        "paper": payload.get("paper"),
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }


def _update_generation_job(job_id: int, **fields) -> None:
    with SessionLocal() as db:
        job = db.get(GenerationJob, job_id)
        if job is None:
            return
        for key, value in fields.items():
            if key == "result_data":
                value = jsonable_encoder(value)
            setattr(job, key, value)
        db.commit()


def _variant_labels_for(payload: GeneratePaperRequest) -> list[str]:
    requested = [label.strip() for label in payload.variant_labels if label.strip()]
    if len(requested) >= payload.variant_count:
        return requested[: payload.variant_count]
    defaults = [f"Set {chr(65 + index)}" for index in range(payload.variant_count)]
    combined = requested + [label for label in defaults if label not in requested]
    return combined[: payload.variant_count]


async def _generate_variant_papers(
    db: Session,
    user: User,
    payload: GeneratePaperRequest,
    *,
    progress_callback=None,
) -> list[dict]:
    labels = _variant_labels_for(payload)
    results: list[dict] = []
    excluded_question_ids = list(payload.exclude_question_ids)
    excluded_question_texts = list(payload.exclude_question_texts)

    for index, label in enumerate(labels, start=1):
        variant_payload = payload.model_copy(deep=True)
        variant_payload.variant_count = 1
        variant_payload.variant_label = label
        variant_payload.exclude_question_ids = list(dict.fromkeys(excluded_question_ids))
        variant_payload.exclude_question_texts = list(dict.fromkeys(excluded_question_texts))
        if payload.variant_count > 1:
            variant_payload.title = f"{payload.title} ({label})"

        if progress_callback is not None:
            base = int(((index - 1) / max(len(labels), 1)) * 100)

            def variant_progress(progress: int, stage: str, message: str) -> None:
                scaled = min(99, base + int(progress / max(len(labels), 1)))
                progress_callback(scaled, f"{stage}:{label}", f"{label}: {message}")

        else:
            variant_progress = None

        result = await generate_ai_paper(
            db,
            user,
            variant_payload,
            progress_callback=variant_progress,
        )
        results.append(result)

        excluded_question_ids.extend(
            [
                int(question["question_id"])
                for question in result.get("questions", [])
                if isinstance(question.get("question_id"), int)
            ]
        )
        excluded_question_texts.extend(
            [str(question.get("text", "")).strip() for question in result.get("questions", [])]
        )

    return results


async def _run_generation_job(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(GenerationJob, job_id)
        if job is None:
            return
        user_id = int(job.user_id)
        request_params = dict(job.request_params or {})
        job.status = JobStatus.PROCESSING
        job.progress = 2
        job.error_message = None
        job.result_data = {"stage": "queued", "message": "Preparing background generation"}
        db.commit()

    payload = GeneratePaperRequest.model_validate(request_params)

    def progress_callback(progress: int, stage: str, message: str) -> None:
        _update_generation_job(
            job_id,
            status=JobStatus.PROCESSING,
            progress=progress,
            result_data={"stage": stage, "message": message},
        )

    try:
        with SessionLocal() as worker_db:
            user = worker_db.get(User, user_id)
            if user is None:
                raise ValueError("User not found for generation job")
            papers = await _generate_variant_papers(
                worker_db,
                user,
                payload,
                progress_callback=progress_callback,
            )
        final_paper = papers[-1] if papers else None
        _update_generation_job(
            job_id,
            status=JobStatus.COMPLETED,
            progress=100,
            completed_at=datetime.now(timezone.utc),
            result_data={
                "stage": "completed",
                "message": "Paper generation completed",
                "paper_id": final_paper.get("id") if final_paper else None,
                "paper": final_paper,
                "papers": papers,
            },
        )
    except Exception as exc:
        _update_generation_job(
            job_id,
            status=JobStatus.FAILED,
            progress=100,
            completed_at=datetime.now(timezone.utc),
            error_message=str(exc),
            result_data={"stage": "failed", "message": str(exc)},
        )


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": settings.ollama_model}


@app.post("/api/v1/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    return authenticate_user(db, payload.email, payload.password)


@app.post("/api/v1/auth/refresh", response_model=TokenResponse)
def refresh_token(
    payload: RefreshRequest, db: Session = Depends(get_db)
) -> dict[str, str]:
    decoded = decode_token(payload.refresh_token)
    if decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )
    user = db.get(User, int(decoded["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User unavailable"
        )
    return create_auth_tokens(user)


@app.get("/api/v1/users/me", response_model=UserSummary)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    dept_name = None
    if user.dept_id:
        department = db.get(Department, user.dept_id)
        dept_name = department.name if department else None
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "dept_id": user.dept_id,
        "department_name": dept_name,
    }


@app.get("/api/v1/auth/me", response_model=UserSummary)
def auth_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    return me(user=user, db=db)


@app.get("/api/v1/subjects", response_model=list[SubjectResponse])
def subjects(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    stmt = select(Subject).options(selectinload(Subject.department))
    if user.role != Role.ADMIN and user.dept_id is not None:
        stmt = stmt.where(Subject.dept_id == user.dept_id)
    return [
        {
            "id": subject.id,
            "code": subject.code,
            "name": subject.name,
            "semester": subject.semester,
            "dept_id": subject.dept_id,
            "department_name": subject.department.name,
            "academic_year": subject.academic_year,
            "credits": subject.credits,
            "max_marks": subject.max_marks,
            "regulation_scheme": subject.regulation_scheme,
            "ia_pattern": subject.ia_pattern,
            "exam_duration": subject.exam_duration,
            "number_of_modules": subject.number_of_modules,
            "theory_lab_type": subject.theory_lab_type,
            "pattern_type": subject.pattern_type,
        }
        for subject in db.scalars(stmt.order_by(Subject.semester, Subject.name))
    ]

@app.post("/api/v1/subjects", response_model=SubjectResponse)
def create_subject(
    payload: SubjectCreate,
    user: User = Depends(require_roles(Role.ADMIN, Role.HOD)),
    db: Session = Depends(get_db)
) -> dict:
    dept = db.scalar(select(Department).where(Department.name == payload.department)) if payload.department else None

    if not dept and user.dept_id:
        dept = db.get(Department, user.dept_id)

    if not dept:
        dept = db.scalar(select(Department).limit(1))
        if not dept:
            raise HTTPException(status_code=400, detail="No department found")

    new_subject = Subject(
        name=payload.name,
        code=payload.code,
        semester=payload.semester,
        academic_year=payload.academic_year,
        credits=payload.credits,
        max_marks=payload.max_marks,
        regulation_scheme=payload.regulation_scheme,
        ia_pattern=payload.ia_pattern,
        exam_duration=payload.exam_duration,
        number_of_modules=payload.number_of_modules,
        theory_lab_type=payload.theory_lab_type,
        pattern_type=payload.pattern_type,
        dept_id=dept.id
    )
    db.add(new_subject)
    db.commit()
    db.refresh(new_subject)

    return {
        "id": new_subject.id,
        "code": new_subject.code,
        "name": new_subject.name,
        "semester": new_subject.semester,
        "dept_id": new_subject.dept_id,
        "department_name": dept.name,
        "academic_year": new_subject.academic_year,
        "credits": new_subject.credits,
        "max_marks": new_subject.max_marks,
        "regulation_scheme": new_subject.regulation_scheme,
        "ia_pattern": new_subject.ia_pattern,
        "exam_duration": new_subject.exam_duration,
        "number_of_modules": new_subject.number_of_modules,
        "theory_lab_type": new_subject.theory_lab_type,
        "pattern_type": new_subject.pattern_type,
    }


@app.post("/api/v1/questions", response_model=QuestionResponse)
def add_question(
    payload: QuestionCreate,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> QuestionResponse:
    return create_question(db, user, payload.model_dump())


@app.post("/api/v1/questions/upload", response_model=UploadResponse)
def upload_question_bank(
    subject_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    document, questions, ai_mode = parse_uploaded_document(db, user, subject_id, file)
    return {
        "document_id": document.id,
        "extracted_questions": len(questions),
        "filename": document.filename,
        "ai_mode": ai_mode,
    }


@app.get("/api/v1/documents/images/{image_id}")
def get_document_image(
    image_id: int,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
):
    img = db.get(DocumentImage, image_id)
    if not img or not Path(img.image_path).exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(img.image_path)

@app.get("/api/v1/documents/{document_id}/preview", response_model=DocumentPreviewResponse)
def preview_document(
    document_id: int,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    # Use selectinload to eagerly load the relationship collections
    stmt = select(Document).options(
        selectinload(Document.chunks),
        selectinload(Document.images)
    ).where(Document.id == document_id)

    document = db.scalar(stmt)
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document not found"
        )

    return {
        "id": document.id,
        "filename": document.filename,
        "parsed_text": document.parsed_text,
        "chunks": [
            {
                "id": c.id,
                "page": c.page,
                "text": c.text,
                "source_type": c.source_type,
                "block_index": c.block_index
            } for c in document.chunks
        ],
        "images": [
            {
                "id": img.id,
                "image_path": img.image_path,
                "source_page": img.source_page,
                "keywords": img.keywords,
                "context_before": img.context_before,
                "context_after": img.context_after,
                "ai_caption": img.ai_caption,
                "width": img.width,
                "height": img.height
            } for img in document.images
        ]
    }


@app.post("/api/v1/ai/process-question-bank")
async def ai_process_question_bank(
    subject_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    result = await process_question_bank(file, subject_id, user.id, db)
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
    }


@app.get(
    "/api/v1/ai/question-bank-summary",
    response_model=QuestionBankSummaryResponse,
)
def ai_question_bank_summary(
    subject_id: int | None = None,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    subject_ids: list[int] | None = None
    teacher_id: int | None = user.id if user.role == Role.TEACHER else None

    if subject_id is not None:
        subject = db.get(Subject, subject_id)
        if subject is None:
            raise HTTPException(status_code=404, detail="Subject not found")
        if user.role != Role.ADMIN and user.dept_id != subject.dept_id:
            raise HTTPException(status_code=403, detail="Department access denied")
        if user.role == Role.TEACHER:
            assigned = db.scalar(
                select(Subject.id)
                .join_from(Subject, TeacherSubject, Subject.id == TeacherSubject.subject_id)
                .where(TeacherSubject.teacher_id == user.id, Subject.id == subject_id)
            )
            if assigned is None:
                raise HTTPException(
                    status_code=403,
                    detail="Teacher is not assigned to this subject",
                )
        subject_ids = [subject_id]
    elif user.role == Role.HOD and user.dept_id is not None:
        subject_ids = list(
            db.scalars(select(Subject.id).where(Subject.dept_id == user.dept_id))
        )

    summary = summarize_question_bank(db, subject_ids=subject_ids, teacher_id=teacher_id)
    return {
        "total_documents": summary.total_documents,
        "total_questions": summary.total_questions,
        "verified_questions": summary.verified_questions,
        "pending_questions": summary.pending_questions,
        "retrieval_ready_questions": summary.retrieval_ready_questions,
        "by_module": summary.by_module,
        "by_rbt": summary.by_rbt,
        "by_co": summary.by_co,
        "by_difficulty": summary.by_difficulty,
        "recent_documents": summary.recent_documents,
        "gaps": summary.gaps,
    }


@app.post("/api/v1/ai/generate-paper")
async def ai_generate_paper(
    payload: GeneratePaperRequest,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    single_payload = payload.model_copy(update={"variant_count": 1})
    try:
        results = await _generate_variant_papers(db, user, single_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return results[0]


@app.post("/api/v1/ai/generate-paper/variants")
async def ai_generate_paper_variants(
    payload: GeneratePaperRequest,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> list[dict]:
    variant_payload = payload.model_copy(
        update={"variant_count": max(2, payload.variant_count)}
    )
    try:
        return await _generate_variant_papers(db, user, variant_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/v1/ai/generate-paper/jobs",
    response_model=PaperGenerationJobResponse,
)
async def create_generation_job(
    payload: GeneratePaperRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    subject = db.get(Subject, payload.subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    ensure_subject_access(user, subject, db)

    job = GenerationJob(
        subject_id=payload.subject_id,
        user_id=user.id,
        status=JobStatus.PENDING,
        progress=0,
        request_params=payload.model_dump(mode="json"),
        result_data={"stage": "queued", "message": "Job accepted"},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(_run_generation_job, job.id)
    return _serialize_generation_job(job)


@app.get(
    "/api/v1/ai/generate-paper/jobs/{job_id}",
    response_model=PaperGenerationJobResponse,
)
def get_generation_job(
    job_id: int,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    job = db.get(GenerationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Generation job not found")
    subject = db.get(Subject, job.subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Job subject not found")
    ensure_subject_access(user, subject, db)
    return _serialize_generation_job(job)


@app.post(
    "/api/v1/ai/generate-paper/batch",
    response_model=BatchPaperGenerationResponse,
)
async def batch_generate_papers(
    payload: BatchPaperGenerationRequest,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    generated: list[dict] = []
    failures: list[dict] = []

    for subject_id in payload.subject_ids:
        subject = db.get(Subject, subject_id)
        if subject is None:
            failures.append({"subject_id": subject_id, "error": "Subject not found"})
            continue
        try:
            ensure_subject_access(user, subject, db)
            request = GeneratePaperRequest(
                subject_id=subject_id,
                title=f"{payload.title_prefix} - {subject.name}",
                exam_type=payload.exam_type,
                semester=payload.semester,
                batch=payload.batch,
                max_marks=payload.max_marks,
                duration_minutes=payload.duration_minutes,
                exam_date=payload.exam_date,
                teaching_department=payload.teaching_department,
                prompt=payload.prompt,
                rbt_levels=payload.rbt_levels,
                module_numbers=payload.module_numbers,
                module_co_mapping=payload.module_co_mapping,
                difficulty_distribution=payload.difficulty_distribution,
                co_targets=payload.co_targets,
                co_descriptions=payload.co_descriptions,
                difficulty=payload.difficulty,
                instructions=payload.instructions,
                template_id=payload.template_id,
                variant_count=payload.variant_count,
                variant_labels=payload.variant_labels,
                allow_ai_rewrite=payload.allow_ai_rewrite,
                creativity=payload.creativity,
                use_notes=payload.use_notes,
                use_question_bank=payload.use_question_bank,
                use_previous_papers=payload.use_previous_papers,
                use_syllabus=payload.use_syllabus,
                strict_syllabus_mode=payload.strict_syllabus_mode,
            )
            papers = await _generate_variant_papers(db, user, request)
            for paper in papers:
                generated.append(
                    {
                        "subject_id": subject_id,
                        "subject_name": subject.name,
                        "paper_id": paper.get("id"),
                        "title": paper.get("title"),
                        "variant_label": paper.get("ai_config", {}).get("variant_label"),
                        "status": paper.get("status"),
                        "paper": paper,
                    }
                )
        except Exception as exc:
            failures.append({"subject_id": subject_id, "subject_name": subject.name, "error": str(exc)})

    return {
        "total_requested": len(payload.subject_ids) * payload.variant_count,
        "total_generated": len(generated),
        "mode": "sequential",
        "generated": generated,
        "failures": failures,
    }


@app.get("/api/v1/questions", response_model=list[QuestionResponse])
def list_questions(
    search: str | None = None,
    subject_id: int | None = None,
    bloom_level: str | None = None,
    difficulty: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[QuestionResponse]:
    return list_questions_for_user(
        db, user, search, subject_id, bloom_level, difficulty
    )


@app.put("/api/v1/questions/{question_id}", response_model=QuestionResponse)
def edit_question(
    question_id: int,
    payload: QuestionCreate,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> QuestionResponse:
    return update_question(db, user, question_id, payload.model_dump())


@app.delete("/api/v1/questions/{question_id}", status_code=200, response_class=Response)
def remove_question(
    question_id: int,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    delete_question(db, user, question_id)


@app.post("/api/v1/papers/generate", response_model=PaperResponse)
def create_paper(
    payload: GeneratePaperRequest,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    paper = generate_paper(db, user, payload.model_dump())
    paper = db.scalar(
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.id == paper.id)
    )
    return serialize_paper(db, paper)


@app.get("/api/v1/papers", response_model=list[PaperResponse])
def list_papers(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[dict]:
    return [serialize_paper(db, paper) for paper in list_papers_for_user(db, user)]


@app.get("/api/v1/papers/{paper_id}/preview", response_model=PaperResponse)
def preview_paper(
    paper_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    paper = db.scalar(
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.id == paper_id)
    )
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found"
        )
    ensure_paper_access(db, user, paper)
    return serialize_paper(db, paper)


@app.put("/api/v1/papers/{paper_id}", response_model=PaperResponse)
def edit_paper(
    paper_id: int,
    payload: PaperUpdateRequest,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    paper = db.scalar(
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.id == paper_id)
    )
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found"
        )
    paper = update_paper(
        db,
        user,
        paper,
        payload.title,
        payload.prompt,
        payload.question_text_overrides,
        [item.model_dump() for item in payload.question_updates],
    )
    paper = db.scalar(
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.id == paper.id)
    )
    return serialize_paper(db, paper)


@app.post("/api/v1/papers/{paper_id}/submit", response_model=PaperResponse)
def submit_paper_for_review(
    paper_id: int,
    user: User = Depends(require_roles(Role.TEACHER)),
    db: Session = Depends(get_db),
) -> dict:
    paper = db.scalar(
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.id == paper_id)
    )
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found"
        )
    paper = submit_paper(db, user, paper)
    paper = db.scalar(
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.id == paper.id)
    )
    return serialize_paper(db, paper)


@app.get("/api/v1/reviews/pending", response_model=list[PaperResponse])
def pending_reviews(
    user: User = Depends(require_roles(Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = (
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.status == PaperStatus.PENDING_REVIEW)
    )
    if user.role == Role.HOD and user.dept_id is not None:
        subject_ids = select(Subject.id).where(Subject.dept_id == user.dept_id)
        stmt = stmt.where(QuestionPaper.subject_id.in_(subject_ids))
    return [
        serialize_paper(db, paper)
        for paper in db.scalars(stmt.order_by(QuestionPaper.submitted_at.desc()))
    ]


@app.post("/api/v1/reviews/{paper_id}/action", response_model=PaperResponse)
def take_review_action(
    paper_id: int,
    payload: ReviewActionRequest,
    user: User = Depends(require_roles(Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    paper = db.scalar(
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.id == paper_id)
    )
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found"
        )
    paper = review_paper(db, user, paper, payload.decision, payload.comments)
    paper = db.scalar(
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.id == paper.id)
    )
    return serialize_paper(db, paper)


@app.get("/api/v1/papers/{paper_id}/download")
def download_paper(
    paper_id: int,
    user: User = Depends(require_roles(Role.HOD, Role.ADMIN, Role.TEACHER)),
    db: Session = Depends(get_db),
) -> FileResponse:
    paper = db.scalar(
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.id == paper_id)
    )
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found"
        )

    path = export_paper_docx(db, user, paper)

    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
    )


@app.delete("/api/v1/papers/{paper_id}", status_code=200, response_class=Response)
def remove_paper(
    paper_id: int,
    user: User = Depends(require_roles(Role.TEACHER, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> None:
    paper = db.scalar(
        select(QuestionPaper)
        .options(selectinload(QuestionPaper.questions))
        .where(QuestionPaper.id == paper_id)
    )
    if paper is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found"
        )
    delete_paper(db, user, paper)


@app.post("/api/v1/admin/users", response_model=UserSummary)
def create_user(
    payload: AdminUserCreate,
    user: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    created = create_admin_user(db, user, payload.model_dump())
    dept_name = None
    if created.dept_id:
        department = db.get(Department, created.dept_id)
        dept_name = department.name if department else None
    return {
        "id": created.id,
        "email": created.email,
        "full_name": created.full_name,
        "role": created.role,
        "dept_id": created.dept_id,
        "department_name": dept_name,
    }


@app.get("/api/v1/admin/audit-logs", response_model=list[AuditLogResponse])
def audit_logs(
    _: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    return list(
        db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(100))
    )


@app.get("/api/v1/admin/dashboard", response_model=DashboardResponse)
def admin_dashboard(
    _: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    return dashboard_stats(db)


# ---------------------------------------------------------------------------
# Spec-compatible aliases.
# The current React app uses /papers and /reviews, while the production brief
# names the same workflow /question-papers and /hod/question-papers.
# ---------------------------------------------------------------------------

@app.post("/api/v1/question-papers/generate", response_model=PaperGenerationJobResponse)
async def generate_question_paper_job(
    payload: GeneratePaperRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_roles(Role.TEACHER, Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    return await create_generation_job(payload, background_tasks, user, db)


@app.get("/api/v1/question-papers", response_model=list[PaperResponse])
def list_question_papers_alias(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict]:
    return list_papers(user=user, db=db)


@app.get("/api/v1/question-papers/{paper_id}", response_model=PaperResponse)
def get_question_paper_alias(
    paper_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return preview_paper(paper_id=paper_id, user=user, db=db)


@app.get("/api/v1/question-papers/{paper_id}/preview", response_model=PaperResponse)
def preview_question_paper_alias(
    paper_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    return preview_paper(paper_id=paper_id, user=user, db=db)


@app.post("/api/v1/question-papers/{paper_id}/submit", response_model=PaperResponse)
def submit_question_paper_alias(
    paper_id: int,
    user: User = Depends(require_roles(Role.TEACHER)),
    db: Session = Depends(get_db),
) -> dict:
    return submit_paper_for_review(paper_id=paper_id, user=user, db=db)


@app.get("/api/v1/question-papers/{paper_id}/status")
def question_paper_status_alias(
    paper_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    paper = db.get(QuestionPaper, paper_id)
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    ensure_paper_access(db, user, paper)
    return {
        "status": paper.status,
        "submitted_at": paper.submitted_at,
        "reviewed_at": paper.reviewed_at,
        "hod_comments": None,
    }


@app.get("/api/v1/question-papers/{paper_id}/download")
def download_question_paper_alias(
    paper_id: int,
    user: User = Depends(require_roles(Role.HOD, Role.ADMIN, Role.TEACHER)),
    db: Session = Depends(get_db),
) -> FileResponse:
    return download_paper(paper_id=paper_id, user=user, db=db)


@app.get("/api/v1/hod/question-papers", response_model=list[PaperResponse])
def hod_question_papers_alias(
    user: User = Depends(require_roles(Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> list[dict]:
    return pending_reviews(user=user, db=db)


@app.get("/api/v1/hod/question-papers/{paper_id}", response_model=PaperResponse)
def hod_question_paper_detail_alias(
    paper_id: int,
    user: User = Depends(require_roles(Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    return preview_paper(paper_id=paper_id, user=user, db=db)


@app.post("/api/v1/hod/question-papers/{paper_id}/approve", response_model=PaperResponse)
def hod_approve_alias(
    paper_id: int,
    payload: dict | None = None,
    user: User = Depends(require_roles(Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    request = ReviewActionRequest(decision=ReviewDecision.APPROVED, comments=(payload or {}).get("comments", "Approved"))
    return take_review_action(paper_id=paper_id, payload=request, user=user, db=db)


@app.post("/api/v1/hod/question-papers/{paper_id}/reject", response_model=PaperResponse)
def hod_reject_alias(
    paper_id: int,
    payload: dict,
    user: User = Depends(require_roles(Role.HOD, Role.ADMIN)),
    db: Session = Depends(get_db),
) -> dict:
    reason = payload.get("reason") or payload.get("comments") or "Rejected after HOD review"
    request = ReviewActionRequest(decision=ReviewDecision.REJECTED, comments=reason)
    return take_review_action(paper_id=paper_id, payload=request, user=user, db=db)


@app.get("/api/v1/notifications")
def list_notifications_alias(
    user: User = Depends(get_current_user),
) -> dict:
    return {"items": [], "total": 0, "user_id": user.id}


@app.post("/api/v1/notifications/{notification_id}/read")
def mark_notification_read_alias(
    notification_id: int,
    _: User = Depends(get_current_user),
) -> dict:
    return {"message": "Marked as read", "id": notification_id}


@app.post("/api/v1/notifications/read-all")
def mark_all_notifications_read_alias(
    user: User = Depends(get_current_user),
) -> dict:
    return {"message": "All notifications marked as read", "user_id": user.id}
