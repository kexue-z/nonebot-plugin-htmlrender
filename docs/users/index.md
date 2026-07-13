---
title: 用户概览
description: 接入、使用、排障与迁移的统一入口
icon: lucide/users
status: new
tags:
  - Users
---

# 面向用户

!!! info "库型插件说明"
    本插件以 **library** 形态提供能力，不内置任何可直接触发的 `message matcher`。
    你需要在自己的插件或应用里调用 API 来完成渲染流程。

## 推荐阅读顺序

<div class="grid cards" markdown>

- **1. 接入**

    ---

    [快速开始](quickstart.md) -> [配置总览](config/index.md)

- **2. 调用**

    ---

    [API 与兼容层](api.md) -> [示例项目](examples.md) -> [最佳实践](best-practices.md)

- **3. 部署**

    ---

    [远程 Playwright 与 Filehost](remote-playwright.md) -> [安全须知](security.md)

- **4. 收口**

    ---

    [故障排查](troubleshooting.md) -> [常见问题](faq.md) -> [旧版本迁移指南](migration.md)

</div>

## 按问题找文档

=== "正在接入"

    - [快速开始](quickstart.md)：最短接入路径
    - [配置总览](config/index.md)：配置面全览
    - [Playwright 配置](config/playwright.md)：浏览器、连接、安装与启动策略
    - [依赖扩展与观测](config/integrations.md)：filehost、sentry、prometheus

=== "编写业务代码"

    - [API 与兼容层](api.md)：公共 API、兼容层与高级入口
    - [示例项目](examples.md)：常见调用方式
    - [最佳实践](best-practices.md)：目录组织、模板管理与接入节奏

=== "排障或部署"

    - [远程 Playwright 与 Filehost](remote-playwright.md)：远程浏览器、资源可达性与 filehost
    - [故障排查](troubleshooting.md)：按报错现象定位问题
    - [常见问题](faq.md)：部署与接入高频问题
    - [安全须知](security.md)：远端连接、任意 HTML、filehost 暴露面的加固建议

=== "迁移旧项目"

    - [v0.7.2 迁移说明](migration-v072.md)：远程 Playwright 的 Markdown 渲染修复
    - [旧版本迁移指南](migration.md)：从旧 API、旧配置和历史行为迁移到新路径

## 新项目建议

推荐新项目直接使用以下新 API：

- `render_text`
- `render_markdown`
- `render_html`
- `render_template`

兼容层仅用于迁移，不建议作为新代码入口。
