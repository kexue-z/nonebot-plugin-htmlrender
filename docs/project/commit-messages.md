---
title: 提交消息指南
description: 参考 Angular 风格的 commit message 约定
icon: lucide/message-square-text
status: new
tags:
  - Project
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
docs(project): add coding standards and contribution guide
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

`make install-prek` 会安装 `commit-msg` hook，并按 `.pre-commit-config.yaml` 拒绝不在上述集合中的 `type`。该 hook 只验证本地 commit subject 的结构与 type，不判断scope 是否准确、subject 是否清晰，也不会替代 squash 前对 PR 标题的人工检查。

## scope 建议

- `core`
- `application`
- `provider/playwright`
- `preparation`
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

- PR 默认使用 squash merge，PR 标题必须可以直接作为最终 subject；
- 合并前清理 `fix typo`、`wip`、`fixup!` 等中间提交语义；
- squash body 保留必要的动机、兼容性说明、breaking change 和 issue 关联；
- `master` 只接受 squash merge；需要长期保留的设计边界写入 PR 描述、文档和最终 squash body，而不是依赖临时分支提交拓扑。

完整 review、checks 与合并后清理约定见 [Pull Request 生命周期](pull-requests.md)。
