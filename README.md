<div align="center">

<img src="docs/assets/nonebot_plugin.svg" alt="nonebot-plugin-htmlrender" width="180" />

# nonebot-plugin-htmlrender

_NoneBot2 浏览器渲染库插件（Library Plugin）_

[![PyPI](https://img.shields.io/pypi/v/nonebot-plugin-htmlrender.svg)](https://pypi.org/project/nonebot-plugin-htmlrender/)
[![Python](https://img.shields.io/pypi/pyversions/nonebot-plugin-htmlrender.svg)](https://pypi.org/project/nonebot-plugin-htmlrender/)
[![License](https://img.shields.io/github/license/kexue-z/nonebot-plugin-htmlrender.svg)](./LICENSE)
[![Docs](https://img.shields.io/badge/docs-users%20%26%20maintainers-EA5252)](docs/index.md)

</div>

## 特性

- 统一渲染 API：`render_text` / `render_markdown` / `render_html` / `render_template`
- 支持本地与远程渲染（Remote Playwright WS / Remote Browser CDP）
- 支持模板变量资源解析（含 filehost 方案）
- 支持渲染链路遥测（可选接入 sentry / prometheus）

## 快速导航

- [安装](#安装)
- [快速开始](#快速开始)
- [配置与文档](#配置与文档)
- [开发与测试](#开发与测试)

## 安装

### 基础安装

```bash
uv add nonebot-plugin-htmlrender
```

### 可选能力

```bash
uv add "nonebot-plugin-htmlrender[filehost]"
uv add "nonebot-plugin-htmlrender[sentry]"
uv add "nonebot-plugin-htmlrender[prometheus]"
uv add "nonebot-plugin-htmlrender[filehost,sentry,prometheus]"
```

## 快速开始

```python
from nonebot import require

require("nonebot_plugin_htmlrender")

from nonebot_plugin_htmlrender import render_markdown, render_template, render_text


async def demo() -> None:
    img_text = await render_text("Hello, HTMLRender")
    img_md = await render_markdown("# Title\n\n**Hello**")
    img_tpl = await render_template(
        "templates",
        template_name="card.html",
        templates={"name": "nonebot"},
    )
```

更多使用方式请参考 [API 文档](docs/users/api.md)。

## 配置与文档

### 用户文档

- [文档首页](docs/index.md)
- [快速开始](docs/users/quickstart.md)
- [API](docs/users/api.md)
- [核心配置](docs/users/config/core.md)
- [Playwright 配置](docs/users/config/playwright.md)
- [集成配置](docs/users/config/integrations.md)
- [远程渲染说明](docs/users/remote-playwright.md)

### 开发者文档

- [面向开发者总览](docs/maintainers/index.md)
- [架构说明](docs/maintainers/architecture/architecture.md)
- [贡献指南](docs/maintainers/contributing/contributing.md)
- [提交消息指南](docs/maintainers/contributing/commit-message.md)
- [编码规范](docs/maintainers/contributing/coding-standards.md)
- [测试矩阵](docs/maintainers/quality/testing-matrix.md)
- [工程流程](docs/maintainers/contributing/engineering-guide.md)
- [CI Actions](docs/maintainers/quality/ci-actions.md)
- [文档版本管理](docs/maintainers/quality/versioning.md)

### 仓库协作文档

- [贡献指南](CONTRIBUTING.md)
- [提交消息指南](COMMIT_MESSAGE.md)
- [编码规范](CODING_STANDARDS.md)
- [行为准则](CODE_OF_CONDUCT.md)
- [安全策略](SECURITY.md)

## 开发与测试

```bash
make prepare
make check
make test-ci
make test-local
make install-browser
make ruff-format
make ruff-check
make typecheck
make ty
make build-artifacts
```

远程联调 smoke test：

```bash
make remote-smoke
```

首次构建镜像、基础镜像变更或 `pyproject.toml` / `uv.lock` 变更后，再使用：

```bash
make remote-smoke-build
```

开发容器（代码挂载 + 远程 Playwright）：

```bash
docker compose -f docker-compose.dev.yaml up --build -d
docker compose -f docker-compose.dev.yaml exec dev sh
```

## FAQ

### 系统要求

[require by playwright](https://playwright.dev/python/docs/intro#system-requirements)

```text
Python 3.10 or higher.
Windows 11+, Windows Server 2019+ or Windows Subsystem for Linux (WSL).
macOS 14 Ventura, or later.
Debian 12, Debian 13, Ubuntu 22.04, Ubuntu 24.04, on x86-64 and arm64 architecture.
```

## 致谢

- [nonebot](https://github.com/nonebot)（提供框架能力支持）
- [MeetWq](https://github.com/MeetWq)（数学公式与代码高亮相关支持）
- [zhenxun-org/zhenxun_bot](https://github.com/zhenxun-org/zhenxun_bot) 与 [MountainDash/nonebot-bison](https://github.com/MountainDash/nonebot-bison)（感谢庞大用户群体提供的长期反馈）
- [nonebot-plugin-filehost](https://github.com/nonebot/plugin-filehost)、[nonebot-plugin-sentry](https://github.com/nonebot/plugin-sentry)、[nonebot-plugin-prometheus](https://github.com/nonebot/plugin-prometheus)（提供 filehost / sentry / prometheus 能力载入支持）
- [nonebot/plugin-htmlkit](https://github.com/nonebot/plugin-htmlkit)（提供测试思路参考）
