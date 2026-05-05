---
title: 快速开始
description: 以最短路径接入 nonebot-plugin-htmlrender
icon: lucide/rocket
status: new
tags:
  - Users
  - Getting Started
---

# 快速开始

## 接入前提

开始前只需要先明确两件事：

- 这是一个库型插件，你会在自己的代码里调用它
- 新版需要显式指定渲染后端，默认推荐 `playwright`

## 安装

=== "基础安装"

    ```bash
    uv add nonebot-plugin-htmlrender
    ```

=== "包含 filehost 能力"

    ```bash
    uv add "nonebot-plugin-htmlrender[filehost]"
    ```

=== "包含全部可选能力"

    ```bash
    uv add "nonebot-plugin-htmlrender[filehost,sentry,prometheus]"
    ```

## 最小配置

对大多数本地接入场景，最小配置只需要指定后端：

=== "Dotenv"

    ```dotenv
    RENDER_BACKEND=playwright
    ```

=== "nonebot.init"

    ```python
    import nonebot

    nonebot.init(render_backend="playwright")
    ```

完整配置说明见 [基础配置与加载](config/core.md)。

## 加载插件

```python
from nonebot import require

require("nonebot_plugin_htmlrender")
```

## 最小调用示例

```python
from nonebot_plugin_htmlrender import render_markdown

image = await render_markdown("# Hello\n\n**World**")
```

这时 `image` 的类型是 `bytes`，你可以把它交给适配器发送，或写入文件做调试。

## 一个更贴近真实业务的例子

```python
from nonebot import on_command, require

require("nonebot_plugin_htmlrender")

from nonebot_plugin_htmlrender import render_template

show_profile = on_command("profile")


@show_profile.handle()
async def handle_profile() -> None:
    image = await render_template(
        "templates",
        template_name="profile.html",
        templates={"name": "Tacrolimus", "score": 98},
    )
```

## 模板目录的最小可运行例子

如果你要接 `render_template`，至少要有一份模板目录和一个可解析的 `base_url`：

```python
from pathlib import Path

from nonebot_plugin_htmlrender import render_template

TEMPLATE_DIR = Path("templates")

image = await render_template(
    str(TEMPLATE_DIR),
    template_name="card.html",
    templates={"title": "Hello", "value": "World"},
    pages={
        "viewport": {"width": 480, "height": 240},
        "base_url": TEMPLATE_DIR.resolve().as_uri(),
    },
)
```

这条路径更适合本地模式。  
如果你接的是远程浏览器，请继续看 [远程 Playwright 与 Filehost](remote-playwright.md) 中关于 `about:blank`、资源解析和 filehost 的说明。

## 下一步该看什么

如果你已经能成功渲染第一张图，下一步按需要继续：

- 想看公共接口：去 [API 与兼容层](api.md)
- 想整理配置：去 [配置总览](config/index.md)
- 想接远程浏览器或 filehost：去 [远程 Playwright 与 Filehost](remote-playwright.md)
- 想从旧项目迁移：去 [旧版本迁移指南](migration.md)

如果启动阶段直接失败，先看 [故障排查](troubleshooting.md) 里的 `Render runtime startup failed.` 与 Playwright 安装相关条目。
