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

- 当前仓库正式支持 `playwright` 与 `takumi` 两套 backend。
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

`playwright` 提供完整浏览器、JavaScript、网络与元素截图语义；`takumi` 提供进程内 Rust 原生静态排版、SVG、测量和动画能力。两者复用同一套文本、Markdown、Jinja preparation 与资源缓存，但执行能力并不伪装成完全相同。

## 插件级配置

> 以下默认值以当前代码实现为准（`nonebot_plugin_htmlrender/config.py`）。

| 配置项                                          | 类型                      | 默认值                                              | 说明                                                                                                  |
| ----------------------------------------------- | ------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `render_backend`                                | `Optional[RenderBackend]` | `null`                                              | 未配置时插件不会自动选择渲染后端。生产环境应显式设置为 `playwright` 或 `takumi`。                     |
| `render_startup_mode`                           | `RenderStartupMode`       | `off`                                               | 启动策略：`off` 仅加载插件；`warmup` 启动时拉起运行时；`probe` 在 warmup 后再执行一次最小可用性探测。 |
| `render_storage_path`                           | `Path`                    | `nonebot_plugin_localstore.get_plugin_data_dir()`   | 插件数据目录（运行时解析为实际绝对路径）。                                                            |
| `render_cache_path`                             | `Path`                    | `nonebot_plugin_localstore.get_plugin_cache_dir()`  | 保留的插件缓存目录配置；当前没有模板消费者。                                                          |
| `render_config_path`                            | `Path`                    | `nonebot_plugin_localstore.get_plugin_config_dir()` | 保留的插件配置目录配置；当前没有模板消费者。                                                          |
| `render_resource_cache_max_entries`             | `int`                     | `256`                                               | 共用资源 byte cache 的条目上限。                                                                      |
| `render_resource_cache_max_bytes`               | `int`                     | `67108864`                                          | 共用资源 byte cache 的权重上限（64 MiB）。                                                            |
| `render_resource_cache_revalidate_seconds`      | `float`                   | `1.0`                                               | filesystem 资源 revision 重新检查间隔（秒）。                                                         |
| `render_template_environment_cache_max_entries` | `int`                     | `64`                                                | Jinja environment cache 条目上限。                                                                    |

!!! info "关于 `render_backend` 的一个常见误区"

    `render_backend` 并不是默认 `playwright`，而是默认 `null`。\
    如果你希望插件在启动时自动完成渲染运行时初始化，还需要显式设置 `RENDER_STARTUP_MODE=warmup` 或 `probe`。
    枚举值定义为：`playwright` / `takumi` / `skia` / `pillow` / `htmlkit`。其中当前仓库正式支持 `playwright` 与 `takumi`；其余值仅表示公开枚举与扩展接口，不应视为已落地后端。

## 推荐阅读顺序

1. 先在本页确定 `render_backend` 与 `render_startup_mode`
1. 再按后端阅读 [Playwright 配置](playwright.md) 或 [Takumi 配置与能力](takumi.md)
1. 最后按需看 [依赖扩展与观测](integrations.md)

## 配置方式

本仓库文档默认主推两种写法：

- `.env` 中使用 `RENDER_PLAYWRIGHT={...}` / `RENDER_TAKUMI={...}` 的 JSON 风格
- `nonebot.init(render_playwright={...})` / `nonebot.init(render_takumi={...})` 的 Python dict 风格

双下划线展开环境变量写法（例如 `RENDER_PLAYWRIGHT__CONNECT_CDP__ENDPOINT=...`）仍可使用，但本仓库不把它作为主文档风格，仅在示例或部署系统必须逐项展开时提及。

=== "Dotenv"

    ```dotenv
    RENDER_BACKEND=playwright
    RENDER_STARTUP_MODE=probe
    RENDER_PLAYWRIGHT={"connect_ws":{"endpoint":"ws://playwright:53333/playwright"}}

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
            "connect_ws": {"endpoint": "ws://playwright:53333/playwright"},
        },
        sentry_dsn="https://<key>@sentry.example.com/<project>",
        sentry_traces_sample_rate=0.2,
        # 可省略；仅在你需要显式声明时设置
        prometheus_enable=True,
    )
    ```

## 内置模板与 localstore

内置 text / Markdown 模板只作为 package resource 随 wheel 分发，由 `importlib.resources` 与 Jinja `PackageLoader` 读取，并登记在 wheel 的 `RECORD` 中。卸载 Python distribution 时，它们随包文件一起删除。

插件不会把内置模板复制到 localstore，也不提供 uninstall hook、localstore purge、用户覆盖模板目录或“首次启动解压模板”流程。这样可以避免 package 版本与落盘副本产生双重真源。用户模板始终从调用方显式传入的 filesystem 目录加载。

共用资源缓存、Jinja environment cache 与 `PreparedAsset` 都是进程内对象，不写入 `render_cache_path`。`render_cache_path` 和 `render_config_path` 当前保留给未来有明确生命周期契约的消费者，不能依赖它们包含可覆盖或可删除的模板副本。
