# ============================================================
# ORM 模型
# 表结构对齐人事/OA 基础场景，供 Agent 工具读写
# ============================================================

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def now() -> datetime:
    return datetime.now()


class User(Base):
    """员工账号。Agent 的工具上下文（user_id）由此注入，不由模型决定。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(64))
    dept_name: Mapped[str] = mapped_column(String(64), default="")
    position: Mapped[str] = mapped_column(String(64), default="")
    manager_name: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class LeaveBalance(Base):
    """假期余额：一个员工一种假别一条记录。"""

    __tablename__ = "leave_balances"
    __table_args__ = (
        UniqueConstraint("user_id", "leave_type", name="uq_user_leave_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # annual=年假 sick=病假 personal=事假 compensatory=调休
    leave_type: Mapped[str] = mapped_column(String(32), index=True)
    total_days: Mapped[float] = mapped_column(Float, default=0.0)
    used_days: Mapped[float] = mapped_column(Float, default=0.0)

    @property
    def remaining_days(self) -> float:
        return round(self.total_days - self.used_days, 1)


class LeaveRequest(Base):
    """请假申请单。"""

    __tablename__ = "leave_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    leave_type: Mapped[str] = mapped_column(String(32))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    days: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="")
    # pending=审批中 approved=已通过 rejected=已驳回
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    current_step: Mapped[str] = mapped_column(String(32), default="直属主管")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ExpenseRequest(Base):
    """费用报销申请单。"""

    __tablename__ = "expense_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    # travel=差旅 meal=餐饮 office=办公用品 transport=交通
    category: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text, default="")
    invoice_count: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    current_step: Mapped[str] = mapped_column(String(32), default="直属主管")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class ApprovalRecord(Base):
    """审批流水。biz_type + biz_id 构成多态关联，请假/报销共用一张流水表。"""

    __tablename__ = "approval_records"
    __table_args__ = (
        Index("ix_approval_biz", "biz_type", "biz_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    biz_type: Mapped[str] = mapped_column(String(16))  # leave | expense
    biz_id: Mapped[int] = mapped_column(Integer)
    approver_name: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(16))  # submit | approve | reject
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Policy(Base):
    """公司制度片段（check_policy 工具的数据源）。"""

    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)
    keywords: Mapped[str] = mapped_column(String(256), default="")  # 空格分隔，用于简单召回
    content: Mapped[str] = mapped_column(Text)


class ExpenseStandard(Base):
    """费用标准（get_expense_standard 工具的数据源）。"""

    __tablename__ = "expense_standards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    category_name: Mapped[str] = mapped_column(String(32))
    limit_amount: Mapped[float] = mapped_column(Float)
    description: Mapped[str] = mapped_column(Text, default="")