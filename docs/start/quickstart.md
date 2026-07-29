---
title: 快速开始
description: 安装 Provider、配置插件并完成第一次渲染
icon: lucide/rocket
---

# 快速开始

## 1. 安装

本体默认不携带 Playwright、HTMLKit、Takumi、Pillow 或 Skia。仅需要Preparation/模板到 HTML 时可直接安装 core：

```bash
uv add "nonebot-plugin-htmlrender>=0.8.0,<0.9"
```

浏览器语义最完整，推荐首次接入选择 Playwright。生产部署首选把浏览器放在独立 Docker 服务中，通过 WS 连接；Bot 宿主机只安装 Python client：

```bash
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0,<0.9"
```

Docker 服务的版本匹配、网络隔离和连接配置见[远程 Playwright 部署](../configuration/remote-playwright.md)。直接在 Bot 宿主机运行 Playwright 是第二选项，适合本地开发或无法部署独立服务的环境：

```bash
uv run playwright install --with-deps chromium
```

!!! warning "单机模式不要共享浏览器目录"

    浏览器必须由当前项目虚拟环境中的同一 Playwright 版本安装。不要手工替换浏览器文件，也不要让全局 CLI 或其他虚拟环境修改同一个浏览器目录，否则 client 要求的 browser revision 可能消失。为项目配置独占的 `storage_path`，并使用同一路径的 `PLAYWRIGHT_BROWSERS_PATH` 执行 `uv run playwright install`；依赖升级后必须重新安装。

macOS 或 Windows 本地开发不需要 Linux 系统包，使用 `uv run playwright install chromium`。`playwright` extra 不包含浏览器二进制或系统包；完整要求见 [Playwright 配置](../configuration/providers/playwright.md#browser-runtime-requirements)。

完全静态且不需要 JavaScript 的内容可以选择 Takumi：

```bash
uv add "nonebot-plugin-htmlrender[takumi]>=0.8.0,<0.9"
```

也可以试用无需浏览器进程的 HTMLKit；它当前只支持 asyncio，并要求调用时显式使用 `device_pixel_ratio=1.0`、`height=None`：

```bash
uv add "nonebot-plugin-htmlrender[htmlkit]>=0.8.0,<0.9"
```

详见 [HTMLKit 配置与限制](../configuration/providers/htmlkit.md)。

!!! important "Extra 不等于完整宿主环境"

    Playwright、HTMLKit、Takumi、Pillow 与 Skia 的 Python extra 负责选择 Python distribution；浏览器、native wheel 平台和宿主动态库仍需分别满足。尤其是 Linux 上的 Skia 还要求 `libEGL.so.1`、`libGL.so.1` 与 `libexpat.so.1`。完整对照见[部署依赖矩阵](choosing-provider.md#deployment-dependency-matrix)。

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
  provider_config:
    connect_ws:
      endpoint: ws://playwright:3000/
    remote_local_resource_policy: memory
  resources:
    local_access:
      allowed_paths: [templates]
```

该配置使用推荐的 Docker/WS 远程模式。若采用第二选项、直接在 Bot 宿主机运行浏览器，删除 `provider_config.connect_ws` 即可。

Dotenv 使用双下划线表示嵌套字段：

```dotenv
RENDER__PROVIDER=playwright
RENDER__STARTUP=warmup
RENDER__PROVIDER_CONFIG__CONNECT_WS__ENDPOINT=ws://playwright:3000/
RENDER__PROVIDER_CONFIG__REMOTE_LOCAL_RESOURCE_POLICY=memory
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
