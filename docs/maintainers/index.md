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

## 建议阅读顺序

1. [分层架构](architecture/architecture.md)
2. [自定义 Backend 指南](architecture/custom-backends.md)
3. [Filehost 资源解析方案](architecture/filehost-resource-resolution.md)
4. [工程协作与规范](contributing/engineering-guide.md)
5. [测试矩阵](quality/testing-matrix.md)
6. [CI Actions](quality/ci-actions.md)

## 架构与设计

- [分层架构](architecture/architecture.md)
- [自定义 Backend 指南](architecture/custom-backends.md)
- [Filehost 资源解析方案](architecture/filehost-resource-resolution.md)

## 协作流程

- [贡献指南](contributing/contributing.md)
- [工程协作与规范](contributing/engineering-guide.md)
- [编码规范](contributing/coding-standards.md)
- [提交消息指南](contributing/commit-message.md)

## 质量与发布

- [测试矩阵](quality/testing-matrix.md)
- [CI Actions](quality/ci-actions.md)
- [文档版本管理](quality/versioning.md)

## 当前维护重点

如果你正在处理这轮重构后的收口工作，优先关注：

- `render.py` 与 `backend/` 的生命周期边界
- `backend/playwright/` 中 runtime、operations、compat 的职责分离
- `resources/` 中资源解析、filehost 守卫、lease/caching 的一致性
- 测试分层是否仍对应主实现边界，而不是跟着历史目录漂移
