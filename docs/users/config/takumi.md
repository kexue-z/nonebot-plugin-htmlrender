---
title: Takumi 配置与能力
description: Takumi 原生 Provider 的静态渲染、字体和 typed Capability
icon: lucide/gauge
---

# Takumi 配置与能力

Takumi 在进程内执行 Rust 原生排版，不启动浏览器，不执行 JavaScript，也不
访问网络。

## 安装与选择

```bash
uv add "nonebot-plugin-htmlrender[takumi]>=0.8.0a1,<0.9"
```

```yaml
render:
  provider: takumi
  startup: probe
  provider_config:
    max_concurrency: 4
```

## 配置

下表字段均位于 `render.provider_config`：

| 完整路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.provider_config.load_default_fonts` | `true` | 加载 Takumi 默认字体 |
| `render.provider_config.fonts` | `[]` | 启动时注册的字体 |
| `render.provider_config.font_cache_policy` | `revalidate` | 默认字体文件 cache policy |
| `render.provider_config.max_concurrency` | `min(cpu_count, 4)` | native 调用并发上限，1–64 |
| `render.provider_config.compiled_cache_max_entries` | `128` | compiled LRU 条目上限 |
| `render.provider_config.compiled_cache_max_source_bytes` | `33554432` | compiled cache 的模板 source UTF-8 字节预算（非 native 常驻内存）；条目数量硬上限仍由 `compiled_cache_max_entries` 提供 |
| `render.provider_config.html_options.presets` | `chromium` | `chromium` 或 `none` |
| `render.provider_config.html_options.tailwind_property` | `null` | Tailwind 属性名 |
| `render.provider_config.html_options.max_depth` | `null` | parser 最大深度 |
| `render.provider_config.default_lang` | `null` | 默认语言 |
| `render.provider_config.font_families` | `[]` | 字体回退顺序 |

`fonts` 中每个条目的字段如下；未知字段会被拒绝：

| 字段 | 默认值 | 约束 |
| --- | --- | --- |
| `path` | 必填 | 非空字体文件路径 |
| `name` | `null` | 注册后的字体族名称 |
| `weight` | `null` | `1`–`1000` |
| `style` | `null` | 字体 style |
| `subset_of` | `null` | 作为指定字体族的子集注册 |
| `generic_family` | `null` | CSS generic family，如 `sans-serif`、`serif`、`monospace`、`emoji` |
| `cache_policy` | `null` | `immutable` / `revalidate`；为空时继承 `font_cache_policy` |

字体示例：

```yaml
render:
  provider: takumi
  resources:
    local_access:
      allowed_paths: [/app/fonts]
  provider_config:
    load_default_fonts: false
    fonts:
      - path: /app/fonts/NotoSansSC-Regular.otf
        name: Noto Sans SC
        generic_family: sans-serif
        cache_policy: immutable
    font_families: [Noto Sans SC, sans-serif]
```

只有随镜像不可变的字体才应使用 `immutable`。运行中的 native renderer
不会热替换已注册字体；文件变化后需重建 composition。字体路径同样受
`render.resources.local_access.allowed_paths` 约束。

## 能力边界

Takumi 支持静态 HTML、文本、模板和大多数 Markdown；下列需求会明确失败：

- JavaScript、远程网络资源和页面导航；
- 无法在 Preparation 阶段物化的 `@import`、字体或图片；
- Provider 无法表达的 conditional stylesheet；
- 浏览器页面、User-Agent、header 与 selector 操作。

`PreparedAsset` 直接把 bytes 交给 native renderer，不创建临时文件。

## typed Capability

node、measure、SVG、动画和动态字体是 Takumi 专属能力：

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.capabilities import TAKUMI_CAPABILITIES

capability = get_default_application().extensions.require(TAKUMI_CAPABILITIES)
async with capability.extension() as extension:
    svg = await extension.render_svg_html("<strong>Hello</strong>", width=320)
```

`extension()` 的异步上下文绑定并持有当前有效 lease。调用方不得让
`extension` 逃逸出上下文，也不应把它保存为进程级单例。

## 选择建议

需要脚本、网页导航或浏览器布局语义时选择 Playwright；内容完全受控、希望
避免浏览器进程，或需要 native measure/SVG/animation 时选择 Takumi。

启用或再分发 Takumi 前，请自行检查 `takumi-py` 当前版本的许可与平台 wheel；
这里不构成法律意见。
