<div align="center">

<img src="docs/assets/nonebot_plugin.svg" alt="nonebot-plugin-htmlrender" width="180" />

# nonebot-plugin-htmlrender

> 面向 NoneBot 的可插拔 HTML 渲染库

[![PyPI](https://img.shields.io/pypi/v/nonebot-plugin-htmlrender.svg)](https://pypi.org/project/nonebot-plugin-htmlrender/)
[![Python](https://img.shields.io/pypi/pyversions/nonebot-plugin-htmlrender.svg)](https://pypi.org/project/nonebot-plugin-htmlrender/)
[![License](https://img.shields.io/github/license/kexue-z/nonebot-plugin-htmlrender.svg)](./LICENSE)
[![Docs](https://img.shields.io/badge/docs-users%20%26%20maintainers-EA5252)](docs/index.md)

</div>

## 特性

- 统一的 `render_html`、`render_text`、`render_markdown`、`render_template` API
- `Application` / `Renderer` 组合边界与可发现的渲染 Provider
- Playwright 浏览器 Provider 与 Takumi 原生 Provider
- 与引擎无关的 Preparation、资源服务和 `PreparedHtml`
- `RenderedImage` / `RenderedHtml` 类型化产物
- Playwright、Takumi 专属能力通过类型化 Capability 获取
- 有界资源缓存、严格本地路径策略和可选观测集成

## 安装

选择一个渲染 Provider：

```bash
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0a1,<0.9"
# 或
uv add "nonebot-plugin-htmlrender[takumi]>=0.8.0a1,<0.9"
```

按需增加 `filehost`、`sentry`、`prometheus`；`all` 会安装全部可选能力。

```bash
uv add "nonebot-plugin-htmlrender[playwright,filehost,prometheus]>=0.8.0a1,<0.9"
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

`render_*` 返回类型化产物；交给消息适配器时显式使用
`bytes(artifact)`，需要 MIME 类型时读取 `artifact.media_type`。

## 文档

- [快速开始](docs/users/quickstart.md)
- [API](docs/users/api.md)
- [配置](docs/users/config/index.md)
- [远程 Playwright](docs/users/remote-playwright.md)
- [v0.8 迁移指南](docs/users/migration-v080.md)
- [架构](docs/maintainers/architecture/architecture.md)
- [Provider 开发](docs/maintainers/architecture/provider-development.md)

## 开发

```bash
make prepare
make check
make docs-build
make test-local
make build-artifacts
```

远程浏览器联调使用 `make remote-smoke-build`；常规变更可复用镜像执行
`make remote-smoke`。

## 许可

项目使用 MIT License。启用 Takumi 或其他第三方 Provider 前，请同时检查其
依赖与分发许可。
