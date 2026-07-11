# v0.8 迁移指南

0.8 是破坏性版本：配置迁移到统一的 `render` 命名空间，公共 API 改为返回类型化产物（typed artifacts），旧的 Backend/Render 契约与兼容层被删除。检测到任何 0.7 配置键时插件会在加载阶段直接失败并提示本页。

## 配置迁移

旧的平铺 `render_*` 键全部废除，改为嵌套的 `render` 命名空间：

```yaml
render:
  provider: playwright        # 或 takumi / 第三方 provider id / 留空表示仅 preparation
  startup: "off"              # off / warmup / probe
  provider_config:            # 由所选 provider 校验
    engine: chromium
    skip_browser_install: true
  resources:
    cache:
      max_entries: 256
      max_bytes: 67108864
      revalidate_seconds: 1.0
    templates:
      environment_cache_max_entries: 64
    local_access:
      allow_any_path: false
      allowed_paths: []
  observability:
    sentry: false
    prometheus: false
```

键位映射：

| 0.7 | 0.8 |
| --- | --- |
| `render_backend` | `render.provider` |
| `render_startup_mode` | `render.startup` |
| `render_playwright.*` | `render.provider_config.*`（provider 为 playwright 时） |
| `render_takumi.*` | `render.provider_config.*`（provider 为 takumi 时） |
| `render_resource_cache_max_entries` | `render.resources.cache.max_entries` |
| `render_resource_cache_max_bytes` | `render.resources.cache.max_bytes` |
| `render_resource_cache_revalidate_seconds` | `render.resources.cache.revalidate_seconds` |
| `render_template_environment_cache_max_entries` | `render.resources.templates.environment_cache_max_entries` |
| `render_playwright.filehost_allow_any_path` | `render.resources.local_access.allow_any_path` |
| `render_playwright.filehost_allowed_paths` | `render.resources.local_access.allowed_paths` |
| `render_storage_path` | `render.provider_config.storage_path`（playwright；默认仍由 localstore 管理） |

filehost 的运行参数（TTL、预热、请求头）仍在 playwright 的 `provider_config` 中（`filehost_cache_ttl_seconds` 等）；本地路径安全策略上收到核心 `resources.local_access`。

## 安装 extras

Playwright 不再是核心依赖：

```bash
pip install nonebot-plugin-htmlrender[playwright]   # 浏览器引擎
pip install nonebot-plugin-htmlrender[takumi]       # 原生引擎
pip install nonebot-plugin-htmlrender[all]          # 全部可选能力
```

不带引擎 extra 时插件仍可加载并执行 preparation（`prepare_*` 与 `render_template_html`）；真正渲染位图时报 `ProviderUnavailable`。

## API 迁移

顶层便捷函数保留原名，但改为返回类型化产物且不再接受浏览器专属参数：

```python
from nonebot_plugin_htmlrender import render_text

artifact = await render_text("hello", width=500)
image_bytes = bytes(artifact)      # 或 artifact.data
media_type = artifact.media_type    # "image/png"
```

| 0.7 | 0.8 |
| --- | --- |
| `render_html(...) -> bytes` | `render_html(...) -> RenderedImage` |
| `render_template_html(...) -> str` | `render_template_html(...) -> RenderedHtml`（`str(artifact)`） |
| `image_type=` | `image_format=` |
| `device_scale_factor=` | `device_pixel_ratio=` |
| `md=` / `md_path=` | `markdown=` / `markdown_path=` |
| `resource_strict=` / `resolve_resources=` | `resource_policy=ResourcePolicy.STRICT / AUTO / OFF` |
| `wait=` / `screenshot_timeout=` | `timeout_seconds=`（整体操作超时） |
| `startup_render()` / `shutdown_render()` | `get_default_application().startup()` / `.aclose()` |
| `get_render_context()` / `get_new_page()` | Playwright capability：`app.capabilities.require(PLAYWRIGHT_CAPABILITIES).page(...)` |
| `capture_html_element(...)` | `...require(PLAYWRIGHT_CAPABILITIES).capture_element(...)` |
| `require_render_extension(TAKUMI_EXTENSION)` | `...require(TAKUMI_CAPABILITIES).extension()` |
| `text_to_pic` / `md_to_pic` / `template_to_pic` / `html_to_pic` 等 `_compat` 别名 | 已删除，使用对应 `render_*` |

Provider 专属能力键从各自适配器导入：

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.adapters.playwright.capabilities import (
    PLAYWRIGHT_CAPABILITIES,
)

app = get_default_application()
browser = app.capabilities.require(PLAYWRIGHT_CAPABILITIES)
async with browser.page(viewport={"width": 800, "height": 600}) as page:
    await page.goto("https://example.com")
```

## 第三方渲染引擎

0.8 起第三方引擎是正式公共能力：实现 `EngineProvider` 协议并通过 entry point 组
`nonebot_plugin_htmlrender.providers` 注册（entry point 名必须等于 `provider.id`；
`playwright` 与 `takumi` 为保留 ID）。仓库 `examples/echo-provider/` 提供了一个最小可用示例。
