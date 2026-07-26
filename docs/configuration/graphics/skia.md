---
title: Skia 后端
description: Skia RasterScene Capability 的安装、启用与平台约束
icon: lucide/pen-tool
---

# Skia 后端

Skia 后端执行与 Pillow 相同的 `RasterScene` 契约，但使用 `skia-python` native
renderer。选择它不会改变场景模型，也不保证与 Pillow 产生相同 bytes。

## 安装

```bash
uv add "nonebot-plugin-htmlrender[skia]>=0.8.0a1,<0.9"
```

`skia` extra 安装 `skia-python>=144.0.post2`。未安装 extra 却启用后端时，composition 抛出带安装提示的 `RasterBackendUnavailable`，不会回退到 Pillow。

## 平台约束

!!! warning "Skia 发布平台限制"

    `skia-python` 当前只发布预编译 wheel，没有 sdist 或 musllinux wheel。Linux wheel 要求 manylinux_2_28 兼容环境，并可能需要系统提供 OpenGL、`libEGL` 与 fontconfig；macOS 需要 11 或更高版本。Windows x64 覆盖Python 3.10–3.14，ARM64 只覆盖 3.11–3.14，且没有 win32 wheel。Alpine/musl、较旧 glibc 或缺少图形运行库的镜像不应启用 `skia` extra；`all` extra 也包含 Skia，具有相同平台约束。

## 启用

```yaml
render:
  graphics:
    backends:
      - skia
```

像素、命令与并发限制由共享的 `render.graphics` 配置控制，见[Graphics 后端总览](index.md#graphics-settings)。调用方通过`app.extensions.skia` 获取 renderer；native draw 或 encode 失败翻译为`RasterBackendExecutionError`。

完整调用示例见[绘制 RasterScene](../../guides/raster-scenes.md)。
