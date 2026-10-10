# ============================================================
# 企业办公 Agent —— 镜像构建
# 多阶段非必需：本项目纯 Python，单阶段即可
# ============================================================
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Shanghai

WORKDIR /app

# 先装依赖，代码改动时可复用镜像层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple

# 再拷业务代码（含 app/static 单文件聊天页）
COPY app ./app

# SQLite 数据目录；compose 会将其挂载到宿主机以便持久化演示数据
RUN mkdir -p /app/data

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8002/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
