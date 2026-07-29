---
title: 贡献指南
description: 参考 Angular 协作方式整理的本仓库贡献流程
icon: lucide/users
status: new
tags:
  - Project
  - Contribution
---

# 贡献指南

本文参考 [angular/angular](https://github.com/angular/angular) 的协作思路，并结合 Python、NoneBot 与多渲染后端技术栈做了裁剪。具体合并门禁见 [Pull Request 生命周期](pull-requests.md)，实现层约束见 [编码规范](coding-standards.md)。

## 你可以贡献什么

- 修复 bug、补测试、完善文档
- 新增渲染能力（后端、资源解析、可观测性）
- 优化 CI、开发体验与示例

## 开始之前

1. Fork 仓库并从最新 `master` 创建短生命周期分支。
2. 安装依赖并准备本地环境。
3. 如果变更涉及真实浏览器路径，先安装 Playwright Chromium。

```bash
make sync-all
make install-prek
make install-browser   # 仅需要真实浏览器测试时执行
```

## 分支与变更建议

- 一个 PR 聚焦一个主题，避免“功能 + 重构 + 格式化”混在一起。
- 架构变更需同步更新 `docs/extensions/` 中的对应专题。
- 对外 API 行为变化需同步更新 `docs/reference/`，并按任务影响更新 `docs/guides/`。
- 依赖和锁文件通过 `uv` 更新，不直接手写依赖解析结果。
- 项目支持 Python 3.10–3.14；公共代码不得只在单一 Python 版本上验证。

## 提交前检查

至少跑过以下命令：

```bash
make ruff-format
make check
prek run --all-files
make docs-build          # 文档、配置或文档工具链变更
```

根据变更范围追加验证：

```bash
make test-local          # 本地 Playwright / Chromium 行为
make remote-smoke        # 远程 Playwright 或跨容器资源行为
make build-artifacts     # 依赖、包结构、元数据或发布逻辑
prek run actionlint --all-files --hook-stage=manual  # workflow 变更
```

Prek hook 可能自动修改文件；必须检查 diff 并重跑到无新增修改且成功退出。增量开发可以使用 `prek run --files <path>...`，但不能代替 PR 前的 `--all-files`。stage、自动修复与排除规则见[工程协作流程](engineering-workflow.md#prek-gates)。

CI 会在 Python 3.10–3.14 上运行 pytest/coverage 与 [`noneload`](https://github.com/BalconyJH/noneload) 插件加载矩阵。本地单一版本通过不能替代矩阵结果。

## Pull Request 要求

PR 描述必须包含：

1. 变更动机（为什么要改）
2. 方案说明（怎么改）
3. 风险与兼容性（可能影响什么）
4. 验证结果（跑了哪些命令）
5. 文档同步情况（是否更新 docs，或为何不适用）

## Review 约定

- Review 重点优先级：正确性 > 回归风险 > 可维护性 > 风格。
- 对建议项（nit）和阻塞项（must fix）请明确区分。
- 如评审意见影响公共行为，请在 PR 里补充说明与测试。
- 实质性更新后重新请求 review，并等待更新后的 checks。
- 合并前更新到最新 `master`，默认使用 squash merge，合并后删除功能分支。

!!! warning "流程约定尚未由 Ruleset 完整强制"
    当前仓库审计未发现 `master` 已启用 branch protection / Ruleset。维护者必须人工确认 review 和适用 checks 全部满足，不得把 GitHub 允许点击合并视为门禁已通过。可导入配置和启用顺序见[仓库治理与保护](governance.md)。

## 文档预览与包预览

- 文档相关 PR（包括 fork）会严格构建并部署临时 Pages 预览；受信任的部署 workflow 不把 artifact 当作脚本执行，但 HTML/JavaScript 会在浏览器中执行。预览与正式文档共用 GitHub Pages origin，必须视为不可信内容，不能依赖同源 secret 或可信 `localStorage`。
- `Publish (TestPyPI)` 仅供维护者手动触发，不在 PR 上自动发布，也不是合并门禁。
- 正式版本 PR 合并后的 tag 与发布链路见 [发布流程](release.md)。

## 行为准则

参与协作时默认遵守 [Code of Conduct](https://github.com/kexue-z/nonebot-plugin-htmlrender/blob/master/CODE_OF_CONDUCT.md)。
