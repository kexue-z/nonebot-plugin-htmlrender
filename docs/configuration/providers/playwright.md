---
title: Playwright 配置
description: 本地/远程浏览器连接、资源 transport 与 typed Capability
icon: lucide/monitor-cog
---

# Playwright 配置

## 安装与最小配置

```bash
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0,<0.9"
```

```yaml
render:
  provider: playwright
  startup: probe
  provider_config:
    engine: chromium
    connect_ws:
      endpoint: ws://playwright:3000/
    remote_local_resource_policy: memory
```

## 部署优先级 { #deployment-priority }

1. **首选：Docker 远程 Playwright。** 在独立容器中部署版本匹配的 Playwright browser service，Bot 通过 `connect_ws.endpoint` 连接。浏览器二进制、Linux 系统依赖、sandbox 与进程生命周期都留在服务容器内；Bot 宿主机只需要 `playwright` extra。生产环境默认采用这一形态，具体拓扑见[远程 Playwright 部署](../remote-playwright.md)。
2. **第二选项：Bot 宿主机本地 Playwright。** 不配置 `connect_ws` / `connect_cdp`，由 Bot 直接启动浏览器。它适合本地开发、单机部署或无法增加独立服务的环境，但宿主机必须承担浏览器下载、系统动态库、权限和进程清理。

CDP 用于接入已有 Chromium，不是一般部署的首选替代；它不支持 Firefox 或 WebKit，协议能力也不同于版本匹配的 Playwright WS 服务。

## 浏览器运行环境 { #browser-runtime-requirements }

`playwright` extra 只安装 Playwright Python client。每个 Playwright 版本都要求特定版本的浏览器二进制；升级依赖或更新 lockfile 后，需要用同一个 Python 环境重新执行浏览器安装。上游的[浏览器安装说明](https://playwright.dev/python/docs/browsers/)也把 Python package、浏览器二进制和 Linux 系统依赖视为三个独立层次。

采用第二选项时，在 macOS 或 Windows 安装选中的浏览器：

```bash
uv run playwright install chromium
```

Debian/Ubuntu、容器与 CI 应在镜像构建阶段同时安装浏览器及其系统依赖：

```bash
uv run playwright install --with-deps chromium
```

!!! warning "单机模式必须保持 client 与 browser revision 强一致"

    `storage_path` 中的浏览器必须由当前项目虚拟环境内解析出的同一 Playwright Python package 版本安装。这里的“强一致”是指 client 声明的 browser revision 完全匹配，并非只比较 Chromium 显示的产品版本字符串。

    不要手工替换目录内的浏览器 executable，也不要让全局 Playwright CLI 或其他虚拟环境对同一个 `storage_path` / `PLAYWRIGHT_BROWSERS_PATH` 执行安装、升级、卸载或缓存清理。这些操作可能移除当前 client 要求的 revision，使单机 Provider 立即不可用。

    为每个项目虚拟环境分配独占目录，并始终通过该项目的 `uv run` 安装：

    ```bash
    PLAYWRIGHT_BROWSERS_PATH=/var/lib/htmlrender/playwright-project \
      uv run playwright install --with-deps chromium
    ```

    ```yaml
    render:
      provider: playwright
      startup: probe
      provider_config:
        storage_path: /var/lib/htmlrender/playwright-project
        skip_browser_install: true
    ```

    安装用户必须能写入该目录，Bot 服务用户必须能读取并执行其中的文件。依赖更新后，即使目录仍然存在，也要从更新后的同一虚拟环境重新执行安装。

将 `chromium` 替换为实际配置的 `engine`。`--with-deps` 在 Linux 上会调用系统包管理器，构建用户必须有相应权限；生产服务进程不应依赖启动时临时取得 root 或访问下载源。htmlrender 在本地浏览器二进制确实缺失时会尝试一次同样的安装和重启，但已经存在浏览器而系统动态库不完整时会直接报告 runtime dependency failure。生产部署应预装完整环境；确认 `storage_path` 中已有匹配版本后，可以设置 `skip_browser_install: true` 禁止运行时下载。

使用 Playwright 官方容器镜像时，镜像已经包含浏览器与系统依赖，但不包含项目的 Python package；镜像 tag 必须与 lockfile 最终解析到的 Playwright 版本匹配。官方浏览器不支持 Alpine/musl 上的 Firefox 与 WebKit，容器部署应使用受支持的 glibc 基础镜像。详见上游的 [Docker 说明](https://playwright.dev/python/docs/docker/)。

推荐的 Docker/WS 远程模式下，Bot 进程仍需 `playwright` extra，但不需要本地浏览器二进制及其系统依赖；这些要求由远程服务承担。WS 服务与 client 必须精确锁定到同一 Playwright 版本。连接前虽有版本风险门禁，但它在相邻 minor、部分 patch 差异或无法探测远端版本时仍会继续，不能代替版本锁定；CDP 则完全不执行该版本比较。详细行为与服务端检查表见[远程 Playwright 部署](../remote-playwright.md#ws-version-gate-and-startup-probe)。

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
| `render.provider_config.storage_path` | `null` | Playwright 浏览器存储目录；默认使用插件数据目录 |

`channel` 只适用于 Chromium；CDP 只适用于 Chromium；WS 与 CDP endpoint互斥。空的 `executable_path` 会归一化为 `null`。

`storage_path` 仅覆盖 Playwright 浏览器文件与运行时快照的存储位置。单机部署不得让不同项目虚拟环境共享该目录；对应的安装命令必须通过同一路径的 `PLAYWRIGHT_BROWSERS_PATH` 定位它。

## 资源 transport

| 完整路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.provider_config.resource_resolve_mode` | `auto` | `off`、`auto`、`strict` |
| `render.provider_config.remote_local_resource_policy` | `memory` | `memory`、`passthrough`、`filehost`、`error` |
| `render.provider_config.local_local_resource_policy` | `file` | `file`、`passthrough`、`filehost` |

未传每次调用的 `resource_policy` 时，执行端严格采用`resource_resolve_mode`；显式 `ResourcePolicy` 会覆盖该默认值。`off` 调用不读取、物化或发布本地引用；若选中的 transport 是 `filehost`，composition 仍会准备publisher，使后续单次调用可以覆盖为 `auto` 或 `strict`。`auto` 容忍无法读取的引用，`strict` 则将其报告为资源错误。

远程模式推荐 `memory`：本地图片、字体和 CSS 被物化为 render-scoped asset，由页面 route 返回，不要求共享 filesystem。`passthrough` 仅适用于显式共享卷；`error` 用于禁止所有本地引用。

`filehost` 是需要真实 HTTP URL 时的兼容 transport，由 htmlrender 内置的 hosted
asset store 提供。可选 `filehost` extra 会安装 `py-machineid`，用于派生默认请求头守卫值：

```bash
uv add "nonebot-plugin-htmlrender[playwright,filehost]>=0.8.0,<0.9"
```

不安装该 extra 时 transport 仍可使用内置机器标识回退；对多副本或需要显式轮换的部署，直接配置 secret `render.resources.filehost.request_header_value`，不要依赖自动派生值。

两种远程 transport 遵循同一浏览器响应契约：`memory` 的 Page route 会返回正确媒体类型、cache header 与 `Access-Control-Allow-Origin: *`；filehost 只为通过请求头守卫的资源请求添加该 CORS 响应头，未认证请求返回 403。

!!! warning "filehost 代理必须保留双向 header"

    反向代理必须向 Bot 透传 `render.resources.filehost.request_header_name` 对应的请求头，并向浏览器保留 `Access-Control-Allow-Origin` 响应头。通配 CORS 只允许浏览器读取资源，不代替 filehost 授权。

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

路径授权不在 Provider 配置中；统一使用`render.resources.local_access.allow_any_path` 与`render.resources.local_access.allowed_paths`。

## typed Capability

通用 `render_*` 不接受导航、header 或 User-Agent。页面控制通过`app.extensions.playwright` 获取：

```python
from nonebot_plugin_htmlrender import get_default_application

playwright = get_default_application().extensions.playwright
async with playwright.page(
    viewport={"width": 1280, "height": 800},
    extra_http_headers={"X-Trace": "example"},
) as page:
    await page.goto("https://example.com")
```

远程部署与安全边界见 [远程 Playwright](../remote-playwright.md)。

若需要完整 `Browser` 能力而不只是一张自动回收的 Page，可改用`playwright.browser()`。它直接返回 Provider 所有的 Playwright Browser，保留上游全部类型提示；生命周期、资源所有权和 telemetry 约束见[Capability 参考](../../reference/capabilities.md#playwright)。
