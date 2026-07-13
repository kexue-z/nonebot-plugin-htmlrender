---
title: 安全须知
description: 渲染任意 HTML、本地资源暴露、远程连接的威胁面与防护建议
icon: lucide/shield-alert
status: new
tags:
  - Users
  - Security
---

# 安全须知

本插件让 NoneBot 进程拥有"渲染任意 HTML / 模板 / 截图任意 URL"的能力。
只要业务侧把不可信内容拼进渲染入口，整条链路就成为攻击面。
本页梳理威胁模型、默认防护与必要的加固选项。

## 威胁模型概览

| 入口 | 威胁 | 默认行为 | 责任方 |
| --- | --- | --- | --- |
| `render_html(...)` | 攻击者构造 HTML/JS 在浏览器进程执行 | 直接装载到 Page | 调用方 |
| `render_markdown(...)` | Markdown 携带原始 HTML、脚本或外链资源 | 转换后作为 HTML 片段装载到 Page，不做消毒 | 调用方 |
| `render_template(..., templates=...)` | 模板变量未转义被插入 HTML | Jinja2 `select_autoescape()` 仅对 `.html/.xml` 自动转义 | 调用方 |
| `capture_html_element(url, ...)` | 任意 URL 被远端浏览器请求 | 直接 `goto(url)` | 调用方 |
| filehost `/filehost/*` | 浏览器/外部请求读取本地文件 | 路径白名单 + 请求头守卫 | 配置方 |
| 远端 WS / CDP 连接 | 攻击者连接到运行中的浏览器服务 | 端点本身不带认证 | 部署方 |

简言之：**插件不会替你过滤业务输入**。需要按下文列出的位置加固。

## 渲染任意 HTML / Markdown

`render_html` 直接把字符串装载到 Playwright Page。Page 默认开启 JS 执行、网络访问。
如果调用方把用户输入直接拼进 HTML：

- 用户输入里的 `<script>` 会真实执行；
- 模板内的外链可能拉取攻击者控制的资源；
- 浏览器进程可对内网发起请求（参考下文 SSRF）。

### Markdown 原始 HTML

`render_markdown` 使用 Python-Markdown 生成 HTML。为了让段落、标题、引用块和
KaTeX 等转换结果形成真实 DOM，生成的 HTML 片段不会再经过 Jinja2 转义。
Python-Markdown 会保留输入中的原始 HTML，因此 `render_markdown` **不提供 HTML
消毒或安全边界**：输入中的 `<script>`、事件处理属性和带外链的元素可能进入页面，
脚本执行与网络访问风险和 `render_html` 相同。

模型输出也应视为不可信内容。用户可以通过提示词诱导模型输出原始 HTML、脚本或
指向内网的资源 URL；“内容由模型生成”不能替代输入校验。

建议：

- 不需要富文本时使用 `render_text`，其文本插槽保持 HTML 转义；
- 需要 Markdown 时，在调用 `render_markdown` 前按业务需求对原始 HTML 的标签、属性和 URL 做白名单清洗；
- 不可信数据需要进入自定义布局时，使用 `render_template` 的模板变量，不要拼接模板或 HTML 字符串；
- 不要拼字符串。`render_template` 默认 `select_autoescape()` 对 `.html/.xml` 后缀模板启用 HTML 转义，模板变量中的 `<` / `>` / `&` 会被转义；
- 自定义模板后缀（如 `.j2`）时显式开 `autoescape=True`，否则等于零防护；
- 需要原始 HTML 的字段，明确定义白名单标签集合后再交给模板，不要走 `|safe`。

```python
import jinja2

env = jinja2.Environment(
    loader=jinja2.FileSystemLoader("templates"),
    autoescape=jinja2.select_autoescape(default_for_string=True, default=True),
)
```

## SSRF 与外部请求

`render_html` / `render_markdown` / `render_template` / `capture_html_element`
触发的浏览器内网请求不受 NoneBot HTTP 客户端的限制。
攻击者可以让你的浏览器请求：

- 内网管理界面（`http://10.0.0.1/admin`）；
- 元数据服务（`http://169.254.169.254/`）；
- 本地服务（`http://localhost:6379` 等）。

加固选项：

- **不要让用户控制 URL/HTML 中的远程地址**。外链字段（图片、视频、iframe）必须做协议与域名白名单。
- 部署 Playwright 远端时，把它放在隔离网络环境，只暴露给业务进程；不要直接对接公网或 VPC 内核心服务。
- 通过 `proxy_server` / `proxy_bypass` 把浏览器流量收敛到出口代理，配合代理层做出站策略。
- 远端浏览器（CDP）必须屏蔽访问元数据/本地 loopback。常见做法：容器内用 `--no-sandbox` 但配合 namespace + 网络策略。

## Filehost 暴露面

filehost 把本地路径以 HTTP 形式暴露给"运行中的浏览器"。
误配置可能等价于把整个文件系统对外公开。

### 默认护栏

1. **路径白名单**：未传 `template_base` 且 `filehost_allowed_paths` 为空时，任何本地路径都会被拒绝（`Refused to expose local path via filehost without an allowed root.`）。
2. **目录隔离**：路径必须落在 `template_base` 或 `filehost_allowed_paths` 任一根目录下。否则报 `Local path ... is outside allowed filehost roots`。
3. **请求头守卫**：插件向 NoneBot 的 FastAPI 应用注入 `/filehost/*` 中间件，要求请求带 `X-HTMLRender-Filehost-Request: <token>`。token 默认基于设备指纹派生（`py-machineid` 或 MAC 地址）。
4. **请求侧自动附带 token**：插件渲染请求时通过 Playwright `extra_http_headers` 自动带上 token，配合中间件形成闭环。

### 风险开关

`render_playwright.filehost_allow_any_path=true` 会**完全跳过路径白名单**。
等同于把 NoneBot 进程的 filesystem 任意只读路径开放给当前 filehost 入口。仅在以下情境使用：

- 部署在严格隔离的容器中；
- 该容器没有任何敏感数据；
- filehost 入口本身不被外部访问。

否则保持默认 `false`。

### 多机/共享 token

跨机器部署或多 Bot 共用 filehost 入口时，默认基于设备派生的 token 不一致，请求会被守卫拦截（`403 Forbidden: missing or invalid filehost request header.`）。
显式指定共享 token：

```dotenv
RENDER_PLAYWRIGHT={"filehost_request_header_value":"<a-long-random-secret>"}
```

token 应当：

- 至少 32 字节随机；
- 仅在 trusted infra 内分发；
- 与 `filehost_request_header_salt` 配合使用毫无意义——salt 仅用于自动派生，显式 token 不参与派生。

### 守卫安装失败的影响

如果出现 `Filehost request guard unavailable (...): driver is not ASGI-based.` 或 `... is not FastAPI.`，
意味着 `/filehost/*` 端点裸露，没有 token 校验。**不要在生产忽略这条 warning**。
要么换支持的 driver，要么在网络入口（反向代理/网关）补一层鉴权。

### TTL 与瞬时性

- 文件类资源缓存 key 为 `path + mtime + size`，文件被覆盖会立刻失效；
- 默认 `filehost_cache_ttl_seconds=300`；过期后下次访问需重新上传；
- bytes/`BytesIO` 不缓存，每次都重新调用 `FileHost(...).to_url()`。

filehost 暴露的是**临时 URL**，但只要进程存活、TTL 未过、token 未变，URL 仍然有效。不要把它当成"截图后即失效"的一次性资源。

## 远端 WS / CDP 连接

Playwright Server 与 Chromium DevTools Endpoint **本身不带认证**。
任何能 TCP 触达端点的进程都可以接管你的浏览器：

- 加载任意网页；
- 读取已登录会话；
- 通过浏览器对内网发起请求。

加固：

- 端点只监听内网/Unix socket；不要直接对外暴露 `0.0.0.0`；
- 用 nginx / Caddy / 自建 reverse proxy 加 token 鉴权或 mTLS；
- 容器化部署时通过 docker network / VPC peering 限制访问者；
- 监控异常连接来源；
- WS 模式下，本地与远端 `playwright` 版本应一致，避免被攻击者用版本差异探测。

## 模板渲染的次生风险

Jinja2 模板本身可以执行代码（`{% set ... %}` / `{{ obj.__class__ ... }}`）。
**不要把用户输入直接当模板渲染**。本插件的所有 API 都把用户输入放在 `templates=...`（变量），而不是模板源码：

```python
# 安全
await render_template("templates", "card.html", templates={"user_input": value})

# 危险：把外部内容当模板源
await render_template_html(template=user_supplied_template_string)
```

业务侧若需要支持用户自定义模板，至少：

- 限制模板加载目录；
- 用 SandboxedEnvironment 替换默认 Environment；
- 移除 `__class__` / `__mro__` 等敏感属性访问。

## 日志与脱敏

插件已内置：

- 镜像/代理 URL 脱敏（移除查询串与 userinfo），见 `_redact_url`；
- 远端连接日志只打 host:port，不带凭据。

业务侧加日志时同样注意：

- 不要把 `templates=...` dict 完整 dump 到日志；
- 不要把 `extra_http_headers`（含 filehost token）原样落盘。

## 检查清单

部署前快速复核：

- [ ] 渲染入口已与不可信用户输入解耦（用模板变量而非字符串拼接）；
- [ ] 传给 `render_markdown` 的不可信内容已经过 HTML 标签、属性和 URL 白名单清洗；
- [ ] 自定义模板后缀时显式开 `autoescape=True`；
- [ ] 不要使用 `filehost_allow_any_path=true`，除非环境严格隔离；
- [ ] `filehost_allowed_paths` 显式列出可暴露目录，且不包含 `~`、`/etc`、`/var`、`/srv` 整目录；
- [ ] 多机部署时配置了共享 `filehost_request_header_value`；
- [ ] 启动日志没有 `Filehost request guard unavailable` 或类似 warning；
- [ ] 远端 WS / CDP 端点不直接对外暴露，前面有反代+鉴权；
- [ ] 对外可触达的字段做了 URL 协议/域名白名单；
- [ ] Sentry/Prometheus 不会泄露请求体或 filehost token。
