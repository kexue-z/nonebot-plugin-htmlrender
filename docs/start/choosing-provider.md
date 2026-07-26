---
title: 选择渲染后端
description: 按渲染语义、运行环境与专属能力选择执行后端
icon: lucide/waypoints
---

# 选择渲染后端

`render.provider` 选择 HTML 执行引擎；Pillow 与 Skia 是独立的`RasterScene` Capability，不参与 Provider 选择。业务代码如果只使用通用`render_*` API，可以在不改变 Preparation 和调用形态的情况下更换 Provider。

## 选择矩阵

| 需求 | 推荐选择 | 主要约束 |
| --- | --- | --- |
| 浏览器布局、JavaScript、网页导航或元素截图 | Playwright | 需要浏览器进程或兼容的远程服务 |
| 轻量静态 HTML，宿主环境提供 HTMLKit | HTMLKit | 支持的 CSS、选项与事件循环受 native 引擎约束 |
| 无浏览器静态渲染、node、SVG 或 animation | Takumi | 依赖 native wheel，安装与平台支持需单独确认 |
| 物理像素矩形绘制 | Pillow 或 Skia | 不是 HTML 后端，只执行 `RasterScene` |
| 只生成或检查 HTML | 不配置 Provider | Preparation 与 `render_template_html` 仍可使用 |

首次接入优先选择 Playwright：它覆盖最完整的浏览器语义，也最容易判断网页与CSS 的实际行为。只有确认内容不依赖浏览器布局或 JavaScript 时，再根据部署体积、平台与专属能力选择 HTMLKit 或 Takumi。

## 通用能力与专属能力

能消费 `PreparedHtml` 并准确满足请求的 Provider 才会提供通用位图渲染。页面、node、measure、animation 等引擎语义通过 typed Capability 暴露，不会成为通用 request 的可选参数。第一方能力从 `app.extensions.playwright`、`.takumi`、`.pillow` 或 `.skia` 直接取得；第三方能力使用 `get(KEY)` / `require(KEY)`。缺失的必需能力会抛出稳定的 `CapabilityUnavailable`。

## 下一步

- [完成第一次渲染](quickstart.md)
- [配置 Provider](../configuration/index.md)
- [了解通用与专属 API](../reference/index.md)
- [开发第三方 Provider](../extensions/provider-development.md)
