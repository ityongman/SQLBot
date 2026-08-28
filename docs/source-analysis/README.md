# 《SQLBot 源码深度阅读文档》

> 基于 GitHub 仓库 [dataease/SQLBot](https://github.com/dataease/SQLBot) 真实源码编写，
> 面向希望深入理解 SQLBot 架构、核心链路与二次开发方式的工程师。
> 文中所有类名、函数名、文件路径均来自仓库实际代码，可对照源码阅读。

## 阅读路线

| 章节 | 文件 | 内容概要 |
| --- | --- | --- |
| 第 1 章 | [01-project-overview.md](./01-project-overview.md) | 项目总览：定位、核心能力、技术栈、仓库目录结构 |
| 第 2 章 | [02-deployment-guide.md](./02-deployment-guide.md) | 快速部署与启动流程：安装、配置、启动、访问 |
| 第 3 章 | [03-architecture.md](./03-architecture.md) | 整体架构：架构图 + 分层说明 + 模块依赖图 |
| 第 4 章 | [04-core-business-flow.md](./04-core-business-flow.md) | 核心业务全流程：文本转 SQL 流程图 + 请求时序图 |
| 第 5 章 | [05-module-analysis.md](./05-module-analysis.md) | 核心模块源码逐块解析（backend / frontend / installer / g2-ssr） |
| 第 6 章 | [06-core-classes.md](./06-core-classes.md) | 核心类与数据结构（UML 简图） |
| 第 7 章 | [07-security-permission-cache-extension.md](./07-security-permission-cache-extension.md) | 安全、权限、缓存、扩展机制 |
| 第 8 章 | [08-pitfalls-and-key-logic.md](./08-pitfalls-and-key-logic.md) | 源码难点、关键逻辑、坑点解析 |
| 第 9 章 | [09-secondary-development.md](./09-secondary-development.md) | 二次开发与集成指南 |
| 第 10 章 | [10-summary-and-suggestions.md](./10-summary-and-suggestions.md) | 总结与优化建议 |

## 建议阅读方式

1. **快速了解**：第 1、3 章，10 分钟建立整体认知；
2. **核心链路**：第 4、5 章，对照 `backend/apps/chat/task/llm.py` 阅读效果最佳；
3. **动手改造**：第 7、9 章，理解权限/扩展点后再动手；
4. **避坑**：第 8 章，均为源码中真实存在的设计细节与潜在陷阱。

## 关键入口文件速查

| 关注点 | 入口文件 |
| --- | --- |
| 应用启动/生命周期 | `backend/main.py` |
| 路由聚合 | `backend/apps/api.py` |
| 问答 API 层 | `backend/apps/chat/api/chat.py` |
| Text2SQL 任务引擎 | `backend/apps/chat/task/llm.py` |
| Prompt 模板 | `backend/templates/template.yaml`、`backend/templates/sql_examples/*.yaml` |
| 数据源与 Schema 构建 | `backend/apps/datasource/crud/datasource.py` |
| 多数据库执行层 | `backend/apps/db/db.py`、`backend/apps/db/db_sql.py` |
| 认证中间件 | `backend/apps/system/middleware/auth.py` |
| 权限装饰器 | `backend/apps/system/schemas/permission.py` |
| MCP 服务 | `backend/apps/mcp/mcp.py` |
| 前端对话页 | `frontend/src/views/chat/index.vue` |
| 部署脚本 | `installer/install.sh`、`Dockerfile`、`start.sh` |
| 图表 SSR 渲染 | `g2-ssr/app.js` |
