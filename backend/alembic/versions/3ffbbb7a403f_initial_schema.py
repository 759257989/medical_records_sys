# alembic/versions/xxxx_initial_schema.py
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "0001_initial"          # 若与文件名不一致，改成文件里已有的 revision 值
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0) 先装 pgvector 扩展（建带向量列的表之前必须先有它）
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 1) users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("role IN ('provider','admin')", name="ck_users_role"),
    )

    # 2) patients（+ 大小写不敏感的自然键唯一索引）
    op.create_table(
        "patients",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("dob", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_patients_identity "
        "ON patients (lower(first_name), lower(last_name), dob)"
    )

    # 3) templates
    op.create_table(
        "templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("encounter_type", sa.String(100)),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # 4) icd10_codes（带向量列）
    op.create_table(
        "icd10_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(20), nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("embedding", Vector(1536)),
    )
    # 余弦相似度的近似最近邻索引（300 行其实不需要，但展示工程意识）
    op.execute("CREATE INDEX ix_icd_vec ON icd10_codes USING hnsw (embedding vector_cosine_ops)")

    # 5) encounters
    op.create_table(
        "encounters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("patient_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("patients.id"), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("templates.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("transcript", sa.Text),
        sa.Column("working_note", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('draft','generated','finalized')", name="ck_enc_status"),
    )
    op.create_index("ix_enc_provider", "encounters", ["provider_id", "created_at"])
    op.create_index("ix_enc_patient", "encounters", ["patient_id"])

    # 6) note_versions
    op.create_table(
        "note_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("encounter_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("encounters.id"), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("subjective", sa.Text),
        sa.Column("objective", sa.Text),
        sa.Column("assessment", sa.Text),
        sa.Column("plan", sa.Text),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("encounter_id", "version_no", name="uq_note_enc_ver"),
    )

    # 7) note_version_codes（多对多关联）
    op.create_table(
        "note_version_codes",
        sa.Column("note_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("note_versions.id"), primary_key=True),
        sa.Column("icd10_code_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("icd10_codes.id"), primary_key=True),
    )

    # 8) audit_log
    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50)),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True)),
        sa.Column("details", postgresql.JSONB),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("note_version_codes")
    op.drop_table("note_versions")
    op.drop_index("ix_enc_patient", table_name="encounters")
    op.drop_index("ix_enc_provider", table_name="encounters")
    op.drop_table("encounters")
    op.execute("DROP INDEX IF EXISTS ix_icd_vec")
    op.drop_table("icd10_codes")
    op.drop_table("templates")
    op.execute("DROP INDEX IF EXISTS uq_patients_identity")
    op.drop_table("patients")
    op.drop_table("users")