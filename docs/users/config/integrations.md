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
takumi = ["takumi-py==0.2.0"]
```

## 安装方式

=== "按需安装单个"

    ```bash
    uv add "nonebot-plugin-htmlrender[filehost]"
    uv add "nonebot-plugin-htmlrender[sentry]"
    uv add "nonebot-plugin-htmlrender[prometheus]"
    uv add "nonebot-plugin-htmlrender[takumi]"
    ```

=== "一次安装多个"

    ```bash
    uv add "nonebot-plugin-htmlrender[filehost,takumi,sentry,prometheus]"
    ```

## 组件说明

<div class="dep-grid" markdown>

<div class="dep-card dep-card-required" markdown>

### :lucide-folders: [localstore](https://github.com/nonebot/plugin-localstore)

提供插件数据/缓存/配置目录能力，`nonebot-plugin-htmlrender` 运行依赖它，默认会自动 `require`。内置模板不复制到这些目录：它们属于 wheel package resources，卸载 distribution 时随包删除。`render_cache_path` 与 `render_config_path` 当前是保留配置，没有模板消费者；进程内 byte cache 与 `PreparedAsset` 也不在 localstore 落盘。

</div>

<div class="dep-card dep-card-optional" markdown>

### :lucide-folder-symlink: [filehost](https://github.com/nonebot/plugin-filehost)

用于显式兼容模式下把本地资源解析为可访问 URL。v0.7.2 的远程默认路径是 render-scoped 内存资产桥，不安装 filehost extra 也能跨容器传输本地图片、CSS 与字体。
同时会启用资源请求头校验；默认会基于设备标识（`py-machineid`）派生请求 token。
插件不会在默认导入阶段加载 filehost；只有 Playwright 配置显式选择 `filehost` 时，才会在插件 bootstrap 阶段 `require("nonebot_plugin_filehost")` 并安装请求守卫。
推荐搭配 ASGI + FastAPI driver 使用；否则 `/filehost/*` 请求头守卫可能无法安装。详细配置与运行机制可参考 filehost 项目文档。

</div>

<div class="dep-card dep-card-optional" markdown>

### :lucide-chess-rook: [sentry](https://github.com/nonebot/plugin-sentry)

用于将渲染链路指标/追踪接入 Sentry。
Sentry 适配器按第一次实际使用惰性初始化，并直接适配 Sentry Python SDK 2.x 的 transaction/span 与 `metrics.count` API。
依赖缺失、关闭或初始化失败都不会阻断插件导入；是否实际上报仍取决于 `sentry_dsn` 与 tracing/profiling 相关配置。
接入思路建议参考 NoneBot 错误追踪最佳实践，参数语义以 Sentry Python SDK 配置项说明为准。

</div>

<div class="dep-card dep-card-optional" markdown>

### :lucide-chart-spline: [prometheus](https://github.com/nonebot/plugin-prometheus)

用于将渲染链路指标暴露到 Prometheus。
Prometheus 适配器独立于 Sentry 惰性初始化。依赖缺失、关闭或初始化失败都不会阻断插件导入；是否实际记录指标仍受 `prometheus_enable` 控制（显式设为 `false` 时禁用）。
指标暴露与采集方式可参考 plugin-prometheus 文档。

</div>

</div>

## 对应配置属性映射

- `localstore`: `render_storage_path`、`render_cache_path`、`render_config_path`
    这些路径默认由 localstore 提供；后两者当前没有模板消费者。

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

| 类型      | 名称                                  | labels                    |
| --------- | ------------------------------------- | ------------------------- |
| Counter   | `nonebot_htmlrender_operations_total` | `op`, `backend`, `status` |
| Histogram | `nonebot_htmlrender_duration_seconds` | `op`, `backend`, `status` |

说明：

- `op` 对应 `track_render(op=...)` 中的操作名，例如 `render.get_render`、`render.startup`、`playwright.html_render.render_template`、`takumi.render_html`
- `backend` 为稳定的低基数标签，正式后端取值为 `playwright` 或 `takumi`
- `status` 由遥测层写为 `ok` 或 `error`

两个 exporter 完全隔离。记录 span/counter/histogram 失败时只降级观测，不覆盖成功渲染结果，也不替换原始业务异常。标签限制为低基数 `backend`、`op`、`status` 与汇总 cache stats，不记录路径、HTML、URL、字体名、digest 或资源内容。

### Sentry

| 类型            | 名称                          | tags                      |
| --------------- | ----------------------------- | ------------------------- |
| Counter metric  | `nonebot.htmlrender.count`    | `op`, `backend`, `status` |
| Duration metric | `nonebot.htmlrender.duration` | `op`, `backend`, `status` |

Sentry trace/span 的操作名同样来自 `track_render(op=...)` 的 `op`。
Takumi 的公共操作使用 `takumi.render_*` / `takumi.rasterize_html`，特有能力使用 `takumi.extension.*`；span 与 metric 不附带 HTML、Markdown、模板路径、URL 或资源内容。

### Page telemetry

页面请求数、失败数、导航时序、资源类型分布仅适用于 Playwright，目前主要以日志快照形式输出，不是 Prometheus / Sentry 中单独注册的一组稳定指标名。Takumi 没有网络页面，因此不产生这组页面日志。

## 用这些字段怎么做聚合

- 按 `op + status` 看哪类渲染动作最容易失败
- 按 `backend + status` 看某个 backend 是否整体不稳定
- 按 `op` 看 P95/P99 延迟，优先定位 `render.startup`、`playwright.open_session`、`playwright.html_render.render_template`
