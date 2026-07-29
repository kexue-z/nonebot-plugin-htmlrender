---
title: 指南
description: 从首次渲染到部署、排障与升级的任务路径
icon: lucide/list-checks
---

# 指南

指南回答“怎样完成一件事”，不要求从头读到尾。首次接入沿入门路径前进；已有项目直接选择渲染任务、部署运维或迁移章节。需要核对字段、类型和错误契约时转到[参考手册](../reference/index.md)；只需确认名词含义时查[术语表](../reference/glossary.md)。

## 首次接入

1. [快速开始](../start/quickstart.md)：使用默认推荐的 Playwright 完成第一张图片。
2. [选择渲染后端](../start/choosing-provider.md)：需要替换默认后端时比较能力与环境约束。
3. [渲染内容](rendering-content.md)：接入 HTML、Markdown、文本或 Jinja 模板。
4. 按需查阅[配置总览](../configuration/index.md)，不要预先阅读全部配置字段。

## 按任务进入

| 目标 | 章节 |
| --- | --- |
| 组织模板、图片、字体和样式 | [模板与资源](templates-and-resources.md) |
| 导航网页或截取指定元素 | [操作浏览器页面](browser-automation.md) |
| 绘制后端中立的像素场景 | [绘制 RasterScene](raster-scenes.md) |
| 约束生命周期、超时和错误处理 | [最佳实践](best-practices.md) |
| 连接远程浏览器 | [远程 Playwright](../configuration/remote-playwright.md) |
| 刷新资源、理解缓存或调优容量 | [缓存组件、失效与调优](cache-lifecycle.md) |
| 处理生产安全与故障 | [安全须知](../configuration/security.md) · [故障排查](../configuration/troubleshooting.md) |
| 从旧版本升级 | [升级与迁移](migration/index.md) |

任务页链接仓库中的可运行示例；示例展示组合方式，稳定契约仍以参考手册为准。
