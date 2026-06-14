---
title: 贡献指南
description: 参考 Angular 协作方式整理的本仓库贡献流程
icon: lucide/users
status: new
tags:
  - Maintainers
  - Contribution
---

# 贡献指南

本文参考了 [angular/angular](https://github.com/angular/angular) 的协作思路，并结合本仓库技术栈做了裁剪。

## 你可以贡献什么

- 修复 bug、补测试、完善文档
- 新增渲染能力（后端、资源解析、可观测性）
- 优化 CI、开发体验与示例

## 开始之前

1. Fork 仓库并创建分支（建议短生命周期分支）。
2. 安装依赖并准备本地环境。
3. 如果变更涉及真实浏览器路径，先安装 Playwright Chromium。

```bash
make sync-all
make install-prek
make install-browser   # 仅需要真实浏览器测试时执行
```

## 分支与变更建议

- 一个 PR 聚焦一个主题，避免“功能 + 重构 + 格式化”混在一起。
- 架构变更需同步补文档（`docs/maintainers/architecture/architecture.md` / 相关专题）。
- 对外 API 行为变化需同步补用户文档（`docs/users/`）。

## 提交前检查

至少跑过以下命令：

```bash
make ruff-format
make ruff-check
make typecheck
make ty
make test-ci
make docs-build          # 若本次修改了文档
```

如变更涉及真实浏览器行为，建议再跑：

```bash
make test-local
```

## Pull Request 要求

PR 描述建议包含：

1. 变更动机（为什么要改）
2. 方案说明（怎么改）
3. 风险与兼容性（可能影响什么）
4. 验证结果（跑了哪些命令）
5. 文档同步情况（是否更新 docs）

## Review 约定

- Review 重点优先级：正确性 > 回归风险 > 可维护性 > 风格。
- 对建议项（nit）和阻塞项（must fix）请明确区分。
- 如评审意见影响公共行为，请在 PR 里补充说明与测试。

## 行为准则

参与协作时默认遵守 [Code of Conduct](https://github.com/kexue-z/nonebot-plugin-htmlrender/blob/master/CODE_OF_CONDUCT.md)。
