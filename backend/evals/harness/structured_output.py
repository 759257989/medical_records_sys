# backend/evals/harness/structured_output.py
#
# 套件①：结构化输出合规率。确定性解析，零模型调用。
# 校验三件事：①valid 笔记含 4 个段落标记且顺序正确；②ASSESSMENT 段至少一条合法 ICD 行；
#            ③insufficient 笔记只输出 ###INSUFFICIENT###(不夹带 SOAP 段落)。
from __future__ import annotations

import re

MARKERS = ["###SUBJECTIVE###", "###OBJECTIVE###", "###ASSESSMENT###", "###PLAN###"]
# ICD-10 行：形如 "- I10: Essential hypertension" / "- E11.9: ..." / "- J20.9: ..."
ICD_LINE = re.compile(r"^- ([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?): .+", re.M)


def validate_note(note: str, label: str) -> dict:
    """返回 {"pass": bool, "reason": str}。reason 为空表示通过。"""
    note = note.strip()

    if label == "insufficient":
        # 该判"信息不足"：必须以 ###INSUFFICIENT### 开头，且不能夹带任何 SOAP 段落标记
        ok = note.startswith("###INSUFFICIENT###") and not any(m in note for m in MARKERS)
        return {"pass": ok, "reason": "" if ok else "expected ###INSUFFICIENT### only"}

    # label == "valid"：检查 4 个标记齐全 + 顺序正确
    positions = [note.find(m) for m in MARKERS]
    if any(p == -1 for p in positions):
        return {"pass": False, "reason": "missing one or more section markers"}
    if positions != sorted(positions):
        return {"pass": False, "reason": "markers out of order"}

    # ASSESSMENT 段(到 PLAN 之前)至少要有一条合法 ICD 行
    assess = note[note.find("###ASSESSMENT###"): note.find("###PLAN###")]
    if not ICD_LINE.search(assess):
        return {"pass": False, "reason": "no valid ICD-10 line in ASSESSMENT"}

    return {"pass": True, "reason": ""}


def run(generated_cases: list[dict]) -> dict:
    """对一批已生成的笔记跑结构校验，汇总成指标。"""
    details = []
    for c in generated_cases:
        v = validate_note(c["generated"], c["label"])
        details.append({"id": c["id"], "label": c["label"], **v})

    n = len(details)
    passed = sum(1 for d in details if d["pass"])
    return {
        "pass_rate": round(passed / n, 3) if n else 0.0,
        "passed": passed,
        "total": n,
        "failures": [d for d in details if not d["pass"]],   # 留下未过的，方便排查
    }