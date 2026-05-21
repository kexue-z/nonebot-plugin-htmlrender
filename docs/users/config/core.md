---
title: 基础配置与加载
description: 插件基础配置项与配置方式
icon: lucide/sliders-horizontal
status: new
tags:
  - Users
  - Config
---

# 基础配置与加载

## 先记住两个结论

- 当前仓库的正式主路径 backend 是 `playwright`。
- `render_backend` 默认不是 `playwright`，而是 `null`；不配置就不会自动选择后端。

## 为什么存在 `render_backend`

`RENDER_BACKEND` 的意义不是“多写一个看起来重复的配置”，而是把“渲染 API”与“具体运行时实现”明确拆开：

- 用户代码调用的是统一的 `render_text`、`render_markdown`、`render_html`、`render_template`
- 插件内部需要根据 backend 决定由谁负责创建页面、执行截图、处理生命周期与资源解析
- 这让公共 API、兼容层、启动流程和后端实现之间有清晰边界，而不是把 `playwright` 硬编码成不可替换的隐式前提

因此 `render_backend` 的配置意义主要有三点：

- 显式声明你要启用哪套渲染实现，避免插件在启动时“猜测”运行方式
- 让启动阶段、健康检查和错误信息都围绕同一个已选 backend 展开
- 为后续扩展或实验性 backend 保留协议边界，同时不污染调用方 API

对当前仓库而言，正式支持的值仍应视为 `playwright`。  
也就是说，今天你配置 `RENDER_BACKEND=playwright`，本质上是在告诉插件：“请把统一渲染 API 绑定到 Playwright 这套运行时上，并按它的生命周期与配置模型工作。”

## 插件级配置

> 以下默认值以当前代码实现为准（`nonebot_plugin_htmlrender/config.py`）。

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `render_backend` | `Optional[RenderBackend]` | `null` | 未配置时插件不会自动选择渲染后端。建议生产环境显式设置为 `playwright`。 |
| `render_startup_mode` | `RenderStartupMode` | `off` | 启动策略：`off` 仅加载插件；`warmup` 启动时拉起运行时；`probe` 在 warmup 后再执行一次最小可用性探测。 |
| `render_storage_path` | `Path` | `nonebot_plugin_localstore.get_plugin_data_dir()` | 插件数据目录（运行时解析为实际绝对路径）。 |
| `render_cache_path` | `Path` | `nonebot_plugin_localstore.get_plugin_cache_dir()` | 插件缓存目录。 |
| `render_config_path` | `Path` | `nonebot_plugin_localstore.get_plugin_config_dir()` | 插件配置目录。 |

!!! info "关于 `render_backend` 的一个常见误区"
    `render_backend` 并不是默认 `playwright`，而是默认 `null`。  
    如果你希望插件在启动时自动完成渲染运行时初始化，还需要显式设置 `RENDER_STARTUP_MODE=warmup` 或 `probe`。
    枚举值定义为：`playwright` / `skia` / `pillow` / `htmlkit`。其中当前仓库正式支持的实现是 `playwright`；其他值仅表示公开枚举与扩展接口，不应视为已落地后端。

## 推荐阅读顺序

1. 先在本页确定 `render_backend` 与 `render_startup_mode`
2. 再看 [Playwright 配置](playwright.md) 处理浏览器、远程连接、资源解析
3. 最后按需看 [依赖扩展与观测](integrations.md)

## 配置方式

本仓库文档默认主推两种写法：

- `.env` 中使用 `RENDER_PLAYWRIGHT={...}` 的 JSON 风格
- `nonebot.init(render_playwright={...})` 的 Python dict 风格

双下划线展开环境变量写法（例如 `RENDER_PLAYWRIGHT__CONNECT_CDP__ENDPOINT=...`）仍可使用，但本仓库不把它作为主文档风格，仅在示例或部署系统必须逐项展开时提及。

=== "Dotenv"

    ```dotenv
    RENDER_BACKEND=playwright
    RENDER_STARTUP_MODE=probe
    RENDER_PLAYWRIGHT={"resource_resolve_mode":"auto","remote_local_resource_policy":"filehost"}

    # sentry（可选）
    SENTRY_DSN=https://<key>@sentry.example.com/<project>
    SENTRY_TRACES_SAMPLE_RATE=0.2

    # prometheus（可选；默认非 false 即启用，通常可省略）
    PROMETHEUS_ENABLE=true
    ```

=== "nonebot.init"

    ```python
    import nonebot

    nonebot.init(
        render_backend="playwright",
        render_startup_mode="probe",
        render_playwright={
            "resource_resolve_mode": "auto",
            "remote_local_resource_policy": "filehost",
        },
        sentry_dsn="https://<key>@sentry.example.com/<project>",
        sentry_traces_sample_rate=0.2,
        # 可省略；仅在你需要显式声明时设置
        prometheus_enable=True,
    )
    ```
