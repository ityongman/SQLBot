# 第 5 章 核心模块源码逐块解析

按"backend → frontend → g2-ssr → installer"顺序，逐模块拆解。
每节给出：**文件定位 → 关键代码走读 → 设计要点**。

---

## 5.1 backend/main.py —— 应用装配中心

职责：生命周期、中间件、OpenAPI i18n、MCP 挂载。

```python
app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan, ...)

mcp_app = FastAPI()                        # 独立的 MCP 进程入口
mcp_app.mount("/images", StaticFiles(...)) # MCP 图片静态服务

mcp = FastApiMCP(app, include_operations=[
    "mcp_datasource_list", "get_model_list", "mcp_question",
    "mcp_start", "mcp_assistant", "mcp_ws_list", "access_token"], ...)
mcp.mount(mcp_app)

app.add_middleware(TokenMiddleware)        # 鉴权
app.add_middleware(ResponseMiddleware)     # 统一响应包装
app.add_middleware(RequestContextMiddleware)      # 权限上下文
app.include_router(api_router, prefix=settings.API_V1_STR)
```

设计要点：

1. **中间件顺序**：Starlette 中间件后注册先执行，实际执行顺序为
   RequestContext → Response → Token → CORS；
2. **OpenAPI 多语言**：`generate_openapi_for_lang` 按 `?lang=` 生成并缓存
   不同语言的 schema，所有 summary 用 `PLACEHOLDER_xxx` 占位再替换
   （`apps/swagger/i18n.py`），实现一份代码四语言文档；
3. **MCP 与主应用同源**：`FastApiMCP(app, ...)` 从主应用路由表生成工具，
   `mcp_app` 只是独立端口承载，业务实现仍在 `apps/mcp/mcp.py`。

## 5.2 apps/chat —— Text2SQL 核心

### 5.2.1 api/chat.py（接入层）

| 端点 | 方法 | 功能 |
| --- | --- | --- |
| `/chat/list`、`/chat/{id}` | GET | 会话列表、会话详情（含记录） |
| `/chat/start`、`/chat/assistant/start` | POST | 创建会话（后者供小助手） |
| `/chat/question` | POST | 提问主入口（SSE） |
| `/chat/record/{id}/data`、`data_live` | GET | 图表数据（`data_live` 重新执行 SQL） |
| `/chat/record/{id}/{analysis\|predict}` | POST | 分析/预测 |
| `/chat/record/{id}/excel/export/{chat_id}` | GET | Excel 导出（pandas + xlsxwriter） |
| `/chat/recommend_questions/{record_id}` | POST | 推荐问题（SSE） |

值得注意的模式：所有同步 CRUD 均用 `asyncio.to_thread(inner)` 包裹，
避免阻塞事件循环；权限用装饰器声明：

```python
@router.post("/start")
@require_permissions(permission=SqlbotPermission(
    type='ds', keyExpression="create_chat_obj.datasource"))
@system_log(LogConfig(operation_type=OperationType.CREATE, ...))
async def start_chat(...):
```

### 5.2.2 models/chat_model.py（领域模型）

- `Chat` / `ChatRecord` / `ChatLog`：三张核心表（SQLModel table 模型）；
- `OperationEnum`：14 种操作步骤枚举（GENERATE_SQL、CHOOSE_TABLE、
  FILTER_TERMS、EXECUTE_SQL、GENERATE_PICTURE...），是 chat_log 的
  `operate` 字段取值，也是前端"执行详情"步骤列表的来源；
- `AiModelQuestion`：**Prompt 装配器**。`sql_sys_question()` 把
  方言模板 + 基础模板拼装成 system/rules/schema/terminologies/
  data_training/custom_prompt 六段；`sql_user_question()` 注入当前时间、
  上次错误信息、语言等运行时变量；
- `ChatFinishStep`：MCP 可指定"只到 SQL / 只到数据 / 到图表"三档终止。

### 5.2.3 task/llm.py（任务引擎）

全文件约 1970 行，是系统心脏。结构：

| 成员/方法 | 作用 |
| --- | --- |
| `LLMService.__init__` | 校验会话归属、加载数据源（含小助手外部数据源）、创建 LLM 实例、注入上次 SQL 执行错误 |
| `LLMService.create`（classmethod） | 先解析模型：小助手自定义模型 → 工作空间模型 → 系统默认模型；再读参数配置（`chat.sqlbot_name`、`chat.limit_rows`、`chat.context_record_count`） |
| `init_messages` | 构建 SQL/图表两套消息列表（含历史轮次） |
| `select_datasource` / `generate_sql` / `generate_chart` | 三类 LLM 调用，均带 `start_log`/`end_log` 埋点 |
| `generate_filter` / `generate_assistant_dynamic_sql` | 行权限改写 / 动态数据源子查询替换 |
| `check_sql` / `check_save_chart` | LLM 输出解析与校验 |
| `run_task` | 主流水线（见第 4 章流程图） |
| `await_result` + `pop_chunk` | 线程池生产者 / SSE 消费者桥接 |
| `process_stream` | LangChain chunk → `{content, reasoning_content}`，兼容 `additional_kwargs.reasoning_content` 与 `<think>` 标签解析 |
| `request_picture` | 调 g2-ssr 出图 |

**生产者-消费者桥接**是本章关键代码：

```python
def run_task_async(self, ...):
    self.future = executor.submit(self.run_task_cache, ...)  # 后台线程生产

def run_task_cache(self, ...):
    for chunk in self.run_task(...):
        self.chunk_list.append(chunk)      # 入队

def await_result(self):                    # 主协程消费
    while self.is_running():
        while (chunk := self.pop_chunk()) is not None:
            yield chunk
    ...
```

`StreamingResponse(llm_service.await_result())` 使 HTTP 响应在任务
结束前保持打开，chunk 通过 `list` 队列在两个执行体间传递。

## 5.3 apps/template + templates/ —— Prompt 模板体系

- `templates/template.yaml`：基础模板，键包括 `sql`（system/rules/
  user/regenerate_hint...）、`chart`、`guess`、`analysis`、`predict`、
  `datasource`、`permissions`、`dynamic_sql`、`terminology`、`data_training`；
- `templates/sql_examples/*.yaml`：**按数据库方言**提供的规则与示例
  （`PostgreSQL.yaml`、`MySQL.yaml`、`Oracle.yaml`、`ClickHouse.yaml`、
  `AWS_Redshift.yaml`、`DM.yaml`、`Kingbase.yaml`、`Doris.yaml`、
  `StarRocks.yaml`、`Microsoft_SQL_Server.yaml`、`Elasticsearch.yaml`、`Hive.yaml`），
  文件名即 `DB` 枚举的 `template_name`；
- `apps/template/template.py`：`@cache` 缓存 yaml 解析结果；
  `get_sql_template(db_type)` 找不到方言文件时**回退到 PostgreSQL 模板**
  （`DB.get_db(db_type, default_if_none=True)`）。

## 5.4 apps/datasource —— 数据源与 Schema 构建

### 模型

`CoreDatasource`（连接配置 AES 加密存 `configuration`）、
`CoreTable`（checked 勾选、`custom_comment` 人工注释、`embedding` 向量）、
`CoreField`（同上）。

### 关键函数走读

`get_table_schema(session, current_user, ds, question)`（crud/datasource.py）：

1. `get_table_obj_by_ds`：取数据源下 `checked=True` 的表与字段，
   并对普通用户做**列权限过滤**（`get_column_permission_fields`）；
2. 拼 Schema 文本：`# Table: db.table, 表注释\n[(col:type, 注释), ...]`；
3. `calc_table_embedding`：表向量与问题向量余弦相似度排序，取 Top10；
4. 补全**表关系**：`ds.table_relation` 中 X6 图数据（edge）涉及但未入选的
   表被补进 schema，并输出 `【Foreign keys】tableA.colA=tableB.colB`。

`sync_table`：创建/更新数据源时同步表与字段元数据，
删除未勾选记录，并触发 `run_save_table_embeddings` /
`run_save_ds_embeddings` 异步向量化。

`get_tables_sample_data`：每张表取 3 行样例（长字符串截断 100 字符），
注入 Prompt 帮助模型理解数据形态。

## 5.5 apps/db —— 多数据库执行层

### DB 枚举（constant.py）

每种数据库登记：类型码、展示名、标识符前后缀（`` ` ``/`"`/`[]`）、
连接方式（`sqlalchemy` / `py_driver`）、模板名、非法参数黑名单。

| 连接方式 | 数据库 |
| --- | --- |
| sqlalchemy | excel、ck、sqlServer、mysql、oracle、pg |
| py_driver（原生驱动） | redshift、dm、doris、es、kingbase、starrocks、hive |

### db.py 关键组件

- `get_engine` / `get_driver_connection`：按类型建连；
- `ConnectionPoolManager` / `DriverConnectionPoolManager`：
  **LRU 连接池管理器**（各 max 500），`OrderedDict + Lock`，
  数据源更新/删除时 `remove_pool` 主动清理；
- `exec_sql`：先去尾分号 → `check_sql_read` 只读校验 →
  方言执行 → `convert_value` 类型归一化（Decimal/日期/二进制等）；
- `check_sql_read`（安全核心，见第 7 章）；
- `get_sqlglot_dialect`：类型码 → sqlglot 方言映射，供解析使用。

### db_sql.py —— 元数据 SQL 字典

`get_version_sql` / `get_table_sql` / `get_field_sql` 为每种数据库
编写 information_schema / pg_catalog / ALL_TABLES 等查询，
处理了 ClickHouse 版本差异（22 以下无 comment 列）、
SQL Server `sys.extended_properties` 注释关联、Oracle 表/视图/物化视图
UNION 等方言细节。

## 5.6 apps/ai_model —— LLM 接入

`model_factory.py`：

```python
class LLMFactory:
    _llm_types = {"openai": OpenAILLM, "tongyi": OpenAILLM,
                  "vllm": OpenAIvLLM, "azure": OpenAIAzureLLM}

    @classmethod
    @lru_cache(maxsize=32)
    def create_llm(cls, config: LLMConfig) -> BaseLLM: ...

    @classmethod
    def register_llm(cls, model_type, llm_class): ...   # 扩展点
```

- `get_default_config`：优先小助手指定模型 → 否则 `default_model=True`；
  API Key/域名**落库时 AES 加密**，读取时 `sqlbot_decrypt`（若已是明文
  http 开头则跳过）；
- `protocol=1` → openai 兼容，否则 vllm；
- `embedding.py` 的 `EmbeddingModelCache` 持有本地 sentence-transformers
  模型（`LOCAL_MODEL_PATH=/opt/sqlbot/models`），供 RAG 检索使用。

## 5.7 apps/system —— 用户/工作空间/小助手

| 子模块 | 内容 |
| --- | --- |
| `api/login.py` | 登录、token 签发 |
| `middleware/auth.py` | `TokenMiddleware`：Bearer / SK / Assistant / Embedded 四类令牌（第 7 章详述） |
| `schemas/permission.py` | `require_permissions` 装饰器 + `RequestContext`（ContextVar 保存当前 Request） |
| `crud/user.py` | 用户 CRUD、`authenticate`（MD5+盐 校验） |
| `crud/workspace.py`、`crud/user.py user_ws_list` | 工作空间与用户-空间权重（weight=1 空间管理员） |
| `crud/assistant.py` | 小助手 CRUD、`AssistantOutDs`（外部数据源 API 客户端）、动态 CORS |
| `crud/aimodel_manage.py` | 模型增删改 + 密钥加密迁移 |
| `crud/parameter_manage.py` | 系统参数（`chat.limit_rows` 等运行参数） |
| `crud/system_variable.py` | 系统变量（供 SQL 中 `${var}` 绑定） |

`AssistantModel.type` 语义（由 `get_assistant_ds`、`dynamic_ds_types=[1,3]`、
`type==4` 等分支归纳）：

| type | 场景 | 数据源来源 |
| --- | --- | --- |
| 0 / 2 | 内嵌页面，指定工作空间数据源 | `configuration.oid` 指定空间的数据源（可配 public_list） |
| 1 / 3 | 第三方系统对接 | 第三方数据源 API 动态下发（`AssistantOutDs`），支持子查询/行规则 |
| 4 | 页面嵌入（Embedded Token） | 同 0，走 Embedded 令牌 |

## 5.8 apps/mcp —— MCP 业务接口

`mcp.py` 提供 7 个 operation（由 FastApiMCP 暴露为 MCP Tool）：

- `access_token` / `mcp_start`：账密或 token 换取 access_token 并创建会话；
- `mcp_ws_list` / `mcp_ds_list`：列工作空间、数据源（脱敏，
  剔除 `configuration`、`embedding` 等敏感字段）；
- `mcp_question`：核心提问工具，内部直接调 `question_answer_inner`
  （`in_chat=False`），输出 Markdown 或 JSON；
- `mcp_assistant`：传入第三方数据接口 URL + 凭证，构造临时
  type=1 小助手进行问数（`finish_step=QUERY_DATA`）。

## 5.9 common —— 横切设施

| 组件 | 文件 | 说明 |
| --- | --- | --- |
| 配置 | `core/config.py` | pydantic-settings，全部环境变量化（第 2 章已列关键项） |
| 依赖注入 | `core/deps.py` | `SessionDep` / `CurrentUser` / `CurrentAssistant` / `Trans`（i18n） |
| 缓存 | `core/sqlbot_cache.py` | 封装 fastapi-cache，`@cache`/`@clear_cache` 支持 `keyExpression`（`args[0]`、`user.oid` 属性路径）自动构建 key |
| 响应 | `core/response_middleware.py` | 统一 `{code,data,message}` 包装与全局异常处理 |
| 审计 | `audit/schemas/logger_decorator.py` | `@system_log(LogConfig(...))` 从入参/返回值表达式提取资源 ID 写操作日志 |
| 分布式锁 | `utils/distributed_lock.py` | `SingleWorkerGuard.once/release`，保证单实例执行启动任务 |
| 向量线程 | `utils/embedding_threads.py` | 后台线程池做 embedding 回填与增量计算 |
| i18n | `utils/locale.py` + `locales/*.json` | 四语言，`Trans` 依赖注入 |
| 错误 | `error.py` | `SingleMessageError`（直接展示给用户）、`SQLBotDBError`、`SQLBotDBConnectionError`、`ParseSQLResultError` |

## 5.10 frontend —— Vue3 前端

```text
src/
├── main.ts / App.vue          # 入口
├── router/                    # index.ts 静态路由 + dynamic.ts 动态路由 + watch.ts 守卫
├── stores/                    # user、assistant 等 Pinia store
├── utils/request.ts           # Axios 实例：token 注入、401 处理、
│                              #   小助手模式自动加 Assistant/Embedded 前缀
├── api/                       # 19 个后端模块封装（chat.ts 含 SSE 处理）
├── views/
│   ├── chat/                  # 对话：index.vue 主控 + answer/* + component/charts/*
│   │   └── execution-component/* # "执行详情"各步骤面板（对应 OperationEnum）
│   ├── dashboard/             # 仪表板画布（X6/拖拽/预览）
│   ├── datasource/            # 数据源管理、表字段注释、表关系(X6)
│   ├── training/ terminology/ # 数据训练、术语库
│   ├── setting/               # 模型/参数/用户/工作空间/小助手/权限
│   └── embedded/page.vue      # 嵌入式小助手容器
└── i18n/                      # zh-CN / zh-TW / en / ko-KR
```

要点：

- `views/chat/index.vue` 用 `fetch + ReadableStream` 消费 SSE，
  按 `type` 分发到消息列表（`ChatListContainer` / `ChatRow` / `ChartBlock`）；
- 图表配置 → G2：`component/charts/{Bar,Column,Line,Pie,Table}.ts`，
  统一入口 `ChartComponent.vue`，`utils.ts` 做数据透视（把后端
  `axis{x,y,series}` 转成 G2 所需结构）；
- `ExecutionDetails.vue` + `execution-component/*` 展示 `chat_log`
  各步骤的输入输出与 Token 消耗，是排障利器。

## 5.11 g2-ssr —— 图表服务端渲染

```text
g2-ssr/
├── app.js             # Express/HTTP 服务，接收 {path,type,data,axis}
├── charts/            # bar/column/line/pie 四种图的 G2 渲染逻辑 + utils.js
├── ecosystem.config.js# pm2 配置
└── Arial_Unicode.ttf  # 中文字体（复制到系统字体目录）
```

工作流：后端 `request_picture` POST 图表配置 → node-canvas 离屏渲染 →
PNG 写入 `path`（`/opt/sqlbot/images/c_{chat_id}_r_{record_id}`）→
前端/Agent 通过 `SERVER_IMAGE_HOST + c_x_r_y.png` 访问。

## 5.12 installer —— 部署套件

| 文件 | 作用 |
| --- | --- |
| `install.sh` | 主安装脚本（环境检查 → docker 安装 → 镜像加载 → compose 启动） |
| `install.conf` | 用户可改配置（端口/密钥/外部库/CORS/缓存） |
| `uninstall.sh` | 卸载（可选保留数据） |
| `sctl` | 安装后的服务管理命令 |
| `sqlbot/docker-compose.yml` | 渲染后的编排文件（templates/ 内为模板） |

下一章：[第 6 章 核心类与数据结构](./06-core-classes.md)
