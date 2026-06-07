# app/seed_icd.py
# 把 ICD 码灌进 RDS；若配了 OPENAI_API_KEY，则顺带算好语义向量。
import asyncio

from sqlalchemy import select

from app.core.db import SessionLocal, engine
from app.core.llm import embed_texts
from app.data.icd10_seed import ICD10_CODES
from app.models.icd import Icd10Code


async def main() -> None:
    async with SessionLocal() as db:
        # 1) 插入还不存在的码
        existing = set(await db.scalars(select(Icd10Code.code)))
        new_rows = [Icd10Code(code=c, description=d) for (c, d) in ICD10_CODES if c not in existing]
        if new_rows:
            db.add_all(new_rows)
            await db.commit()
        print(f"inserted {len(new_rows)} codes (total in file: {len(ICD10_CODES)})")

        # 2) 给还没有向量的码计算 embedding（仅真实 key 模式）
        todo = list(await db.scalars(select(Icd10Code).where(Icd10Code.embedding.is_(None))))
        if not todo:
            print("all codes already embedded.")
        else:
            batch = 100
            for i in range(0, len(todo), batch):
                chunk = todo[i:i + batch]
                vectors = await embed_texts([r.description for r in chunk])
                if vectors is None:
                    print("no OPENAI_API_KEY -> skip embeddings (search will use keyword fallback).")
                    break
                for r, v in zip(chunk, vectors):
                    r.embedding = v
                await db.commit()
                print(f"embedded {min(i + batch, len(todo))}/{len(todo)}")

    await engine.dispose()
    print("seed_icd done.")


if __name__ == "__main__":
    asyncio.run(main())