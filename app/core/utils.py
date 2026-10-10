# ============================================================
# 通用小工具
# ============================================================

import random
from datetime import datetime


def generate_request_no(prefix: str) -> str:
    """
    生成业务单号，例如 LV20261008153022123。

    采用「时间戳 + 随机数」而非数据库自增，避免并发下重号。
    """
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{prefix}{ts}{random.randint(100, 999)}"


# 假别编码 -> 中文名
LEAVE_TYPE_NAMES = {
    "annual": "年假",
    "sick": "病假",
    "personal": "事假",
    "compensatory": "调休",
}

# 报销类别编码 -> 中文名
EXPENSE_CATEGORY_NAMES = {
    "travel": "差旅费",
    "meal": "餐饮费",
    "office": "办公用品",
    "transport": "交通费",
}


def leave_type_name(code: str) -> str:
    return LEAVE_TYPE_NAMES.get(code, code)


def expense_category_name(code: str) -> str:
    return EXPENSE_CATEGORY_NAMES.get(code, code)