---
title: 分层架构
description: 模块职责与依赖方向
icon: lucide/layers-3
status: new
tags:
  - Maintainers
  - Architecture
---

# 分层架构

## 依赖方向

`__init__/render` -> `backend` -> `backend.playwright.*` -> `resources`

!!! info "约束"
    目录拆分只是开始，关键是依赖方向不能反转。

## 五层语义

由上至下：

1. **Render（渲染层）**：面向用户的最高层接口，例如 `render_html`、`render_template`。对 `Backend` 做抽象封装，负责会话复用与默认实例管理。
2. **Backend（后端层）**：具体驱动实现（当前为 Playwright）。负责 `Runtime` 与 `Session` 的创建、销毁、健康检查。
3. **Runtime（运行时）**：一次驱动实例化的产物，对应一个 Playwright 进程或一条远端连接。
4. **Session（会话）**：建立在 `Runtime` 之上的渲染环境。Playwright 后端中通常对应一个 `Browser` 实例。
5. **Context（上下文）**：单次渲染容器。Playwright 后端中对应 `BrowserContext` + `Page`，由 `operations` 模块在每次渲染时按需创建并退出释放。

层次约束：
- 上层只能透过下层暴露的接口操作下层资源，不直接持有更下层对象。
- `Render` 不感知 Playwright 细节；`Backend` 不感知 NoneBot 生命周期。
- 资源解析（`resources/`）作为旁路被 `operations` 调用，不参与渲染主链路的依赖反转。

## 架构图

```mermaid
flowchart TD
    A["nonebot_plugin_htmlrender/__init__.py<br/>插件入口/导出 API"] --> B["render.py<br/>默认实例/生命周期"]
    B --> C["backend/base.py + backend/factory.py<br/>后端抽象与注册"]
    C --> D["backend/playwright/render.py<br/>runtime/config/install"]
    D --> E["backend/playwright/operations.py<br/>渲染动作"]
    E --> F["resources/"]

    subgraph F["resources/ 资源解析层"]
        F1["resolve.py<br/>资源解析引擎（policy/路径/URL）"]
        F2["template.py<br/>模板变量与 HTML/CSS 替换"]
        F3["filehost/<br/>cache · guard · warmup"]
        F2 --> F1
        F1 --> F3
    end

    G["tests/render/test_render_api.py"] --> B
    H["tests/backend/playwright/test_*.py"] --> D
    I["tests/resources/test_resources*.py"] --> F
```

## 渲染动作时序（HTML -> 图片）

```mermaid
sequenceDiagram
    autonumber
    participant Caller as 业务插件/调用方
    participant API as render.render_html
    participant Render as Render.get_render
    participant Backend as PlaywrightBackend
    participant Ops as operations.render_html
    participant Browser as Browser(Session)
    participant Page as Playwright Page

    Caller->>API: await render_html(html/request)
    API->>Render: get_render()
    alt session 可复用
        Render-->>API: 返回现有 session
    else 冷启动
        Render->>Backend: create_runtime()
        Backend-->>Render: runtime
        Render->>Backend: create_session(runtime)
        Backend-->>Render: session
        Render-->>API: 返回新 session
    end
    API->>Backend: backend.render_html(session, request)
    Backend->>Ops: operations.render_html(...)
    Ops->>Browser: new_page(...) (通过 open_page_context)
    Browser-->>Ops: page
    Ops->>Page: goto(base_url)
    Ops->>Page: set_content(html)
    Ops->>Page: screenshot(...)
    Page-->>Ops: bytes
    Ops->>Page: 退出上下文，关闭 page
    Ops-->>Backend: image bytes
    Backend-->>API: image bytes
    API-->>Caller: image bytes
```

## 插件初始化与关闭时序

```mermaid
sequenceDiagram
    autonumber
    participant NB as NoneBot Driver
    participant Plugin as nonebot_plugin_htmlrender.__init__
    participant Render as Render(Default)
    participant Backend as PlaywrightBackend
    participant Runtime as Playwright Runtime
    participant Session as Browser Session

    NB->>Plugin: on_startup -> init()
    alt 配置了 render_backend 且 startup_mode=probe
        Plugin->>Render: startup_render()
        Plugin->>Render: probe_render()
        Render->>Backend: startup_steps()
        Render->>Backend: create_runtime()
        Backend-->>Runtime: runtime handle
        Render->>Backend: create_session(runtime)
        Backend-->>Session: browser session
        Render-->>Plugin: startup + probe 完成
    else 配置了 render_backend 且 startup_mode=warmup
        Plugin->>Render: startup_render()
        Render->>Backend: startup_steps()
        Render->>Backend: create_runtime()
        Backend-->>Runtime: runtime handle
        Render->>Backend: create_session(runtime)
        Backend-->>Session: browser session
        Render-->>Plugin: startup 完成
    else 未配置 backend 或 startup_mode=off
        Plugin-->>NB: 直接返回
    end

    NB->>Plugin: on_shutdown -> shutdown()
    Plugin->>Render: shutdown_render()
    Render->>Session: aclose()
    Render->>Runtime: aclose()
    Render-->>Plugin: 状态清空
    Plugin-->>NB: shutdown 完成
```

## 兼容层原则

- 兼容层只转发旧 API
- 新能力只放在新 API（避免语义漂移）

## 当前实现状态

- backend 抽象层已经落地，扩展面在 `backend/base.py` 与 `backend/factory.py`。
- 当前仓库的正式 backend 实现只有 Playwright。
- `RenderBackend.SKIA`、`PILLOW`、`HTMLKIT` 目前只保留公开枚举与扩展接口，不代表仓库内已经提供对应实现。
