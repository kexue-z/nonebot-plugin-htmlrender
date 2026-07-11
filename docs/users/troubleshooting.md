---
title: 故障排查
description: 高频报错与修复手册
icon: lucide/wrench
status: new
tags:
  - Users
  - Troubleshooting
---

# 故障排查

按报错信息检索，每条给出根因与修复路径。
日志全文中通常包含来自 Playwright / Filehost 的二级错误，请一并附上再判断。

## 启动阶段

### `Render runtime startup failed.`

NoneBot `on_startup` 阶段拉起渲染失败时抛出，原因来自二级 exception。常见情况：

- 配置缺失：`RENDER_BACKEND` 未设置或值错误。检查 `.env` 或 `nonebot.init` 是否传了 `render_backend="playwright"`。
- Playwright 未安装：见下一条。

排查：开启 DEBUG 日志看 `Failed to start render runtime.` 之前的 traceback，根因在那里。

### `Playwright environment is not set up correctly.`

本地启动浏览器时所有候选路径都失败抛出。Playwright 浏览器二进制缺失或被系统隔离。

修复：

```bash
make install-browser
# 等价于
uv run playwright install --with-deps chromium
```

如果依赖系统级浏览器：

```dotenv
RENDER_PLAYWRIGHT={"engine":"chromium","executable_path":"/usr/bin/chromium"}
```

机器无法访问 Playwright 下载源时配镜像：

```dotenv
RENDER_PLAYWRIGHT={"install_mirror":"https://npmmirror.com/mirrors/playwright/","install_proxy":"http://127.0.0.1:7890"}
```

参考链接见报错末尾给出的 [Playwright system requirements](https://playwright.dev/python/docs/intro#system-requirements)。

### `install_browser failed: ...`

`playwright install` 子进程失败。典型原因：

- 网络下载超时：默认 `PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=300000`（5 分钟）已设，仍失败时换镜像或代理。
- 磁盘空间不足。
- 权限不足无法写入安装目录（容器内尤其常见）。

如果你的部署环境**不希望插件自动装浏览器**：

```dotenv
RENDER_PLAYWRIGHT={"skip_browser_install":true}
```

设为 `true` 后，本地浏览器缺失时会直接拒绝可用，并在 `list_render_backend_statuses()` 中暴露原因，而不是反复尝试下载。

### `No installed Playwright browser was found for chromium ...`

`skip_browser_install=true` 但本地确实没有浏览器。两种解法：

- 提前装好（CI/容器构建阶段执行 `playwright install`）。
- 退回到自动安装：`skip_browser_install=false`。

## 远程连接

### `Invalid configuration: connect_cdp.endpoint and connect_ws.endpoint cannot both be set.`

两种远程模式互斥。只保留一个：

```dotenv
# 选其一
RENDER_PLAYWRIGHT={"connect_ws":{"endpoint":"ws://host:3000/"}}
# RENDER_PLAYWRIGHT={"connect_cdp":{"endpoint":"http://host:9222/"}}
```

### `CDP connection requires render_playwright.engine="chromium".`

CDP 仅支持 Chromium 系。把 `engine` 显式设为 `chromium` 或换 WS 模式。

### `WS endpoint is empty.` / `CDP endpoint is empty.`

`connect_ws.endpoint` 或 `connect_cdp.endpoint` 配置成了空字符串。检查环境变量解析是否正确。

### `WS version mismatch is out of allowed range: local=..., remote=...`

本地 `playwright` 包版本与远端 Playwright Server 差距过大，连接被拒绝。
固定本地与远端使用同一 minor 版本：

```bash
uv add "playwright==<remote-version>"
```

如果远端版本无法读取，会降级为 warning（`WS version gate: unable to detect remote Playwright version`）继续连接。

### `Local playwright package version is unavailable.`

本地未装 `playwright` 包。`uv sync` 后重试。

## 渲染阶段

### `screenshot timeout` / `Page.screenshot: Timeout ... exceeded`

Playwright 截图超时（默认 30s）。提高 `screenshot_timeout`：

```python
img = await render_template(
    "templates",
    template_name="card.html",
    templates={...},
    screenshot_timeout=60_000,
)
```

更常见的根因是页面里有外链资源加载不下来阻塞渲染。优先排查：

- 模板里是否有外部 CDN/字体被墙。
- 本地路径是否能按 `base_url` 物化为 `PreparedAsset`（参考 [远程 Playwright 与资源桥](remote-playwright.md)）。

### `HTML content cannot be empty` / `template_path cannot be empty` / `template_name cannot be empty`

请求模型校验失败：传入了空字符串。检查调用入参，特别是 `request` 是字符串路径时必传 `template_name`。

### `template_name is required when ... is a path string`

直接给 `render_template` / `render_template_html` 传字符串路径时必须配套 `template_name`。
更稳的写法是用 `TemplateRenderRequest` / `TemplateConfig` 显式构造请求对象。

### `base_url must start with 'file://', 'http://', 'https://', or 'about:'`

`PageConfig.base_url` 是 v0.7.1 导航字段的弃用兼容别名，只接受这四类 URL scheme。新代码将导航目标放入 `PageConfig.document_url`；filesystem 模板、Markdown 与 CSS 的资源基址由 preparation source 自动保留。

不要再用 Page 配置表达 prepared resource base。原始 HTML 的显式资源基址应通过 `prepare_html(..., base_url=...)` 写入 `PreparedHtml.base_url`。

### 远程 `Page.goto: net::ERR_FILE_NOT_FOUND`

若日志中的 URL 指向 Bot 容器内的 `site-packages/.../templates/*.html`，说明仍在运行 v0.7.1 或更早的 `file://` 文档导航路径。v0.7.2 的 text、Markdown 和普通模板会在 `about:blank` 上 `page.set_content()`，本地资源默认经内存资产桥传输。

确认：

1. 实际安装版本为 v0.7.2，且容器没有挂载旧 wheel；
1. 没有显式设置 `document_url=file:///...`；
1. 共享卷部署才选择 `passthrough`，普通跨容器部署保持 `auto + memory`；
1. 不需要为 `md_to_pic` 手工提供 HTTP `base_url`。

## 资源解析与 Filehost

### `Refused to expose local path via filehost without an allowed root.`

filehost 拒绝暴露任意本地路径。在严格模式下抛错；非严格模式记录 warning 后原值返回。
解决：

- 渲染时传 `template_base=Path("templates_dir")`，显式划定可暴露根。

- 全局配置白名单：

    ```dotenv
    RENDER_PLAYWRIGHT={"filehost_allowed_paths":["/srv/bot/assets"]}
    ```

- 信任部署环境时显式开放（**不推荐**）：

    ```dotenv
    RENDER_PLAYWRIGHT={"filehost_allow_any_path":true}
    ```

    详见 [安全须知](security.md)。

### `Local path ... is outside allowed filehost roots: ...`

路径不在任何允许根下。要么把目录加入 `filehost_allowed_paths`，要么传 `template_base` 指到该目录的祖先。

### `nonebot-plugin-filehost is required for filehost resource resolution.`

未安装 `nonebot-plugin-filehost`。

```bash
uv add "nonebot-plugin-htmlrender[filehost]"
```

### `Filehost request guard unavailable (... ): driver is not ASGI-based.` / `... is not FastAPI.`

filehost 的 `/filehost/*` 请求头守卫安装失败，浏览器请求会被原服务直接受理（无 token 校验）。原因：

- 当前 NoneBot driver 不是 ASGI（如 BotProtocol）。
- ASGI app 不是 FastAPI（守卫依赖 FastAPI 中间件机制）。

修复：换 ASGI + FastAPI driver（NoneBot 默认 `~fastapi`），或在网络边界自行加 token 鉴权。

### `Filehost plugin bootstrap failed (...): ...`

严格模式下 filehost 插件初始化失败抛出。检查 traceback；典型原因是 `nonebot-plugin-filehost` 未启用 driver 兼容、未在 `nonebot.init` 之前 `require`。

### `Local resources are not allowed under current resource policy.`

`remote_local_resource_policy` 设为 `error`。如果实际需要使用本地资源：

- 保持默认 `memory`，让资源通过当前 Page 的内存 route 传输。
- 既有系统必须提供 HTTP URL 时改成 `filehost`。
- 调用方提前把本地资源转 URL，避免命中本地资源识别。

### `Resolved resource is not URL text: got bytes.`

调用 `to_resource_url(bytes_value)` 但 resolver 不接受 bytes。`filehost` 策略支持 `str/Path/bytes`；`file` 策略仅支持路径。

## 渲染产物异常

### CJK 字符显示为方框 / 缺字体

容器中通常没装中文字体。`uv run playwright install --with-deps` 不一定带 CJK，按发行版补：

```bash
# Debian/Ubuntu
apt-get install -y fonts-noto-cjk fonts-noto-color-emoji
# Alpine
apk add font-noto-cjk
```

远端模式下应在远端浏览器镜像中装字体，本地仅渲染模板/截图。

### 图片输出空白 / 内容未加载完

页面 onload 完成但脚本/图片仍在加载就被截图。建议：

- 给 `render_html` / `render_template` 传 `wait`（毫秒）显式延迟。
- 如果模板里依赖外链 CDN，优先把资源本地化并交给内存资产桥。
- 非必要不要在模板里使用 SPA/客户端渲染框架。

### `RENDER_STARTUP_MODE=probe` 启动慢

`probe` 模式会创建一次最小页面上下文。若启动时间敏感（如冷启容器），降级为 `warmup`：

```dotenv
RENDER_STARTUP_MODE=warmup
```

或 `off`，延后到首次调用再拉起。代价是问题暴露时机变晚。

## 缓存与残留

### `Legacy Playwright cache directory detected ...`

旧版本默认把 Playwright 浏览器装在系统级路径（如 `~/Library/Caches/ms-playwright`），新版改为项目级缓存。
默认仅告警；要自动清理：

```dotenv
RENDER_PLAYWRIGHT={"cleanup_legacy_cache":true}
```

如不希望清理但又想消除告警，把旧目录手动删掉即可。

### Filehost 上传次数过多

v0.7.2 对 `Path`、`bytes`、`bytearray` 与 `BytesIO` 都按内容 SHA-256 去重，并对相同 digest 使用 singleflight。若上传仍持续增长：

- 检查输入内容是否每次都实际变化；
- 检查 `filehost_cache_ttl_seconds` 是否过短——它只控制 URL mapping TTL；
- 优先确认是否真的需要 filehost，普通远程渲染应使用默认内存资产桥；
- 通过低基数的 upload bytes、dedup hits、active mappings/leases 指标判断是内容变化还是 mapping 过期。

mapping 清理不会逐文件删除 filehost 物理文件；物理目录由 filehost 进程生命周期管理。
