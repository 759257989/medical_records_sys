# backend/app/core/security/phi.py
#
# PHI 脱敏。两个能力：
#   scrub(text)         不可逆替换成 <PHI> —— 写日志/trace 前用("日志无 PHI")
#   pseudonymize/reidentify  可逆占位 + 还原 —— 严格模式下"发模型前去标识"用
# 装了 Presidio 用 Presidio(含姓名 NER)；没装则退回正则兜底(仅结构化标识符)。
from __future__ import annotations

import re

# ── 正则兜底：Presidio 不可用时也能擦掉最关键的结构化 PHI ──────────────────────────
_REGEX: list[tuple[str, re.Pattern]] = [
    ("US_SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    # 电话：注意不要在 '(' 前加 \b(会失效)；覆盖 (415) 555-0132 / 415-555-0132 / +1 ...
    ("PHONE", re.compile(r"(?:\+?1[-.\s]?)?(?:\(\d{3}\)[-.\s]?|\d{3}[-.\s])\d{3}[-.\s]?\d{4}")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("MRN", re.compile(r"\bMRN[:#]?\s*\d{5,10}\b", re.I)),
    ("DATE", re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")),
]


def _regex_scrub(text: str) -> str:
    for label, rx in _REGEX:
        text = rx.sub(f"<{label}>", text)
    return text


# ── 懒加载 Presidio(进程内只初始化一次；失败则永久走兜底)──────────────────────────
_ENGINE = None   # None=未初始化  False=不可用(走兜底)  tuple=(analyzer, anonymizer, OperatorConfig)


def _engine():
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    try:
        from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine
        from presidio_anonymizer.entities import OperatorConfig

        # 用轻量 sm 模型(而非默认 lg)，省下数百 MB
        nlp = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
        }).create_engine()
        analyzer = AnalyzerEngine(nlp_engine=nlp)
        # 自定义识别器：病历号 MRN(Presidio 默认没有)
        analyzer.registry.add_recognizer(PatternRecognizer(
            supported_entity="MRN",
            patterns=[Pattern("mrn", r"\bMRN[:#]?\s*\d{5,10}\b", 0.8)],
        ))
        _ENGINE = (analyzer, AnonymizerEngine(), OperatorConfig)
    except Exception:
        _ENGINE = False        # 没装 / 模型缺失 → 兜底
    return _ENGINE


def scrub(text: str) -> str:
    """不可逆脱敏：PHI → <实体>。用于写日志/trace 前。"""
    if not text:
        return text
    eng = _engine()
    if not eng:
        return _regex_scrub(text)
    analyzer, anonymizer, OperatorConfig = eng
    results = analyzer.analyze(text=text, language="en")
    masked = anonymizer.anonymize(
        text=text, analyzer_results=results,
        operators={"DEFAULT": OperatorConfig("replace", {"new_value": "<PHI>"})},
    ).text
    # 兜底：结构化标识符始终再走一遍确定性正则，弥补 Presidio 的漏判。
    # 例：Presidio 把 123-45-6789（=123456789）当“样本 SSN”而故意不识别。
    return _regex_scrub(masked)


def scrub_obj(obj):
    """递归擦字典/列表里的字符串值 —— trace 的 input 常是 {'transcript': '...'} 这种结构。"""
    if isinstance(obj, str):
        return scrub(obj)
    if isinstance(obj, dict):
        return {k: scrub_obj(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub_obj(v) for v in obj]
    return obj

# ── 可逆去标识：发给模型前替换、拿回结果后还原 ─────────────────────────────────────
def _detect_spans(text: str) -> list[tuple[int, int, str, str]]:
    """返回 [(start, end, entity_type, value)]，按起点排序。
    Presidio（若可用）负责姓名等命名实体；结构化标识符始终叠加正则兜底，
    确保 SSN/电话/邮箱/MRN/日期不因 Presidio 的 NER/校验漏判而泄露。"""
    spans = []
    eng = _engine()
    if eng:
        analyzer = eng[0]
        rs = analyzer.analyze(text=text, language="en")
        spans += [(r.start, r.end, r.entity_type, text[r.start:r.end]) for r in rs]
    for label, rx in _REGEX:
        spans += [(m.start(), m.end(), label, m.group()) for m in rx.finditer(text)]
    return sorted(spans)


def pseudonymize(text: str) -> tuple[str, dict[str, str]]:
    """把 PHI 换成稳定占位符(如 __NAME_1__)；返回 (去标识文本, {token: 原值})。
    同一原值复用同一 token，便于模型理解上下文，也便于还原。"""
    spans = _detect_spans(text)
    mapping: dict[str, str] = {}
    value_to_token: dict[str, str] = {}
    counters: dict[str, int] = {}
    out, last = [], 0
    for start, end, etype, value in spans:
        if start < last:               # 跨度重叠(Presidio 偶发) → 跳过，避免错位
            continue
        token = value_to_token.get(value)
        if token is None:
            counters[etype] = counters.get(etype, 0) + 1
            token = f"__{etype}_{counters[etype]}__"   # 不易被模型改写的醒目占位
            value_to_token[value] = token
            mapping[token] = value
        out.append(text[last:start]); out.append(token); last = end
    out.append(text[last:])
    return "".join(out), mapping


def reidentify(text: str, mapping: dict[str, str]) -> str:
    """把占位符还原成原值(模型输出回来后调用)。"""
    for token, value in mapping.items():
        text = text.replace(token, value)
    return text