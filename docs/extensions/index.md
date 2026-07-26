---
title: 原理与扩展
description: 系统设计原理、资源管线与 Provider 扩展
icon: lucide/blocks
---

# 原理与扩展

本区包含两条独立路径：理解现有系统时阅读设计原理；实现第三方渲染后端时进入Provider 扩展。只有开发扩展时才需要把两条路径串联起来。

本区解释概念之间的关系，不重复定义名词；定义统一收录在[术语表](../reference/glossary.md)。

## 理解设计

1. [分层架构](architecture.md)：理解 application、preparation、resource 与 adapter 边界。
2. [资源管线](resource-pipeline.md)：深入授权、缓存、物化与远程传输不变量。

## 开发 Provider

1. [Provider 契约](provider-contract.md)：查阅 discovery、settings、bindings 与 Capability 约束。
2. [Provider 开发指南](provider-development.md)：实现、测试并发布第三方 Provider。

第三方 Provider 对外只依赖公开 SDK；不要导入 bootstrap、内部配置模块或具体Resource Service 实现。
