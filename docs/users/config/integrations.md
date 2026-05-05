---
title: 依赖扩展与观测
description: localstore / filehost / sentry / prometheus 接入说明
icon: lucide/puzzle
status: new
tags:
  - Users
  - Config
  - Integrations
---

# 依赖扩展与观测

## 依赖声明

```toml
[project.optional-dependencies]
filehost = ["nonebot-plugin-filehost>=0.2.0", "py-machineid>=0.8.0"]
sentry = ["nonebot-plugin-sentry>=2.0.0"]
prometheus = ["nonebot-plugin-prometheus>=0.4.0"]
```

## 安装方式

=== "按需安装单个"

    ```bash
    uv add "nonebot-plugin-htmlrender[filehost]"
    uv add "nonebot-plugin-htmlrender[sentry]"
    uv add "nonebot-plugin-htmlrender[prometheus]"
    ```

=== "一次安装多个"

    ```bash
    uv add "nonebot-plugin-htmlrender[filehost,sentry,prometheus]"
    ```

## 组件说明

<div class="dep-grid" markdown>

<div class="dep-card dep-card-required" markdown>

#### :lucide-folders: [localstore](https://github.com/nonebot/plugin-localstore)

提供插件数据/缓存/配置目录能力，`nonebot-plugin-htmlrender` 运行依赖它，默认会自动 `require`。
可结合 NoneBot 的数据存储最佳实践文档一起使用。

</div>

<div class="dep-card dep-card-optional" markdown>

#### :lucide-folder-symlink: [filehost](https://github.com/nonebot/plugin-filehost)

用于远程模式下把本地资源解析为可访问 URL，避免远程浏览器无法读取本地 `file://` 资源。
同时会启用资源请求头校验；默认会基于设备标识（`py-machineid`）派生请求 token。
若环境中安装了 `nonebot-plugin-filehost`，插件会在导入阶段提前 `require("nonebot_plugin_filehost")`；
是否真正进入 filehost 解析流程仍由渲染策略配置决定。
推荐搭配 ASGI + FastAPI driver 使用；否则 `/filehost/*` 请求头守卫可能无法安装。详细配置与运行机制可参考 filehost 项目文档。

</div>

<div class="dep-card dep-card-optional" markdown>

#### :lucide-chess-rook: [sentry](https://github.com/nonebot/plugin-sentry)

用于将渲染链路指标/追踪接入 Sentry。
若环境中安装了 `nonebot-plugin-sentry`，插件会在导入阶段提前尝试 `require("nonebot_plugin_sentry")`。
是否实际上报链路指标/追踪仍取决于 `sentry_dsn` 与 tracing/profiling 相关配置。
接入思路建议参考 NoneBot 错误追踪最佳实践，参数语义以 Sentry Python SDK 配置项说明为准。

</div>

<div class="dep-card dep-card-optional" markdown>

#### :lucide-chart-spline: [prometheus](https://github.com/nonebot/plugin-prometheus)

用于将渲染链路指标暴露到 Prometheus。
若环境中安装了 `nonebot-plugin-prometheus`，插件会在导入阶段提前尝试 `require("nonebot_plugin_prometheus")`。
是否实际记录指标仍受 `prometheus_enable` 控制（显式设为 `false` 时禁用）。
指标暴露与采集方式可参考 plugin-prometheus 文档。

</div>

</div>

## 对应配置属性映射

- `localstore`: `render_storage_path`、`render_cache_path`、`render_config_path`
  这些路径默认由 localstore 提供。

- `filehost`: `render_playwright.resource_resolve_mode`、`render_playwright.remote_local_resource_policy`、`render_playwright.local_local_resource_policy`
  安全相关：`render_playwright.filehost_allow_any_path`、`render_playwright.filehost_allowed_paths`、`render_playwright.filehost_request_header_name`、`render_playwright.filehost_request_header_value`、`render_playwright.filehost_request_header_salt`
  预热与缓存：`render_playwright.filehost_prewarm_paths`、`render_playwright.filehost_prewarm_enabled`、`render_playwright.filehost_prewarm_max_files`、`render_playwright.filehost_prewarm_extensions`、`render_playwright.filehost_cache_ttl_seconds`
  以及渲染调用参数：`resolve_resources`、`resource_resolver`、`resource_strict`。

- `sentry`: `sentry_dsn`（启用关键）
  追踪相关：`sentry_traces_sample_rate`、`sentry_traces_sampler`
  Profiling 相关：`sentry_profiles_sample_rate`、`sentry_profiles_sampler`、`sentry_profile_session_sample_rate`。

- `prometheus`: `prometheus_enable`（显式设为 `false` 时禁用；否则默认启用）。

## 观测指标与追踪名称

当前导出的名称以代码实现为准，可直接用于 dashboard、告警和聚合。

### Prometheus

| 类型 | 名称 | labels |
| --- | --- | --- |
| Counter | `nonebot_htmlrender_operations_total` | `op`, `backend`, `status` |
| Histogram | `nonebot_htmlrender_duration_seconds` | `op`, `backend`, `status` |

说明：

- `op` 对应 `track_render(op=...)` 中的操作名，例如 `render.get_render`、`render.startup`、`playwright.html_render.render_template`
- `backend` 当前主路径通常为 `playwright`
- `status` 由遥测层写为 `ok` 或 `error`

### Sentry

| 类型 | 名称 | tags |
| --- | --- | --- |
| Counter metric | `nonebot.htmlrender.count` | `op`, `backend`, `status` |
| Duration metric | `nonebot.htmlrender.duration` | `op`, `backend`, `status` |

Sentry trace/span 的操作名同样来自 `track_render(op=...)` 的 `op`。

### Page telemetry

页面请求数、失败数、导航时序、资源类型分布目前主要以日志快照形式输出，不是 Prometheus / Sentry 中单独注册的一组稳定指标名。

## 用这些字段怎么做聚合

- 按 `op + status` 看哪类渲染动作最容易失败
- 按 `backend + status` 看某个 backend 是否整体不稳定
- 按 `op` 看 P95/P99 延迟，优先定位 `render.startup`、`playwright.open_session`、`playwright.html_render.render_template`
