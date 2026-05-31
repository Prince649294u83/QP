"""Add institutional template and generation job tables.

Revision ID: 0001_add_template_generation_jobs
Revises:
Create Date: 2026-05-17 21:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0001_add_template_generation_jobs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("institutional_templates"):
        op.create_table(
            "institutional_templates",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("template_id", sa.String(length=120), nullable=False),
            sa.Column("template_name", sa.String(length=255), nullable=False),
            sa.Column("institution_name", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("owner_user_id", sa.Integer(), nullable=True),
            sa.Column("config_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
            sa.UniqueConstraint("template_id"),
        )
        op.create_index(
            "ix_institutional_templates_template_id",
            "institutional_templates",
            ["template_id"],
            unique=True,
        )

    if not inspector.has_table("generation_jobs"):
        op.create_table(
            "generation_jobs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("subject_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("request_params", sa.JSON(), nullable=False),
            sa.Column("result_data", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("generation_jobs"):
        op.drop_table("generation_jobs")
    if inspector.has_table("institutional_templates"):
        if "ix_institutional_templates_template_id" in {
            index["name"] for index in inspector.get_indexes("institutional_templates")
        }:
            op.drop_index("ix_institutional_templates_template_id", table_name="institutional_templates")
        op.drop_table("institutional_templates")
