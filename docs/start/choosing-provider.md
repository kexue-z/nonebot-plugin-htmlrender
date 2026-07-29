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

首次接入优先选择 Playwright：它覆盖最完整的浏览器语义，也最容易判断网页与CSS 的实际行为。Playwright 的部署形态按“Docker 中的远程 WS 服务 > Bot 宿主机本地浏览器”排序：远程服务隔离浏览器二进制、系统图形库和进程生命周期，是生产部署首选；宿主机模式作为第二选项，适合本地开发或无法增加服务的环境。只有确认内容不依赖浏览器布局或 JavaScript 时，再根据部署体积、平台与专属能力选择 HTMLKit 或 Takumi。

## 部署依赖矩阵 { #deployment-dependency-matrix }

Extra 只声明 Python distribution，不能替代浏览器二进制、系统动态库或不匹配平台时的源码工具链。项目当前锁定版本的部署边界如下：

| 引擎 | Extra 安装的内容 | 宿主环境仍需提供 |
| --- | --- | --- |
| Playwright | Python client | 首选 Docker 中版本匹配的远程 WS 服务，把浏览器与系统依赖隔离在服务端；第二选项是在 Bot 宿主机安装匹配浏览器，Linux 还需浏览器系统依赖 |
| HTMLKit | `nonebot-plugin-htmlkit` native wheel | 支持的平台 wheel 已包含 litehtml、Cairo 与 Fontconfig 实现，不需要单独安装对应 `.so`；仍需可用字体。无匹配 wheel 时源码构建需要 Xmake 与 native toolchain |
| Takumi | `takumi-py` Rust native wheel | 支持的平台 wheel 只依赖对应 manylinux/glibc 或操作系统基线；仍需业务使用的字体。无匹配 wheel 时需要 Rust/maturin 源码工具链 |
| Pillow | Pillow wheel | 官方 wheel 已包含当前 `RasterScene` 所需的图像库；源码构建才需要相应开发库 |
| Skia | `skia-python` native wheel | Linux 需要 manylinux 2.28 兼容的 glibc，以及 `libEGL.so.1`、`libGL.so.1`、`libexpat.so.1` 等运行库；仍需业务使用的字体 |

安装完成不代表运行时已经可导入。容器和 CI 应在构建阶段完成系统包安装，并对启用的 native backend 执行 import smoke；各引擎的精确命令见对应配置页。

## 通用能力与专属能力

能消费 `PreparedHtml` 并准确满足请求的 Provider 才会提供通用位图渲染。页面、node、measure、animation 等引擎语义通过 typed Capability 暴露，不会成为通用 request 的可选参数。第一方能力从 `app.extensions.playwright`、`.takumi`、`.pillow` 或 `.skia` 直接取得；第三方能力使用 `get(KEY)` / `require(KEY)`。缺失的必需能力会抛出稳定的 `CapabilityUnavailable`。

## 下一步

- [完成第一次渲染](quickstart.md)
- [配置 Provider](../configuration/index.md)
- [了解通用与专属 API](../reference/index.md)
- [开发第三方 Provider](../extensions/provider-development.md)
