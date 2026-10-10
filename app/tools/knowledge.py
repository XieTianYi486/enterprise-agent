# ============================================================
# 制度查询工具：check_policy（只读）
#
# 说明：这里是一份「轻量关键词打分」的示例实现，
# 用于让 Agent 具备查制度的能力，并不是生产级检索。
# 更完整的混合检索方案见另一个项目（RAG 知识库），两个项目职责不重叠。
# ============================================================

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolContext, ToolOutcome
from app.db.models import Policy


class CheckPolicyArgs(BaseModel):
    query: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="要咨询的制度问题或关键词，例如「请假审批流程」「差旅住宿标准」",
    )
    top_k: int = Field(3, ge=1, le=5, description="返回的条款条数，默认 3 条")


def _bigrams(text: str) -> List[str]:
    """中文按 2-gram 切分，作为最简召回单元。"""
    clean = "".join(ch for ch in text if not ch.isspace())
    return [clean[i : i + 2] for i in range(len(clean) - 1)] or [clean]


def _score(query: str, policy: Policy) -> float:
    """关键词命中 3 分/个，标题 2-gram 命中 2 分，正文 2-gram 命中 1 分。"""
    lowered = query.lower()
    score = 0.0

    for keyword in (policy.keywords or "").split():
        if keyword and keyword.lower() in lowered:
            score += 3.0

    grams = _bigrams(lowered)
    title = (policy.title or "").lower()
    content = (policy.content or "").lower()
    score += sum(2.0 for g in grams if g in title)
    score += sum(1.0 for g in grams if g in content)
    return score


def _check_policy(ctx: ToolContext, args: CheckPolicyArgs) -> ToolOutcome:
    policies = ctx.db.query(Policy).all()
    scored: List[Tuple[float, Policy]] = sorted(
        ((_score(args.query, p), p) for p in policies), key=lambda x: x[0], reverse=True
    )
    hits = [(s, p) for s, p in scored if s > 0][: args.top_k]

    if not hits:
        # 查不到不是错误，而是「无依据」——交给模型如实告知用户，不要编造
        return ToolOutcome(
            ok=True,
            data={
                "ok": True,
                "found": False,
                "query": args.query,
                "message": "公司制度库中没有与该问题相关的条款，请如实告知用户并建议其咨询 HR。",
            },
        )

    return ToolOutcome(
        ok=True,
        data={
            "ok": True,
            "found": True,
            "query": args.query,
            "policies": [
                {
                    "title": p.title,
                    "category": p.category,
                    "content": p.content,
                    "relevance": round(s, 1),
                }
                for s, p in hits
            ],
        },
    )


TOOLS = [
    Tool(
        name="check_policy",
        description=(
            "查询公司内部规章制度，覆盖请假制度、报销标准、报销流程、考勤加班、年假福利等。"
            "当用户询问「制度是怎么规定的」「有没有相关规定」「流程是什么」时应调用此工具，"
            "并基于返回的条款原文回答；若返回 found=false，必须如实说明制度库中无相关条款。"
        ),
        args_model=CheckPolicyArgs,
        handler=_check_policy,
    ),
]