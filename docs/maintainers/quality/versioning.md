<!-- markdownlint-disable-file MD013 MD041 -->
---
title: 文档版本管理
description: 使用 mike 进行多版本文档发布与管理
icon: lucide/git-branch
status: new
tags:

- Maintainers
- Docs
- Versioning

---

# 文档版本管理

文档站使用 [mike](https://github.com/squidfunk/mike) 实现多版本管理，每个版本部署为 GitHub Pages 上的独立子目录。

## 工作原理

- 推送到 `master` 分支且涉及文档相关路径时，Docs workflow 自动读取 `pyproject.toml` 中的版本号，通过 `mike deploy` 发布到 `gh-pages` 分支
- 版本以子目录形式存在，例如 `docs.example.com/0.7.0/`、`docs.example.com/0.8.0/`
- `latest` 别名始终指向最新版本，根路径自动重定向到 `latest`
- 旧版本页面顶部会显示过期提醒横幅

PR 阶段的文档预览由独立的 `Docs PR Preview` workflow 部署到 `gh-pages` 的 `pr-preview/pr-<NUMBER>/`，PR 关闭时自动清理，不会影响 `mike` 维护的版本目录。

## CI 自动发布

发版时不需要手动打 tag。维护者只需在 PR 中改好 `pyproject.toml` 的 `project.version` 后合并到 `master`：

1. 合并到 `master` 触发 `Docs` workflow，将新版本通过 `mike` 部署为版本化文档；
2. 同时触发 `Auto Tag` workflow，读取版本号自动创建 `v<version>` tag；
3. `Auto Tag` 通过 `gh workflow run` 调起 `Publish`，完成 PyPI 发布与 GitHub Release。

完整 workflow 触发条件与排障入口见 [CI Actions](ci-actions.md)。

```bash
mike deploy --push --update-aliases <version> latest
mike set-default --push latest
```

版本号从 `pyproject.toml` 的 `project.version` 字段读取。

## 本地操作

### 构建文档

```bash
make docs-build
```

### 本地预览

```bash
make docs-serve
```

### 手动部署（不通过 CI）

```bash
# 部署新版本并更新 latest 别名
uv run mike deploy --push --update-aliases 0.7.0 latest

# 设置根路径重定向
uv run mike set-default --push latest

# 删除旧版本
uv run mike delete --push 0.6.0
```

## 版本发布约定

1. 文档版本号与 `pyproject.toml` 中的项目版本保持一致
2. 发布新版本时确保 `latest` 别名指向最新版本
3. 有破坏性变更时，保留旧版本文档供用户参考
