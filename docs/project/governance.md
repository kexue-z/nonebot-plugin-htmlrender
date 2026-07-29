---
title: 仓库治理与保护
description: master、release 分支、发布 tag 与 deployment environment 的远端保护契约
icon: lucide/shield-check
status: new
tags:
  - Project
  - GitHub
  - Ruleset
---

# 仓库治理与保护

本页定义 GitHub 远端设置应执行的保护契约。仓库内的 workflow 和 Ruleset JSON只能描述期望状态；远端设置仍需由管理员显式应用，并在每次相关改动后重新审计。

## 当前审计结果

截至 2026-07-14，远端状态为：

- `master` 没有传统 branch protection，也没有 Repository Ruleset；
- merge commit、squash merge、rebase merge 全部可用；
- 没有启用合并后自动删除 head branch，也没有提供 Update branch；
- `release` 和 `testpypi` environment 没有 deployment branch/tag policy；
- `github-pages` environment 只接受 `master` 和 `gh-pages`，该设置应保留。

在 Ruleset 正式启用前，GitHub 允许直接 push、force push、删除 `master` 或绕过 checks合并。文档约定不能替代平台门禁。

## 权威引用边界

仓库只保护真正具有长期权威性的引用：

| 引用                    | 定位                              | 保护策略                                                  |
| ----------------------- | --------------------------------- | --------------------------------------------------------- |
| `master`                | 唯一可发布源码历史                | PR、review、strict checks、线性历史、禁止删除和 force push |
| `release/v*`            | 短生命周期 release PR head        | 不单独保护；合入时完整经过 `master` Ruleset，合并后删除   |
| `v*`                    | 已发布源码的不可变锚点            | 允许自动创建，创建后禁止移动和删除                        |
| `gh-pages`              | workflow 生成的 Pages 物化结果    | 不作为源码；由部署 workflow 进行非 force、带重试的更新    |
| `feat/*`、`fix/*` 等    | 可丢弃、可重建的并行开发工作分支  | 不设远端保护，由目标分支的 PR Ruleset 约束                |

保护 `release/v*` 反而会把临时协调分支误塑造成长期稳定线，并妨碍 release PR 合并后的清理。真正的版本边界是合入 `master` 的 gated SHA 和随后创建的不可移动 tag。

## `Protect master` Ruleset

导入 [`.github/rulesets/protect-master.json`](https://github.com/kexue-z/nonebot-plugin-htmlrender/blob/master/.github/rulesets/protect-master.json)，目标选择默认分支，并保持 `Active`：

- 禁止删除和 non-fast-forward push；
- 要求线性历史，合并方式只允许 squash；
- 所有变更必须通过 PR；
- 要求一名非作者维护者 approval；新 reviewable commit 会撤销旧 approval；
- 最新一次 reviewable push 必须由另一人确认；
- 所有 review conversation 必须 resolved；
- required checks 使用 GitHub Actions 作为固定来源，并严格要求分支基于最新 `master`：

| Workflow                | Required check context |
| ----------------------- | ---------------------- |
| `CI`                    | `Required Checks`      |
| `Coverage`              | `Coverage Matrix`      |
| `Prek`                  | `Prek`                 |
| `Docs PR Preview Build` | `Docs Preview`         |

不要绑定矩阵内部 job，也不要把只在 `master` push 上运行的 `Docs` 设为 PR required check。四个汇总 job 对所有目标为 `master` 的 PR 都会产生确定结论，包括“不涉及文档”的 PR。

Ruleset 不配置日常 bypass。管理员仍能编辑 Ruleset，但这应被视为显式的事故恢复操作，而不是正常合并路径。仓库设置同时应只启用 squash merge、启用 Update branch，并在合并后自动删除 head branch。

## `Protect release tags` Ruleset

导入 [`.github/rulesets/protect-release-tags.json`](https://github.com/kexue-z/nonebot-plugin-htmlrender/blob/master/.github/rulesets/protect-release-tags.json)，匹配 `refs/tags/v*`：

- 禁止删除；
- 禁止 non-fast-forward 更新；
- 不限制创建，因为 `Auto Tag on Version Change` 的 `GITHUB_TOKEN` 必须创建新 tag；
- 不设置 bypass，任何修复都必须使用新版本号，而不是移动已经存在的 tag。

`Publish` 不监听 tag push。手工误建 tag 不会直接获得 PyPI OIDC；自动发布只来自通过精确 SHA 门禁的 Auto Tag dispatch，恢复发布则由维护者从默认分支或同名 tag 显式dispatch。Auto Tag 遇到同名 tag 指向其他 SHA 时会失败，不会覆盖它。

## Deployment environments

Ruleset 约束 Git 引用，environment 约束不可逆部署权限，两者不能互相替代：

| Environment    | Selected branches and tags                      | Required reviewer |
| -------------- | ----------------------------------------------- | ----------------- |
| `release`      | branch `master`、tag `v*`                       | 无                |
| `testpypi`     | branch `master`、branch `release/*`             | 无                |
| `github-pages` | 保留 branch `master`、branch `gh-pages`         | 无                |

正式发布的人工批准发生在版本 PR review，而不是在 PyPI job 再重复一次。`release`
environment 接受 Auto Tag 从 release tag 发起的正常发布，以及默认分支上的人工恢复；feature/release branch 上的 workflow 即使被手工触发，也不能取得 PyPI trusted
publishing 的 OIDC 身份。

## 启用顺序

required check context 必须先由 GitHub Actions 实际产生。错误的启用顺序会让 GitHub 永久等待一个不存在的 check：

1. 先合入新增汇总 job 和本页对应的 workflow 改动；
1. 发起一个普通 PR，确认合并框中准确出现四个汇总 context，来源均为 GitHub Actions；
1. 在 **Settings → Rules → Rulesets** 依次导入两个 JSON，复核目标和规则后设为 Active；
1. 在 **Settings → Environments** 配置上表的 branch/tag policy；
1. 在 **Settings → General → Pull Requests** 只保留 squash merge，启用 Update branch 和automatically delete head branches；
1. 使用普通 PR 验证：未 approval、分支落后、任一 required check 失败或 conversation 未解决时均不能合并；
1. 通过 API 复核远端实际规则，而不是只相信设置页面：

```bash
gh api repos/kexue-z/nonebot-plugin-htmlrender/rulesets
gh api repos/kexue-z/nonebot-plugin-htmlrender/rules/branches/master
gh api repos/kexue-z/nonebot-plugin-htmlrender/environments
```

不要用真实 release tag 测试删除或移动保护。tag Ruleset 可用一个不匹配 `v*` 的临时 tag验证普通 Git 行为，但 `v*` 的不可变规则应通过 Ruleset API 和一次正常自动发布观察确认。

## 紧急恢复

没有 bypass 意味着 CI 平台级故障时不能正常合并。此时管理员应：

1. 记录故障、待合入 SHA、失败 context 和为什么不能等待恢复；
1. 由另一名维护者确认变更内容与临时放宽范围；
1. 只临时禁用阻塞的 status-check rule，不关闭 PR、review、删除或 force-push 保护；
1. 合并后立即恢复规则并用 API 复核；
1. 在事故记录中保留 Ruleset audit、PR 和恢复时间。

发布 tag 的更新/删除保护不进入这条应急路径。只要 tag 已存在，就按[发布流程](release.md#partial-failure-recovery)恢复或提升版本。
