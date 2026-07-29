---
title: 配置总览
description: render 命名空间的完整配置树与专题入口
icon: lucide/settings-2
---

# 配置总览

所有配置都位于 `render`：

```yaml
render:
  provider: playwright
  startup: warmup
  provider_config: {}
  html:
    max_source_bytes: 67108864
    max_pixels: 16777216
    max_output_bytes: 67108864
    max_device_pixel_ratio: 4.0
    max_auto_height: 16384
    max_concurrency: 2
  graphics:
    backends: []
    max_pixels: 16777216
    max_concurrency: 2
    max_commands: 100000
  resources:
    cache:
      max_entries: 256
      max_bytes: 67108864
      max_resource_bytes: 67108864
      revalidate_seconds: 1.0
    templates:
      environment_cache_max_entries: 64
      environment_compiled_cache_size: 256
    traversal:
      max_nodes: 10000
      max_depth: 64
      max_concurrency: 16
    local_access:
      allow_any_path: false
      allowed_paths: []
    remote_access:
      allow_private_networks: false
      allow_hosts: []
      deny_hosts: []
      max_redirects: 5
      request_timeout_seconds: 30.0
      max_concurrent_fetches: 8
    filehost:
      public_base_url: null
      max_entries: 256
      max_bytes: 268435456
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

完整 dotted paths：

- `render.provider`
- `render.startup`
- `render.provider_config`
- `render.html.max_source_bytes`
- `render.html.max_pixels`
- `render.html.max_output_bytes`
- `render.html.max_device_pixel_ratio`
- `render.html.max_auto_height`
- `render.html.max_concurrency`
- `render.graphics.backends`
- `render.graphics.max_pixels`
- `render.graphics.max_concurrency`
- `render.graphics.max_commands`
- `render.resources.cache.max_entries`
- `render.resources.cache.max_bytes`
- `render.resources.cache.max_resource_bytes`
- `render.resources.cache.revalidate_seconds`
- `render.resources.templates.environment_cache_max_entries`
- `render.resources.templates.environment_compiled_cache_size`
- `render.resources.traversal.max_nodes`
- `render.resources.traversal.max_depth`
- `render.resources.traversal.max_concurrency`
- `render.resources.local_access.allow_any_path`
- `render.resources.local_access.allowed_paths`
- `render.resources.remote_access.allow_private_networks`
- `render.resources.remote_access.allow_hosts`
- `render.resources.remote_access.deny_hosts`
- `render.resources.remote_access.max_redirects`
- `render.resources.remote_access.request_timeout_seconds`
- `render.resources.remote_access.max_concurrent_fetches`
- `render.resources.filehost.public_base_url`
- `render.resources.filehost.max_entries`
- `render.resources.filehost.max_bytes`
- `render.resources.filehost.cache_ttl_seconds`
- `render.resources.filehost.prewarm_enabled`
- `render.resources.filehost.prewarm_max_files`
- `render.resources.filehost.prewarm_paths`
- `render.resources.filehost.prewarm_extensions`
- `render.resources.filehost.request_header_name`
- `render.resources.filehost.request_header_value`
- `render.resources.filehost.request_header_salt`
- `render.observability.sentry`
- `render.observability.prometheus`

按配置域查阅：

- 核心配置：[`.env` 配置](dotenv.md)、[启动与生命周期](lifecycle.md)、[HTML 渲染预算](html-rendering.md)、[资源与访问策略](resources.md)、[可选依赖与可观测性](observability.md)；缓存的操作方法见[缓存组件、失效与调优](../guides/cache-lifecycle.md)
- [HTML 后端](providers/index.md)：[Playwright](providers/playwright.md)、[HTMLKit](providers/htmlkit.md)、[Takumi](providers/takumi.md)
- [Graphics 后端](graphics/index.md)：[Pillow](graphics/pillow.md)、[Skia](graphics/skia.md)

Provider 专属字段始终嵌套在 `render.provider_config`，并由所选 Provider 校验。`render.graphics` 不属于 Provider 配置；它组合独立的 typed Capability。

Python 侧的公共 `RenderPluginConfig` 是 NoneBot 配置入口，容纳顶层 `render` 字段；`RenderSettings` 对应其内部完整命名空间。两者用于宿主接线、测试或显式配置校验，普通业务调用无需自行实例化。
