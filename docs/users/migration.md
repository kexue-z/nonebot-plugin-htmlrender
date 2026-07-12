---
title: 旧版本迁移索引
description: 0.7.2 与 0.8 迁移文档的历史索引
icon: lucide/move
status: new
tags:
  - Users
  - Migration
---

# 旧版本迁移索引

!!! warning "历史索引"

    0.8 已删除 0.7 的兼容 API、过渡对象模型与平铺配置键。旧符号不会再转发，
    `RENDER_BACKEND`、`RENDER_STARTUP_MODE`、`RENDER_PLAYWRIGHT` 等旧配置会在
    插件加载时被拒绝。本页不提供可复制的当前配置。

请选择与来源版本对应的迁移文档：

- 0.7.1 → 0.7.2：[v0.7.2 迁移说明](migration-v072.md)
- 0.7.x → 0.8：[v0.8 迁移指南](migration-v080.md)

新项目直接从[快速开始](quickstart.md)与[基础配置](config/core.md)开始；架构背景见
[分层架构](../maintainers/architecture/architecture.md)，当前公开契约见 [0.8 API](api.md)。
