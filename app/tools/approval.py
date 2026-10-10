# ============================================================
# 审批查询工具：get_approval_status（只读）
# ============================================================

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.agent.registry import Tool, ToolContext, ToolOutcome
from app.core.exceptions import ToolExecutionError
from app.core.utils import expense_category_name, leave_type_name
from app.db.models import ApprovalRecord, ExpenseRequest, LeaveRequest


class GetApprovalStatusArgs(BaseModel):
    request_no: Optional[str] = Field(
        None,
        description="要查询的具体单号（如 LV20261001101502202）。不填则返回最近的申请列表。",
    )
    biz_type: Optional[Literal["leave", "expense"]] = Field(
        None, description="按业务类型过滤：leave=请假, expense=报销。不填则两类都查。"
    )
    include_finished: bool = Field(
        False, description="是否包含已结束（已通过/已驳回）的历史单据，默认只看审批中的。"
    )


def _leave_item(r: LeaveRequest) -> Dict[str, Any]:
    return {
        "biz_type": "leave",
        "request_no": r.request_no,
        "type_name": leave_type_name(r.leave_type),
        "start_date": r.start_date.isoformat(),
        "end_date": r.end_date.isoformat(),
        "days": r.days,
        "reason": r.reason,
        "status": r.status,
        "current_step": r.current_step,
    }


def _expense_item(r: ExpenseRequest) -> Dict[str, Any]:
    return {
        "biz_type": "expense",
        "request_no": r.request_no,
        "type_name": expense_category_name(r.category),
        "amount": r.amount,
        "invoice_count": r.invoice_count,
        "reason": r.reason,
        "status": r.status,
        "current_step": r.current_step,
    }


def _query_requests(ctx: ToolContext, args: GetApprovalStatusArgs) -> List[Dict[str, Any]]:
    """按条件拉取该员工本人的申请单。"""
    items: List[Dict[str, Any]] = []

    if args.biz_type in (None, "leave"):
        query = ctx.db.query(LeaveRequest).filter(LeaveRequest.user_id == ctx.user_id)
        if args.request_no:
            query = query.filter(LeaveRequest.request_no == args.request_no)
        if not args.include_finished and not args.request_no:
            query = query.filter(LeaveRequest.status == "pending")
        items += [_leave_item(r) for r in query.order_by(LeaveRequest.id.desc()).limit(10).all()]

    if args.biz_type in (None, "expense"):
        query = ctx.db.query(ExpenseRequest).filter(ExpenseRequest.user_id == ctx.user_id)
        if args.request_no:
            query = query.filter(ExpenseRequest.request_no == args.request_no)
        if not args.include_finished and not args.request_no:
            query = query.filter(ExpenseRequest.status == "pending")
        items += [_expense_item(r) for r in query.order_by(ExpenseRequest.id.desc()).limit(10).all()]

    return items


def _get_approval_status(ctx: ToolContext, args: GetApprovalStatusArgs) -> ToolOutcome:
    items = _query_requests(ctx, args)

    if args.request_no and not items:
        raise ToolExecutionError(
            f"未找到单号 {args.request_no} 对应的申请记录（仅能查询本人提交的单据）。"
        )

    return ToolOutcome(
        ok=True,
        data={
            "ok": True,
            "count": len(items),
            "only_pending": not args.include_finished,
            "requests": items,
        },
    )


TOOLS = [
    Tool(
        name="get_approval_status",
        description=(
            "查询当前登录员工本人的请假/报销申请单及其审批进度。"
            "可按单号精确查询，也可按业务类型列出最近单据；默认只返回审批中的单据。"
            "用户问「我的请假批了吗」「上次报销到哪一步了」时应调用此工具。"
        ),
        args_model=GetApprovalStatusArgs,
        handler=_get_approval_status,
    ),
]