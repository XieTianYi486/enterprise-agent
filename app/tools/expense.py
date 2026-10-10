# ============================================================
# 报销相关工具：查费用标准 / 提交报销
# ============================================================

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolContext, ToolOutcome
from app.core.exceptions import ToolExecutionError
from app.core.utils import expense_category_name, generate_request_no
from app.db.models import ApprovalRecord, ExpenseRequest, ExpenseStandard

ExpenseCategory = Literal["travel", "meal", "office", "transport"]


# ----------------------------------------------------------------------
# 1) get_expense_standard —— 查询费用标准（只读）
# ----------------------------------------------------------------------
class GetExpenseStandardArgs(BaseModel):
    category: ExpenseCategory = Field(
        ...,
        description="费用类别：travel=差旅费, meal=餐饮费, office=办公用品, transport=交通费",
    )


def _get_expense_standard(ctx: ToolContext, args: GetExpenseStandardArgs) -> ToolOutcome:
    standard = (
        ctx.db.query(ExpenseStandard).filter(ExpenseStandard.category == args.category).first()
    )
    if standard is None:
        raise ToolExecutionError(f"未找到「{expense_category_name(args.category)}」的费用标准。")

    return ToolOutcome(
        ok=True,
        data={
            "ok": True,
            "category": standard.category,
            "category_name": standard.category_name,
            "single_limit_amount": standard.limit_amount,
            "description": standard.description,
        },
    )


# ----------------------------------------------------------------------
# 2) submit_expense —— 提交报销申请（写操作，需确认）
# ----------------------------------------------------------------------
class SubmitExpenseArgs(BaseModel):
    amount: float = Field(..., gt=0, le=200000, description="报销金额（元），必须大于 0")
    category: ExpenseCategory = Field(
        ..., description="费用类别：travel=差旅费, meal=餐饮费, office=办公用品, transport=交通费"
    )
    reason: str = Field(..., min_length=2, max_length=200, description="费用事由，需具体说明用途")
    invoice_count: int = Field(1, ge=1, le=50, description="发票张数，默认 1 张")


def _validate_submit_expense(ctx: ToolContext, args: SubmitExpenseArgs) -> tuple[ExpenseStandard, str]:
    """报销业务规则校验（只读、无副作用）：标准存在 + 是否超单笔上限。

    返回 (standard, approval_step)；校验不通过抛 ToolExecutionError。
    本函数同时被「二次确认前的预检」与「真正执行」复用，保证两处规则一致。
    """
    standard = (
        ctx.db.query(ExpenseStandard).filter(ExpenseStandard.category == args.category).first()
    )
    if standard is None:
        raise ToolExecutionError(f"未找到「{expense_category_name(args.category)}」的费用标准，无法提交。")

    # 业务规则拦截：超标准金额直接驳回，而不是让脏数据进库
    if standard.limit_amount > 0 and args.amount > standard.limit_amount:
        raise ToolExecutionError(
            f"{standard.category_name}单笔报销上限为 {standard.limit_amount} 元，"
            f"本次申请 {args.amount} 元已超出，无法提交。"
            f"（{standard.description}）建议拆分为多笔或先与部门经理确认后再提交。"
        )

    # 审批路径：沿用与请假一致的公司规则，超 5000 元需总经理终审
    step = "总经理" if args.amount > 5000 else "部门经理"
    return standard, step


def _precheck_submit_expense(ctx: ToolContext, args: SubmitExpenseArgs) -> None:
    """二次确认前的业务规则预检：只校验、不写库。"""
    _validate_submit_expense(ctx, args)


def _submit_expense(ctx: ToolContext, args: SubmitExpenseArgs) -> ToolOutcome:
    standard, step = _validate_submit_expense(ctx, args)

    request = ExpenseRequest(
        request_no=generate_request_no("EX"),
        user_id=ctx.user_id,
        category=args.category,
        amount=round(args.amount, 2),
        reason=args.reason,
        invoice_count=args.invoice_count,
        status="pending",
        current_step=step,
    )
    ctx.db.add(request)
    ctx.db.flush()

    ctx.db.add(
        ApprovalRecord(
            biz_type="expense",
            biz_id=request.id,
            approver_name=ctx.user_name,
            action="submit",
            comment="员工提交报销申请",
        )
    )
    ctx.db.commit()

    return ToolOutcome(
        ok=True,
        data={
            "ok": True,
            "message": "报销申请已提交成功，等待审批。",
            "request_no": request.request_no,
            "category_name": standard.category_name,
            "amount": request.amount,
            "invoice_count": request.invoice_count,
            "reason": args.reason,
            "status": "审批中",
            "current_step": step,
            "pay_note": "审批通过后由财务在每月 15 日、30 日统一打款。",
        },
    )


def _summarize_submit_expense(args: SubmitExpenseArgs) -> str:
    return (
        f"提交{expense_category_name(args.category)}报销：{args.amount} 元，"
        f"{args.invoice_count} 张发票，事由「{args.reason}」"
    )


TOOLS = [
    Tool(
        name="get_expense_standard",
        description=(
            "查询某类费用的报销标准（单笔上限与具体规定）。"
            "当用户询问「能不能报」「能报多少」「标准是多少」时应调用此工具。"
        ),
        args_model=GetExpenseStandardArgs,
        handler=_get_expense_standard,
    ),
    Tool(
        name="submit_expense",
        description=(
            "为当前登录员工提交一条费用报销申请。"
            "必须先从用户处问清金额、费用类别、事由三项信息才能调用，不得臆造金额。"
            "此操作会写入系统并进入审批流程，需要用户确认后才真正生效。"
        ),
        args_model=SubmitExpenseArgs,
        handler=_submit_expense,
        is_write=True,
        requires_confirmation=True,
        precheck=_precheck_submit_expense,
        summarize=_summarize_submit_expense,
    ),
]