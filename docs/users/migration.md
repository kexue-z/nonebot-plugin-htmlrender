---
title: 旧版本迁移指南
description: 从旧版 API 平滑迁移到新版的对照表与兼容配置
icon: lucide/move
status: new
tags:
  - Users
  - Migration
---

# 旧版本迁移指南

从 v0.7.1 升级时，请先阅读 [v0.7.2 迁移说明](migration-v072.md)。该版本修复远程 `file://` 模板加载，并调整远程资源与页面导航的默认语义。

新版本将渲染逻辑与底层驱动解耦，引入分层架构（Render / Backend / Runtime / Session / Context）。
旧 API 仍保留为兼容层，但调用时会触发弃用警告，且不再承载新能力。
新项目请直接使用新 API；存量项目按本页对照表逐步迁移即可。

如果希望先理解新版的对象模型与生命周期再做决策，请阅读：

- [分层架构](../maintainers/architecture/architecture.md)
- [API 与兼容层](api.md)

## API 对照表

| 旧 API（已弃用）      | 新 API（推荐）         | 说明                                       |
| :-------------------- | :--------------------- | :----------------------------------------- |
| `text_to_pic`         | `render_text`          | 渲染纯文本为图片                           |
| `md_to_pic`           | `render_markdown`      | 渲染 Markdown 为图片                       |
| `html_to_pic`         | `render_html`          | 渲染 HTML 字符串/请求为图片                |
| `template_to_pic`     | `render_template`      | 模板渲染为图片（推荐）                     |
| `template_to_html`    | `render_template_html` | 模板渲染为 HTML 字符串                     |
| `capture_element`     | `capture_html_element` | 截取页面中指定元素                         |
| `get_new_page`        | `get_render_context`   | 获取页面上下文，建议在 `async with` 中使用 |
| `startup_htmlrender`  | `startup_render`       | 启动渲染会话                               |
| `shutdown_htmlrender` | `shutdown_render`      | 关闭渲染会话                               |

!!! warning "兼容层边界"

    兼容层只做转发与弃用提示，不承载新能力。
    例如 `template_to_pic` 不暴露 `render_template` 新增的资源解析参数（`resolve_resources` / `resource_resolver` / `resource_strict`）。
    如需这些能力，请直接调用 `render_template`。

## 当前兼容策略

- 兼容层仍然保留，目的是给存量项目留迁移窗口。
- 兼容层的职责只有两件事：转发旧 API、发出 `DeprecationWarning`。
- 当前仓库**没有承诺具体的移除版本号或精确下线窗口**。
- 这不表示可以长期停留在兼容层。对新代码来说，兼容层已经不再是正式入口。

换句话说：现在没有一个被文档锁定的“最后期限”，但迁移动作应当立即开始。

## 接近旧版"开箱即用"的最小配置

旧版习惯插件加载即可直接渲染。新版需显式指定后端，并选择启动策略：

=== "Dotenv"

    ```dotenv
    RENDER_BACKEND=playwright
    RENDER_STARTUP_MODE=probe
    RENDER_PLAYWRIGHT={"engine":"chromium","skip_browser_install":false,"close_on_exit":true}
    ```

=== "nonebot.init"

    ```python
    import nonebot

    nonebot.init(
        render_backend="playwright",
        render_startup_mode="probe",
        render_playwright={
            "engine": "chromium",
            "skip_browser_install": False,
            "close_on_exit": True,
        },
    )
    ```

要点：

- `RENDER_BACKEND=playwright`：新版需要显式指定后端。
- `RENDER_STARTUP_MODE=probe`：启动阶段拉起浏览器并执行最小可用性探测，提早暴露环境问题。
- `skip_browser_install=false`：本地缺少浏览器时允许自动安装，更接近旧版"开箱即用"体感。

完整配置项参见 [基础配置与加载](config/core.md) 与 [Playwright 配置](config/playwright.md)。

## 迁移后常用能力的入口

迁移过程中可能会发现部分原本散落在业务代码里的逻辑被新版抽走，统一通过 API 提供：

- 远程渲染（远程 Playwright / 远程浏览器）：[远程 Playwright 与资源桥](remote-playwright.md)
- 模板资源解析（本地文件转远端 URL）：[API 与兼容层](api.md) 中 `render_template` 一节
- 后端可用性查询：[API 与兼容层](api.md) 中"后端状态查询"一节
- 接入节奏与目录组织：[最佳实践](best-practices.md)

## 迁移优先级

1. 先替换使用频率最高的旧 API，通常是 `md_to_pic`、`template_to_pic`
1. 再移除生命周期旧入口，如 `startup_htmlrender`、`shutdown_htmlrender`
1. 最后处理只在少量路径出现的兼容模块导入，如 `browser.py`、`data_source.py`

## 迁移建议节奏

1. 先在 `.env` 中加入 `RENDER_BACKEND` 与 `RENDER_STARTUP_MODE`，确认插件可正常启动。
1. 把使用最多的旧 API（通常是 `md_to_pic` / `template_to_pic`）替换为新 API，验证渲染产物一致。
1. 处理日志中的弃用警告，逐个移除剩余旧 API 调用。
1. 视需求接入资源解析、远程渲染、可观测性扩展。

## 升级后验收清单

- [ ] `render_text` 或 `render_markdown` 本地渲染成功
- [ ] 模板目录渲染成功，`template_name` 与相对资源来源基址行为符合预期
- [ ] 如使用远程浏览器，WS 或 CDP 连接正常
- [ ] 如模板里含本地静态资源，内存桥、共享卷或显式 filehost 策略符合预期
- [ ] 日志里不再出现旧 API 的 `DeprecationWarning`
