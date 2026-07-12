---
title: 配置总览
description: 统一 render 命名空间与 Provider 配置
icon: lucide/settings-2
---

# 配置总览

所有配置都位于 `render`：

```yaml
render:
  provider: playwright
  startup: warmup
  provider_config: {}
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

完整 dotted paths：

- `render.provider`
- `render.startup`
- `render.provider_config`
- `render.resources.cache.max_entries`
- `render.resources.cache.max_bytes`
- `render.resources.cache.max_resource_bytes`
- `render.resources.cache.revalidate_seconds`
- `render.resources.templates.environment_cache_max_entries`
- `render.resources.local_access.allow_any_path`
- `render.resources.local_access.allowed_paths`
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

阅读顺序：

1. [基础配置与加载](core.md)
2. [Playwright 配置](playwright.md) 或 [Takumi 配置](takumi.md)
3. [依赖扩展与观测](integrations.md)

Provider 专属字段始终嵌套在 `render.provider_config`，并由所选 Provider 校验。
