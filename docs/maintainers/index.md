---
title: 开发者概览
description: 面向维护者的架构、流程与质量入口
icon: lucide/wrench
status: new
tags:
  - Developers
---

# 面向开发者

维护者文档关注三件事：

- 当前实现是怎么组织的
- 这套实现应该如何验证与发布
- 后续演进时哪些边界不能被破坏

<div class="grid cards" markdown>

- **架构与 backend**

    ---

    理解渲染主链路、Backend Protocol、资源解析和后端开发的落地步骤。

    [分层架构](architecture/architecture.md)

- **协作流程**

    ---

    对齐贡献入口、工程规范、编码风格和提交消息格式。

    [Pull Request 生命周期](contributing/pull-requests.md)

- **质量与发布**

    ---

    查看测试分层、CI 工作流、软件发布和文档版本规则。

    [发布流程](quality/release-process.md)

</div>

## 建议阅读顺序

=== "维护代码"

    1. [分层架构](architecture/architecture.md)
    2. [Filehost 资源解析方案](architecture/filehost-resource-resolution.md)
    3. [工程协作与规范](contributing/engineering-guide.md)
    4. [测试矩阵](quality/testing-matrix.md)

=== "开发 backend"

    1. [分层架构](architecture/architecture.md)
    2. [自定义 Backend 指南](architecture/custom-backends.md)
    3. [渲染后端开发指南](architecture/render-backend-development.md)
    4. [测试矩阵](quality/testing-matrix.md)

=== "发布文档"

    1. [贡献指南](contributing/contributing.md)
    2. [Pull Request 生命周期](contributing/pull-requests.md)
    3. [发布流程](quality/release-process.md)
    4. [CI Actions](quality/ci-actions.md)
    5. [文档版本管理](quality/versioning.md)

## 推荐同步阅读的用户文档

维护者在排查 issue、判断兼容性影响或评估默认行为时，通常也需要回看用户侧文档：

- [故障排查](../users/troubleshooting.md)
- [常见问题](../users/faq.md)
- [安全须知](../users/security.md)
- [旧版本迁移指南](../users/migration.md)

## 架构与设计

- [分层架构](architecture/architecture.md)
- [自定义 Backend 指南](architecture/custom-backends.md)
- [渲染后端开发指南](architecture/render-backend-development.md)
- [Filehost 资源解析方案](architecture/filehost-resource-resolution.md)

## 协作流程

- [贡献指南](contributing/contributing.md)
- [Pull Request 生命周期](contributing/pull-requests.md)
- [工程协作与规范](contributing/engineering-guide.md)
- [编码规范](contributing/coding-standards.md)
- [提交消息指南](contributing/commit-message.md)

## 质量与发布

- [测试矩阵](quality/testing-matrix.md)
- [CI Actions](quality/ci-actions.md)
- [发布流程](quality/release-process.md)
- [文档版本管理](quality/versioning.md)

## 当前维护重点

如果你正在处理这轮重构后的收口工作，优先关注：

- `render.py` 与 `backend/` 的生命周期边界
- `backend/playwright/` 中 runtime、operations、compat 的职责分离
- `resources/` 中资源解析、filehost 守卫、lease/caching 的一致性
- 测试分层是否仍对应主实现边界，而不是跟着历史目录漂移
