---
title: 快速开始
description: 安装 Provider、配置插件并完成第一次渲染
icon: lucide/rocket
---

# 快速开始

## 1. 安装

本体默认不携带 Playwright、HTMLKit、Takumi、Pillow 或 Skia。仅需要Preparation/模板到 HTML 时可直接安装 core：

```bash
uv add "nonebot-plugin-htmlrender>=0.8.0a1,<0.9"
```

浏览器语义最完整，推荐首次接入选择 Playwright：

```bash
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0a1,<0.9"
uv run playwright install chromium
```

完全静态且不需要 JavaScript 的内容可以选择 Takumi：

```bash
uv add "nonebot-plugin-htmlrender[takumi]>=0.8.0a1,<0.9"
```

也可以试用无需浏览器进程的 HTMLKit；它当前只支持 asyncio，并要求调用时显式使用 `device_pixel_ratio=1.0`、`height=None`：

```bash
uv add "nonebot-plugin-htmlrender[htmlkit]>=0.8.0a1,<0.9"
```

详见 [HTMLKit 配置与限制](../configuration/providers/htmlkit.md)。

## 2. 配置

`pyproject.toml`：

```toml
[tool.nonebot]
plugins = ["nonebot_plugin_htmlrender"]
```

NoneBot 配置：

```yaml
render:
  provider: playwright
  startup: warmup
  resources:
    local_access:
      allowed_paths: [templates]
```

Dotenv 使用双下划线表示嵌套字段：

```dotenv
RENDER__PROVIDER=playwright
RENDER__STARTUP=warmup
RENDER__RESOURCES__LOCAL_ACCESS__ALLOWED_PATHS='["templates"]'
```

完整 JSON、环境文件优先级及其他后端示例见[`.env` 配置](../configuration/dotenv.md)。

`startup: off` 延迟到第一次依赖 Provider runtime 的操作再启动；`warmup` 在 NoneBot启动时创建运行时；`probe` 还会执行一次最小可用性探测。

## 3. 渲染

```python
from nonebot import require

require("nonebot_plugin_htmlrender")

from nonebot_plugin_htmlrender import render_markdown

async def make_image() -> bytes:
    artifact = await render_markdown(
        "# Status\n\n- Provider ready\n- Typed artifact",
        width=720,
        timeout_seconds=15,
    )
    return bytes(artifact)
```

模板示例：

模板目录必须位于 `render.resources.local_access.allowed_paths` 中。

```python
from pathlib import Path

from nonebot_plugin_htmlrender import render_template

TEMPLATES = Path(__file__).parent / "templates"

async def make_card(name: str) -> bytes:
    artifact = await render_template(
        TEMPLATES,
        "card.html",
        variables={"name": name},
        width=480,
        height=320,
    )
    return bytes(artifact)
```

## 4. 发送到消息适配器

```python
artifact = await render_markdown("**hello**")
await matcher.finish(UniMessage(Image(raw=bytes(artifact))))
```

下一步按需查阅[参考手册](../reference/index.md)；需要页面导航或元素截图时阅读[操作浏览器页面](../guides/browser-automation.md)。
