---
title: Takumi 配置与能力
description: takumi-py 原生渲染后端的安装、能力边界、资源模型与观测
icon: lucide/gauge
status: new
tags:
  - Users
  - Config
  - Takumi
---

# Takumi 配置与能力

Takumi 后端把 `takumi-py==0.2.0` 作为可选的进程内渲染引擎。它不启动浏览器，也不建立远程连接；同步的 Rust 原生调用统一进入受并发限制的 worker thread，避免阻塞 NoneBot 事件循环。

## 安装与选择

```bash
uv add "nonebot-plugin-htmlrender[takumi]"
```

```dotenv
RENDER_BACKEND=takumi
RENDER_STARTUP_MODE=probe
RENDER_TAKUMI={"max_concurrency":4,"compiled_cache_max_entries":128}
```

后端可用性检查只读取模块与 distribution metadata，并要求精确版本 `0.2.0`；真正加载 native extension 和创建 `Renderer` 发生在 runtime 启动阶段。

## 如何选择后端

| 能力 | Playwright | Takumi |
| --- | --- | --- |
| `render_html` / `render_text` / `render_template` | 支持 | 支持静态内容 |
| `render_markdown` | 支持，含浏览器执行的 KaTeX | 支持；遇到需要 JavaScript 的数学公式会明确拒绝 |
| 共享 `PreparedHtml` + `RasterOptions` | 支持 | 支持 |
| JavaScript、网络请求、远程页面 | 支持 | 不支持 |
| `file://` / filehost 资源解析 | 支持 | 不使用；资源必须以内存 bytes 明确提供 |
| 元素定位截图 | 支持 | 不支持 |
| Node、measure、SVG | 通过浏览器上下文自行实现 | typed extension 原生支持 |
| WebP / APNG / GIF 动画与 frame 编码 | 不属于公共 API | typed extension 原生支持 |

需要执行脚本、加载网页、等待 DOM 更新或复用浏览器插件时选择 Playwright。内容完全可控、希望避免浏览器进程开销，或需要原生 measure / SVG / animation 时选择 Takumi。

## 配置项

所有后端配置位于 `render_takumi`：

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `load_default_fonts` | `true` | 是否加载 Takumi 自带默认字体 |
| `fonts` | `[]` | 启动时注册的字体文件列表 |
| `font_cache_policy` | `immutable` | 字体 byte cache 策略：`immutable` 或 `revalidate` |
| `max_concurrency` | `min(cpu_count, 4)` | 同时执行 native 调用的 worker 上限，范围 1–64 |
| `compiled_cache_max_entries` | `128` | HTML 与 stylesheet 编译缓存的 LRU 条目上限；`0` 禁用 |
| `html_options.presets` | `chromium` | Takumi HTML parser preset，可选 `chromium` / `none` |
| `html_options.tailwind_property` | `null` | 交给 Takumi 的 Tailwind 属性名 |
| `html_options.max_depth` | `null` | HTML parser 最大节点深度 |
| `default_lang` | `null` | 默认语言标记 |
| `font_families` | `[]` | 默认字体族回退顺序 |

字体示例：

```dotenv
RENDER_TAKUMI={"load_default_fonts":false,"fonts":[{"path":"/app/fonts/NotoSansSC-Regular.otf","name":"Noto Sans SC","generic_family":"sans-serif"}],"font_families":["Noto Sans SC","sans-serif"],"max_concurrency":4}
```

字体文件通过共用的有界 byte cache 读取，并在每个 Takumi runtime 中注册一次。对随部署镜像固定的字体使用 `immutable`；运行中可能被替换的字体使用 `revalidate`。

## 共用 preparation API

文本、Markdown、Jinja 模板和原始 HTML 先进入 backend-neutral preparation，再交给选中的 executor：

```python
from nonebot_plugin_htmlrender import RasterOptions, prepare_html, rasterize_html

prepared = prepare_html(
    "<style>.card { color: #663399 }</style><div class='card'>Hello</div>"
)
image = await rasterize_html(
    prepared,
    RasterOptions(width=480, device_pixel_ratio=2, format="png"),
)
```

`RasterOptions` 的尺寸是 CSS pixel；Takumi 会按 DPR 转成 native device-pixel canvas，因此 `width=480, device_pixel_ratio=2` 生成 960 physical pixels 宽的图片。

`PreparedHtml` 同时保留浏览器需要的完整 `html`、native executor 使用的无 `<style>` `markup`、按顺序提取的 `stylesheets`、`base_url`、显式 `assets` 和执行需求。不要把 Python 对象、JSON/base64 中间层或临时文件当作跨 native 边界协议；字符串和资源都以 `str` / `bytes` 直接传递。

## Takumi typed extension

公共 API 只承载后端间真正共用的语义。Takumi 特有能力通过类型化 token 获取，不向 `Render` 塞入 union 或后端判断：

```python
from nonebot_plugin_htmlrender import require_render_extension
from nonebot_plugin_htmlrender.backend.takumi import (
    TAKUMI_EXTENSION,
    TakumiImageResource,
)

extension = await require_render_extension(TAKUMI_EXTENSION)
image = await extension.render_html(
    '<img src="memory:avatar" width="96" height="96">',
    images=[TakumiImageResource("memory:avatar", avatar_bytes)],
    width=96,
    height=96,
    device_pixel_ratio=2,
)
svg = await extension.render_svg_html("<strong>Hello</strong>", width=320)
```

`TakumiExtension` 提供：

- 编译 HTML、node、stylesheet、keyframes，并复用有界 compiled LRU
- 渲染 HTML / compiled document / node，输出 PNG、JPEG/JPG、WebP、ICO 或 raw bytes
- measure HTML / compiled document / node
- 输出 HTML / compiled document / node 的 SVG
- 输出 WebP、APNG、GIF 动画，按时间渲染 sequence，以及编码 raw frames
- 运行时注册字体 bytes / 字体文件
- 使用共用 Jinja environment cache 渲染模板为静态图片或 SVG

## 资源约束

Takumi 不访问调用方 filesystem，不发起 HTTP 请求，也不执行 JavaScript：

- `<script>`、`<link rel="stylesheet">`、CSS `@import` 与 URL 型 `@font-face` 会得到明确的 `TakumiUnsupportedError`
- `<img>`、SVG image 与 CSS `url(...)` 必须使用 data URI，或用完全相同的 `src` key 携带 `bytes`
- `PreparedAsset` / `TakumiImageResource` 的 key 必须唯一；缺失或重复会在进入 native renderer 前失败
- `wait`、User-Agent、HTTP headers、浏览器 session/page 配置不会被静默忽略，而会明确拒绝

这套约束使 remote/local 部署具有相同资源语义，也避免把本地路径错误地传给 native 或另一个容器。

## 缓存、并发与失效

- 文件 cache 同时按 entry 数和 byte 数限制，动态文件通过 stat revision 与 revalidate window 失效；内置模板、固定字体可标为 immutable
- 同一路径冷读使用 singleflight，避免并发重复 I/O；文件读取在线程池执行
- Jinja environment cache 按模板根、扩展与 filter identity 隔离，并有独立 LRU 上限
- Takumi compiled cache 属于 runtime；runtime 关闭时清空，不跨 renderer 复用 native 对象
- `max_concurrency` 是 native 执行的容量限制，不是额外线程池大小

共用缓存上限由基础配置中的 `render_resource_cache_max_entries`、`render_resource_cache_max_bytes`、`render_resource_cache_revalidate_seconds` 与 `render_template_environment_cache_max_entries` 控制。

## Sentry 与 metrics

Takumi 复用项目统一的 `track_render`：每个公共操作、runtime 生命周期与 typed extension 操作都会同时进入 Sentry span/metrics 和 Prometheus metrics。标签只有稳定的 `op`、`backend=takumi`、`status`，不会记录 HTML、Markdown、模板路径、URL、字体名或资源 bytes。

典型操作名：

- `takumi.open_runtime` / `takumi.close_runtime`
- `takumi.render_html` / `takumi.render_text` / `takumi.render_markdown` / `takumi.render_template`
- `takumi.rasterize_html`
- `takumi.extension.render_node` / `measure_html` / `render_svg_html` / `render_animation`

指标名称、Sentry 配置与 Prometheus labels 见 [依赖扩展与观测](integrations.md)。

## 平台与许可检查

`takumi-py 0.2.0` 提供 CPython abi3 wheels：macOS arm64、manylinux glibc x86_64 / aarch64、Windows x86_64；其他平台会回退到 source distribution，是否能构建取决于本机 Rust 与 native 构建环境。

!!! warning "发布前检查依赖许可"
    `nonebot-plugin-htmlrender` 本身使用 MIT；`takumi-py 0.2.0` 的 distribution metadata 声明 `GPL-3.0-or-later`。启用可选 extra、再分发镜像或二进制前，应由项目维护者完成适用于自身分发方式的许可兼容性审查。这里仅记录上游 metadata，不构成法律意见。参见 [PyPI 0.2.0](https://pypi.org/project/takumi-py/0.2.0/) 与 [v0.2.0 release](https://github.com/BalconyJH/takumi-py/releases/tag/v0.2.0)。
