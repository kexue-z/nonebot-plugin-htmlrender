---
title: Pillow 后端
description: Pillow RasterScene Capability 的安装、启用与运行约束
icon: lucide/image
---

# Pillow 后端

Pillow 后端执行后端中立的 `RasterScene`，适合优先考虑安装兼容性和普通 CPU位图输出的部署环境。

## 安装

```bash
uv add "nonebot-plugin-htmlrender[pillow]>=0.8.0a1,<0.9"
```

`pillow` extra 安装 Pillow 12 或更高版本。未安装 extra 却启用后端时，composition抛出带安装提示的 `RasterBackendUnavailable`，不会回退到 Skia。

## 启用

```yaml
render:
  graphics:
    backends:
      - pillow
```

像素、命令与并发限制由共享的 `render.graphics` 配置控制，见[Graphics 后端总览](index.md#graphics-settings)。

## 运行边界

Pillow 不进入 `render.provider`，调用方通过 `app.extensions.pillow`获取 renderer。输出遵循共享的 RGBA、source-over、JPEG matte 与质量语义；native draw 或 encode 失败翻译为 `RasterBackendExecutionError`。

完整调用示例见[绘制 RasterScene](../../guides/raster-scenes.md)。
