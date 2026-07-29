---
title: HTMLKit 配置
description: 实验性 litehtml Provider 的安装、配置与能力边界
icon: lucide/box
status: new
---

# HTMLKit 配置

HTMLKit 通过 litehtml、Cairo 与 Fontconfig 在进程内执行 HTML/CSS 排版，不启动浏览器。当前适配器精确支持 `nonebot-plugin-htmlkit==0.1.0rc5`，属于实验性Provider；上游仍是 prerelease，并绑定 NoneBot 与 asyncio 生命周期。

## 安装与选择

```bash
uv add "nonebot-plugin-htmlrender[htmlkit]>=0.8.0,<0.9"
```

```yaml
render:
  provider: htmlkit
  startup: probe
  provider_config:
    max_concurrency: 2
```

`htmlkit` extra 与 `playwright`、`takumi`、`pillow`、`skia` 相互独立。HTMLKit 是消费 `PreparedHtml` 的 HTML engine；Pillow/Skia 是消费 `RasterScene` 的 graphics
Capability。两者可以在同一个 composition 中并存，但不共享 backend 类型：

```yaml
render:
  provider: htmlkit
  graphics:
    backends: [pillow]
```

## 配置

下表字段均位于 `render.provider_config`：

| 完整路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.provider_config.max_concurrency` | `min(cpu_count, 4)` | detached native render 的并发上限，1–64 |
| `render.provider_config.default_font_size` | `12.0` | litehtml 默认字体大小 |
| `render.provider_config.font_name` | `sans-serif` | 默认字体族 |
| `render.provider_config.language` | `zh` | CSS/排版语言 |
| `render.provider_config.culture` | `CN` | CSS/排版区域 |
| `render.provider_config.media_dpi` | `96.0` | CSS media environment 的 resolution，不是输出 DPR |
| `render.provider_config.media_height` | `600.0` | CSS media environment 的 device height，不是输出高度 |
| `render.provider_config.resource_resolve_mode` | `auto` | `off`、`auto`、`strict` |

Fontconfig 是上游插件拥有的进程级全局状态。`fontconfig_file`、`fontconfig_path`、`fontconfig_sysroot`、`fc_debug`、`fc_dbg_match_filter`、`fc_lang` 与 `fontconfig_use_mmap` 由 `nonebot-plugin-htmlkit` 自己从 NoneBot配置读取，不属于 `render.provider_config`，也不能按 `Application` 隔离。

## 当前通用 API 限制

HTMLKit rc5 的 `dpi` 不会把 CSS pixel 缩放为物理 pixel，`device_height` 也不会裁剪或补齐输出画布。因此适配器不会静默忽略 `RasterOptions`：

- `device_pixel_ratio` 必须显式设为 `1.0`；
- `height` 必须保持 `None`，输出高度由内容决定；
- 违反这两项会得到 `UnsupportedRenderOption`；
- JavaScript 文档会得到 `UnsupportedRequirement`。

通用便利函数目前默认 `device_pixel_ratio=2.0`，所以使用 HTMLKit 时必须明确覆盖：

```python
from nonebot_plugin_htmlrender import render_html, render_markdown

html_image = await render_html(
    "<strong>Hello from litehtml</strong>",
    width=640,
    device_pixel_ratio=1.0,
)
markdown_image = await render_markdown(
    "# Static content",
    width=640,
    height=None,
    device_pixel_ratio=1.0,
)
```

这不是 Playwright 的 drop-in 等价实现。需要脚本、浏览器布局、selector、页面导航、精确 DPR 或固定 viewport crop 时应选择 Playwright。

## 资源、事件循环与取消

适配器禁用了 HTMLKit 自带的 filesystem/network fetcher。图片和 CSS 只从`PreparedAsset` 或 composition 注入的 `ProviderResources.read_bytes()` 获取，因此继续遵守本地路径白名单、单资源大小限制、共享缓存和 `ResourcePolicy`。Provider拿不到底层 reader、policy 或完整 `ResourceService`。外部 stylesheet 的独立 base
URL 会在交给 native renderer 前保留。

rc5 只支持 asyncio；在 Trio 下启动、探测或执行会得到 `ProviderUnavailable`，不会泄漏原始 event-loop 错误。native 层每次渲染创建 detached thread，取消Python await 无法终止它。为避免 native callback 访问已关闭资源，适配器在传播取消或超时错误前会等待该 native operation 真正结束；因此卡住的 native 调用可能使实际返回时间超过 `timeout_seconds`。

## 平台与许可

rc5 提供 Windows x86-64、macOS ARM64，以及 manylinux/musllinux x86-64 与AArch64 wheel。当前 Linux wheel 已将 litehtml、Cairo 与 Fontconfig 实现包含在 native core 中，不需要宿主另外提供 Cairo 或 Fontconfig `.so`；字体文件、Fontconfig 配置与 locale 仍属于部署资源。其他平台可能回退到需要 Xmake 和 native toolchain 的源码构建。

Python wrapper 使用 MIT，native core 使用 LGPL-3.0-or-later。若重新分发或捆绑其二进制，请单独核对 LGPL 义务；本页不构成法律意见。
