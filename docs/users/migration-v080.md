---
title: v0.8 迁移指南
description: 从 0.7 配置、返回值、浏览器 API 与扩展模型迁移到 0.8
icon: lucide/git-compare-arrows
tags:
  - Users
  - Migration
---

# v0.8 迁移指南

0.8 是破坏性版本：配置进入统一 `render` 命名空间，位图 API 返回 typed
artifacts，Provider/Capability 取代 0.7 的 Backend/Render 公共契约。插件在
加载阶段拒绝旧配置键，不做歧义兼容。

## 配置

```yaml
render:
  provider: playwright
  startup: probe
  provider_config:
    engine: chromium
  resources:
    cache:
      max_entries: 256
      max_bytes: 67108864
      max_resource_bytes: 67108864
      revalidate_seconds: 1.0
    templates:
      environment_cache_max_entries: 64
    local_access:
      allow_any_path: false
      allowed_paths: []
    filehost:
      cache_ttl_seconds: 300.0
      prewarm_enabled: true
      prewarm_max_files: 256
      prewarm_paths: []
      prewarm_extensions: []
      request_header_name: X-HTMLRender-Filehost-Request
      request_header_value: null
      request_header_salt: nonebot-plugin-htmlrender:filehost:guard:v1
  observability:
    sentry: false
    prometheus: false
```

| 0.7 | 0.8 |
| --- | --- |
| `render_backend` | `render.provider` |
| `render_startup_mode` | `render.startup` |
| `render_playwright.*` | `render.provider_config.*`（选择 Playwright） |
| `render_takumi.*` | `render.provider_config.*`（选择 Takumi） |
| `render_resource_cache_max_entries` | `render.resources.cache.max_entries` |
| `render_resource_cache_max_bytes` | `render.resources.cache.max_bytes` |
| `render_resource_cache_revalidate_seconds` | `render.resources.cache.revalidate_seconds` |
| `render_template_environment_cache_max_entries` | `render.resources.templates.environment_cache_max_entries` |
| `render_playwright.filehost_allow_any_path` | `render.resources.local_access.allow_any_path` |
| `render_playwright.filehost_allowed_paths` | `render.resources.local_access.allowed_paths` |
| `render_playwright.filehost_cache_ttl_seconds` | `render.resources.filehost.cache_ttl_seconds` |
| `render_playwright.filehost_prewarm_enabled` | `render.resources.filehost.prewarm_enabled` |
| `render_playwright.filehost_prewarm_max_files` | `render.resources.filehost.prewarm_max_files` |
| `render_playwright.filehost_prewarm_paths` | `render.resources.filehost.prewarm_paths` |
| `render_playwright.filehost_prewarm_extensions` | `render.resources.filehost.prewarm_extensions` |
| `render_playwright.filehost_request_header_name` | `render.resources.filehost.request_header_name` |
| `render_playwright.filehost_request_header_value` | `render.resources.filehost.request_header_value` |
| `render_playwright.filehost_request_header_salt` | `render.resources.filehost.request_header_salt` |
| `render_storage_path` | `render.provider_config.storage_path`（Playwright） |

filehost TTL/预热/请求头与本地路径授权都由核心 Resource Service 管理；Provider
只选择 transport strategy。

## extras

```bash
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0a1,<0.9"
# 或
uv add "nonebot-plugin-htmlrender[takumi]>=0.8.0a1,<0.9"
# 或（实验性、asyncio-only）
uv add "nonebot-plugin-htmlrender[htmlkit]>=0.8.0a1,<0.9"
```

core 安装默认不包含任何位图渲染后端。HTMLKit rc5 另有
`device_pixel_ratio=1.0`、`height=None` 的显式限制，详见
[HTMLKit 配置](config/htmlkit.md)。

`nonebot-plugin-localstore` 仍是 core 宿主基础设施，由插件入口统一加载；它不应
移动到 Playwright extra 或由 Playwright Provider 单独声明 requirement。

未选择 Provider 时插件仍可执行 Preparation 与 `render_template_html`；由于位图
操作未绑定，调用会抛出 `CapabilityUnavailable`。选择了 Provider 但缺少对应
extra 时，位图执行或启动会报告 `ProviderUnavailable`。

## typed artifacts 与参数

```python
from nonebot_plugin_htmlrender import render_text

artifact = await render_text("hello", width=500)
image_bytes = bytes(artifact)
media_type = artifact.media_type
```

| 0.7 | 0.8 |
| --- | --- |
| `render_html(...) -> bytes` | `render_html(...) -> RenderedImage` |
| `render_template_html(...) -> str` | `render_template_html(...) -> RenderedHtml` |
| `image_type=` | `image_format=` |
| `device_scale_factor=` | `device_pixel_ratio=` |
| `md=` / `md_path=` | `markdown=` / `markdown_path=` |
| `templates=` | `variables=` |
| `pages=` | 中立 `width` / `height`；浏览器参数移入 Capability |
| `resource_strict=` / `resolve_resources=` | `resource_policy=ResourcePolicy.STRICT / AUTO / OFF` |
| `wait=` / `screenshot_timeout=` | `timeout_seconds=` |

图片消费者改为 `bytes(artifact)`；HTML 消费者改为 `str(artifact)`。

## lifecycle 与浏览器操作

| 已删除的 0.7 契约 | 0.8 |
| --- | --- |
| `startup_render()` / `shutdown_render()` | `Application.startup()` / `Application.aclose()` |
| `get_render_context()` / `get_new_page()` | `PLAYWRIGHT_CAPABILITIES.page()` |
| `capture_html_element(...)` | `PLAYWRIGHT_CAPABILITIES.capture_element(...)` |
| `list_render_backend_statuses()` 等状态 API | `Application.probe()` 与 Capability 探测 |
| `require_render_extension(TAKUMI_EXTENSION)` | `async with app.capabilities.require(TAKUMI_CAPABILITIES).extension()` |

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.capabilities import PLAYWRIGHT_CAPABILITIES

app = get_default_application()
playwright = app.capabilities.require(PLAYWRIGHT_CAPABILITIES)
async with playwright.page(viewport={"width": 800, "height": 600}) as page:
    await page.goto("https://example.com")
```

第一方 key 与 Protocol 的稳定导入路径是
`nonebot_plugin_htmlrender.capabilities`。adapter 内部 capability 模块不是公共
兼容路径。

## 删除符号

以下名字只用于迁移检索，不存在兼容 adapter：

- `Backend`、`BackendCapability`、`BackendExtension`
- `RenderBackend`、`RenderRuntime`、`RenderSession`
- `register_backend`、`build_backend`
- `PreparationService`、`SingleflightResourceReader`、
  `ResourceValueResolver`、`clean_playwright_cache`
- `PageConfig.base_url`；页面导航只使用 `document_url`
- `_compat` 中的 `text_to_pic`、`md_to_pic`、`html_to_pic`、
  `template_to_pic`、`template_to_html`

项目内搜索这些名字与旧配置键，并逐一迁移后再升级。

## 第三方 Provider

实现 `EngineProvider[SettingsT]`，通过 entry point group
`nonebot_plugin_htmlrender.providers` 注册。entry point 名必须等于
`provider.id`；`htmlkit`、`playwright` 与 `takumi` 是保留 ID。

0.7 与 0.8 开发分支中曾存在的过渡 Provider 接口不构成兼容契约。第三方
Provider 必须适配 0.8.0a1 起公开的类型化 settings、`ProviderDependencies`、
`EngineBindings`、`ProviderResources`、`ResourceStrategy` 与 provider-local
lease；不提供兼容 shim。当前 `ProviderDependencies` 只包含 operation/cache
observer、`resources` 与可选 `asset_publisher`，不再暴露 worker、raw reader、local
policy 或完整 `ResourceService`。`EngineBindings` 也不再包含 `description` 或
`observation_attributes`；Provider ID 是引擎身份的唯一来源。以
`examples/echo-provider` 和 [Provider 开发指南](../maintainers/architecture/provider-development.md)
为准。

## 检查表

- [ ] 全部配置移入 `render`，启动日志无旧键错误。
- [ ] 安装所选 Provider extra。
- [ ] 所有图片消费者使用 `bytes(artifact)`。
- [ ] 模板参数使用 `variables`，raster 参数不再嵌套。
- [ ] 页面/selector/native 专属操作改用 typed Capability。
- [ ] 只捕获稳定 `RenderingError` 子类。
- [ ] examples、类型检查、strict docs build 与真实 Provider smoke 通过。
