# backend/app/core/providers/pricing.py
#
# model → 每百万 token 的美元单价。用于给每次调用算 cost_usd。
# ⚠️ 价格会变：以各厂商官网价目页为准，这里只是出厂默认，定期 review。
from app.core.providers.base import Usage

# (input_per_million_usd, output_per_million_usd)
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o":                  (2.50, 10.00),
    "text-embedding-3-small":  (0.02,  0.00),   # 嵌入只有输入价
    # Anthropic（数字取自 claude-api 技能的价目表）
    "claude-opus-4-8":         (5.00, 25.00),
    "claude-sonnet-4-6":       (3.00, 15.00),
}


def cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """按价目表算这次调用的美元成本；未知模型按 0 计（并不会抛错，避免记账拖垮主流程）。"""
    pin, pout = _PRICE_PER_MTOK.get(model, (0.0, 0.0))
    return (prompt_tokens / 1_000_000) * pin + (completion_tokens / 1_000_000) * pout


def attach_cost(usage: Usage, model: str) -> Usage:
    """把成本填回 Usage（就地修改并返回，方便链式）。"""
    usage.cost_usd = cost_usd(model, usage.prompt_tokens, usage.completion_tokens)
    return usage