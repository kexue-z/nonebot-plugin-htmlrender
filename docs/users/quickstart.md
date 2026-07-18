---
title: 快速开始
description: 安装 Provider、配置插件并完成第一次渲染
icon: lucide/rocket
---

# 快速开始

## 1. 安装

本体默认不携带 Playwright、HTMLKit、Takumi、Pillow 或 Skia。仅需要
Preparation/模板到 HTML 时可直接安装 core：

```bash
uv add "nonebot-plugin-htmlrender>=0.8.0a1,<0.9"
```

core 同时包含 `nonebot-plugin-localstore`，用于为整个插件提供规范的数据目录；
它不是浏览器引擎依赖，也不会自行启用任何 Provider。

浏览器语义最完整，推荐首次接入选择 Playwright：

```bash
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0a1,<0.9"
uv run playwright install chromium
```

完全静态且不需要 JavaScript 的内容可以选择 Takumi：

```bash
uv add "nonebot-plugin-htmlrender[takumi]>=0.8.0a1,<0.9"
```

也可以试用无需浏览器进程的 HTMLKit；它当前只支持 asyncio，并要求调用时
显式使用 `device_pixel_ratio=1.0`、`height=None`：

```bash
uv add "nonebot-plugin-htmlrender[htmlkit]>=0.8.0a1,<0.9"
```

详见 [HTMLKit 配置与限制](config/htmlkit.md)。

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

Dotenv 需要把整个嵌套对象写入 `RENDER`：

```dotenv
RENDER={"provider":"playwright","startup":"warmup","resources":{"local_access":{"allowed_paths":["templates"]}}}
```

`startup: off` 延迟到第一次操作启动；`warmup` 在 NoneBot 启动时创建运行时；
`probe` 还会执行一次最小可用性探测。

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

下一步阅读 [API](api.md)；需要页面导航或元素截图时阅读
[Playwright typed Capability](api.md#playwright-capability)。
