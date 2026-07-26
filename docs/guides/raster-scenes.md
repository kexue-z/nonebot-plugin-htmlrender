---
title: 绘制 RasterScene
description: 使用 Pillow 或 Skia Capability 绘制后端中立的物理像素场景
icon: lucide/shapes
---

# 绘制 RasterScene

`RasterScene` 适合无需 HTML 布局的矩形与纯色场景。Pillow 和 Skia 分别提供独立Capability，但接受同一组后端中立命令。

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.graphics import (
    FillRect,
    PixelRect,
    RasterEncodeOptions,
    RasterScene,
    RenderRasterSceneRequest,
    RGBAColor,
)

renderer = get_default_application().extensions.pillow
request = RenderRasterSceneRequest(
    scene=RasterScene(
        width=320,
        height=180,
        background=RGBAColor(255, 255, 255),
        commands=(
            FillRect(
                PixelRect(x=24, y=24, width=128, height=72),
                RGBAColor(229, 57, 53, 192),
            ),
        ),
    ),
    output=RasterEncodeOptions(format="png"),
)
image = await renderer.render(request)
```

坐标使用物理像素与左闭右开矩形，超出画布的部分会裁剪；命令按 tuple 顺序使用source-over 合成。两个 backend 不保证生成相同 bytes 或逐 channel 完全一致。

安装、启用方式与共享预算见 [Graphics 后端](../configuration/graphics/index.md)，完整模型与错误契约见 [Capability 参考](../reference/capabilities.md)。可运行项目位于`examples/graphics_render`。
