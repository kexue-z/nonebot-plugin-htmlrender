# Pillow/Skia RasterScene 示例

展示如何显式获取 Pillow 或 Skia 的 `RasterSceneRenderer` typed Capability，并渲染同一个后端中立、物理像素级场景。Pillow/Skia 不是 HTML Provider，也不会消费`render.provider_config`。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/graphics_scene [pillow\|skia]` | 使用已启用的 graphics backend 渲染场景 |

## Pillow 安装与配置

```bash
nb create  # 创建 NoneBot 项目并选择 OneBot V11 adapter
uv add "nonebot-plugin-htmlrender[pillow]>=0.8.0,<0.9"
uv add nonebot-plugin-alconna
```

复制 `plugins/graphics_render` 到项目插件目录，并写入：

```dotenv
RENDER={"provider":null,"graphics":{"backends":["pillow"],"max_pixels":16777216,"max_concurrency":2}}
```

## 同时启用 Skia

```bash
uv add "nonebot-plugin-htmlrender[pillow,skia]>=0.8.0,<0.9"
```

```dotenv
RENDER={"provider":null,"graphics":{"backends":["pillow","skia"],"max_pixels":16777216,"max_concurrency":2}}
```

两个 backend 共用 composition-owned 像素与并发预算，但各自拥有独立的 capability
key。Skia 的 wheel 和系统图形库存在平台限制；不受支持的环境应只启用 Pillow。
