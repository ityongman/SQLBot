# 第 3 章 整体架构

## 3.1 总体架构图

```mermaid
flowchart TB
    subgraph Client["客户端"]
        B1["浏览器 Web UI"]
        B2["第三方页面<br/>嵌入式小助手 iframe"]
        B3["MCP 客户端<br/>MaxKB / n8n / DataEase"]
    end

    subgraph Container["SQLBot 容器"]
        direction TB
        subgraph Port8000[":8000 主应用 main:app"]
            FE["前端静态资源<br/>frontend/dist"]
            MW["中间件栈<br/>CORS → Response → Token → RequestContext"]
            API["REST API 层<br/>/api/v1（apps/*/api）"]
            CHAT["问答任务引擎<br/>LLMService（线程池）"]
            XPACK["sqlbot_xpack<br/>许可/权限/提示词/认证"]
        end
        subgraph Port8001[":8001 main:mcp_app"]
            MCPSRV["FastApiMCP Server<br/>+ /images 静态图"]
        end
        SSR["g2-ssr :3000<br/>Node.js 图表渲染"]
        PG["PostgreSQL :5432<br/>元数据库（可外置）"]
    end

    subgraph External["外部依赖"]
        LLM["LLM API<br/>OpenAI 兼容 / vLLM"]
        BIZDB["业务数据库<br/>MySQL/PG/Oracle/CK/..."]
        REDIS["Redis<br/>可选缓存"]
    end

    B1 --> FE
    B1 --> MW
    B2 --> MW
    B3 --> MCPSRV
    MW --> API
    API --> CHAT
    MCPSRV -.复用同一批接口.-> API
    CHAT --> LLM
    CHAT --> BIZDB
    CHAT --> SSR
    API --> PG
    CHAT --> PG
    API -.-> REDIS
    API --> XPACK
```

**要点解读**：

- **双端口单镜像**：`main:app`（8000，含前端静态资源托管）与 `main:mcp_app`
  （8001，MCP + 图片静态服务）由同一份代码、两个 uvicorn 进程承载，
  见 `start.sh` 与 `backend/main.py` 末尾的 `mcp_app` 定义。
- **MCP 零手写**：`FastApiMCP(app, include_operations=[...])` 自动把
  `mcp_question`、`mcp_start`、`mcp_datasource_list` 等 7 个 operation
  转成 MCP Tool，无需重复定义协议层。
- **g2-ssr 独立进程**：图表 PNG 渲染走 Node.js（canvas 原生依赖），
  主应用以 HTTP POST 方式提交渲染任务（`request_picture`），
  产物落 `/opt/sqlbot/images`，由 8001 端口 `/images` 路由对外提供。

## 3.2 后端分层

后端是典型的"**API 层 → CRUD 层 → 模型层**"结构，外加两个横向层：

```mermaid
flowchart TB
    subgraph L1["接入层"]
        A1["apps/*/api/*.py<br/>FastAPI Router + 权限装饰器 + 审计日志"]
        A2["middleware/auth.py<br/>TokenMiddleware（3 种令牌）"]
        A3["schemas/permission.py<br/>require_permissions + RequestContext"]
    end
    subgraph L2["业务编排层"]
        B1["chat/task/llm.py<br/>LLMService 任务流水线"]
        B2["ai_model/model_factory.py<br/>LLM 工厂"]
        B3["template/*.py<br/>Prompt 模板装配"]
    end
    subgraph L3["领域 CRUD 层"]
        C1["chat/curd、system/crud"]
        C2["datasource/crud<br/>schema 构建/权限过滤"]
        C3["terminology、data_training"]
    end
    subgraph L4["基础设施层"]
        D1["apps/db<br/>连接池/方言/只读校验"]
        D2["common/core<br/>config/db/deps/cache/security"]
        D3["common/utils<br/>分布式锁/embedding 线程/i18n"]
        D4["common/audit<br/>操作日志"]
    end
    subgraph L5["数据层"]
        E1["SQLModel 表模型<br/>+ Alembic 迁移"]
        E2["PostgreSQL 元数据库"]
        E3["业务数据库"]
    end

    A1 --> B1
    A2 --> A1
    A3 --> A1
    B1 --> B2
    B1 --> B3
    B1 --> C1
    B1 --> C2
    B1 --> C3
    C2 --> D1
    B1 --> D1
    C1 --> E1
    C2 --> E1
    E1 --> E2
    D1 --> E3
    B1 --> D2
    C1 --> D4
```

各层职责（以问答链路为例）：

| 层 | 代表代码 | 职责 |
| --- | --- | --- |
| 接入层 | `chat/api/chat.py` | 参数校验（Pydantic）、鉴权、SSE 封装、异常兜底 |
| 编排层 | `chat/task/llm.py` | 多步 LLM 流水线、消息构建、结果解析、持久化埋点 |
| CRUD 层 | `chat/curd/chat.py`（注意目录名是 `curd`） | 会话/记录/日志增删改查 |
| 基础设施 | `apps/db/db.py` | 多方言连接、LRU 连接池、只读 SQL 校验 |
| 数据层 | SQLModel + Alembic | 表结构与迁移（启动自动 upgrade） |

## 3.3 后端模块依赖图

按 `import` 关系整理出的模块依赖（箭头表示"依赖"）：

```mermaid
graph TD
    MAIN["main.py"] --> API_AGG["apps/api.py"]
    MAIN --> SYSMW["system.middleware.auth"]
    MAIN --> SWAGGER["apps/swagger"]
    MAIN --> XPACK["sqlbot_xpack"]
    MAIN --> LOCK["common.utils.distributed_lock"]
    MAIN --> EMBTHREAD["common.utils.embedding_threads"]

    API_AGG --> CHAT["apps/chat"]
    API_AGG --> SYSTEM["apps/system"]
    API_AGG --> DS["apps/datasource"]
    API_AGG --> TERM["apps/terminology"]
    API_AGG --> TRAIN["apps/data_training"]
    API_AGG --> DASH["apps/dashboard"]
    API_AGG --> MCP["apps/mcp"]
    API_AGG --> SETTINGS["apps/settings"]

    CHAT --> AIFAC["apps/ai_model"]
    CHAT --> DBL["apps/db"]
    CHAT --> DS
    CHAT --> TPL["apps/template"]
    CHAT --> TERM
    CHAT --> TRAIN
    CHAT --> SYSTEM
    CHAT --> XPACK

    MCP --> CHAT
    MCP --> DS
    MCP --> SYSTEM

    DS --> DBL
    DS --> XPACK
    SYSTEM --> XPACK

    CHAT --> COMMON["common/*"]
    DS --> COMMON
    SYSTEM --> COMMON
    DBL --> COMMON
    TPL --> DBL

    COMMON --> CFG["common.core.config"]
    COMMON --> CACHE["common.core.sqlbot_cache"]
```

依赖方向的关键约定：

1. `apps/mcp` 复用 `apps/chat` 的 `question_answer_inner`，即 **MCP 与 Web
   共用同一条问答流水线**，只是 `in_chat=False`（输出 Markdown 而非 SSE JSON）；
2. `apps/template` 只依赖 `apps/db/constant.py` 的 `DB` 枚举
   （用 `template_name` 选方言 yaml），不反向依赖业务层；
3. `sqlbot_xpack` 被 chat/system/datasource 依赖，但通过函数级 import 与
   许可开关（`SQLBotLicenseUtil.valid()`）做到"无许可时功能降级"。

## 3.4 前端架构

```mermaid
flowchart LR
    subgraph Frontend["frontend (Vue3 + Vite)"]
        ROUTER["router<br/>静态路由 + 动态路由 + 守卫"]
        STORES["stores(Pinia)<br/>user / assistant / ..."]
        VIEWS["views<br/>chat / dashboard / datasource<br/>training / setting / embedded"]
        APIL["api/*<br/>Axios 封装 + 拦截器"]
        I18N["i18n<br/>zh-CN/zh-TW/en/ko-KR"]
        CHARTS["chat/component/charts<br/>G2 Bar/Column/Line/Pie/Table"]
    end
    AX["axios 实例<br/>X-SQLBOT-TOKEN 注入<br/>401 跳登录"] --> BACKEND["/api/v1"]
    APIL --> AX
    VIEWS --> APIL
    ROUTER --> VIEWS
    VIEWS --> CHARTS
    VIEWS --> I18N
    VIEWS --> STORES
```

- 对话页 `views/chat/index.vue`（约 1500 行）承担 SSE 事件分发：
  按 `type`（`id/question/datasource/sql-result/sql/sql-data/chart-result/chart/finish/error`）
  驱动 UI 状态机；
- 图表渲染统一抽象为 `charts/*.ts`（Bar、Column、Line、Pie、Table），
  与后端图表配置的 `type` 字段一一对应；
- 嵌入式场景（`views/embedded/page.vue`）通过
  `X-SQLBOT-ASSISTANT-TOKEN: Embedded <jwt>` 走小助手鉴权。

## 3.5 运行时进程视图

```mermaid
graph LR
    subgraph 容器内进程
        P1["uvicorn main:app<br/>单 worker"]
        P2["uvicorn main:mcp_app"]
        P3["pm2 → node g2-ssr"]
        P4["postgres"]
    end
    P1 -- exec_sql --> BIZ["业务数据库"]
    P1 -- LLM stream --> LLM["模型供应商"]
    P1 -- POST 渲染 --> P3
    P2 -- 静态 /images --> IMG["/opt/sqlbot/images"]
    P1 -- SQLAlchemy --> P4
```

下一章：[第 4 章 核心业务全流程](./04-core-business-flow.md)
