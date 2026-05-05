---
title: 提交消息指南
description: 参考 Angular 风格的 commit message 约定
icon: lucide/message-square-text
status: new
tags:
  - Maintainers
  - Commit
---

# 提交消息指南

本文采用接近 Angular 的提交消息风格，便于后续生成变更日志与快速定位变更类型。

## 基础格式

```text
<type>(<scope>): <subject>

<body>

<footer>
```

最常用的是第一行（subject line）：

```text
feat(render): add shared page lease recycle
fix(resources): guard filehost inflight state on errors
docs(maintainers): add coding standards and contribution guide
```

## type 建议

- `feat`：新功能
- `fix`：缺陷修复
- `docs`：文档改动
- `refactor`：重构（不改变外部行为）
- `perf`：性能优化
- `test`：测试改动
- `build`：构建系统/依赖
- `ci`：CI 配置与流程
- `chore`：杂项维护
- `revert`：回滚提交

## scope 建议

- `core`
- `render`
- `backend/playwright`
- `resources`
- `utils`
- `tests`
- `docs`
- `ci`
- `release`

scope 不是强制，但推荐使用。

## subject 规则

- 使用祈使语气，描述“这次提交做了什么”
- 建议小写开头，避免句号结尾
- 尽量不超过 72 个字符
- 关注事实，不写主观评价

## body 与 footer（可选）

- `body`：解释“为什么改/怎么改”，而不是重复代码细节。
- `footer`：用于关联 issue 或声明 breaking change。

示例：

```text
fix(render): avoid double-close on shared page lifecycle

The render context now tracks page ownership and only closes pages
created inside the current context.

Closes #123
```

## Breaking Changes

如果存在不兼容改动，建议使用以下两种方式之一：

```text
feat(api)!: rename render_html_to_image to render_html
```

或在 footer 中声明：

```text
BREAKING CHANGE: `render_html_to_image` has been removed. Use `render_html`.
```

## Squash 与历史整洁

- 合并前建议整理“中间提交”（如 `fix typo`、`wip`）；
- 保留有意义的提交边界，避免一个大提交覆盖多个独立主题。

