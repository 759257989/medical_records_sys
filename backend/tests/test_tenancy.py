# backend/tests/test_tenancy.py
import uuid
import pytest
from sqlalchemy import text
from app.core.db import SessionLocal
from app.models.patient import Patient

A = "00000000-0000-0000-0000-00000000000a"
B = "00000000-0000-0000-0000-00000000000b"


@pytest.mark.asyncio
async def test_rls_isolates_tenants():
    # 准备：分别以 A、B 租户上下文各建一个患者
    async with SessionLocal() as s:
        await s.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": A})
        s.add(Patient(first_name="Alice", last_name="A", dob="1980-01-01", tenant_id=uuid.UUID(A)))
        await s.commit()
    async with SessionLocal() as s:
        await s.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": B})
        s.add(Patient(first_name="Bob", last_name="B", dob="1980-01-01", tenant_id=uuid.UUID(B)))
        await s.commit()

    # 断言：在 A 的上下文里，只看得到 A 的患者
    async with SessionLocal() as s:
        await s.execute(text("SELECT set_config('app.tenant_id', :t, false)"), {"t": A})
        names = [p.first_name for p in (await s.execute(text("SELECT first_name FROM patients"))).all()]
        assert "Alice" in names and "Bob" not in names      # ← B 的数据被 RLS 挡掉

    # 断言：没设租户时，一行都看不到(fail closed)
    async with SessionLocal() as s:
        await s.execute(text("SELECT set_config('app.tenant_id', '', false)"))
        rows = (await s.execute(text("SELECT * FROM patients"))).all()
        assert rows == []