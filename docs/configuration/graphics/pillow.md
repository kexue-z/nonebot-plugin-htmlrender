---
title: Pillow 后端
description: Pillow RasterScene Capability 的安装、启用与运行约束
icon: lucide/image
---

# Pillow 后端

Pillow 后端执行后端中立的 `RasterScene`，适合优先考虑安装兼容性和普通 CPU位图输出的部署环境。

## 安装

```bash
uv add "nonebot-plugin-htmlrender[pillow]>=0.8.0,<0.9"
```

`pillow` extra 安装 Pillow 12 或更高版本。未安装 extra 却启用后端时，composition抛出带安装提示的 `RasterBackendUnavailable`，不会回退到 Skia。

## 平台约束

Pillow 为受支持的 Python 和主流平台发布 wheel。官方 Linux wheel 已捆绑当前`RasterScene` draw/PNG/JPEG 路径需要的常用图像库，因此正常 wheel 安装不要求额外的 EGL、OpenGL、Cairo 或 Fontconfig 动态库。若安装器找不到匹配 wheel 而回退到源码构建，则必须按 Pillow 的[构建说明](https://pillow.readthedocs.io/en/stable/installation/building-from-source.html)准备对应头文件与编译工具链；不要把源码构建依赖当作 wheel 的运行时依赖。

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
