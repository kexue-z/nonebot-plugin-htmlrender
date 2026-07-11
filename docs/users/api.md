---
title: API 与兼容层
description: 新 API 用法与迁移路径
icon: lucide/code-2
status: new
tags:
  - Users
  - API
---

# API 与兼容层

所有公共 API 均从 `nonebot_plugin_htmlrender` 顶层导入：

```python
from nonebot_plugin_htmlrender import render_text, render_markdown, render_template
```

---

## 渲染 API

### `render_text`

将纯文本渲染为图片。

```python
async def render_text(
    text: str,
    css_path: str = "",
    width: int = 500,
    image_type: Literal["jpeg", "png"] = "png",
    quality: Optional[int] = None,
    device_scale_factor: float = 2,
    screenshot_timeout: Optional[float] = 30_000,
    *,
    resource_strict: bool = False,
    render: Optional[RenderConfig] = None,
) -> bytes
```

| 参数                  | 类型                     | 默认值  | 说明                                  |
| --------------------- | ------------------------ | ------- | ------------------------------------- |
| `text`                | `str`                    | 必填    | 要渲染的纯文本内容                    |
| `css_path`            | `str`                    | `""`    | 自定义 CSS 文件路径，为空使用内置样式 |
| `width`               | `int`                    | `500`   | 视口宽度（像素）                      |
| `image_type`          | `Literal["jpeg", "png"]` | `"png"` | 输出图片格式                          |
| `quality`             | `Optional[int]`          | `None`  | JPEG 质量（0-100），仅 jpeg 有效      |
| `device_scale_factor` | `float`                  | `2`     | 设备像素比（DPR）                     |
| `screenshot_timeout`  | `Optional[float]`        | `30000` | 截图超时（毫秒）                      |
| `render`              | `Optional[RenderConfig]` | `None`  | 高级：覆盖完整渲染配置                |

**返回值：** `bytes` — 图片二进制数据

---

### `render_markdown`

将 Markdown 渲染为图片，内置 KaTeX 数学公式支持。

```python
async def render_markdown(
    markdown_text: str = "",
    md_path: str = "",
    css_path: str = "",
    width: int = 500,
    image_type: Literal["jpeg", "png"] = "png",
    quality: Optional[int] = None,
    device_scale_factor: float = 2,
    screenshot_timeout: Optional[float] = 30_000,
    *,
    render: Optional[RenderConfig] = None,
) -> bytes
```

| 参数                  | 类型                     | 默认值  | 说明                                                          |
| --------------------- | ------------------------ | ------- | ------------------------------------------------------------- |
| `markdown_text`       | `str`                    | `""`    | Markdown 文本，与 `md_path` 二选一；兼容层仍支持旧关键字 `md` |
| `md_path`             | `str`                    | `""`    | Markdown 文件路径，与 `markdown_text` 二选一                  |
| `css_path`            | `str`                    | `""`    | 自定义 CSS 文件路径，为空使用 GitHub 风格                     |
| `width`               | `int`                    | `500`   | 视口宽度（像素）                                              |
| `image_type`          | `Literal["jpeg", "png"]` | `"png"` | 输出图片格式                                                  |
| `quality`             | `Optional[int]`          | `None`  | JPEG 质量（0-100），仅 jpeg 有效                              |
| `device_scale_factor` | `float`                  | `2`     | 设备像素比                                                    |
| `screenshot_timeout`  | `Optional[float]`        | `30000` | 截图超时（毫秒）                                              |
| `resource_strict`     | `bool`                   | `False` | 无基址或无法读取的本地资源是否立即报错                        |
| `render`              | `Optional[RenderConfig]` | `None`  | 高级：覆盖完整渲染配置                                        |

**返回值：** `bytes` — 图片二进制数据

---

### `render_html`

将原始 HTML 渲染为图片。支持传入字符串或 `HtmlRenderRequest` 对象。

```python
async def render_html(
    request: Union[HtmlRenderRequest, str],
    wait: int = 0,
    template_path: Optional[str] = None,
    image_type: Literal["jpeg", "png"] = "png",
    quality: Optional[int] = None,
    device_scale_factor: float = 2,
    screenshot_timeout: Optional[float] = 30_000,
    *,
    full_page: bool = True,
    viewport: Optional[dict[str, int]] = None,
    user_agent: Optional[str] = None,
    extra_http_headers: Optional[dict[str, str]] = None,
) -> bytes
```

| 参数                  | 类型                            | 默认值  | 说明                                                     |
| --------------------- | ------------------------------- | ------- | -------------------------------------------------------- |
| `request`             | `Union[HtmlRenderRequest, str]` | 必填    | HTML 内容或完整渲染请求对象                              |
| `wait`                | `int`                           | `0`     | 截图前额外等待时间（毫秒）                               |
| `template_path`       | `Optional[str]`                 | `None`  | 页面 base URL（用于解析相对资源）                        |
| `image_type`          | `Literal["jpeg", "png"]`        | `"png"` | 输出图片格式                                             |
| `quality`             | `Optional[int]`                 | `None`  | JPEG 质量（0-100），仅 jpeg 有效                         |
| `device_scale_factor` | `float`                         | `2`     | 设备像素比                                               |
| `screenshot_timeout`  | `Optional[float]`               | `30000` | 截图超时（毫秒）                                         |
| `full_page`           | `bool`                          | `True`  | 是否截取完整页面                                         |
| `viewport`            | `Optional[dict[str, int]]`      | `None`  | 高级：覆盖页面视口，例如 `{"width": 800, "height": 600}` |
| `user_agent`          | `Optional[str]`                 | `None`  | 高级：覆盖页面 User-Agent                                |
| `extra_http_headers`  | `Optional[dict[str, str]]`      | `None`  | 高级：附加页面请求头                                     |

**返回值：** `bytes` — 图片二进制数据

常用高级参数：

- `viewport`：页面视口，例如 `{"width": 800, "height": 600}`
- `user_agent`：覆盖页面 UA
- `extra_http_headers`：为页面请求附加 header，例如远端 filehost 场景

---

### `render_template`

基于 Jinja2 模板渲染图片，支持资源解析（远程场景下将本地资源转为可访问 URL）。

```python
async def render_template(
    request: Union[TemplateRenderRequest, str],
    template_name: Optional[str] = None,
    templates: Optional[dict] = None,
    filters: Optional[dict[str, Any]] = None,
    pages: Optional[dict] = None,
    wait: int = 0,
    image_type: Literal["jpeg", "png"] = "png",
    quality: Optional[int] = None,
    device_scale_factor: float = 2,
    screenshot_timeout: Optional[float] = 30_000,
    *,
    resolve_resources: Optional[bool] = None,
    resource_resolver: Union[ResourceResolver, str, None] = None,
    resource_strict: bool = False,
) -> bytes
```

| 参数                  | 类型                                 | 默认值  | 说明                                                  |
| --------------------- | ------------------------------------ | ------- | ----------------------------------------------------- |
| `request`             | `Union[TemplateRenderRequest, str]`  | 必填    | 模板目录路径或完整请求对象                            |
| `template_name`       | `Optional[str]`                      | `None`  | 模板文件名（`request` 为字符串时必填）                |
| `templates`           | `Optional[dict]`                     | `None`  | 模板变量（键值对）                                    |
| `filters`             | `Optional[dict[str, Any]]`           | `None`  | 自定义 Jinja2 过滤器                                  |
| `pages`               | `Optional[dict]`                     | `None`  | 页面配置（`viewport`、`base_url`、`document_url` 等） |
| `wait`                | `int`                                | `0`     | 截图前额外等待时间（毫秒）                            |
| `image_type`          | `Literal["jpeg", "png"]`             | `"png"` | 输出图片格式                                          |
| `quality`             | `Optional[int]`                      | `None`  | JPEG 质量（0-100），仅 jpeg 有效                      |
| `device_scale_factor` | `float`                              | `2`     | 设备像素比                                            |
| `screenshot_timeout`  | `Optional[float]`                    | `30000` | 截图超时（毫秒）                                      |
| `resolve_resources`   | `Optional[bool]`                     | `None`  | 是否启用资源解析（`None` 由配置决定）                 |
| `resource_resolver`   | `Union[ResourceResolver, str, None]` | `None`  | 资源解析策略：`None`/`"auto"`/`"filehost"` 或自定义   |
| `resource_strict`     | `bool`                               | `False` | 严格模式：解析失败时是否直接抛错                      |

**返回值：** `bytes` — 图片二进制数据

`pages` 常用 key：

| key            | 说明                                         |
| -------------- | -------------------------------------------- |
| `viewport`     | 页面视口，如 `{"width": 480, "height": 240}` |
| `document_url` | 显式导航目标；仅设置后才调用 `page.goto()`                                  |
| `base_url`     | v0.7.1 导航字段的弃用兼容别名；新代码不要使用，也不再表示 prepared 资源基址 |

旧兼容入口曾把 `PageConfig.base_url` 用作导航目标。v0.7.2 会对这种用法发出弃用警告；新代码使用 `document_url`。资源基址由 `PreparedHtml.base_url` 表达，filesystem 模板与 Markdown/CSS 文件会在 preparation 时自动保留各自来源目录。

更完整的页面模型见文末的 `PageConfig` / `RenderConfig` 请求模型说明。

---

### `render_template_html`

仅渲染模板生成 HTML 字符串，不截图。适用于需要自行控制页面行为的场景。

```python
async def render_template_html(
    template: Union[TemplateConfig, str],
    template_name: Optional[str] = None,
    filters: Optional[dict[str, Any]] = None,
    **kwargs: Any,
) -> str
```

| 参数            | 类型                         | 默认值 | 说明                                    |
| --------------- | ---------------------------- | ------ | --------------------------------------- |
| `template`      | `Union[TemplateConfig, str]` | 必填   | 模板配置对象或模板目录路径              |
| `template_name` | `Optional[str]`              | `None` | 模板文件名（`template` 为字符串时必填） |
| `filters`       | `Optional[dict[str, Any]]`   | `None` | 自定义 Jinja2 过滤器                    |
| `**kwargs`      | `Any`                        | —      | 模板变量，直接作为关键字参数传入        |

**返回值：** `str` — 渲染后的 HTML 字符串

---

### `capture_html_element`

对指定 URL 页面中的某个元素截图。

```python
async def capture_html_element(
    url: str,
    element: str,
    page_kwargs: Optional[dict] = None,
    goto_kwargs: Optional[dict] = None,
    screenshot_kwargs: Optional[dict] = None,
) -> bytes
```

| 参数                | 类型             | 默认值 | 说明                                   |
| ------------------- | ---------------- | ------ | -------------------------------------- |
| `url`               | `str`            | 必填   | 目标页面 URL                           |
| `element`           | `str`            | 必填   | CSS 选择器（定位截图元素）             |
| `page_kwargs`       | `Optional[dict]` | `None` | 传给 `new_page()` 的额外参数           |
| `goto_kwargs`       | `Optional[dict]` | `None` | 传给 `page.goto()` 的额外参数          |
| `screenshot_kwargs` | `Optional[dict]` | `None` | 传给 `element.screenshot()` 的额外参数 |

**返回值：** `bytes` — 图片二进制数据

---

## 底层上下文

### `get_render_context`

异步上下文管理器，获取底层 Playwright `Page` 对象。适用于需要精细控制 `page.goto`、`page.screenshot` 等步骤的高级场景。

```python
@asynccontextmanager
async def get_render_context(**kwargs) -> AsyncIterator[Page]
```

```python
from nonebot_plugin_htmlrender import get_render_context

async with get_render_context() as page:
    await page.goto("https://example.com")
    await page.screenshot(path="output.png")
```

!!! tip

    大多数场景下 `render_*` API 已足够，仅在需要自定义页面行为时使用此接口。

---

## 资源解析

### `resolve_template_vars`

递归遍历模板变量 dict，将本地资源（`Path`、路径字符串、`bytes`）转换为可访问 URL。

```python
async def resolve_template_vars(
    template_vars: dict[str, Any],
    *,
    template_base: Union[str, Path, None] = None,
    strict: bool = False,
    resolver: Union[ResourceResolver, str, None] = None,
    lease_id: Optional[str] = None,
) -> dict[str, Any]
```

通常由 `render_template` 内部自动调用，无需手动使用。\
只有在你需要先做模板变量预处理、再把结果交给别的渲染逻辑时，才需要显式调用。

### `to_resource_url`

将单个本地资源转换为可访问 URL。

```python
async def to_resource_url(
    value: Union[str, Path, bytes],
    *,
    template_base: Union[str, Path, None] = None,
    strict: bool = False,
    resolver: Union[ResourceResolver, str, None] = None,
    lease_id: Optional[str] = None,
) -> str
```

适用场景：

- 你只需要处理一个资源，而不是整组模板变量
- 你要在自定义 HTML 拼装流程里拿到 filehost 或 `file://` URL

### `ResourceResolveError`

资源解析失败时抛出的异常（严格模式下）。继承自 `RuntimeError`。

---

## 生命周期

### `startup_render` / `probe_render` / `shutdown_render`

启动、探测和关闭默认渲染实例。通常由插件自动在 NoneBot `on_startup` / `on_shutdown` 中调用。

```python
async def startup_render(**kwargs) -> RenderSession
async def probe_render() -> None
async def shutdown_render() -> None
```

这组接口通常由插件在 NoneBot 生命周期中自动调用。\
业务插件不应把它们作为常规入口；只有在测试、手动预热或特殊部署控制场景下才需要显式调用。

### `get_render`

获取当前渲染会话。若会话不存在或已失效，自动创建新会话。

```python
async def get_render(**kwargs) -> RenderSession
```

### `get_default_render`

获取默认 `Render` 实例（同步）。若不存在则自动创建。

```python
def get_default_render() -> Render
```

---

## 后端状态查询

### `list_render_backend_statuses`

列出所有已注册后端的状态。

```python
def list_render_backend_statuses() -> tuple[BackendStatus, ...]
```

`BackendStatus` 包含字段：`backend`（`RenderBackend`）、`registered`（`bool`）、`available`（`bool`）、`reason`（`Optional[str]`）。

!!! info "关于 backend 枚举值"

    `RenderBackend` 里公开了 `playwright` / `skia` / `pillow` / `htmlkit`。\
    当前仓库正式实现的是 `playwright`；其他值不应被理解为“已经落地可用的正式 backend”。

### `get_render_backend_status`

查询指定后端的状态。

```python
def get_render_backend_status(backend: RenderBackend) -> BackendStatus
```

### `is_render_backend_available` / `is_render_backend_registered`

```python
def is_render_backend_available(backend: RenderBackend) -> bool
def is_render_backend_registered(backend: RenderBackend) -> bool
```

### `available_render_backends` / `registered_render_backends` / `unavailable_render_backends`

```python
def available_render_backends() -> tuple[RenderBackend, ...]
def registered_render_backends() -> tuple[RenderBackend, ...]
def unavailable_render_backends() -> tuple[RenderBackend, ...]
```

---

## 兼容层（已弃用）

以下 API 仅做转发和弃用提示，**不承载新能力**。

| 旧 API                | 新 API                 | 说明           |
| --------------------- | ---------------------- | -------------- |
| `text_to_pic`         | `render_text`          | 纯文本渲染     |
| `md_to_pic`           | `render_markdown`      | Markdown 渲染  |
| `html_to_pic`         | `render_html`          | HTML 渲染      |
| `template_to_pic`     | `render_template`      | 模板渲染       |
| `template_to_html`    | `render_template_html` | 模板生成 HTML  |
| `capture_element`     | `capture_html_element` | 元素截图       |
| `get_new_page`        | `get_render_context`   | 获取页面上下文 |
| `startup_htmlrender`  | `startup_render`       | 启动渲染       |
| `shutdown_htmlrender` | `shutdown_render`      | 关闭渲染       |

!!! warning "兼容层边界"

    兼容层只做转发与弃用提示，不承载新能力。\
    `render_template` 的资源解析参数（`resolve_resources` / `resource_resolver` / `resource_strict`）在兼容入口 `template_to_pic` 中不可用。

---

## 请求模型

渲染 API 支持传入结构化请求对象以进行精细控制：

- **`HtmlRenderRequest`** — HTML 渲染请求（`content` + `render` 配置）
- **`TemplateRenderRequest`** — 模板渲染请求（`template` + `render` 配置）
- **`TemplateConfig`** — 模板配置（路径、文件名、变量、过滤器）
- **`RenderConfig`** — 渲染配置（页面 + 截图选项）
- **`PageConfig`** — 页面配置（viewport、base_url、document_url、user_agent、extra_http_headers）
- **`ViewportConfig`** — 视口配置（width、height）

```python
from nonebot_plugin_htmlrender.backend.playwright.models import (
    HtmlRenderRequest,
    TemplateRenderRequest,
    TemplateConfig,
    RenderConfig,
    PageConfig,
    ViewportConfig,
)
```
