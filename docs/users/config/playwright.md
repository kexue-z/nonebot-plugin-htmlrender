---
title: Playwright 配置
description: Playwright 连接、启动与资源解析配置
icon: lucide/monitor-cog
status: new
tags:
  - Users
  - Config
  - Playwright
---

# Playwright 配置

## 配置项默认值（代码基准）

> 以下默认值以当前代码实现为准（`nonebot_plugin_htmlrender/backend/playwright/config.py`）。

### 启动与连接

| 配置项                                   | 默认值     | 说明                                             |
| ---------------------------------------- | ---------- | ------------------------------------------------ |
| `render_playwright.engine`               | `chromium` | 浏览器引擎：`chromium` / `firefox` / `webkit`    |
| `render_playwright.channel`              | `null`     | 仅 `engine=chromium` 时可用                      |
| `render_playwright.executable_path`      | `null`     | 空字符串或 `.` 会被归一化为 `null`               |
| `render_playwright.launch_args`          | `null`     | 本地浏览器启动附加参数（空格分隔字符串）         |
| `render_playwright.proxy_server`         | `null`     | 浏览器代理地址                                   |
| `render_playwright.proxy_bypass`         | `null`     | 浏览器代理绕过规则                               |
| `render_playwright.connect_ws.endpoint`  | `null`     | 远程 Playwright WS 地址                          |
| `render_playwright.connect_cdp.endpoint` | `null`     | 远程 Chromium CDP 地址                           |
| `render_playwright.install_mirror`       | `null`     | 安装浏览器时额外镜像地址                         |
| `render_playwright.install_proxy`        | `null`     | 安装浏览器时下载代理（HTTP/HTTPS）               |
| `render_playwright.skip_browser_install` | `false`    | 本地模式环境检查失败时，是否跳过自动安装         |
| `render_playwright.cleanup_legacy_cache` | `false`    | 是否在启动时自动删除旧版全局 Playwright 缓存目录 |
| `render_playwright.close_on_exit`        | `true`     | 本地模式 session 关闭时是否关闭浏览器            |

### 资源解析与 filehost

| 配置项                                            | 默认值                                                                                                                         | 说明                         |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ | ---------------------------- |
| `render_playwright.resource_resolve_mode`         | `auto`                                                                                                                         | `off` / `auto` / `strict`    |
| `render_playwright.remote_local_resource_policy`  | `memory`                                                                                                                       | 远程模式下本地资源策略       |
| `render_playwright.local_local_resource_policy`   | `file`                                                                                                                         | 本地模式下本地资源策略       |
| `render_playwright.filehost_allow_any_path`       | `false`                                                                                                                        | 是否放开任意本地路径暴露     |
| `render_playwright.filehost_allowed_paths`        | `[]`                                                                                                                           | 额外允许暴露目录白名单       |
| `render_playwright.filehost_prewarm_paths`        | `[]`                                                                                                                           | filehost 预热目录            |
| `render_playwright.filehost_prewarm_enabled`      | `true`                                                                                                                         | 是否启用 filehost 目录预热   |
| `render_playwright.filehost_prewarm_max_files`    | `256`                                                                                                                          | 单次目录预热最大文件数       |
| `render_playwright.filehost_cache_ttl_seconds`    | `300.0`                                                                                                                        | filehost 资源缓存 TTL（秒）  |
| `render_playwright.filehost_prewarm_extensions`   | `[".css", ".js", ".mjs", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".ico", ".woff", ".woff2", ".ttf", ".otf", ".map"]` | 参与目录预热的后缀           |
| `render_playwright.filehost_request_header_name`  | `X-HTMLRender-Filehost-Request`                                                                                                | filehost 请求头名            |
| `render_playwright.filehost_request_header_value` | `null`                                                                                                                         | 显式 token；为空时走自动派生 |
| `render_playwright.filehost_request_header_salt`  | `nonebot-plugin-htmlrender:filehost:guard:v1`                                                                                  | 自动派生 token 盐值          |

## 归一化与校验规则

- `connect_ws.endpoint` 与 `connect_cdp.endpoint` 不能同时配置。
- `connect_cdp.endpoint` 只允许搭配 `engine=chromium`。
- `channel` 只允许在 `engine=chromium` 时配置。
- `executable_path` 传空字符串或 `.` 会被归一化为 `null`。
- `filehost_allowed_paths` / `filehost_prewarm_paths` 传单个字符串时会自动转为列表。
- `filehost_prewarm_extensions` 支持逗号分隔字符串，会自动补 `.`、转小写、去重并保持顺序。
- `filehost_request_header_name` 传空白字符串会回退到默认值。
- `filehost_request_header_value` 传空白字符串会回退为 `null`（表示自动派生 token）。
- `filehost_request_header_salt` 传空白字符串会回退到默认值。

## 默认内存资产桥

远程 session 在 `auto + memory` 下把本地图片、字体、CSS 等资源读取为 `PreparedAsset`，按内容 SHA-256 去重，并用 Page 级 route 直接向浏览器返回 bytes。资产只活到本次页面关闭，不写磁盘，也不要求 Bot 与浏览器共享 filesystem。

`passthrough` 只适用于显式共享卷；`error` 用于强制禁止本地引用；`filehost` 是需要 HTTP URL 时的显式兼容模式。

## filehost 显式兼容模式

启用 filehost 解析后，插件会在进程内按**内容 digest**去重 URL mapping：

- **内容身份**：`Path`、`bytes`、`bytearray` 与 `BytesIO` 都计算 SHA-256；不同路径的相同内容共享一次上传。
- **一致快照**：文件读取前后校验 revision，避免边读边改产生不完整 blob。
- **TTL**：`filehost_cache_ttl_seconds`（默认 300 秒）只控制 URL mapping；命中会刷新 mapping 的过期时间。
- **租约保护**：单次渲染使用的 blob revision 会钉住到渲染结束，不被并发清理抢先移除。
- **并发去重**：同一 digest 的上传通过 singleflight 共享；成功、异常和取消都会唤醒等待者。

htmlrender 不访问 `nonebot-plugin-filehost` 的私有物理文件字段，也不提供逐文件删除承诺。mapping 过期只释放 htmlrender 的映射；物理文件由 filehost 的进程级临时目录生命周期管理。

实现细节与公共 API（`prune_filehost_cache()` 等）参见维护者文档：[资源准备与传输方案](../../maintainers/architecture/filehost-resource-resolution.md)。

## 本地启动配置

`render_playwright.engine`
:   浏览器引擎类型。\
    参考：[Playwright Browsers](https://playwright.dev/python/docs/browsers)

`render_playwright.channel`
:   Chromium channel（仅 `engine=chromium`）。\
    参考：[BrowserType.launch(channel)](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch)

`render_playwright.executable_path`
:   指定浏览器可执行文件路径。\
    参考：[BrowserType.launch(executable_path)](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch)

`render_playwright.launch_args`
:   附加浏览器启动参数。\
    参考：[BrowserType.launch(args)](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch)

`render_playwright.proxy_server` / `render_playwright.proxy_bypass`
:   浏览器代理与绕过规则。\
    参考：[BrowserType.launch(proxy)](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch)

`render_playwright.cleanup_legacy_cache`
:   是否自动清理旧版默认缓存目录（如 `~/Library/Caches/ms-playwright`）。默认仅告警不删除；显式设为 `true` 后，插件会在启动阶段发现 legacy 目录时自动清理。

## 远程连接配置

远程渲染分为两类：远程 Playwright（WS）与远程浏览器（CDP）。

### 远程 Playwright（WS）

`render_playwright.connect_ws.endpoint`
:   Playwright WS 连接地址。\
    参考：[BrowserType.connect](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect)

=== "Dotenv"

    ```dotenv
    RENDER_PLAYWRIGHT={"engine":"chromium","connect_ws":{"endpoint":"ws://127.0.0.1:3000/"}}
    ```

=== "nonebot.init"

    ```python
    import nonebot

    nonebot.init(
        render_playwright={
            "engine": "chromium",
            "connect_ws": {"endpoint": "ws://127.0.0.1:3000/"},
        }
    )
    ```

### 远程浏览器（CDP）

`render_playwright.connect_cdp.endpoint`
:   Chromium CDP 连接地址。\
    参考：[BrowserType.connect_over_cdp](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp)

=== "Dotenv"

    ```dotenv
    RENDER_PLAYWRIGHT={"engine":"chromium","connect_cdp":{"endpoint":"http://127.0.0.1:9222/"}}
    ```

=== "nonebot.init"

    ```python
    import nonebot

    nonebot.init(
        render_playwright={
            "engine": "chromium",
            "connect_cdp": {"endpoint": "http://127.0.0.1:9222/"},
        }
    )
    ```

### WS / CDP 差异

| 维度     | 远程 Playwright（WS）            | 远程浏览器（CDP）         |
| -------- | -------------------------------- | ------------------------- |
| 连接协议 | Playwright 协议（WebSocket）     | Chrome DevTools Protocol  |
| 配置项   | `connect_ws.endpoint`            | `connect_cdp.endpoint`    |
| 引擎支持 | Playwright 管理的浏览器          | 仅 Chromium 系            |
| 常见部署 | Playwright Server 容器/服务      | 远程 Chrome/Chromium 实例 |
| 选型建议 | 需要更完整 Playwright 特性时优先 | 已有 CDP 基础设施时优先   |

## 资源解析配置

`render_playwright.resource_resolve_mode`
:   `off` / `auto` / `strict`

`render_playwright.remote_local_resource_policy`
:   `memory` / `passthrough` / `filehost` / `error`

`render_playwright.local_local_resource_policy`
:   `file` / `filehost` / `passthrough`

## 页面导航与资源基址

`PreparedHtml.base_url` 只表示资源解析基址。`PageConfig` 中只有 `document_url` 才在注入 HTML 前触发 `page.goto()`；未设置时在 `about:blank` 上直接 `page.set_content()`。

`PageConfig.base_url` 仅保留为 v0.7.1 导航字段的弃用兼容别名，不再承载资源基址。请迁移到 `document_url`，并避免同时提供两种导航表达。远程 `file://` 文档导航只有在 Chromium 能看到同一路径、且显式选择 `passthrough` 的共享卷部署中才有效；默认 `memory` 只传输文档引用的资产，不会把导航目标本身变成远端文件。

## Filehost 安全配置

`render_playwright.filehost_allow_any_path`
:   是否允许 filehost 暴露任意本地路径。默认 `false`（推荐保持默认）。

`render_playwright.filehost_allowed_paths`
:   filehost 额外允许暴露的本地目录白名单（绝对/相对路径均可）。\
    未命中白名单且不在模板目录下的路径会被拒绝。

`render_playwright.filehost_request_header_name`
:   filehost 资源请求校验用 header 名。默认 `X-HTMLRender-Filehost-Request`。

`render_playwright.filehost_request_header_value`
:   filehost 资源请求校验 token。\
    配置后将直接使用该值，覆盖自动派生逻辑。

`render_playwright.filehost_request_header_salt`
:   filehost 自动派生 token 的盐值。默认 `nonebot-plugin-htmlrender:filehost:guard:v1`。\
    仅在 `filehost_request_header_value` 未配置时生效。

!!! info "请求头校验默认生效"

    只要启用 filehost 解析策略，插件会在启动时安装 `/filehost/*` 请求头守卫，并在渲染请求中自动附带该 header。

!!! info "Token 生成与消费行为"

    生成端与消费端使用同一规则，确保可识别一致：

    1. 若配置 `filehost_request_header_value`，直接使用该值。
    1. 否则按 `sha256(filehost_request_header_salt + ":" + device_id)` 生成。\
        其中 `device_id` 优先来自 `py-machineid`，不可用时回退为 `unknown-device`。
