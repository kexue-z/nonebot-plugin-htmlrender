---
title: 自定义 Backend 指南
description: Backend Protocol、能力声明、注册与 Render 契约
icon: lucide/plug-zap
status: new
tags:
  - Maintainers
  - Architecture
  - Backend
---

# 自定义 Backend 指南

backend 分离的目标不是为了把 Playwright 搬目录，而是把“渲染能力”与“具体驱动”拆开。  
如果后续要接入新 backend，入口从这里开始。

## 先记住的边界

- `Render` 是上层门面，负责默认实例、会话复用、生命周期管理
- `Backend` 是驱动实现，负责 runtime、session、context 的真实创建与关闭
- backend 可以注册，但当前仓库正式主路径只有 Playwright

## `Backend` Protocol 的职责

`backend/base.py` 中的 `Backend` Protocol 约束了一个 backend 至少要提供：

- `startup_steps()`：启动前的异步准备步骤
- `create_runtime()`：创建进程级或连接级资源
- `create_session(runtime, **kwargs)`：基于 runtime 创建可复用会话
- `is_alive(session)`：判断会话是否还能复用
- `get_render_context(session, **kwargs)`：为单次渲染创建上下文

如果 backend 还要支持 HTML / Markdown / template 渲染，就需要满足 `SupportsHtmlRenderBackend`。

## Runtime 与 Session 的语义

- `RenderRuntime` 表示 backend 级资源，例如一个 Playwright 实例或一条远端连接
- `RenderSession` 表示绑定到 runtime 的可复用渲染会话，例如一个 `Browser`
- 两者都必须提供 `_aclose`，因为 `Render` 层会在 shutdown 或重建时统一调用关闭逻辑

责任边界：

- backend 负责正确创建和关闭 runtime / session
- `Render` 负责缓存、复用、失效重建和最终释放

## 能力声明规则

backend 通过 `BackendCapability` 声明自己能提供什么：

- `RENDER_CONTEXT`
- `HTML_RENDER`
- `TEXT_RENDER`
- `MARKDOWN_RENDER`
- `TEMPLATE_RENDER`
- `TEMPLATE_HTML_RENDER`
- `HTML_ELEMENT_CAPTURE`
- `RASTER_RENDER`

这些是 backend-facing building blocks。  
`Render` 层再把它们映射成用户可见的 `RenderCapability`。

规则很简单：

- 只声明你真的实现了的能力
- 不要为了“未来可能支持”而提前声明 capability
- 一旦 capability 声明出来，`Render` 层就会把相应 API 暴露给上层

## 注册与状态查询

backend 注册入口在 `backend/factory.py`：

- `register_backend(...)`
- `BackendAvailability`
- `BackendStatus`
- `build_backend(...)`

推荐方式：

- 在 backend 包导入时完成注册
- 不要等首次调用 `render_*` 时再动态拼装注册逻辑

`BackendAvailability` 用于表达环境是否可用，例如：

- 依赖包未安装
- 浏览器二进制缺失
- 远端连接模式与 engine 配置冲突

`BackendStatus` 是对外可读状态，用于 `list_render_backend_statuses()` 一类 API。

## 错误语义

工厂层错误应保持可诊断：

- 未配置 backend：说明配置缺失
- backend 未注册：说明仓库没有对应实现或注册逻辑没执行
- backend 不可用：说明实现存在，但当前环境不满足运行条件

不要把这些情况折叠成一个笼统的“启动失败”。

## 与 `Render` 层的契约

- `Render` 不直接持有 backend 私有对象类型，只通过 `RenderRuntime` / `RenderSession` 交互
- backend 不感知 NoneBot 生命周期；`on_startup` / `on_shutdown` 是插件入口的职责
- backend 内部可以有自己的 config、models、operations、runtime 拆分，但不应反向依赖 `render.py`

如果一个 backend 需要从 `Render` 默认实例获取上下文，应走显式注册或参数传递，不要通过循环导入偷拿状态。

## 当前仓库里的实现参考

当前唯一正式实现是 `backend/playwright/`，它同时展示了：

- backend 注册
- runtime / session 管理
- context 创建
- HTML family 渲染
- 远程连接与资源解析协同

但这不是要求新 backend 复制 Playwright 的目录数量。  
真正必须保持的是协议、能力声明和依赖方向。
