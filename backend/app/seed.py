# app/seed.py
import asyncio

from sqlalchemy import select

from app.core.db import SessionLocal, engine
from app.core.security import hash_password
from app.models.user import User
from app.models.template import Template

# (email, password, first_name, last_name)
PROVIDERS = [
    ("dr.smith@clinic.example.com", "Provider123!", "John", "Smith"),
    ("dr.jones@clinic.example.com", "Provider123!", "Mary", "Jones"),
    ("dr.lee@clinic.example.com", "Provider123!", "David", "Lee"),
]
ADMIN = ("admin@clinic.example.com", "Admin123!", "Alice", "Admin")

TEMPLATES = [
    ("General SOAP", "general",
     "You are an experienced clinical documentation specialist. Produce a concise, "
     "professional SOAP note from the transcript. Never fabricate facts not present."),
    ("Orthopedic Follow-up", "ortho_followup",
     "You are documenting an orthopedic follow-up visit. Emphasize range of motion, "
     "pain scores, imaging, and rehab progress in the Objective and Plan sections."),
    ("New Patient Evaluation", "new_patient",
     "You are documenting a comprehensive new patient evaluation. Include a thorough "
     "history of present illness, full review of systems, and a broad differential."),
]


async def main() -> None:
    async with SessionLocal() as db:
        # 1) 账号（已存在则跳过，可重复运行）
        rows = [(*ADMIN, "admin")] + [(*p, "provider") for p in PROVIDERS]
        for email, pw, first, last, role in rows:
            exists = await db.scalar(select(User).where(User.email == email))
            if exists:
                print(f"skip user {email}")
                continue
            db.add(User(
                email=email.lower(),
                password_hash=hash_password(pw),
                role=role,
                first_name=first,
                last_name=last,
            ))
        await db.commit()

        # 2) 取 admin 作为模板创建者
        admin = await db.scalar(select(User).where(User.email == ADMIN[0]))

        # 3) 模板（按 name 去重）
        for name, etype, prompt in TEMPLATES:
            exists = await db.scalar(select(Template).where(Template.name == name))
            if exists:
                print(f"skip template {name}")
                continue
            db.add(Template(
                name=name, encounter_type=etype,
                system_prompt=prompt, created_by=admin.id if admin else None,
            ))
        await db.commit()

    await engine.dispose()
    print("seed done.")


if __name__ == "__main__":
    asyncio.run(main())