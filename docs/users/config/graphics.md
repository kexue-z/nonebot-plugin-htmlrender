---
title: Pillow 与 Skia 位图场景
description: 独立 RasterScene Capability 的安装、配置与资源预算
icon: lucide/shapes
---

# Pillow 与 Skia 位图场景

Pillow 与 Skia 提供独立的、进程内 `RasterScene` 渲染能力。它们不消费
`PreparedHtml`，也不是 Playwright/Takumi 所属的 `EngineProvider` 或 HTML
渲染引擎；是否启用这些能力与 `render.provider` 的选择相互独立。

当前中立场景契约只包含物理像素画布、背景色和按顺序执行的实色矩形。它不模拟
HTML layout、文本 shaping 或后端原生对象。两个后端遵循概念上的 straight-alpha
sRGB 输入与 source-over 合成，但不承诺编码 bytes 或逐 channel 像素完全相同。

## 安装

按实际使用的后端安装 extra：

```bash
uv add "nonebot-plugin-htmlrender[pillow]>=0.8.0a1,<0.9"
uv add "nonebot-plugin-htmlrender[skia]>=0.8.0a1,<0.9"
```

`pillow` extra 安装 Pillow 12 或更高版本。`skia` extra 安装
`skia-python>=144.0.post2`；配置了某个后端但没有安装对应 extra 时，composition
会抛出带安装提示的 `RasterBackendUnavailable`，不会退回另一后端。

!!! warning "Skia 发布平台限制"

    `skia-python` 当前只发布预编译 wheel，没有 sdist，也没有 musllinux wheel。
    Linux wheel 要求 manylinux_2_28 兼容环境，并仍可能需要系统提供 OpenGL、
    `libEGL` 与 fontconfig 等运行库；macOS 需要 11 或更高版本；Windows x64
    覆盖 Python 3.10–3.14，ARM64 只覆盖 3.11–3.14，且没有 win32 wheel。因此
    Alpine/musl、较旧 glibc 或缺少图形运行库的镜像不应启用 `skia` extra。
    `all` extra 也包含 Skia，具有同样的平台约束。

## 配置

```yaml
render:
  provider: null
  graphics:
    backends:
      - pillow
      - skia
    max_pixels: 16777216
    max_concurrency: 2
```

| 路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.graphics.backends` | `[]` | 显式启用的 `pillow` / `skia` Capability；不可重复 |
| `render.graphics.max_pixels` | `16777216` | 单个场景的 `width * height` 上限，必须大于 `0` |
| `render.graphics.max_concurrency` | `2` | 所有已启用 graphics 后端共享的 native work 并发槽，必须大于 `0` |

`backends` 为空时不会导入 Pillow 或 Skia。两个后端同时启用时共享同一个像素策略
与并发预算，不能通过在 Pillow 和 Skia 之间切换来绕过限制。native draw/encode
会交给 composition 注入的 worker 执行，不阻塞异步事件循环。

JPEG 输出会先把完整 RGBA 场景合成到不透明 matte，再编码；默认 matte 为白色，
默认 quality 为 `90`。这些数值是共同输入，不代表两个 native encoder 会产生相同
文件。具体调用方式见 [API 的 RasterScene Capability](../api.md#rasterscene-capability)。
