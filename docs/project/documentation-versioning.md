---
title: 文档版本管理
description: mike 版本目录、PR 预览与 gh-pages 并发写入策略
icon: lucide/git-branch
status: new
tags:
  - Project
  - Docs
  - Versioning
---

# 文档版本管理

正式文档使用 [`mike`](https://github.com/jimporter/mike) 在 `gh-pages` 上维护多版本目录；PR preview 在同一分支的独立 umbrella directory 下短期存在。软件版本发布见 [发布流程](release.md)。

## 正式版本目录

- `Docs` workflow 在 `master` 的文档相关路径变化时只执行 strict build，作为发布前门禁；
- `Publish` 在 PyPI 文件 hash 与 GitHub Release 均确认后，从经过验证的 tag 部署正式文档；
- 版本读取自 tag 内 `pyproject.toml` 的项目版本；
- 每个版本部署为独立目录，例如 `/0.7.0/`、`/0.8.0/`；
- `latest` alias 指向最近部署版本，根路径重定向到 `latest`；
- 旧版本继续保留，用于查阅对应软件版本的 API 与配置。

生产构建使用 `zensical build --strict`。无效链接、引用、anchor 或文档配置错误会让部署停止。

## PR preview 不是正式版本

文档相关 PR 使用三段式 preview：

1. 只读 `pull_request` workflow 构建 PR 内容；
2. 受信任的 `workflow_run` 校验静态 artifact 后部署到 `/pr-preview/pr-<NUMBER>/`；
3. `pull_request_target: closed` cleanup 删除对应目录。

preview 通过 `DOCS_SITE_URL`、`DOCS_SCOPE` 和 `DOCS_VERSION_PROVIDER=preview` 获得正确的子路径资源地址，不写入 `mike` 版本索引。完整信任边界见 [CI Actions](ci.md#fork-safe-docs-preview)。

路径命名空间不提供 origin 隔离：PR preview 与正式文档共用 GitHub Pages origin。来自公开 fork 的 HTML/JavaScript 必须视为不可信内容，Pages origin 不应保存 secret、token 或被正式页面信任的 `localStorage` 状态。

## 与软件发布的关系

文档验证、软件发布和 Pages 部署分别具有自己的失败边界：

- 版本 PR 会因 `pyproject.toml` 变化触发 Docs；同一 SHA 的 Docs 成功是 `Auto Tag on Version Change` 创建 tag 前的门禁；
- Docs 成功只说明 tag 对应源码能够严格构建文档，不会创建 `/<version>/`，也不会更新 `latest`；
- `Publish` 只有在 PyPI hash 回读和 GitHub Release 成功后，才从同一 tag 部署正式文档；
- Pages 部署失败时，已经发布的 PyPI 与 GitHub Release 保持不变；对同一 tag 重跑 `Publish`，由幂等校验补齐文档；
- 不得为了恢复文档而移动 tag、重发版本或从 release 分支手工复制静态文件。

因此 `/0.8.0/` 的出现晚于软件发布，但 GitHub Release 成功仍不等于 Pages 已更新；发布后应分别核对 PyPI、GitHub Release 和版本 URL。

## 分支职责

- `feat/*`、`fix/*` 与 `release/v*` 保存源码、测试和 Markdown，不提交 `site/`；
- release PR 的文档只发布到临时 `/pr-preview/pr-<NUMBER>/`，关闭 PR 后清理；
- `gh-pages` 是 CI 维护的生成物分支，长期保存已发布版本、`latest` alias 和仍在评审的 preview；
- `gh-pages` 不参与合并，不作为开发基线，也不接受人工编辑；release 分支关闭或删除不会影响已发布文档。

把生成后的 preview 放进 release 分支会混淆源码与部署状态，也无法让一个 Pages 站点同时提供多个正式版本和多个 PR preview。

## gh-pages 并发写入

正式版本和 PR preview 都会写 `gh-pages`。同一 PR 的新 preview 会取消旧部署，cleanup 与该 PR 共用 concurrency key；不同 PR 和正式发布不能使用一个会丢弃 pending run 的全局 concurrency group。跨 writer 的一致性由 fresh fetch、有限冲突重试和非 force push 保证，任何路径都不得 force push `gh-pages`。

每次生产重试都会重新读取 `versions.json` 并用 PEP 440 比较目标版本与已部署最高版本。较旧 run 即使晚完成，仍可补齐自己的版本目录，但不会把 `latest` alias 和根重定向倒退；等于或高于当前最高版本时才更新 `latest`。

这条约束防止以下竞态：

```text
Docs 从旧 gh-pages 构建版本 commit
        ↘
         PR preview 先推送新 commit
        ↗
Docs 的非快进 push 失败，版本目录缺失
```

有限重试后仍遇到非快进失败时，只重跑失败的 preview workflow 或同一 tag 的 `Publish`；不要 force push `gh-pages`，否则可能删除其他版本或仍在评审的 preview。

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

维护者只有在 CI 不可用、软件版本已经正式发布且确认 `gh-pages` 最新状态后才应从 tag 手动部署：

```bash
git switch --detach v0.8.0
git fetch origin gh-pages:gh-pages
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
