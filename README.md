<div align="center">

<img src="docs/assets/nonebot_plugin.svg" alt="nonebot-plugin-htmlrender" width="180" />

# nonebot-plugin-htmlrender

> 面向 NoneBot 的可插拔 HTML 渲染库

[![PyPI](https://img.shields.io/pypi/v/nonebot-plugin-htmlrender.svg)](https://pypi.org/project/nonebot-plugin-htmlrender/)
[![Python](https://img.shields.io/pypi/pyversions/nonebot-plugin-htmlrender.svg)](https://pypi.org/project/nonebot-plugin-htmlrender/)
[![License](https://img.shields.io/github/license/kexue-z/nonebot-plugin-htmlrender.svg)](./LICENSE)
[![Docs](https://img.shields.io/badge/docs-guides%20%26%20reference-EA5252)](docs/index.md)

</div>

## 特性

- 统一的 `render_html`、`render_text`、`render_markdown`、`render_template` API
- `Application` / `Renderer` 组合边界与可发现的渲染 Provider
- Playwright 浏览器、Takumi 原生与实验性 HTMLKit Provider
- 与引擎无关的 Preparation、资源服务和 `PreparedHtml`
- `RenderedImage` / `RenderedHtml` 类型化产物
- Playwright、Takumi、Pillow 与 Skia 通过 `app.extensions` 的静态属性直接补全；Playwright/Takumi 还可租借保留上游类型的原生对象
- 有界资源缓存、严格本地路径策略和可选观测集成

## 安装

本体默认不安装任何位图渲染后端，只提供 Preparation 与模板到 HTML。按需选择一个 HTML 后端（Provider）：

```bash
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0,<0.9"
# 或
uv add "nonebot-plugin-htmlrender[takumi]>=0.8.0,<0.9"
# 或（实验性、asyncio-only）
uv add "nonebot-plugin-htmlrender[htmlkit]>=0.8.0,<0.9"
```

Pillow/Skia 是独立的 `RasterScene` Capability，不属于 HTML 后端。按需增加`pillow`、`skia`、`sentry`、`prometheus`；内置 filehost transport 可选增加`filehost` extra，以使用 `py-machineid` 派生默认请求头守卫值。`all` 会安装全部可选能力。

```bash
uv add "nonebot-plugin-htmlrender[playwright,filehost,prometheus]>=0.8.0,<0.9"
```

## 快速开始

```yaml
render:
  provider: playwright
  startup: warmup
  resources:
    local_access:
      allowed_paths: [templates]
```

```python
from nonebot import require

require("nonebot_plugin_htmlrender")

from nonebot_plugin_htmlrender import render_markdown, render_template


async def demo() -> tuple[bytes, bytes]:
    markdown = await render_markdown("# Hello\n\n**NoneBot**", width=720)
    card = await render_template(
        "templates",
        "card.html",
        variables={"name": "nonebot"},
        width=480,
    )
    return bytes(markdown), bytes(card)
```

`render_*` 返回类型化产物；交给消息适配器时显式使用`bytes(artifact)`，需要 MIME 类型时读取 `artifact.media_type`。

## 文档

- [快速开始](docs/start/quickstart.md)
- [选择渲染后端](docs/start/choosing-provider.md)
- [参考手册](docs/reference/index.md)
- [配置](docs/configuration/index.md)
- [远程 Playwright](docs/configuration/remote-playwright.md)
- [v0.8 迁移指南](docs/guides/migration/v0.8.md)
- [架构](docs/extensions/architecture.md)
- [Provider 开发](docs/extensions/provider-development.md)

## 开发

```bash
make prepare
make check
make docs-build
make test-local
make build-artifacts
```

远程浏览器联调使用 `make remote-smoke-build`；常规变更可复用镜像执行`make remote-smoke`。

## 许可

项目使用 MIT License。启用 Takumi、HTMLKit 或其他第三方 Provider 前，请同时检查其依赖与分发许可；HTMLKit rc5 的 native core 为 LGPL-3.0-or-later。
