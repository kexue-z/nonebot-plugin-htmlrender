---
title: 文档版本管理
description: mike 版本目录、PR 预览与 gh-pages 并发写入策略
icon: lucide/git-branch
status: new
tags:
  - Maintainers
  - Docs
  - Versioning
---

# 文档版本管理

正式文档使用 [`mike`](https://github.com/jimporter/mike) 在 `gh-pages` 上维护多版本目录；PR preview 在同一分支的独立 umbrella directory 下短期存在。软件版本发布见 [发布流程](release-process.md)。

## 正式版本目录

- `Docs` workflow 在 `master` 的文档相关路径变化时触发；
- 版本读取自 `pyproject.toml` 的项目版本；
- 每个版本部署为独立目录，例如 `/0.7.0/`、`/0.8.0/`；
- `latest` alias 指向最近部署版本，根路径重定向到 `latest`；
- 旧版本继续保留，用于查阅对应软件版本的 API 与配置。

生产构建使用 `zensical build --strict`。无效链接、引用、anchor 或文档配置错误会让部署停止。

## PR preview 不是正式版本

文档相关 PR 使用三段式 preview：

1. 只读 `pull_request` workflow 构建 PR 内容；
2. 受信任的 `workflow_run` 校验静态 artifact 后部署到 `/pr-preview/pr-<NUMBER>/`；
3. `pull_request_target: closed` cleanup 删除对应目录。

preview 通过 `DOCS_SITE_URL`、`DOCS_SCOPE` 和 `DOCS_VERSION_PROVIDER=preview` 获得正确的子路径资源地址，不写入 `mike` 版本索引。完整信任边界见 [CI Actions](ci-actions.md#fork-safe-docs-preview)。

路径命名空间不提供 origin 隔离：PR preview 与正式文档共用 GitHub Pages origin。来自公开 fork 的 HTML/JavaScript 必须视为不可信内容，Pages origin 不应保存 secret、token 或被正式页面信任的 `localStorage` 状态。

## 与软件发布的关系

Docs、PyPI 和 GitHub Release 是独立 workflow：

- 版本 PR 会因 `pyproject.toml` 变化触发 Docs；同一 SHA 的 Docs 成功是 `Auto Tag on Version Change` 创建 tag 前的门禁，`Publish` 在 tag 后独立运行；
- 单纯创建或重跑 tag 不会代替 Docs 的路径触发；
- Docs 失败不应重发 PyPI 或移动 tag；单独重新运行 Docs 即可；
- 软件发布失败也不应回滚一个已经正确部署的文档版本，恢复失败的发布 job 即可。

因此不要把“Pages 上已出现版本”解释为“PyPI 已发布”，也不要把 GitHub Release 成功解释为文档已更新。发布后应分别核对三条链路。

## gh-pages 并发写入

生产版本和 PR preview 都会写 `gh-pages`。生产 run 按 source SHA 使用独立 concurrency key，避免 GitHub concurrency 的“只保留一个 pending”语义吞掉中间版本；实际写入一致性由 fresh fetch、有限冲突重试和非 force push 保证。预览 action 同样使用 rebase/retry，不能覆盖其他提交。

每次生产重试都会重新读取 `versions.json` 并用 PEP 440 比较目标版本与已部署最高版本。较旧 run 即使晚完成，仍可补齐自己的版本目录，但不会把 `latest` alias 和根重定向倒退；等于或高于当前最高版本时才更新 `latest`。

这条约束防止以下竞态：

```text
Docs 从旧 gh-pages 构建版本 commit
        ↘
         PR preview 先推送新 commit
        ↗
Docs 的非快进 push 失败，版本目录缺失
```

遇到非快进失败时重跑 workflow；不要 force push `gh-pages`，否则可能删除其他版本或仍在评审的 preview。

## 本地验证

严格构建：

```bash
make docs-build
```

本地预览：

```bash
make docs-serve
```

检查 `mike` 已部署版本：

```bash
make docs-list
```

维护者只有在 CI 不可用且确认 `gh-pages` 最新状态后才应手动部署：

```bash
uv run mike deploy --update-aliases 0.8.0 latest
uv run mike set-default latest
git push origin gh-pages
```

不要直接在 `site/` 或 `gh-pages` 目录手工复制文件；那会绕过 `mike` 的版本索引和并发保护。

## 发布后核对

- `/<version>/` 返回本次版本内容；
- `/latest/` 指向预期版本；
- 根 URL 正确重定向；
- 静态资源和站内链接保留仓库子路径；
- 仍 open 的 PR preview 未被生产部署删除；
- 已关闭 PR 的 preview 已清理；
- Docs workflow 与 Pages deployment 都成功。
