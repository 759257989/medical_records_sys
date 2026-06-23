# 一条龙:采样→在线评估→漂移检测→产候选。挂到 cron / GH Actions schedule 上跑。
import asyncio
from evals.online import run_online, drift, curate


async def main():
    print("① 在线评估 ...")
    rec = await run_online.run()
    if not rec:
        return
    print("\n② 漂移检测 ...")
    for a in (drift.check() or ["无漂移"]):
        print(a)
    print("\n③ 数据飞轮 ...")
    curate.curate()


if __name__ == "__main__":
    asyncio.run(main())