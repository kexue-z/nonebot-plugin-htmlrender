---
title: 示例项目
description: 三个独立示例项目，覆盖网页截图、本地模板渲染和远程浏览器渲染场景
icon: lucide/folder-open
status: new
tags:
  - Users
  - Examples
---

# 示例项目

仓库 `examples/` 目录下提供了三个独立的 NoneBot 示例项目，分别演示插件的核心使用场景。

每个示例都是完整的 nb-cli 项目，可直接复制到你的 Bot 中使用。

## 网页截图 { #screenshot }

> 目录：`examples/screenshot/`
> 入口：`examples/screenshot/plugins/screenshot/__init__.py`

使用 `get_render_context` 获取 Playwright Page 对象，直接对网页进行截图；
或使用 `capture_html_element` 截取页面中指定 CSS 选择器的元素。

### 命令

| 命令                  | 说明                                          |
| --------------------- | --------------------------------------------- |
| `/screenshot [url]`   | 对指定 URL 进行全页截图，默认截取 GitHub 首页 |
| `/capture <selector>` | 截取 GitHub 首页中指定 CSS 选择器的元素       |

### 核心代码

```python
from nonebot_plugin_htmlrender import get_render_context, capture_html_element
from playwright.async_api import Page

# 全页截图
async with get_render_context(viewport={"width": 1280, "height": 800}) as context:
    page: Page = context  # type: ignore[assignment]
    await page.goto("https://github.com", wait_until="networkidle")
    img = await page.screenshot(full_page=True, type="png")

# 元素截取
img = await capture_html_element(
    "https://github.com",
    "div.application-main",
    page_kwargs={"viewport": {"width": 1280, "height": 800}},
    goto_kwargs={"wait_until": "networkidle", "timeout": 30000},
    screenshot_kwargs={"type": "png"},
)
```

### 使用的 API

- [`get_render_context`](api.md) — 获取底层 Playwright Page，适合需要精细控制页面行为的场景
- [`capture_html_element`](api.md) — 一步到位截取指定元素

### 适合什么时候看这个示例

- 你需要自己控制 `page.goto()`、等待网络稳定、点击后截图
- 你要截整页或指定元素，而不是直接把模板渲染成图片

---

## 本地模板渲染 { #template-render }

> 目录：`examples/template_render/`
> 入口：`examples/template_render/plugins/template_render/__init__.py`

使用 Jinja2 模板 + CSS 渲染自定义卡片图片，附带一个纯文本转图片的示例。

### 命令

| 命令                  | 说明               |
| --------------------- | ------------------ |
| `/profile [username]` | 渲染用户资料卡片   |
| `/textimg <content>`  | 将纯文本渲染为图片 |

### 项目结构

```text
plugins/template_render/
├── __init__.py
└── templates/
    ├── profile.html          # Jinja2 模板
    └── style.css             # 样式表
```

### 核心代码

```python
from nonebot_plugin_htmlrender import render_template, render_text

TEMPLATE_DIR = Path(__file__).parent / "templates"

# 模板渲染：传入模板目录、模板名和变量
img = await render_template(
    str(TEMPLATE_DIR),
    template_name="profile.html",
    templates={
        "avatar_text": "N",
        "username": "NoneBot User",
        "level": 42,
        "stats": [
            {"label": "Days", "value": "128"},
            {"label": "Plugins", "value": "15"},
            {"label": "Messages", "value": "3.2k"},
        ],
    },
    pages={"viewport": {"width": 440, "height": 300}},
)

# 纯文本渲染
img = await render_text("Hello World", width=600)
```

!!! tip "关于 `base_url`"

    filesystem 模板自动以模板目录解析 CSS、图片等相对资源，不需要页面参数。`pages["base_url"]` 是 v0.7.1 导航字段的弃用别名；新代码只在确实需要先打开网页时使用 `document_url`。自定义 prepared 文档的资源基址由 `PreparedHtml.base_url` 表达。

### 使用的 API

- [`render_template`](api.md) — Jinja2 模板渲染为图片
- [`render_text`](api.md) — 纯文本渲染为图片

### 适合什么时候看这个示例

- 你想把页面结构沉淀成模板，而不是拼 HTML 字符串
- 你需要本地 CSS、静态图片和模板变量一起协作

---

## 远程浏览器渲染 { #remote-browser }

> 目录：`examples/remote_browser/`
> 入口：`examples/remote_browser/plugins/remote_render/__init__.py`

演示通过 CDP 或 WebSocket 连接远程浏览器进行渲染。适合 Bot 部署在无桌面环境的服务器，或多个 Bot 共享同一浏览器实例的场景。

项目附带 `docker-compose.yml`，一键启动远程 Chromium。

### 命令

| 命令              | 说明                                     |
| ----------------- | ---------------------------------------- |
| `/render_status`  | 查看渲染后端连接状态                     |
| `/rshot [url]`    | 通过远程浏览器截图，默认截取 GitHub 首页 |
| `/rmd <markdown>` | 通过远程浏览器将 Markdown 渲染为图片     |

### 快速启动

```bash
cd examples/remote_browser
docker compose up -d        # 启动远程 Chromium
cp .env.prod .env           # 使用预设的 CDP 配置
nb run                      # 启动 Bot
```

### 远程模式配置

=== "CDP（Chrome DevTools Protocol）"

    仅支持 Chromium，适合 Docker 部署：

    ```dotenv
    RENDER_BACKEND=playwright
    RENDER_PLAYWRIGHT__CONNECT_CDP__ENDPOINT=http://localhost:9222
    ```

=== "WebSocket"

    支持 Chromium / Firefox / WebKit：

    ```dotenv
    RENDER_BACKEND=playwright
    RENDER_PLAYWRIGHT__CONNECT_WS__ENDPOINT=ws://localhost:3000
    ```

!!! warning "二选一"

    CDP 和 WebSocket 端点不能同时设置，否则启动时会抛出错误。

### 使用的 API

- [`get_render_context`](api.md) — 获取远程浏览器 Page
- [`render_markdown`](api.md) — Markdown 渲染
- [`list_render_backend_statuses`](api.md) — 查看后端状态

### 适合什么时候看这个示例

- 你已经决定浏览器与业务进程分离部署
- 你需要确认 CDP / WS 配置、远程截图与后端状态查询怎么串起来

---

## 通用接入步骤

所有示例项目的接入流程一致：

1. 使用 nb-cli 创建项目并安装依赖：

    ```bash
    nb create
    nb plugin install nonebot-plugin-htmlrender
    nb plugin install nonebot-plugin-alconna
    ```

1. 将示例中的 `plugins/<name>` 目录复制到你的项目插件目录

1. 在 `.env` 中添加：

    ```dotenv
    RENDER_BACKEND=playwright
    ```

1. 启动 Bot：

    ```bash
    nb run
    ```
