from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# Alembic 版本标识（必须声明，否则无法识别迁移）
revision = "1ff3124nfae3"
down_revision = "1a9145015fe0"
branch_labels = None
depends_on = None

TENANT_TABLES = ["patients", "encounters", "note_versions", "note_version_codes",
                 "audit_log", "templates", "users"]


def upgrade():
    # 1) tenants 表
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("rate_limit_per_min", sa.Integer, nullable=False, server_default="120"),
        sa.Column("monthly_budget_usd", sa.Integer, nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # 2) 建一个 default 租户，把所有历史数据归到它名下
    op.execute("""
        INSERT INTO tenants (id, slug, name)
        VALUES ('00000000-0000-0000-0000-000000000001', 'default', 'Default Clinic')
    """)
    # 3) 每张表加 tenant_id(先可空)→ 回填 default → 再设 NOT NULL + 外键
    for t in TENANT_TABLES:
        op.add_column(t, sa.Column("tenant_id", UUID(as_uuid=True), nullable=True))
        op.execute(f"UPDATE {t} SET tenant_id = '00000000-0000-0000-0000-000000000001'")
        op.alter_column(t, "tenant_id", nullable=False)
        op.create_foreign_key(f"fk_{t}_tenant", t, "tenants", ["tenant_id"], ["id"])
        op.create_index(f"ix_{t}_tenant_id", t, ["tenant_id"])


def downgrade():
    for t in TENANT_TABLES:
        op.drop_index(f"ix_{t}_tenant_id", t)
        op.drop_constraint(f"fk_{t}_tenant", t, type_="foreignkey")
        op.drop_column(t, "tenant_id")
    op.drop_table("tenants")