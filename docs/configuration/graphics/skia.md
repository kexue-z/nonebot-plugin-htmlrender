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
uv add "nonebot-plugin-htmlrender[skia]>=0.8.0,<0.9"
```

`skia` extra 安装 `skia-python>=144.0.post2`。未安装 extra 却启用后端时，composition 抛出带安装提示的 `RasterBackendUnavailable`，不会回退到 Pillow。

## 平台约束

!!! warning "Skia 发布平台限制"

    `skia-python` 当前只发布预编译 wheel，没有 sdist 或 musllinux wheel。Linux wheel 要求 manylinux 2.28 兼容环境；macOS 需要 11 或更高版本。Windows x64 覆盖 Python 3.10–3.14，ARM64 只覆盖 3.11–3.14，且没有 win32 wheel。Alpine/musl 或较旧 glibc 镜像不应启用 `skia` extra；`all` extra 也包含 Skia，具有相同平台约束。

### Linux 动态库

`skia-python==144.0.post2` 的 x86-64 与 AArch64 Linux wheels 都捆绑了 Fontconfig、FreeType 与 libpng，但 native module 仍直接链接以下宿主库：

- `libEGL.so.1`；
- `libGL.so.1`；
- `libexpat.so.1`；
- glibc、libstdc++、libgcc 与 zlib 基线运行库。

Python extra、PyOpenGL 或其他 Python wrapper 都不会提供这些 ELF shared objects。Debian/Ubuntu 的最小镜像应在安装 Python 包前补齐运行库：

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libegl1 \
        libexpat1 \
        libgl1 \
        libstdc++6 \
        zlib1g
```

构建镜像后执行 import smoke，避免到测试收集或应用启动时才发现动态库缺失：

```bash
uv run python3 -c "import skia"
```

`ImportError: libEGL.so.1: cannot open shared object file` 表示缺少 Debian/Ubuntu 的 `libegl1`，不是 `skia` extra 未解析成功。修复 `libEGL` 后如果随后报告 `libGL.so.1` 或 `libexpat.so.1`，分别检查 `libgl1` 与 `libexpat1`。字体文件仍需按业务字符集随部署提供，但无需另装 Fontconfig shared library。

## 启用

```yaml
render:
  graphics:
    backends:
      - skia
```

像素、命令与并发限制由共享的 `render.graphics` 配置控制，见[Graphics 后端总览](index.md#graphics-settings)。调用方通过`app.extensions.skia` 获取 renderer；native draw 或 encode 失败翻译为`RasterBackendExecutionError`。

完整调用示例见[绘制 RasterScene](../../guides/raster-scenes.md)。
