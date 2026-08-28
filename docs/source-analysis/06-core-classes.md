# 第 6 章 核心类与数据结构

## 6.1 问答引擎类图

`LLMService` 是运行时中枢，围绕它的类关系如下：

```mermaid
classDiagram
    class LLMService {
        +CoreDatasource ds
        +ChatQuestion chat_question
        +ChatRecord record
        +BaseChatModel llm
        +List sql_message
        +List chart_message
        +List~ChatLog~ generate_sql_logs
        +dict current_logs
        +Future future
        +create()$ LLMService
        +init_messages(session)
        +init_record(session)
        +run_task_async()
        +run_task() Iterator
        +select_datasource(session)
        +generate_sql(session)
        +generate_chart(session)
        +generate_filter(session, sql, tables)
        +check_sql(session, res, operate)
        +check_save_chart(session, res)
        +execute_sql(sql)
        +await_result() Iterator
    }

    class ChatQuestion {
        +int chat_id
        +str question
        +str engine
        +str db_schema
        +str sample_data
        +str terminologies
        +str data_training
        +str custom_prompt
        +str sql
        +lang
        +sql_sys_question(db_type, limit)
        +sql_user_question(time, change_title)
        +chart_sys_question()
        +filter_user_question()
    }

    class ChatRecord {
        +int chat_id
        +str question
        +str sql_answer
        +str sql
        +str data
        +str chart_answer
        +str chart
        +str analysis
        +str predict_data
        +bool finish
        +str error
        +int regenerate_record_id
    }

    class ChatLog {
        +OperationEnum operate
        +int pid
        +list messages
        +str reasoning_content
        +dict token_usage
        +bool error
    }

    class LLMFactory {
        +create_llm(config)$ BaseLLM
        +register_llm(type, cls)$
    }
    class LLMConfig {
        +int model_id
        +str model_type
        +str model_name
        +str api_key
        +str api_base_url
        +dict additional_params
    }
    class CoreDatasource {
        +str name
        +str type
        +str configuration
        +int oid
        +list table_relation
        +str embedding
    }

    LLMService --> ChatQuestion : 持有问题上下文
    LLMService --> ChatRecord : 增量持久化
    LLMService --> ChatLog : 每步埋点
    LLMService --> LLMFactory : 创建 LLM
    LLMFactory --> LLMConfig : 输入
    LLMService --> CoreDatasource : 执行目标
    ChatQuestion --|> AiModelQuestion : 继承
    class AiModelQuestion {
        +prompt 装配方法族
    }
```

说明：`ChatQuestion` 继承自 `AiModelQuestion`，后者承担全部 Prompt
模板装配（`sql_sys_question`、`chart_user_question`、`filter_user_question`
等十余个方法），是"**数据对象兼提示词构建器**"的复合角色。

## 6.2 认证与权限类图

```mermaid
classDiagram
    class TokenMiddleware {
        +dispatch(request, call_next)
        -validateToken(token) Bearer
        -validateAskToken(token) SK-APIKey
        -validateAssistant(token) Assistant/Embedded
    }
    class UserInfoDTO {
        +int id
        +str account
        +int oid
        +bool isAdmin
        +int weight
        +str language
    }
    class AssistantHeader {
        +int id
        +int type
        +str domain
        +str configuration
        +str certificate
        +str request_origin
    }
    class SqlbotPermission {
        +list role
        +str type
        +str keyExpression
    }
    class RequestContext {
        -ContextVar _current_request
        +set_request()$
        +get_request()$
    }

    TokenMiddleware --> UserInfoDTO : request.state.current_user
    TokenMiddleware --> AssistantHeader : request.state.assistant
    RequestContext ..> TokenMiddleware : 中间件写入上下文
    SqlbotPermission ..> RequestContext : 装饰器读取上下文
```

## 6.3 数据模型 ER 图

```mermaid
erDiagram
    SYS_USER ||--o{ SYS_USER_WS : "属于"
    SYS_WORKSPACE ||--o{ SYS_USER_WS : "包含"
    SYS_WORKSPACE ||--o{ CORE_DATASOURCE : "隔离(oid)"
    SYS_WORKSPACE ||--o{ CHAT : "隔离(oid)"
    SYS_WORKSPACE ||--o{ TERMINOLOGY : "隔离(oid)"
    SYS_WORKSPACE ||--o{ DATA_TRAINING : "隔离(oid)"

    CORE_DATASOURCE ||--o{ CORE_TABLE : "包含"
    CORE_TABLE ||--o{ CORE_FIELD : "包含"
    CORE_DATASOURCE ||--o{ DS_PERMISSION : "行列权限"
    DS_PERMISSION }o--o{ DS_RULES : "用户组绑定"

    CHAT ||--o{ CHAT_RECORD : "包含"
    CHAT_RECORD ||--o{ CHAT_LOG : "步骤日志(pid)"
    CHAT_RECORD ||--o| CHAT_RECORD : "regenerate 链"

    AI_MODEL ||--o{ AI_MODEL_WS_MAPPING : "授权到空间"
    SYS_ASSISTANT }o--|| SYS_WORKSPACE : "归属"
    SYS_USER ||--o{ SYS_APIKEY : "持有"

    CHAT {
        bigint id PK
        bigint oid "工作空间ID"
        bigint create_by FK
        str brief "标题"
        str chat_type "chat/datasource"
        bigint datasource FK
        str engine_type
        int origin "0页面 1mcp 2小助手"
    }
    CHAT_RECORD {
        bigint id PK
        bigint chat_id FK
        text question
        text sql_answer "LLM原始输出"
        text sql "最终SQL"
        text data "执行结果JSON"
        text chart "图表配置JSON"
        bool finish
        text error
        bigint regenerate_record_id FK
    }
    CHAT_LOG {
        bigint id PK
        str operate "OperationEnum"
        bigint pid "=chat_record.id"
        jsonb messages "完整对话消息"
        text reasoning_content
        jsonb token_usage
        bool error
    }
    CORE_DATASOURCE {
        bigint id PK
        str name
        str type "DB枚举"
        text configuration "AES加密连接串"
        bigint oid
        jsonb table_relation "X6关系图"
        text embedding "数据源向量"
    }
    CORE_TABLE {
        bigint id PK
        bigint ds_id FK
        bool checked
        text table_name
        text custom_comment "人工注释"
        text embedding "表向量"
    }
    CORE_FIELD {
        bigint id PK
        bigint table_id FK
        bool checked
        text field_name
        str field_type
        text custom_comment
        int field_index
    }
```

（表名以 SQLModel 模型为准：`chat`、`chat_record`、`chat_log`、
`core_datasource`、`core_table`、`core_field`、`sys_user`、`sys_workspace`、
`sys_user_ws`、`sys_assistant`、`sys_apikey`、`ai_model`、
`ai_model_workspace_mapping`；`ds_permission`/`ds_rules` 位于 xpack。）

## 6.4 关键运行时数据结构

### LLM 输出协议（SQL 生成）

```json
{
  "success": true,
  "sql": "SELECT region, SUM(amount) FROM sales GROUP BY region",
  "tables": ["sales"],
  "chart-type": "column",
  "brief": "各区域销售额统计"
}
```

失败时 `success=false` + `message`，由 `check_sql` 抛出
`SingleMessageError` 并推送 `error` 事件。

### 图表配置协议（LLM 输出 → 前端 G2）

```json
{
  "type": "line",            // bar|column|line|pie|table
  "title": "月度销售趋势",
  "axis": {
    "x": {"name": "月份", "value": "month"},
    "y": [{"name": "销售额", "value": "sales"}],
    "series": {"name": "区域", "value": "region"}
  }
}
```

`check_save_chart` 会将所有 `value` 统一转小写（SQL 结果列名归一化），
并兼容 `y` 为对象（旧格式）或数组（多指标）两种形态；
`columns` 结构用于 `type=table`。

### SSE 消息帧

```text
data:{"type":"sql-result","content":"...","reasoning_content":"..."}\n\n
```

所有帧均为 `data:` 前缀 + orjson 序列化 + 双换行，`type` 见 4.4 节协议表。

### chat_log 消息结构

```json
{"type": "human", "content": "...", "sqlbot_system": true}
```

`sqlbot_system=true` 标记系统提示词消息，重建历史上下文时被过滤，
避免提示词随轮次累积（见 `init_messages`）。

## 6.5 状态机视角：一次问答记录的生命周期

```mermaid
stateDiagram-v2
    [*] --> Created: save_question
    Created --> SqlAnswered: save_sql_answer
    SqlAnswered --> SqlSaved: check_save_sql(权限改写后)
    SqlSaved --> DataSaved: save_sql_exec_data
    DataSaved --> ChartSaved: save_chart
    ChartSaved --> Finished: finish_record
    Created --> Failed: save_error_message
    SqlAnswered --> Failed
    SqlSaved --> Failed
    DataSaved --> Failed
    Failed --> Finished: finally 中 finish_record
    Finished --> [*]
```

无论成功或异常，`run_task` 的 `finally` 块都会执行
`finish_record` + `session_maker.remove()`，保证记录状态收敛、
线程级 Session 归还。

下一章：[第 7 章 安全、权限、缓存、扩展机制](./07-security-permission-cache-extension.md)
