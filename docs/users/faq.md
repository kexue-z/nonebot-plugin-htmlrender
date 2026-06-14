---
title: 常见问题
description: 接入与使用过程中最常被问到的问题
icon: lucide/circle-help
status: new
tags:
  - Users
  - FAQ
---

# 常见问题

## 接入与定位

### 为什么 `/render` 之类的命令没出现？

本插件是 **library 类型**，不内置任何 `message matcher`。
调用方需要在自己的业务插件中处理命令或事件，再调用 `render_*` API 返回图片。
模板和命令的最小写法见 [最佳实践](best-practices.md) 第 1 节。

### 远程渲染和本地渲染怎么选？

| 场景 | 建议 |
| --- | --- |
| 单机部署、并发不高、对启动时间敏感 | 本地 |
| 多 Bot 实例共用浏览器、容器化部署、希望与业务进程解耦 | 远程 |
| 已有 Chromium/CDP 基础设施 | 远程（CDP） |
| 想要完整 Playwright 能力栈（多引擎、跟随版本） | 远程（WS） |

远程模式的代价是必须额外解决"远端读不到本地资源"的问题，参考 [远程 Playwright 与 Filehost](remote-playwright.md)。

### 一定要装系统级 Chromium 吗？

不需要。`playwright install --with-deps chromium` 会下载浏览器到 Playwright 自己的缓存目录。
插件首次启动时会自动尝试这条命令（除非 `skip_browser_install=true`）。

只有以下情况才需要系统级浏览器：

- 离线环境，提前打入镜像；
- 想用 Chrome Stable / Beta / Dev 等 channel；
- 部署平台不允许 Playwright 写自定义路径。

后两种通过 `executable_path` 或 `channel` 配置即可。

### 浏览器装在哪？怎么换路径？

新版默认装在项目级缓存目录（`PLAYWRIGHT_BROWSERS_PATH` 或当前 venv 关联路径）。
如果你看到旧的全局路径告警 `Legacy Playwright cache directory detected`，可以：

```dotenv
RENDER_PLAYWRIGHT={"cleanup_legacy_cache":true}
```

让插件启动时自动清理。否则手动 `rm -rf ~/Library/Caches/ms-playwright` 也行（macOS）。

## API 与配置

### 要不要每次都传 `RenderConfig` / `PageConfig`？

不需要。`render_*` 顶层 API 都把常用参数（`width` / `image_type` / `quality` / `device_scale_factor` / `screenshot_timeout` / `viewport` / `user_agent` / `extra_http_headers` 等）拍平成关键字参数。
只有需要更精细控制（同时改多组配置、复用 preset）时再传 `render=RenderConfig(...)`。

### 怎么改 Markdown 默认样式？

传 `css_path`：

```python
img = await render_markdown(text, css_path="assets/my-md.css")
```

留空会使用内置 `github-markdown-light.css`。
如果只是想覆盖几条规则，建议复制内置 CSS 后再改，避免覆盖不全。

### `render_template` 怎么传变量？

`templates` 参数是 dict，键名要与 Jinja2 模板变量对得上：

```python
img = await render_template(
    "templates",
    template_name="card.html",
    templates={"user": "Alice", "score": 100},
)
```

dict 中的 `Path` / 路径字符串在启用资源解析时会被自动转换为可访问 URL，参考 [API 与兼容层](api.md) 中 `render_template` 一节。

### `get_render_context` 和 `render_html` 区别？

- `render_html`：黑盒接口，传入 HTML/请求拿图片，自己不接触 Page。
- `get_render_context`：异步上下文，拿到 Playwright `Page`，可以自己 `goto` / `evaluate` / `screenshot`。

只在以下场景用 context：

- 需要操作 cookie / 认证流程；
- 需要交互（点击 / 滚动）后再截图；
- 需要等待复杂的网络/JS 行为。

### 远程模式下 `executable_path` 还有用吗？

没用。远程模式（`connect_ws` / `connect_cdp`）由远端控制浏览器二进制。本地的 `executable_path` / `launch_args` 只在 launch 模式下生效。

## 故障与限制

### 启动很慢 / 容器冷启动超时

`startup_mode=probe`（推荐）会拉浏览器并做一次最小渲染验证，慢但能提前暴露问题。
对启动时间敏感时降为：

- `warmup`：只拉浏览器，不做探测渲染；
- `off`：插件加载阶段不触碰渲染层，等首次 API 调用再拉起。

代价是 `probe` 能在启动时拦截的错误（缺字体、无法连远端等）改为运行期再暴露。

### 一张图渲染得太慢

按链路自上而下排查：

1. **模板层**：是否引用外链 CDN/字体？尽量把资源放到本地或 filehost；
2. **截图层**：调高 `screenshot_timeout`，但同时检查页面是否真的 onload；
3. **会话层**：远程模式下网络 RTT 大；高频调用考虑本地，或在远端边缘部署；
4. **后端层**：`close_on_exit=false` 让浏览器进程长驻，避免每次 session 关闭都重启。

### 多次调用看上去"卡住"

通常是 session 复用没生效或被竞争。先用 `list_render_backend_statuses()` 看后端状态；
再确认远端 endpoint 没限流；最后看 Bot 主线程是否被同步代码阻塞。

### 兼容层旧 API 还能用多久？

兼容层只做转发与弃用提示，不承载新能力，何时移除取决于版本计划。
新项目直接用新 API；存量项目按 [迁移指南](migration.md) 推进，调用日志里的 `DeprecationWarning` 是直接的 TODO 列表。

## 部署相关

### filehost 必须开吗？

只在远程模式下需要。本地模式直接读 `file://` 即可。
远程时如果模板里只有外链资源（HTTP CDN），也可以不开 filehost，让远端浏览器自己拉。
本地资源（图片、字体、相对路径 CSS）才需要 filehost 把它们临时托管。

### 远程渲染会泄露我的本地文件吗？

**默认不会**。filehost 默认只暴露调用方明确给定的资源（受 `filehost_allowed_paths` 与 `template_base` 双重约束），且 `/filehost/*` 端点带请求头守卫。
但如果你显式打开 `filehost_allow_any_path=true`，就等于绕过路径白名单，需要自己评估风险。
完整说明参考 [安全须知](security.md)。

### 多个 Bot 共用同一远端浏览器可以吗？

可以。WS / CDP 都支持多客户端连接。
注意：

- 不同 Bot 实例使用各自的 filehost token（默认基于设备派生）。如果要在多机间共享 filehost 入口，应显式配置 `filehost_request_header_value` 让多端 token 一致；
- 远端浏览器的并发能力受服务端配置约束，超出后请求会排队。

### CI/CD 里如何加速？

- 把 `playwright install --with-deps chromium` 放在镜像构建阶段，运行时设 `skip_browser_install=true`；
- 把 `node_modules`（如果有）和 Playwright 浏览器缓存上 cache action；
- 测试用 `make test-ci`（不依赖真浏览器），需要真浏览器再 `make test-local`。

## 观测与监控

### Sentry / Prometheus 怎么开？

按需安装 extras，再在配置里启用：

```bash
uv add "nonebot-plugin-htmlrender[sentry,prometheus]"
```

```dotenv
RENDER_TELEMETRY={"sentry":{"enabled":true,"dsn":"..."},"prometheus":{"enabled":true}}
```

具体字段与默认值参考 [依赖扩展与观测](config/integrations.md)。

### 怎么知道当前后端到底在用哪个浏览器？

```python
from nonebot_plugin_htmlrender import list_render_backend_statuses

for status in list_render_backend_statuses():
    print(status.backend, status.registered, status.available, status.reason)
```

启动时也会有 `Connecting to Chromium via CDP / WS` 或 `Using local <engine>` 日志。
