# alembic/versions/yyyy_enable_rls.py
from alembic import op

# Alembic 版本标识（必须声明，否则无法识别迁移）
revision = "greg2134vgr"
down_revision = "1ff3124nfae3"
branch_labels = None
depends_on = None

# 注意：users 不在内(认证引导路径，见 §3.2)
RLS_TABLES = ["patients", "encounters", "note_versions", "note_version_codes",
              "audit_log", "templates"]


def upgrade():
    for t in RLS_TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        # ★坑1：表 owner(我们的 scribe)默认"绕过"RLS。FORCE 让 owner 也受约束，否则策略形同虚设。
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        # ★坑3：current_setting 第二参 true=missing_ok(没设时返回 NULL，不报错)；
        #        且按 text 比较，避免把空串/NULL 强转 uuid 而崩溃。
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {t}
              USING (tenant_id::text = current_setting('app.tenant_id', true))
              WITH CHECK (tenant_id::text = current_setting('app.tenant_id', true))
        """)


def downgrade():
    for t in RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")