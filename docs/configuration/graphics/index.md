---
title: Graphics 后端
description: Pillow 与 Skia 共享的 RasterScene 契约、配置和资源预算
icon: lucide/shapes
---

# Graphics 后端

Graphics 后端提供独立的、进程内 `RasterScene` 渲染能力。它们不消费`PreparedHtml`，也不是 HTML `EngineProvider`；是否启用 Graphics 后端与`render.provider` 的选择相互独立。

当前中立场景契约包含物理像素画布、背景色和按顺序执行的实色矩形。它不模拟HTML layout、文本 shaping 或后端原生对象。Pillow 与 Skia 遵循同一输入契约，但不承诺生成相同的编码 bytes 或逐 channel 完全一致。

## 选择后端

| 后端 | 适合场景 | 主要约束 |
| --- | --- | --- |
| [Pillow](pillow.md) | 兼容面优先、普通 CPU 位图输出 | 需要 Pillow 12 或更高版本 |
| [Skia](skia.md) | 已部署 Skia 运行环境、需要对应 native renderer | wheel、glibc 和系统图形库存在平台限制 |

两个后端可以同时启用。调用方通过不同的 typed Capability key 明确选择后端，不会自动回退或按环境猜测。

## 共享配置 { #graphics-settings }

```yaml
render:
  provider: null
  graphics:
    backends:
      - pillow
      - skia
    max_pixels: 16777216
    max_concurrency: 2
    max_commands: 100000
```

| 路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.graphics.backends` | `[]` | 显式启用的 `pillow` / `skia` Capability；不可重复 |
| `render.graphics.max_pixels` | `16777216` | 单场景 `width * height` 上限，必须大于 `0` |
| `render.graphics.max_concurrency` | `2` | 所有 Graphics 后端共享的 native work 并发槽 |
| `render.graphics.max_commands` | `100000` | 单场景 `FillRect` 命令数量上限 |

`backends` 为空时不会导入 Pillow 或 Skia。两个后端共享像素、命令和并发预算，不能通过切换后端绕过限制。native draw/encode 由 composition 注入的 worker 执行，不会阻塞异步事件循环。

JPEG 输出先把完整 RGBA 场景合成到不透明 matte，再编码；默认 matte 为白色、quality 为 `90`。调用模型与错误契约见[Capability 参考](../../reference/capabilities.md#rasterscene)，环境变量示例见[`.env` 配置](../dotenv.md#common-backends)。
