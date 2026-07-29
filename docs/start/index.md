---
title: 开始使用
description: 完成第一次渲染，并按需选择渲染后端
icon: lucide/book-open
---

# 开始使用

本章帮助新项目完成第一次渲染，并在默认 Playwright 方案不合适时选择其他后端。不需要先读完配置或 API 参考。

## 推荐路径

1. [快速开始](quickstart.md)：安装 Playwright 并得到第一张图片。
2. [选择渲染后端](choosing-provider.md)：默认方案不满足部署或能力要求时，再比较 Playwright、HTMLKit、Takumi 与 Graphics。
3. [渲染内容](../guides/rendering-content.md)：接入 HTML、Markdown、文本或模板。
4. 按需查阅[配置总览](../configuration/index.md)，补充启动、资源与观测设置。

## 按任务查找

| 任务 | 入口 |
| --- | --- |
| 本地 Jinja 模板和图片 | [模板与资源](../guides/templates-and-resources.md) |
| 浏览器导航或元素截图 | [操作浏览器页面](../guides/browser-automation.md) |
| 远程浏览器 | [远程 Playwright 部署](../configuration/remote-playwright.md) |
| 资源刷新与缓存调优 | [缓存组件、失效与调优](../guides/cache-lifecycle.md) |
| 无 HTML 的像素绘制 | [绘制 RasterScene](../guides/raster-scenes.md) |
| 启动或资源失败 | [故障排查](../configuration/troubleshooting.md) |
| 从 0.7 升级 | [v0.8 迁移指南](../guides/migration/v0.8.md) |
| 实现第三方 Provider | [Provider 开发指南](../extensions/provider-development.md) |

阅读中遇到 `PreparedHtml`、Capability、artifact 等术语时，按需查阅[术语表](../reference/glossary.md)，不需要在第一次渲染前预先学习完整对象模型。
