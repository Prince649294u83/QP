"""
Institutional Template System — QPGen v2.

Manages the visual formatting of question papers for different institutions.
Supports:
  - Built-in presets (DSATM, VTU Generic, Minimal)
  - Custom templates with uploaded logos/seals
  - Canvas-based template building (stored as JSON config)

Templates are stored as JSON configurations in the database and
drive both the HTML preview and DOCX/PDF export.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from .models import InstitutionalTemplateRecord


# ---------------------------------------------------------------------------
# Enums & Types
# ---------------------------------------------------------------------------

class HeaderLayout(StrEnum):
    TWO_SEAL = "two-seal"             # Logo | Title | Approvals | Logo
    SINGLE_LOGO_CENTER = "single-logo-center"  # Logo centered above title
    BANNER = "banner"                  # Full-width banner image
    MINIMAL = "minimal"                # Just institution name, no logos


class SectionStyle(StrEnum):
    TABLE = "table"                    # Traditional table layout
    NUMBERED_LIST = "numbered-list"    # Clean numbered list


# ---------------------------------------------------------------------------
# Meta Field Configuration
# ---------------------------------------------------------------------------

@dataclass
class MetaField:
    """A single metadata field shown in the paper info table."""

    label: str              # "Subject:", "Max. Marks:", etc.
    key: str                # Maps to paper data (e.g. "subject_name")
    position: str = "left"  # "left" or "right" column
    bold_label: bool = True
    bold_value: bool = False


DEFAULT_META_FIELDS: list[MetaField] = [
    MetaField(label="Subject:", key="subject_name", position="left"),
    MetaField(label="Subject Code:", key="subject_code", position="right"),
    MetaField(label="Semester:", key="semester", position="left"),
    MetaField(label="Max. Marks:", key="max_marks", position="right"),
    MetaField(label="Batch:", key="batch", position="left"),
    MetaField(label="Duration:", key="duration", position="right"),
    MetaField(label="Date of IAT:", key="exam_date", position="left"),
    MetaField(label="Teaching Department:", key="teaching_department", position="right"),
    MetaField(label="RBT Levels:", key="rbt_levels_text", position="full"),
]


# ---------------------------------------------------------------------------
# Accreditation Line
# ---------------------------------------------------------------------------

@dataclass
class AccreditationLine:
    """A single accreditation/affiliation line with optional highlight."""

    text: str
    highlighted_parts: list[str] = field(default_factory=list)
    # Parts of the text to highlight in red/accent color


# ---------------------------------------------------------------------------
# Institutional Template
# ---------------------------------------------------------------------------

@dataclass
class InstitutionalTemplate:
    """
    Complete visual configuration for a question paper template.

    This drives both the React HTML preview and the DOCX/PDF generator.
    """

    # Identity
    template_id: str
    template_name: str
    is_preset: bool = True          # False for user-created templates

    # Institution branding
    institution_name: str = ""
    affiliation_text: str = ""      # "(Autonomous Institute under VTU)"
    accreditation_lines: list[AccreditationLine] = field(default_factory=list)

    # Seal / Logo configuration
    left_seal_path: str | None = None    # Relative path to uploaded image
    right_seal_path: str | None = None
    left_seal_label: str = ""            # Fallback text if no image
    right_seal_label: str = ""

    # Header layout
    header_layout: HeaderLayout = HeaderLayout.TWO_SEAL
    banner_image_path: str | None = None  # For BANNER layout

    # USN row
    show_usn_row: bool = True
    usn_box_count: int = 10

    # Department heading
    show_department_heading: bool = True
    department_prefix: str = "Department of"

    # Exam title
    show_exam_title_box: bool = True
    exam_title_bordered: bool = True

    # Meta fields table
    meta_fields: list[MetaField] = field(default_factory=lambda: list(DEFAULT_META_FIELDS))

    # Question table configuration
    show_qno_column: bool = True
    show_marks_column: bool = True
    show_co_column: bool = True
    show_rbtl_column: bool = True
    question_table_style: SectionStyle = SectionStyle.TABLE

    # Module headers in question table
    show_module_headers: bool = True
    show_or_separators: bool = True

    # Instructions
    default_instructions: str = "Instruction: Answer the following questions"
    show_template_note: bool = True

    # Footer sections
    show_co_descriptions: bool = True
    show_co_coverage_table: bool = True
    show_module_coverage_table: bool = True

    # Page layout (for DOCX)
    page_width_inches: float = 8.27   # A4
    page_height_inches: float = 11.69
    margin_top_inches: float = 0.35
    margin_bottom_inches: float = 0.45
    margin_left_inches: float = 0.4
    margin_right_inches: float = 0.4

    # Typography
    font_family: str = "Arial"
    base_font_size: int = 9
    header_font_size: int = 11
    title_font_size: int = 12

    # Colors
    accent_color: str = "#C62828"     # Red for highlights
    border_color: str = "#000000"

    def to_dict(self) -> dict[str, Any]:
        """Serialize template to JSON-compatible dict."""
        data = asdict(self)
        # Convert enums to strings
        data["header_layout"] = self.header_layout.value
        data["question_table_style"] = self.question_table_style.value
        data["left_logo_path"] = self.left_seal_path
        data["right_logo_path"] = self.right_seal_path
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstitutionalTemplate:
        """Deserialize from a JSON-compatible dict."""
        # Convert enum strings back
        if "header_layout" in data:
            data["header_layout"] = HeaderLayout(data["header_layout"])
        if "question_table_style" in data:
            data["question_table_style"] = SectionStyle(data["question_table_style"])
        # Reconstruct nested dataclasses
        if "meta_fields" in data and data["meta_fields"]:
            data["meta_fields"] = [
                MetaField(**f) if isinstance(f, dict) else f
                for f in data["meta_fields"]
            ]
        if "accreditation_lines" in data and data["accreditation_lines"]:
            data["accreditation_lines"] = [
                AccreditationLine(**a) if isinstance(a, dict) else a
                for a in data["accreditation_lines"]
            ]
        return cls(**data)


# ---------------------------------------------------------------------------
# Built-in Presets
# ---------------------------------------------------------------------------

DSATM_TEMPLATE = InstitutionalTemplate(
    template_id="dsatm",
    template_name="DSATM (Default)",
    is_preset=True,
    institution_name="Dayananda Sagar Academy of Technology & Management",
    affiliation_text="(Autonomous Institute under VTU)",
    accreditation_lines=[
        AccreditationLine("Affiliated to VTU", ["VTU"]),
        AccreditationLine("Approved by AICTE", ["AICTE"]),
        AccreditationLine("Accredited by NAAC with A+ Grade", ["NAAC", "A+"]),
        AccreditationLine("6 Programs Accredited by NBA", ["NBA"]),
        AccreditationLine("(CSE, ISE, ECE, EEE, MECH, CV)"),
    ],
    left_seal_label="DSATM",
    right_seal_label="IQAC",
    header_layout=HeaderLayout.TWO_SEAL,
    show_usn_row=True,
    usn_box_count=10,
    show_department_heading=True,
    show_exam_title_box=True,
    exam_title_bordered=True,
    show_co_descriptions=True,
    show_co_coverage_table=True,
    show_module_coverage_table=True,
    accent_color="#C62828",
)

VTU_GENERIC_TEMPLATE = InstitutionalTemplate(
    template_id="vtu_generic",
    template_name="VTU Generic",
    is_preset=True,
    institution_name="Visvesvaraya Technological University",
    affiliation_text="Belagavi, Karnataka",
    accreditation_lines=[
        AccreditationLine("Established by Government of Karnataka"),
    ],
    left_seal_label="VTU",
    right_seal_label="",
    header_layout=HeaderLayout.SINGLE_LOGO_CENTER,
    show_usn_row=True,
    usn_box_count=10,
    show_department_heading=True,
    show_exam_title_box=True,
    exam_title_bordered=True,
    show_co_descriptions=True,
    show_co_coverage_table=False,
    show_module_coverage_table=False,
    accent_color="#1565C0",
)

MINIMAL_TEMPLATE = InstitutionalTemplate(
    template_id="minimal",
    template_name="Minimal / Clean",
    is_preset=True,
    institution_name="",
    affiliation_text="",
    accreditation_lines=[],
    header_layout=HeaderLayout.MINIMAL,
    show_usn_row=False,
    show_department_heading=False,
    show_exam_title_box=True,
    exam_title_bordered=False,
    show_co_descriptions=False,
    show_co_coverage_table=False,
    show_module_coverage_table=False,
    meta_fields=[
        MetaField(label="Subject:", key="subject_name", position="left"),
        MetaField(label="Subject Code:", key="subject_code", position="right"),
        MetaField(label="Max. Marks:", key="max_marks", position="left"),
        MetaField(label="Duration:", key="duration", position="right"),
    ],
    accent_color="#333333",
)


# All built-in presets
PRESET_TEMPLATES: dict[str, InstitutionalTemplate] = {
    "dsatm": DSATM_TEMPLATE,
    "vtu_generic": VTU_GENERIC_TEMPLATE,
    "minimal": MINIMAL_TEMPLATE,
}


# ---------------------------------------------------------------------------
# Template Manager
# ---------------------------------------------------------------------------

class TemplateManager:
    """
    Manages template CRUD operations.

    For now, presets are in-memory and custom templates are stored
    in the database as JSON in a dedicated table (future migration).
    """

    def __init__(self, storage_root: Path | None = None):
        self._custom_templates: dict[str, InstitutionalTemplate] = {}
        self._storage_root = storage_root or (settings.storage_path / "templates")
        self._storage_root.mkdir(parents=True, exist_ok=True)

    def _custom_templates_from_db(self, db: Session | None = None) -> dict[str, InstitutionalTemplate]:
        if db is None:
            return dict(self._custom_templates)

        records = list(
            db.scalars(
                select(InstitutionalTemplateRecord).order_by(
                    InstitutionalTemplateRecord.template_name.asc()
                )
            )
        )
        templates: dict[str, InstitutionalTemplate] = {}
        for record in records:
            data = dict(record.config_json or {})
            if "template_id" not in data:
                data["template_id"] = record.template_id
            if "template_name" not in data:
                data["template_name"] = record.template_name
            if "institution_name" not in data:
                data["institution_name"] = record.institution_name
            try:
                template = InstitutionalTemplate.from_dict(data)
            except Exception:
                continue
            templates[template.template_id] = template
        return templates

    def list_templates(self, db: Session | None = None) -> list[dict[str, Any]]:
        """List all available templates (presets + custom)."""
        result: list[dict[str, Any]] = []
        for template in PRESET_TEMPLATES.values():
            result.append({
                "template_id": template.template_id,
                "template_name": template.template_name,
                "is_preset": True,
                "institution_name": template.institution_name,
                "header_layout": template.header_layout.value,
            })
        for template in self._custom_templates_from_db(db).values():
            result.append({
                "template_id": template.template_id,
                "template_name": template.template_name,
                "is_preset": False,
                "institution_name": template.institution_name,
                "header_layout": template.header_layout.value,
            })
        return result

    def get_template(
        self, template_id: str, db: Session | None = None
    ) -> InstitutionalTemplate:
        """Get a template by ID. Falls back to DSATM if not found."""
        if template_id in PRESET_TEMPLATES:
            return PRESET_TEMPLATES[template_id]
        custom_templates = self._custom_templates_from_db(db)
        if template_id in custom_templates:
            return custom_templates[template_id]
        return DSATM_TEMPLATE

    def save_custom_template(
        self,
        template: InstitutionalTemplate,
        db: Session | None = None,
        owner_user_id: int | None = None,
    ) -> InstitutionalTemplate:
        """Save a custom template."""
        template.is_preset = False
        payload = template.to_dict()

        if db is not None:
            existing = db.scalar(
                select(InstitutionalTemplateRecord).where(
                    InstitutionalTemplateRecord.template_id == template.template_id
                )
            )
            if existing is None:
                existing = InstitutionalTemplateRecord(
                    template_id=template.template_id,
                    template_name=template.template_name,
                    institution_name=template.institution_name,
                    owner_user_id=owner_user_id,
                    config_json=payload,
                )
                db.add(existing)
            else:
                existing.template_name = template.template_name
                existing.institution_name = template.institution_name
                existing.owner_user_id = owner_user_id or existing.owner_user_id
                existing.config_json = payload
            db.commit()
            db.refresh(existing)
        else:
            self._custom_templates[template.template_id] = template

            # Persist to disk as JSON for local fallback
            path = self._storage_root / f"{template.template_id}.json"
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        return template

    def delete_custom_template(
        self, template_id: str, db: Session | None = None
    ) -> bool:
        """Delete a custom template. Cannot delete presets."""
        if template_id in PRESET_TEMPLATES:
            return False
        if db is not None:
            record = db.scalar(
                select(InstitutionalTemplateRecord).where(
                    InstitutionalTemplateRecord.template_id == template_id
                )
            )
            if record is None:
                return False
            db.delete(record)
            db.commit()
        elif template_id in self._custom_templates:
            del self._custom_templates[template_id]
            path = self._storage_root / f"{template_id}.json"
            if path.exists():
                path.unlink()
        else:
            return False
        return True

    def save_logo(self, template_id: str, position: str, data: bytes, filename: str) -> str:
        """
        Save an uploaded logo/seal image.

        Returns the relative path for storage in template config.
        """
        logos_dir = self._storage_root / "logos"
        logos_dir.mkdir(parents=True, exist_ok=True)

        ext = Path(filename).suffix or ".png"
        safe_name = f"{template_id}_{position}{ext}"
        path = logos_dir / safe_name
        path.write_bytes(data)

        return f"templates/logos/{safe_name}"

    def load_persisted_templates(self) -> None:
        """Load custom templates from disk on startup."""
        for path in self._storage_root.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                template = InstitutionalTemplate.from_dict(data)
                if not template.is_preset:
                    self._custom_templates[template.template_id] = template
            except Exception:
                pass


# Global instance
_template_manager: TemplateManager | None = None


def get_template_manager() -> TemplateManager:
    """Get or create the global template manager."""
    global _template_manager
    if _template_manager is None:
        _template_manager = TemplateManager()
        _template_manager.load_persisted_templates()
    return _template_manager


def resolve_template_asset_path(asset_path: str | None) -> Path | None:
    """Resolve a stored template asset path to an absolute filesystem path."""
    if not asset_path:
        return None
    path = Path(asset_path)
    if path.is_absolute():
        return path if path.exists() else None
    candidate = settings.storage_path / asset_path
    return candidate if candidate.exists() else None
