# 企业办公 Agent（Enterprise Office Agent）

基于 **Function Calling / ReAct** 的企业办公智能体：员工用自然语言即可完成查询假期余额、查询公司制度、提交请假、提交报销、查询审批进度等操作，由大模型自主决策调用哪个工具、按什么顺序调用，并全程受护栏约束。

> 独立项目，Python + FastAPI 实现；不依赖任何其他仓库，可单独运行、单独演示。

---

## 一、核心能力

| 能力 | 说明 |
|---|---|
| 工具编排 | 6 个业务工具由 JSON Schema 自动生成函数签名，模型多轮自主决策（查余额 → 查制度 → 提交单据） |
| 写操作人工确认 | 涉及写库的调用整批挂起，须用户二次确认后才真正执行，拒绝则零脏数据 |
| 全链路护栏 | 函数名白名单、参数双重校验、错误结构化回喂、轮数与墙钟超时、历史裁剪、越权隔离 |
| 业务规则拦截 | 超标准报销在工具层直接业务拦截并回喂原因，模型不重试、改为向用户解释并给建议 |
| 流式输出 | 对话支持 SSE 流式返回，另有单文件聊天页用于可视化演示 |
| 零配置启动 | 默认 SQLite + 首次启动自动建表写入演示数据，`run.bat` 一键起 |

---

## 二、系统架构

```
                       ┌──────────────────────────────┐
  浏览器 / 客户端  →   │  FastAPI  http://127.0.0.1:8002 │
                       └──────────────┬───────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
        api/auth.py             api/chat.py              app/static/index.html
        JWT 登录换 token        /chat /chat/stream(SSE)   极简聊天页
                                /chat/confirm
                                      │
                                ┌─────▼──────┐
                                │ AgentLoop  │  agent/loop.py
                                │  ReAct 主循环 │  轮数上限 / 超时 / 历史裁剪
                                └─────┬──────┘
                                      │
                       ┌──────────────┼──────────────┐
                       │              │              │
                agent/registry.py  agent/executor.py  agent/state.py
                工具注册 + Schema   校验/执行/错误回喂   待确认动作挂起
                自动生成           写操作需确认          (带 TTL 淘汰)
                                      │
        ┌──────────────┬──────────────┼──────────────┬──────────────┐
        │              │              │              │              │
   get_leave_      submit_      get_expense_    submit_      get_approval_    check_
   balance         leave        standard        expense      status           policy
        │              │              │              │              │              │
        └──────────────┴──────────────┴──────┬───────┴──────────────┴──────────────┘
                                            │
                                   SQLAlchemy + SQLite
                         users / leave_balances / leave_requests /
                         expense_requests / approval_records /
                         policies / expense_standards

   LLM：阿里云百炼 qwen-plus（OpenAI 兼容模式，异步流式，累积 content 与 tool_calls）
```

---

## 三、工具清单

| 工具名 | 类型 | 说明 |
|---|---|---|
| `get_leave_balance` | 只读 | 查本人假期余额（年假 / 病假 / 事假 / 调休） |
| `check_policy` | 只读 | 查公司制度（关键词打分；未命中返回 `found=false`，要求模型如实拒答而非编造） |
| `submit_leave` | **写 · 需确认** | 提交请假，含余额校验、审批中单据占用额度校验、审批节点自动路由 |
| `get_expense_standard` | 只读 | 查某类费用单笔上限与规定 |
| `submit_expense` | **写 · 需确认** | 提交报销，超标准在工具层直接业务拦截，金额超阈值自动路由总经理 |
| `get_approval_status` | 只读 | 查本人单据与审批进度（可传单号精确查） |

新增业务模块只需在 `app/tools/__init__.py` 的 `_MODULES` 中追加，无需改动主循环。

---

## 四、护栏清单（本项目的核心工程价值）

| # | 护栏 | 解决的问题 | 实现位置 |
|---|---|---|---|
| 1 | 函数名白名单 | 模型幻觉出不存在的函数 | `agent/executor.py` → `prepare()` |
| 2 | JSON + Pydantic 双重参数校验，错误结构化回喂 | 参数缺失 / 类型错误，让模型自我修正 | `agent/executor.py` → `prepare()` |
| 3 | `max_turns` 轮数上限 + 整轮墙钟超时 | 循环失控、单次请求长时间挂住 | `agent/loop.py` → `_drive()` |
| 4 | 写操作强制人工二次确认（整批挂起） | 误提交请假 / 报销造成脏数据 | `agent/loop.py` + `agent/state.py` |
| 5 | 历史裁剪（默认 30 条，且不以孤立 tool 消息开头） | 上下文膨胀、非法消息序列 | `agent/loop.py` → `_build_messages()` |
| 6 | `user_id` 仅由登录态注入，模型无法指定 | 越权查询他人余额 / 单据 | `app/api/deps.py` → `build_tool_context()` |

---

## 五、快速开始

### 方式一：本地运行（推荐开发调试）

```powershell
# 1. 安装依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 配置密钥（必填 DASHSCOPE_API_KEY）
Copy-Item .env.example .env
# 编辑 .env，至少填写 DASHSCOPE_API_KEY

# 3. 启动
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8002
```

Windows 下也可直接双击 `run.bat`：自动建虚拟环境 → 装依赖 → 起服务 → 打开聊天页。

启动成功日志：

```
数据库就绪，演示账号：demo / demo123456
Agent 已就绪，注册工具 6 个：get_leave_balance、submit_leave、get_expense_standard、submit_expense、get_approval_status、check_policy
```

| 入口 | 地址 |
|---|---|
| 聊天页 | http://127.0.0.1:8002/ |
| 接口文档 | http://127.0.0.1:8002/docs |
| 演示账号 | `demo` / `demo123456` |

### 方式二：Docker 一键部署

```bash
cp .env.example .env     # 填入 DASHSCOPE_API_KEY
docker compose up -d --build
# 打开 http://127.0.0.1:8002/
```

---

## 六、接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/` | 极简聊天页 |
| POST | `/api/v1/auth/login` | 登录换 JWT，body: `{username, password}` |
| GET | `/api/v1/auth/me` | 当前用户 |
| GET | `/api/v1/tools` | 查看模型可见的工具清单（调试用） |
| POST | `/api/v1/chat` | 对话（非流式），body: `{message, conversation_id?}` |
| POST | `/api/v1/chat/stream` | 对话（SSE 流式） |
| POST | `/api/v1/chat/confirm` | 确认 / 拒绝写操作，body: `{conversation_id, action_id, approved}` |
| GET | `/api/v1/chat/{conversation_id}` | 查看会话历史 |
| DELETE | `/api/v1/chat/{conversation_id}` | 清空会话 |

对话响应中的 `status` 有三种取值：

- `completed`：本轮完成，`answer` 为自然语言回答
- `awaiting_confirmation`：命中写操作，`pending` 内含待确认动作摘要，须调 `/chat/confirm` 继续
- `failed`：达到轮数 / 超时等上限而终止

---

## 七、环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./data/agent.db` | 数据库连接串 |
| `DASHSCOPE_API_KEY` | 空 | **必填**，阿里云百炼密钥 |
| `DASHSCOPE_OPENAI_BASE_URL` | 百炼 compatible-mode | OpenAI 兼容地址 |
| `LLM_MODEL` | `qwen-plus` | 对话模型 |
| `LLM_TEMPERATURE` | `0.1` | 低温度以保证工具决策稳定 |
| `AGENT_MAX_TURNS` | `8` | 单轮最多决策轮数 |
| `AGENT_TIMEOUT_SECONDS` | `60` | 单轮总耗时上限 |
| `WRITE_CONFIRMATION_ENABLED` | `true` | 关闭后写操作不再二次确认（**不建议**） |
| `MAX_HISTORY_MESSAGES` | `30` | 送入模型的历史消息条数上限 |
| `AUTH_ENABLED` | `true` | 设 `false` 可免登录调试 |
| `JWT_SECRET_KEY` | `dev-only-change-me` | 生产必须替换 |

---

## 八、目录结构

```
Enterprise-Agent/
├── app/
│   ├── main.py                 FastAPI 入口、lifespan（建表/种子/预热）、统一异常
│   ├── static/index.html       单文件聊天页
│   ├── core/                   config / exceptions / security / llm / utils
│   ├── db/                     database / models / seed
│   ├── agent/                  registry / executor / loop / state / prompts / runtime
│   ├── tools/                  leave / expense / approval / knowledge
│   └── api/                    deps / schemas / auth / chat
├── data/                       SQLite 数据文件（运行期生成，已 gitignore）
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── run.bat                     Windows 一键启动
```

---

## 九、验收用例（可复现）

| # | 输入 | 预期 |
|---|---|---|
| 1 | `我今年还有几天年假？` | 调 `get_leave_balance` → 用自然语言作答，**不出现原始 JSON** |
| 2 | `请假超过几天需要总经理审批？` | 调 `check_policy` → 依据制度条款回答 |
| 3 | `公司对宠物带进办公室有什么规定？` | `found=false` → 如实说明制度库无相关条款，**不编造** |
| 4 | `帮我请下周三到周五的年假，回老家` | 返回 `awaiting_confirmation` + 动作摘要 → `/chat/confirm` 确认后落库并返回单号与审批节点；`approved=false` 则零写入 |
| 5 | `帮我报销 8000 元差旅费，去北京出差` | 查得上限 5000 → 触发业务拦截 → 模型不再重试，改为解释上限并建议拆分 |
| 6 | `我要请假` | 反问假别、起止日期、事由，**不直接调用** `submit_leave` |

---

## 十、说明

- 制度查询工具 `check_policy` 为示例级的轻量关键词打分实现，用于演示「模型依据检索结果作答、检索不到则拒答」的行为，不是完整的 RAG 检索链路。
- 会话状态保存在进程内（带 TTL 淘汰），多副本部署需替换为 Redis 等共享存储。
