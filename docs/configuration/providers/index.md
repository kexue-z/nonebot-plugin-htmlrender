---
title: HTML 后端
description: Playwright、HTMLKit 与 Takumi 共享的 Provider 契约和配置入口
icon: lucide/panels-top-left
---

# HTML 后端

HTML 后端通过 `EngineProvider` 契约消费后端中立的 `PreparedHtml`，并执行HTML 渲染请求。一次 Application composition 至多选择一个 Provider；未配置Provider 时仍可使用 Preparation，但不能执行需要 HTML 引擎的渲染操作。

Provider 专属的页面、node、measure 或 animation 操作通过 typed Capability暴露，不会扩充通用渲染函数。Pillow 与 Skia 执行独立的 `RasterScene` 契约，不属于 HTML 后端。

## 选择 Provider

| Provider | 适合场景 | 主要约束 |
| --- | --- | --- |
| [Playwright](playwright.md) | 浏览器布局、JavaScript、网页导航与元素截图 | 需要浏览器进程或兼容的远程服务 |
| [HTMLKit](htmlkit.md) | 轻量静态 HTML，宿主环境提供 HTMLKit | CSS、选项和事件循环受 native 引擎约束 |
| [Takumi](takumi.md) | 无浏览器静态渲染、node、SVG 或 animation | 依赖 native wheel，安装与平台支持需单独确认 |

完整的任务与环境选择矩阵见[选择渲染后端](../../start/choosing-provider.md)。

## 共享配置

```yaml
render:
  provider: playwright
  startup: probe
  provider_config: {}
```

- `render.provider` 选择 `playwright`、`htmlkit`、`takumi` 或 `null`。
- `render.startup` 控制所选 Provider 的启动与探测时机。
- `render.provider_config` 由所选 Provider 校验，不同 Provider 的字段不互通。

完整字段树见[配置总览](../index.md)，启动语义见[启动与生命周期](../lifecycle.md)，环境变量写法见[`.env` 配置](../dotenv.md#common-backends)。
