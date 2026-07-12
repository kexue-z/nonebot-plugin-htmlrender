---
title: 用户文档
description: 安装、配置与使用 0.8 渲染 API
icon: lucide/book-open
---

# 用户文档

0.8 的稳定调用面由通用渲染函数、request、Preparation 模型和类型化产物
组成。浏览器页面、Takumi node 等专属操作只从对应 Capability 获取。

## 推荐路径

1. [快速开始](quickstart.md)：安装 Provider 并得到第一张图片。
2. [配置总览](config/index.md)：选择启动策略、资源策略和观测集成。
3. [API](api.md)：使用函数式 API 或显式 `Application`。
4. [最佳实践](best-practices.md)：管理生命周期、错误与产物边界。

## 按场景查找

| 场景 | 文档 |
| --- | --- |
| 远程浏览器 | [远程 Playwright 与资源传输](remote-playwright.md) |
| 本地 Jinja 模板 | [示例项目](examples.md) |
| 无浏览器的静态渲染 | [Takumi 配置与能力](config/takumi.md) |
| 0.7 升级 | [v0.8 迁移指南](migration-v080.md) |
| 启动或资源失败 | [故障排查](troubleshooting.md) |
| 本地文件与不可信输入 | [安全须知](security.md) |

## 结果边界

`RenderedImage` 不是 `bytes` 的别名。消息、HTTP 或文件 API 需要原始字节时，
显式调用 `bytes(artifact)`；模板到 HTML 返回 `RenderedHtml`，使用
`str(artifact)`。这一边界能保留格式、尺寸与媒体类型信息。
