---
title: Pull Request 生命周期
description: 从建分支、评审到 squash merge 与分支清理的协作契约
icon: lucide/git-pull-request-arrow
status: new
tags:
  - Project
  - Contribution
  - Pull Request
---

# Pull Request 生命周期

本页定义仓库的 PR 协作契约。它既适用于外部贡献者，也适用于维护者从仓库内分支发起的变更。

!!! warning "当前没有 Ruleset 强制兜底"
    截至 2026-07-14，对 `master` 的 GitHub branch protection / Ruleset 审计未发现已启用的强制规则。下述 review、checks 与合并方式是仓库约定，但目前不会全部由 GitHub 自动阻止违规合并。可导入配置、启用顺序和远端审计方式见[仓库治理与保护](governance.md)。

## 1. 准备变更

1. 从最新 `master` 创建短生命周期分支；一个分支只承载一个可独立评审的主题。
2. 先补能够复现问题或约束新行为的测试，再完成实现与文档。
3. 避免把无关格式化、依赖升级或重构混入功能 PR。
4. 对外 API、配置或架构边界变化必须同时更新对应分区的 canonical 文档。

分支名称建议表达意图，例如：

```text
feat/takumi-provider
fix/remote-markdown-template
docs/release-process
ci/docs-preview
```

## 2. 发起 PR

PR 标题应能直接作为最终 squash commit 的 subject，并遵循 [提交消息指南](commit-messages.md)：

```text
feat(provider): add takumi renderer
fix(playwright): render remote markdown with set_content
```

PR 描述至少包含：

- 问题或需求背景；
- 方案和关键边界；
- 用户可见行为、兼容性与风险；
- 新增或修改的测试；
- 实际运行过的验证命令；
- 文档是否同步，以及未覆盖项的明确原因。

草稿 PR 可以用于尽早获得架构反馈，但不得以“后续再补”为由合并不完整的实现。

## 3. 等待自动检查

所有与改动相关的 checks 都应成功或明确标记为不适用：

- `CI`：Ruff format/check、`ty`、`basedpyright`、包构建、远程浏览器 smoke 与 `noneload`；
- `Coverage`：Python 3.10–3.14 的 x64 / arm64 测试矩阵；
- `Prek`：仓库级 hooks；
- 文档相关 PR：`Docs PR Preview Build` 严格构建成功，并确认预览评论中的页面可访问。

Ruleset 应绑定不会随矩阵扩展而改名的汇总 job：`CI` 的 `Required Checks`、`Coverage` 的 `Coverage Matrix`、`Prek` 的 `Prek`，以及 `Docs PR Preview Build` 的 `Docs Preview`。前三者汇总各自的全部内部 job；`Docs Preview` 在没有文档变更时正常通过，在有文档变更时要求 strict build 成功。

跳过的 job 必须能够由触发条件解释。例如没有文档相关变更时，文档预览的 build job 可以跳过。取消、超时、基础设施故障或“允许失败”不等于通过。

完整门禁和本地复现命令见 [CI Actions](ci.md) 与 [测试矩阵](testing.md)。

## 4. Review 与更新分支

- 至少由一名没有编写该变更的维护者完成有效 review；高风险的发布、安全、公共 API 或并发改动应增加领域 reviewer。
- 阻塞意见必须在代码、测试或设计说明中得到处理；解决 review thread 前应留下可追踪的答复。
- review 后发生实质性代码变化，应重新请求 review。
- 合并前将分支更新到最新 `master`，解决冲突并等待更新后的整套 checks；不要用过期的绿色结果合并。
- force push 会让既有 review 对应的代码失效。确需整理分支时，应先在 PR 中说明，并在推送后重新请求 review。

## 5. 合并

默认使用 **Squash and merge**：

- PR 标题作为最终 commit subject；
- squash body 保留必要的动机、兼容性说明和 issue 关联；
- 合并前删除 `fixup!`、`WIP`、调试日志等临时内容；
- 确认 review 未被驳回、分支已更新、所有适用 checks 均为绿色。

Ruleset 启用后只允许 squash merge。不要使用 merge commit 或 rebase merge 把临时分支拓扑、未经合并框验证的提交边界带入 `master`。

## 6. 合并后

1. 删除远程功能分支；fork 贡献者同时清理自己的分支。
2. 确认 `master` 上的 CI 没有出现仅在合并后暴露的失败。
3. 如果 `project.version` 确实变化，继续观察同一 source SHA 的 CI/Coverage/Docs/Prek 汇合门禁、`Auto Tag on Version Change` 与[发布流程](release.md)；仅修改依赖或其他 `pyproject.toml` 配置的普通 PR 会因第一父提交与当前版本相同而跳过发布。
4. 如果发现回归，优先发起新的修复或 revert PR；不要移动已发布 tag，也不要直接重写 `master` 历史。

多个 PR 可以连续合并到 `master`。required workflows 会保留每个 master SHA 的运行，Auto Tag 只汇合同一 source SHA；后续合并不会改变已经确定的 release cut。反过来，不要通过提前打 tag、暂停其他分支或把生成后的 Pages 文件提交进 release 分支来制造发布边界。

## Ruleset 基线 { #ruleset-baseline }

仓库维护一份可导入的 `Protect master` Ruleset，完整配置和启用顺序见[仓库治理与保护](governance.md)。其强制基线为：

- 禁止直接 push 和 force push 到 `master`；
- 要求 PR、至少一名有效 approval，并在新提交后撤销过期 approval；
- 要求分支在合并前更新；
- 将上文四个稳定汇总 job 设为 required status checks；
- 要求所有 review conversations 已解决；
- 只允许 squash merge，并要求线性历史。

Ruleset 中使用的是具体 job 名。工作流重命名 job 后应同步更新 Ruleset，避免门禁静默失效或永久等待不存在的 check。
