# ============================================================
# 演示数据：首次启动时写入，保证 Agent 一启动就有数据可查
# ============================================================

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.models import (
    ApprovalRecord,
    ExpenseRequest,
    ExpenseStandard,
    LeaveBalance,
    LeaveRequest,
    Policy,
    User,
)


def seed_demo_data(db: Session) -> None:
    """幂等写入演示数据：已有用户则直接返回。"""
    if db.query(User).count() > 0:
        return

    # ---------- 员工 ----------
    demo = User(
        username=settings.DEMO_USERNAME,
        password_hash=hash_password(settings.DEMO_PASSWORD),
        name="谢天逸",
        dept_name="技术研发部",
        position="后端开发工程师",
        manager_name="李明",
    )
    db.add(demo)
    db.flush()  # 拿到 demo.id

    # ---------- 假期余额 ----------
    balances = [
        LeaveBalance(user_id=demo.id, leave_type="annual", total_days=10.0, used_days=3.5),
        LeaveBalance(user_id=demo.id, leave_type="sick", total_days=10.0, used_days=1.0),
        LeaveBalance(user_id=demo.id, leave_type="personal", total_days=5.0, used_days=0.0),
        LeaveBalance(user_id=demo.id, leave_type="compensatory", total_days=3.0, used_days=0.0),
    ]
    db.add_all(balances)

    # ---------- 历史请假单 ----------
    today = date.today()
    db.add(
        LeaveRequest(
            request_no="LV20260901093001101",
            user_id=demo.id,
            leave_type="annual",
            start_date=today - timedelta(days=30),
            end_date=today - timedelta(days=28),
            days=3.0,
            reason="家中有事，回家探亲",
            status="approved",
            current_step="已归档",
        )
    )
    # ---------- 审批中的请假单 ----------
    db.add(
        LeaveRequest(
            request_no="LV20261001101502202",
            user_id=demo.id,
            leave_type="sick",
            start_date=today - timedelta(days=3),
            end_date=today - timedelta(days=3),
            days=1.0,
            reason="感冒发烧，就医休息",
            status="pending",
            current_step="直属主管",
        )
    )

    # ---------- 历史报销单 ----------
    db.add(
        ExpenseRequest(
            request_no="EX20260910143001303",
            user_id=demo.id,
            category="travel",
            amount=1860.0,
            reason="赴上海参加行业技术交流会，含往返高铁与住宿",
            invoice_count=4,
            status="approved",
            current_step="已归档",
        )
    )
    db.add(
        ExpenseRequest(
            request_no="EX20261005112002404",
            user_id=demo.id,
            category="meal",
            amount=320.0,
            reason="项目上线通宵加班餐费",
            invoice_count=2,
            status="pending",
            current_step="直属主管",
        )
    )

    # ---------- 审批流水 ----------
    db.add_all(
        [
            ApprovalRecord(
                biz_type="leave",
                biz_id=1,
                approver_name=demo.manager_name,
                action="approve",
                comment="同意，注意提前交接工作",
            ),
            ApprovalRecord(
                biz_type="leave",
                biz_id=2,
                approver_name=demo.manager_name,
                action="submit",
                comment="已提交，等待审批",
            ),
            ApprovalRecord(
                biz_type="expense",
                biz_id=1,
                approver_name="财务部-王芳",
                action="approve",
                comment="票据齐全，予以报销",
            ),
        ]
    )

    # ---------- 制度库 ----------
    db.add_all(
        [
            Policy(
                title="员工请假管理制度",
                category="请假",
                keywords="请假 年假 病假 事假 调休 天数 审批 提前",
                content=(
                    "员工请假须提前在 OA 系统提交申请：请假 1 天以内由直属主管审批；"
                    "1 天以上 3 天（含）以内由部门经理审批；超过 3 天须报总经理终审。"
                    "病假需提供二级以上医院出具的病假证明。事假为无薪假，全年累计不超过 15 天。"
                    "调休须在加班发生后 3 个月内使用完毕，过期作废。"
                ),
            ),
            Policy(
                title="差旅费用报销标准",
                category="报销",
                keywords="报销 差旅 住宿 交通 补贴 标准 上限 发票",
                content=(
                    "出差住宿费标准：一线城市每人每晚不超过 500 元，其他城市不超过 350 元。"
                    "市内交通费实报实销；长途交通优先选择高铁二等座。"
                    "出差补贴每人每天 100 元。报销须在出差结束后 15 个工作日内提交，"
                    "并提供合规发票，发票抬头须为公司全称。"
                ),
            ),
            Policy(
                title="费用报销审批流程",
                category="报销",
                keywords="报销 审批 流程 金额 总经理 财务 打款",
                content=(
                    "单笔报销金额 5000 元（含）以内，由部门经理审批后交财务复核；"
                    "超过 5000 元须经总经理终审。财务复核通过后于每月 15 日、30 日统一打款。"
                    "报销单据须注明事由、金额与附件张数，虚报冒领将按公司奖惩制度处理。"
                ),
            ),
            Policy(
                title="考勤与加班管理规定",
                category="考勤",
                keywords="考勤 打卡 加班 迟到 调休 弹性 工时",
                content=(
                    "标准工作时间为每周一至周五 9:00-18:00，午休 12:00-13:00。"
                    "迟到超过 30 分钟按事假半天计。加班须提前申请并经主管批准，"
                    "工作日加班满 2 小时可申请调休 0.5 天，法定节假日加班按 3 倍计算调休。"
                ),
            ),
            Policy(
                title="员工福利与年假规定",
                category="福利",
                keywords="年假 福利 工龄 体检 旅游 补充医疗",
                content=(
                    "入职满 1 年享受 5 天带薪年假，满 3 年 10 天，满 5 年 15 天。"
                    "年假须在当年度内使用完毕，经部门经理批准可跨年顺延至次年 3 月 31 日。"
                    "公司每年为员工提供一次免费体检与一次部门团建活动。"
                ),
            ),
        ]
    )

    # ---------- 费用标准 ----------
    db.add_all(
        [
            ExpenseStandard(
                category="travel",
                category_name="差旅费",
                limit_amount=5000.0,
                description="单笔上限 5000 元。住宿：一线城市 ≤500 元/晚，其他城市 ≤350 元/晚；出差补贴 100 元/天。",
            ),
            ExpenseStandard(
                category="meal",
                category_name="餐饮费",
                limit_amount=2000.0,
                description="单笔上限 2000 元。因公餐饮 ≤150 元/人/餐；加班餐费凭加班审批单报销。",
            ),
            ExpenseStandard(
                category="office",
                category_name="办公用品",
                limit_amount=2000.0,
                description="单笔上限 2000 元，超出须走采购流程。",
            ),
            ExpenseStandard(
                category="transport",
                category_name="交通费",
                limit_amount=3000.0,
                description="单笔上限 3000 元。市内因公交通实报实销，长途交通优先高铁二等座。",
            ),
        ]
    )

    db.commit()