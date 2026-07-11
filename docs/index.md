---
title: 概览
description: 面向用户与维护者的统一文档入口
icon: lucide/book-open
status: new
tags:
  - Guide
  - Overview
---

# nonebot-plugin-htmlrender 文档

`nonebot-plugin-htmlrender` 是一个面向 NoneBot 生态的库型渲染插件。\
它通过 Playwright 浏览器或 Takumi 原生引擎提供统一渲染能力，把文本、Markdown、HTML 和模板页面渲染为图片，适合消息卡片、海报、榜单、报告图和模板化内容生成等场景。

它的定位不是“开箱即用的业务插件”，而是“渲染能力库”：

- 不内置可直接触发的 matcher
- 由业务插件或应用代码负责接收事件或命令
- 由本插件负责生成图片或提供底层页面上下文

如果你只关心怎么接入，请走用户文档。\
如果你要继续维护这个仓库、排查底层行为或参与重构，请走开发者文档。

<div class="grid cards" markdown>

- **面向用户**

    ______________________________________________________________________

    从安装、配置、调用到排障与迁移，覆盖把渲染能力接进业务插件的路径。

    [进入用户文档](users/index.md)

- **面向开发者**

    ______________________________________________________________________

    面向维护者解释架构边界、backend 扩展、资源解析、测试矩阵与发布流程。

    [进入开发者文档](maintainers/index.md)

- **排障与运维**

    ______________________________________________________________________

    按启动失败、浏览器不可用、远程资源不可达、安全边界等场景定位问题。

    [查看故障排查](users/troubleshooting.md)

- **后端扩展**

    ______________________________________________________________________

    理解 `Render` / `Backend` / `Runtime` / `Session` 的职责，并落地新的渲染后端。

    [查看渲染后端开发](maintainers/architecture/render-backend-development.md)

</div>

## 你可以在这里找到什么

核心能力：

- 统一渲染 API：`render_text`、`render_markdown`、`render_html`、`render_template`
- 两套正式后端：Playwright 浏览器执行与 `takumi-py==0.2.0` 原生静态渲染
- 远程能力支持：远程 Playwright / 远程浏览器两种接入模式
- 资源解析链路：默认内存资产桥跨容器传输本地资源，filehost 保留为显式兼容模式
- 观测能力扩展：可选接入 sentry / prometheus 观察渲染链路指标与异常
- 兼容层过渡：保留旧接口用于迁移，但新项目推荐直接使用新 API

文档结构：

- 面向用户：接入、配置、调用、排障、迁移
- 面向开发者：架构、协作流程、测试矩阵、CI 与版本发布

## 阅读路径

=== "我是调用方"

    推荐顺序：

    1. [快速开始](users/quickstart.md)
    1. [API 与兼容层](users/api.md)
    1. [配置总览](users/config/index.md)
    1. [远程 Playwright 与资源桥](users/remote-playwright.md)
    1. [故障排查](users/troubleshooting.md)
    1. [常见问题](users/faq.md)
    1. [安全须知](users/security.md)
    1. [v0.7.2 迁移说明](users/migration-v072.md)
    1. [旧版本迁移指南](users/migration.md)

=== "我是维护者"

    推荐顺序：

    1. [开发者概览](maintainers/index.md)
    1. [分层架构](maintainers/architecture/architecture.md)
    1. [渲染后端开发指南](maintainers/architecture/render-backend-development.md)
    1. [资源准备与传输方案](maintainers/architecture/filehost-resource-resolution.md)
    1. [工程协作与规范](maintainers/contributing/engineering-guide.md)
    1. [测试矩阵](maintainers/quality/testing-matrix.md)

## 用户文档

- [用户概览](users/index.md)
- [快速开始](users/quickstart.md)
- [API 与兼容层](users/api.md)
- [配置总览](users/config/index.md)
- [基础配置与加载](users/config/core.md)
- [Playwright 配置](users/config/playwright.md)
- [Takumi 配置与能力](users/config/takumi.md)
- [依赖扩展与观测](users/config/integrations.md)
- [示例项目](users/examples.md)
- [最佳实践](users/best-practices.md)
- [远程 Playwright 与资源桥](users/remote-playwright.md)
- [故障排查](users/troubleshooting.md)
- [常见问题](users/faq.md)
- [安全须知](users/security.md)
- [v0.7.2 迁移说明](users/migration-v072.md)
- [旧版本迁移指南](users/migration.md)

## 开发者文档

- [开发者概览](maintainers/index.md)
- [分层架构](maintainers/architecture/architecture.md)
- [自定义 Backend 指南](maintainers/architecture/custom-backends.md)
- [渲染后端开发指南](maintainers/architecture/render-backend-development.md)
- [资源准备与传输方案](maintainers/architecture/filehost-resource-resolution.md)
- [工程协作与规范](maintainers/contributing/engineering-guide.md)
- [贡献指南](maintainers/contributing/contributing.md)
- [提交消息指南](maintainers/contributing/commit-message.md)
- [编码规范](maintainers/contributing/coding-standards.md)
- [测试矩阵](maintainers/quality/testing-matrix.md)
- [CI Actions](maintainers/quality/ci-actions.md)
- [文档版本管理](maintainers/quality/versioning.md)

## 仓库外部入口

- [GitHub 仓库](https://github.com/kexue-z/nonebot-plugin-htmlrender)
- [PyPI 页面](https://pypi.org/project/nonebot-plugin-htmlrender/)
