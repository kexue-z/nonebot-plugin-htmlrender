---
title: Takumi 配置
description: Takumi 原生 Provider 的静态渲染、字体和 typed Capability
icon: lucide/gauge
---

# Takumi 配置与能力

Takumi 在进程内执行 Rust 原生排版，不启动浏览器，不执行 JavaScript，也不访问网络。

## 安装与选择

```bash
uv add "nonebot-plugin-htmlrender[takumi]>=0.8.0,<0.9"
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

只有随镜像不可变的字体才应使用 `immutable`。运行中的 native renderer不会热替换已注册字体；文件变化后需重建 composition。字体路径同样受`render.resources.local_access.allowed_paths` 约束。

## 缓存使用与诊断

Takumi runtime 对重复的 HTML/CSS native 编译使用有界 singleflight LRU。`compiled_cache_max_source_bytes` 的单位是输入 source 的 UTF-8 bytes，不是 native heap；调优时必须同时观察条目上限。

```python
from nonebot_plugin_htmlrender import get_default_application

takumi = get_default_application().extensions.takumi
async with takumi.api() as api:
    await api.render_svg_html("<strong>cached</strong>", width=320)
    stats = api.compiled_cache_stats
    print(stats.hits, stats.misses, stats.evictions)
```

统计是当前 runtime 的只读快照。公共 API 不提供 compiled cache clear；需要释放 native compiled object 或替换已注册字体时，关闭并重建 Application。字体 revalidate、native image cache 与完整调优流程见[缓存组件、失效与调优](../../guides/cache-lifecycle.md#takumi-compiled-font-and-image-caches)。

## 能力边界

Takumi 支持静态 HTML、文本、模板和大多数 Markdown；下列需求会明确失败：

- JavaScript、远程网络资源和页面导航；
- 无法在 Preparation 阶段物化的 `@import`、字体或图片；
- Provider 无法表达的 conditional stylesheet；
- 浏览器页面、User-Agent、header 与 selector 操作。

`PreparedAsset` 直接把 bytes 交给 native renderer，不创建临时文件。

## 平台约束

项目当前锁定的 `takumi-py==0.2.0` 提供 macOS 11+ ARM64、manylinux 2.17+ x86-64/AArch64 和 Windows x86-64 wheel。Linux wheel 只链接 glibc、`libgcc` 等 manylinux 基线运行库，不需要 EGL、OpenGL、Cairo 或 Fontconfig 动态库；Alpine/musl、macOS x86-64、Windows ARM64 等没有匹配 wheel 的平台会尝试源码构建，需要 Rust、maturin 与相应 native toolchain。上游仍将 API 和 wheel target 标记为 testing stage，升级锁定版本时应重新核对[发布文件](https://pypi.org/project/takumi-py/)。

Takumi 自带的 Latin fallback 不能覆盖业务所需字符集。需要中文或其他脚本时，应通过 `render.provider_config.fonts` 把字体随部署交付；这属于内容资源，不是系统动态库依赖。

## typed Capability

node、measure、SVG、动画和动态字体是 Takumi 专属能力：

```python
from nonebot_plugin_htmlrender import get_default_application

takumi = get_default_application().extensions.takumi
async with takumi.api() as api:
    svg = await api.render_svg_html("<strong>Hello</strong>", width=320)
```

`api()` 的异步上下文绑定并持有当前有效 lease。调用方不得让 `api`、compiled
document/node/stylesheet 逃逸出上下文，也不应把它们保存为进程级单例；普通`bytes`、SVG 字符串和测量快照不受该限制。

需要尚未进入稳定 API 的上游能力时，可通过`takumi.renderer()` 获取真实 `takumi_py.Renderer`。该高级入口保留上游全部方法和类型，但同步执行、并发、native panic、资源归一化与异常处理均由调用方承担；详见 [Capability 参考](../../reference/capabilities.md#native-renderer)。

## 选择建议

需要脚本、网页导航或浏览器布局语义时选择 Playwright；内容完全受控、希望避免浏览器进程，或需要 native measure/SVG/animation 时选择 Takumi。

启用或再分发 Takumi 前，请自行检查 `takumi-py` 当前版本的许可与平台 wheel；这里不构成法律意见。
