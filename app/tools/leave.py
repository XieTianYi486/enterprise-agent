# ============================================================
# 请假相关工具：查余额 / 提交请假
# ============================================================

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.agent.registry import Tool, ToolContext, ToolOutcome
from app.core.exceptions import ToolExecutionError
from app.core.utils import generate_request_no, leave_type_name
from app.db.models import ApprovalRecord, LeaveBalance, LeaveRequest

LeaveType = Literal["annual", "sick", "personal", "compensatory"]


# ----------------------------------------------------------------------
# 1) get_leave_balance —— 查询假期余额（只读）
# ----------------------------------------------------------------------
class GetLeaveBalanceArgs(BaseModel):
    leave_type: Optional[LeaveType] = Field(
        None,
        description="假别：annual=年假, sick=病假, personal=事假, compensatory=调休。不传则返回全部假别。",
    )


def _get_leave_balance(ctx: ToolContext, args: GetLeaveBalanceArgs) -> ToolOutcome:
    query = ctx.db.query(LeaveBalance).filter(LeaveBalance.user_id == ctx.user_id)
    if args.leave_type:
        query = query.filter(LeaveBalance.leave_type == args.leave_type)

    rows = query.all()
    if not rows:
        raise ToolExecutionError("未查询到该假别的余额记录，请联系 HR 确认假期档案。")

    balances = [
        {
            "leave_type": r.leave_type,
            "leave_type_name": leave_type_name(r.leave_type),
            "total_days": r.total_days,
            "used_days": r.used_days,
            "remaining_days": r.remaining_days,
        }
        for r in rows
    ]
    return ToolOutcome(
        ok=True,
        data={"ok": True, "user_name": ctx.user_name, "balances": balances},
    )


# ----------------------------------------------------------------------
# 2) submit_leave —— 提交请假申请（写操作，需确认）
# ----------------------------------------------------------------------
class SubmitLeaveArgs(BaseModel):
    leave_type: LeaveType = Field(..., description="假别：annual=年假, sick=病假, personal=事假, compensatory=调休")
    start_date: str = Field(..., description="开始日期，格式 YYYY-MM-DD")
    end_date: str = Field(..., description="结束日期，格式 YYYY-MM-DD")
    reason: str = Field(..., min_length=2, max_length=200, description="请假事由，需具体说明")

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_date(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except ValueError:
            raise ValueError("日期格式必须为 YYYY-MM-DD，例如 2026-10-10")
        return value


def _approval_step(days: float) -> str:
    """按天数决定审批节点（与公司请假制度一致）。"""
    if days <= 1:
        return "直属主管"
    if days <= 3:
        return "部门经理"
    return "总经理"


def _validate_submit_leave(ctx: ToolContext, args: SubmitLeaveArgs) -> tuple[float, str, float]:
    """请假业务规则校验（只读、无副作用）：日期顺序 + 余额是否够用。

    返回 (days, approval_step, remaining)；校验不通过抛 ToolExecutionError。
    本函数同时被「二次确认前的预检」与「真正执行」复用，保证两处规则一致。
    """
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)

    if end < start:
        raise ToolExecutionError("结束日期不能早于开始日期，请重新确认日期。")

    days = float((end - start).days + 1)  # 按自然日计算（含首尾）

    balance = (
        ctx.db.query(LeaveBalance)
        .filter(LeaveBalance.user_id == ctx.user_id, LeaveBalance.leave_type == args.leave_type)
        .first()
    )
    if balance is None:
        raise ToolExecutionError(f"未找到「{leave_type_name(args.leave_type)}」的余额记录，无法提交。")

    # 已提交但审批中的申请也要占用额度，避免重复申请超额
    pending_days = sum(
        r.days
        for r in ctx.db.query(LeaveRequest)
        .filter(
            LeaveRequest.user_id == ctx.user_id,
            LeaveRequest.leave_type == args.leave_type,
            LeaveRequest.status == "pending",
        )
        .all()
    )

    remaining = balance.remaining_days - pending_days
    if days > remaining:
        raise ToolExecutionError(
            f"{leave_type_name(args.leave_type)}可用余额不足：剩余 {balance.remaining_days} 天，"
            f"其中 {pending_days} 天已被审批中的申请占用，实际可用 {round(remaining, 1)} 天，"
            f"而本次申请需要 {days} 天。请缩短请假天数或更换假别。"
        )

    return days, _approval_step(days), remaining


def _precheck_submit_leave(ctx: ToolContext, args: SubmitLeaveArgs) -> None:
    """二次确认前的业务规则预检：只校验、不写库。"""
    _validate_submit_leave(ctx, args)


def _submit_leave(ctx: ToolContext, args: SubmitLeaveArgs) -> ToolOutcome:
    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    days, step, remaining = _validate_submit_leave(ctx, args)

    request = LeaveRequest(
        request_no=generate_request_no("LV"),
        user_id=ctx.user_id,
        leave_type=args.leave_type,
        start_date=start,
        end_date=end,
        days=days,
        reason=args.reason,
        status="pending",
        current_step=step,
    )
    ctx.db.add(request)
    ctx.db.flush()

    ctx.db.add(
        ApprovalRecord(
            biz_type="leave",
            biz_id=request.id,
            approver_name=ctx.user_name,
            action="submit",
            comment="员工提交申请",
        )
    )
    ctx.db.commit()

    return ToolOutcome(
        ok=True,
        data={
            "ok": True,
            "message": "请假申请已提交成功，等待审批。",
            "request_no": request.request_no,
            "leave_type_name": leave_type_name(args.leave_type),
            "start_date": args.start_date,
            "end_date": args.end_date,
            "days": days,
            "reason": args.reason,
            "status": "审批中",
            "current_step": step,
            "balance_after_approval": round(remaining - days, 1),
        },
    )


def _summarize_submit_leave(args: SubmitLeaveArgs) -> str:
    days = (date.fromisoformat(args.end_date) - date.fromisoformat(args.start_date)).days + 1
    return (
        f"提交{leave_type_name(args.leave_type)}申请："
        f"{args.start_date} 至 {args.end_date}（{days} 天），事由「{args.reason}」"
    )


# ----------------------------------------------------------------------
# 工具注册
# ----------------------------------------------------------------------
TOOLS = [
    Tool(
        name="get_leave_balance",
        description=(
            "查询当前登录员工本人的假期余额（年假/病假/事假/调休的总额、已用、剩余天数）。"
            "在回答任何与「还剩多少假」相关的问题前必须先调用此工具。"
        ),
        args_model=GetLeaveBalanceArgs,
        handler=_get_leave_balance,
    ),
    Tool(
        name="submit_leave",
        description=(
            "为当前登录员工提交一条请假申请。"
            "必须先从用户处问清假别、开始日期、结束日期、事由四项信息才能调用，缺一不可，不得臆造。"
            "天数按自然日（含首尾）计算。此操作会写入系统并进入审批流程，需要用户确认后才真正生效。"
        ),
        args_model=SubmitLeaveArgs,
        handler=_submit_leave,
        is_write=True,
        requires_confirmation=True,
        precheck=_precheck_submit_leave,
        summarize=_summarize_submit_leave,
    ),
]