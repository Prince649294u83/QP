from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import PaperStatus, ReviewDecision, Role


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: Role
    dept_id: int | None
    department_name: str | None = None


class SubjectCreate(BaseModel):
    name: str
    code: str
    semester: int
    academic_year: str | None = None
    credits: int | None = None
    max_marks: int = 50
    regulation_scheme: str | None = None
    ia_pattern: str | None = None
    exam_duration: int | None = None
    number_of_modules: int = 5
    theory_lab_type: str | None = "Theory"
    pattern_type: str | None = "Autonomous"
    department: str | None = None


class SubjectResponse(BaseModel):
    id: int
    code: str
    name: str
    semester: int
    dept_id: int
    department_name: str
    academic_year: str | None = None
    credits: int | None = None
    max_marks: int = 50
    regulation_scheme: str | None = None
    ia_pattern: str | None = None
    exam_duration: int | None = None
    number_of_modules: int = 5
    theory_lab_type: str | None = "Theory"
    pattern_type: str | None = "Autonomous"


class QuestionCreate(BaseModel):
    subject_id: int
    text: str
    marks: int = Field(ge=1, le=30)
    course_outcome: str
    bloom_level: str
    difficulty: str
    module_number: int = Field(ge=1, le=10)
    tags: list[str] = Field(default_factory=list)


class QuestionResponse(QuestionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    teacher_id: int
    is_verified: bool
    created_at: datetime


class UploadResponse(BaseModel):
    document_id: int
    extracted_questions: int
    filename: str
    ai_mode: str
    summary: dict | None = None

class DocumentChunkResponse(BaseModel):
    id: int
    page: int
    text: str
    source_type: str
    block_index: int

class DocumentImageResponse(BaseModel):
    id: int
    image_path: str
    source_page: int
    keywords: list[str]

from pydantic import BaseModel, ConfigDict, Field

from .models import PaperStatus, ReviewDecision, Role


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class UserSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: Role
    dept_id: int | None
    department_name: str | None = None


class SubjectCreate(BaseModel):
    name: str
    code: str
    semester: int
    academic_year: str | None = None
    credits: int | None = None
    max_marks: int = 50
    regulation_scheme: str | None = None
    ia_pattern: str | None = None
    exam_duration: int | None = None
    number_of_modules: int = 5
    theory_lab_type: str | None = "Theory"
    pattern_type: str | None = "Autonomous"
    department: str | None = None


class SubjectResponse(BaseModel):
    id: int
    code: str
    name: str
    semester: int
    dept_id: int
    department_name: str
    academic_year: str | None = None
    credits: int | None = None
    max_marks: int = 50
    regulation_scheme: str | None = None
    ia_pattern: str | None = None
    exam_duration: int | None = None
    number_of_modules: int = 5
    theory_lab_type: str | None = "Theory"
    pattern_type: str | None = "Autonomous"


class QuestionCreate(BaseModel):
    subject_id: int
    text: str
    marks: int = Field(ge=1, le=30)
    course_outcome: str
    bloom_level: str
    difficulty: str
    module_number: int = Field(ge=1, le=10)
    tags: list[str] = Field(default_factory=list)


class QuestionResponse(QuestionCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    teacher_id: int
    is_verified: bool
    created_at: datetime


class UploadResponse(BaseModel):
    document_id: int
    extracted_questions: int
    filename: str
    ai_mode: str
    summary: dict | None = None

class DocumentChunkResponse(BaseModel):
    id: int
    page: int
    text: str
    source_type: str
    block_index: int

class DocumentImageResponse(BaseModel):
    id: int
    image_path: str
    source_page: int
    keywords: list[str]
    context_before: str
    context_after: str
    ai_caption: str
    width: int | None
    height: int | None

class DocumentPreviewResponse(BaseModel):
    id: int
    filename: str
    parsed_text: str
    chunks: list[DocumentChunkResponse]
    images: list[DocumentImageResponse]


class GeneratePaperRequest(BaseModel):
    subject_id: int
    title: str
    exam_type: str
    semester: str
    batch: str
    max_marks: int = Field(ge=5, le=200)
    duration_minutes: int = Field(ge=30, le=240)
    exam_date: date | None = None
    teaching_department: str
    prompt: str
    rbt_levels: list[str] = Field(default_factory=list)
    module_numbers: list[int] = Field(default_factory=list)
    module_co_mapping: dict[int, list[str]] = Field(default_factory=dict)
    module_bloom_mapping: dict[int, list[str]] = Field(default_factory=dict)
    difficulty_distribution: dict[str, int] = Field(default_factory=dict)
    co_targets: dict[str, int] = Field(default_factory=dict)
    co_descriptions: dict[str, str] = Field(default_factory=dict)
    difficulty: str = "balanced"
    instructions: str = "Instruction: Answer the following questions"
    manual_question_ids: list[int] = Field(default_factory=list)
    exclude_question_ids: list[int] = Field(default_factory=list)
    exclude_question_texts: list[str] = Field(default_factory=list)
    template_id: str | None = None
    
    # Advanced Variance Controls
    semantic_variance: float = Field(0.5, ge=0.0, le=1.0)
    structural_variance: float = Field(0.5, ge=0.0, le=1.0)
    context_variance: float = Field(0.5, ge=0.0, le=1.0)
    difficulty_variance: float = Field(0.5, ge=0.0, le=1.0)
    diagram_variance: float = Field(0.5, ge=0.0, le=1.0)
    variant_count: int = Field(default=1, ge=1, le=8)
    variant_labels: list[str] = Field(default_factory=list)
    variant_label: str | None = None
    allow_ai_rewrite: bool = False
    creativity: float = Field(default=0.7, ge=0.0, le=1.0)
    use_notes: bool = True
    use_question_bank: bool = True
    use_previous_papers: bool = False
    use_syllabus: bool = True
    strict_syllabus_mode: bool = True


class PaperQuestionItem(BaseModel):
    id: int
    question_id: int
    order_index: int
    section_label: str
    custom_marks: int | None
    text: str
    course_outcome: str | None = None
    bloom_level: str | None = None
    module_number: int | None = None
    difficulty: str | None = None
    confidence: float | None = None
    source_documents: list[str] = Field(default_factory=list)
    attached_images: list[dict[str, Any]] = Field(default_factory=list)


class BatchPaperGenerationRequest(BaseModel):
    subject_ids: list[int] = Field(min_length=1, max_length=20)
    title_prefix: str
    exam_type: str
    semester: str
    batch: str
    max_marks: int = Field(ge=5, le=200)
    duration_minutes: int = Field(ge=30, le=240)
    exam_date: date | None = None
    teaching_department: str
    prompt: str
    rbt_levels: list[str] = Field(default_factory=list)
    module_numbers: list[int] = Field(default_factory=list)
    module_co_mapping: dict[int, list[str]] = Field(default_factory=dict)
    difficulty_distribution: dict[str, int] = Field(default_factory=dict)
    co_targets: dict[str, int] = Field(default_factory=dict)
    co_descriptions: dict[str, str] = Field(default_factory=dict)
    difficulty: str = "balanced"
    instructions: str = "Instruction: Answer the following questions"
    template_id: str | None = None
    variant_count: int = Field(default=1, ge=1, le=8)
    variant_labels: list[str] = Field(default_factory=list)
    allow_ai_rewrite: bool = False
    creativity: float = Field(default=0.7, ge=0.0, le=1.0)
    use_notes: bool = True
    use_question_bank: bool = True
    use_previous_papers: bool = False
    use_syllabus: bool = True
    strict_syllabus_mode: bool = True


class BatchPaperGenerationResponse(BaseModel):
    total_requested: int
    total_generated: int
    mode: str
    generated: list[dict] = Field(default_factory=list)
    failures: list[dict] = Field(default_factory=list)


class PaperGenerationJobResponse(BaseModel):
    id: int
    subject_id: int
    status: str
    progress: int = 0
    error_message: str | None = None
    stage: str | None = None
    message: str | None = None
    paper_id: int | None = None
    paper: dict | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class PaperResponse(BaseModel):
    id: int
    subject_id: int
    subject_name: str | None = None
    subject_code: str | None = None
    department_name: str | None = None
    title: str
    exam_type: str
    semester: str
    batch: str
    max_marks: int
    duration_minutes: int
    exam_date: date | None
    teaching_department: str
    status: PaperStatus
    prompt_used: str
    generated_summary: str
    created_at: datetime
    submitted_at: datetime | None
    reviewed_at: datetime | None
    ai_config: dict = Field(default_factory=dict)
    coverage_stats: dict = Field(default_factory=dict)
    questions: list[PaperQuestionItem]


class PaperQuestionUpdateItem(BaseModel):
    id: int
    text: str | None = None
    course_outcome: str | None = None
    bloom_level: str | None = None
    module_number: int | None = None
    attached_images: list[dict[str, Any]] = Field(default_factory=list)


class QuestionBankSummaryResponse(BaseModel):
    total_documents: int
    total_questions: int
    verified_questions: int
    pending_questions: int
    retrieval_ready_questions: int
    by_module: dict[str, int]
    by_rbt: dict[str, int]
    by_co: dict[str, int]
    by_difficulty: dict[str, int]
    recent_documents: list[dict]
    gaps: list[str]


class PaperUpdateRequest(BaseModel):
    title: str | None = None
    prompt: str | None = None
    question_text_overrides: dict[int, str] = Field(default_factory=dict)
    question_updates: list[PaperQuestionUpdateItem] = Field(default_factory=list)


class ReviewActionRequest(BaseModel):
    decision: ReviewDecision
    comments: str = Field(min_length=3)


class AdminUserCreate(BaseModel):
    email: str
    full_name: str
    password: str = Field(min_length=8)
    role: Role
    dept_id: int | None = None


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    action: str
    entity: str
    entity_id: str | None
    details: dict
    created_at: datetime




class ReviewActionRequest(BaseModel):
    decision: ReviewDecision
    comments: str = Field(min_length=3)


class AdminUserCreate(BaseModel):
    email: str
    full_name: str
    password: str = Field(min_length=8)
    role: Role
    dept_id: int | None = None


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    action: str
    entity: str
    entity_id: str | None
    details: dict
    created_at: datetime


class DashboardResponse(BaseModel):
    total_users: int
    total_subjects: int
    total_questions: int
    total_papers: int
    pending_reviews: int
    approved_papers: int
    ai_model: str

class LessonPlanBase(BaseModel):
    module_number: int
    lecture_no: int
    session_topic: str
    rbt_levels: list[str] = Field(default_factory=list)
    course_outcomes: list[str] = Field(default_factory=list)

class LessonPlanCreate(LessonPlanBase):
    subject_id: int

class LessonPlanResponse(LessonPlanBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject_id: int

class AssessmentPlanBase(BaseModel):
    exam_type: str
    alignment_matrix: dict = Field(default_factory=dict)

class AssessmentPlanCreate(AssessmentPlanBase):
    subject_id: int

class AssessmentPlanResponse(AssessmentPlanBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject_id: int
