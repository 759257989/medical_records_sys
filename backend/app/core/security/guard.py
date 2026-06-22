# backend/app/core/security/guard.py
#
# 模型边界护栏(自研、透明、对齐 OWASP LLM Top 10)：
#   scan_input(text)   进来的 transcript 是否藏注入/越狱 → 命中即拦
#   scan_output(note)  出去的笔记是否泄露系统提示 / 越权
import re

# ── 注入/越狱 指纹 ──────────────────────────────────────────────────────────────
_INJECTION = [
    r"ignore (the )?(previous|above|prior) (instructions|prompt)",
    r"disregard (the )?(previous|above|system)",
    r"you are now\b",
    r"reveal.*(system prompt|instructions)",
    r"print.*(system prompt|instructions)",
    r"system prompt",
    r"###(SUBJECTIVE|OBJECTIVE|ASSESSMENT|PLAN|INSUFFICIENT)###",  # 伪造我们的契约标记
    r"</?(system|assistant|user)>",                                # 伪造角色标签
]
_INJ = [re.compile(p, re.I) for p in _INJECTION]


def scan_input(text: str) -> dict:
    """返回 {'blocked': bool, 'reasons': [...]}。命中任一注入指纹即建议拦截。"""
    reasons = [p.pattern for p in _INJ if p.search(text or "")]
    return {"blocked": bool(reasons), "reasons": reasons}


# ── 输出护栏：别把系统提示/契约原文泄露出去 ───────────────────────────────────────
_LEAK_MARKERS = [
    "Format the clinical note using EXACTLY",   # OUTPUT_CONTRACT 的原话
    "You are an experienced clinical documentation specialist",  # persona 原话
]


def scan_output(note: str) -> dict:
    """返回 {'ok': bool, 'issues': [...]}。检测系统提示/契约文本被原样吐出。"""
    issues = [m for m in _LEAK_MARKERS if m.lower() in (note or "").lower()]
    return {"ok": not issues, "issues": issues}