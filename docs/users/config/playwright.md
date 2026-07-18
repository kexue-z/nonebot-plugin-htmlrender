---
title: Playwright 配置
description: 本地/远程浏览器连接、资源 transport 与 typed Capability
icon: lucide/monitor-cog
---

# Playwright 配置

## 安装与最小配置

```bash
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0a1,<0.9"
uv run playwright install chromium
```

```yaml
render:
  provider: playwright
  startup: probe
  provider_config:
    engine: chromium
```

下表所有字段均位于 `render.provider_config`：

| 完整路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.provider_config.engine` | `chromium` | `chromium`、`firefox`、`webkit` |
| `render.provider_config.channel` | `null` | Chromium channel |
| `render.provider_config.executable_path` | `null` | 自定义浏览器路径 |
| `render.provider_config.launch_args` | `null` | 本地 launch 参数字符串 |
| `render.provider_config.proxy_server` | `null` | 浏览器代理 |
| `render.provider_config.proxy_bypass` | `null` | 代理绕过规则 |
| `render.provider_config.connect_ws.endpoint` | `null` | Playwright WebSocket endpoint |
| `render.provider_config.connect_cdp.endpoint` | `null` | Chromium CDP endpoint |
| `render.provider_config.install_mirror` | `null` | 浏览器安装镜像 |
| `render.provider_config.install_proxy` | `null` | 浏览器安装代理 |
| `render.provider_config.skip_browser_install` | `false` | 缺少本地浏览器时禁止自动安装 |
| `render.provider_config.cleanup_legacy_cache` | `false` | 是否清理旧浏览器缓存 |
| `render.provider_config.close_on_exit` | `true` | composition 关闭时关闭本地浏览器 |
| `render.provider_config.storage_path` | `null` | Playwright 浏览器存储目录；默认使用 core localstore data 目录 |

`channel` 只适用于 Chromium；CDP 只适用于 Chromium；WS 与 CDP endpoint
互斥。空的 `executable_path` 会归一化为 `null`。

localstore 是插件 core 的宿主基础设施，而非 Playwright extra。Playwright 只是其
当前消费者之一；`storage_path` 仅覆盖本 adapter 的浏览器存储位置。

## 资源 transport

| 完整路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.provider_config.resource_resolve_mode` | `auto` | `off`、`auto`、`strict` |
| `render.provider_config.remote_local_resource_policy` | `memory` | `memory`、`passthrough`、`filehost`、`error` |
| `render.provider_config.local_local_resource_policy` | `file` | `file`、`passthrough`、`filehost` |

未传每次调用的 `resource_policy` 时，执行端严格采用
`resource_resolve_mode`；显式 `ResourcePolicy` 会覆盖该默认值。`off` 调用不读取、
物化或发布本地引用；若选中的 transport 是 `filehost`，composition 仍会准备
publisher，使后续单次调用可以覆盖为 `auto` 或 `strict`。`auto` 容忍无法读取的
引用，`strict` 则将其报告为资源错误。

远程模式推荐 `memory`：本地图片、字体和 CSS 被物化为 render-scoped asset，
由页面 route 返回，不要求共享 filesystem。`passthrough` 仅适用于显式共享卷；
`error` 用于禁止所有本地引用。

`filehost` 是需要真实 HTTP URL 时的兼容 transport，需安装：

```bash
uv add "nonebot-plugin-htmlrender[playwright,filehost]>=0.8.0a1,<0.9"
```

filehost 运行参数由核心 Resource Service 管理，位于 `render.resources.filehost`：

| 完整路径 | 默认值 |
| --- | --- |
| `render.resources.filehost.cache_ttl_seconds` | `300.0` |
| `render.resources.filehost.prewarm_enabled` | `true` |
| `render.resources.filehost.prewarm_paths` | `[]` |
| `render.resources.filehost.prewarm_max_files` | `256` |
| `render.resources.filehost.prewarm_extensions` | `[]` |
| `render.resources.filehost.request_header_name` | `X-HTMLRender-Filehost-Request` |
| `render.resources.filehost.request_header_value` | `null` |
| `render.resources.filehost.request_header_salt` | 内置稳定值 |

路径授权不在 Provider 配置中；统一使用
`render.resources.local_access.allow_any_path` 与
`render.resources.local_access.allowed_paths`。

## typed Capability

通用 `render_*` 不接受导航、header 或 User-Agent。页面控制通过
`PLAYWRIGHT_CAPABILITIES` 获取：

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.capabilities import PLAYWRIGHT_CAPABILITIES

capability = get_default_application().capabilities.require(PLAYWRIGHT_CAPABILITIES)
async with capability.page(
    viewport={"width": 1280, "height": 800},
    extra_http_headers={"X-Trace": "example"},
) as page:
    await page.goto("https://example.com")
```

远程部署与安全边界见 [远程 Playwright](../remote-playwright.md)。
