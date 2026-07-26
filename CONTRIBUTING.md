<!-- markdownlint-disable-file MD013 -->

# 为 nonebot-plugin-htmlrender 贡献

感谢你参与改进项目。完整协作契约见：

- [贡献指南](docs/project/contributing.md)
- [Pull Request 生命周期](docs/project/pull-requests.md)
- [编码规范](docs/project/coding-standards.md)
- [测试矩阵](docs/project/testing.md)
- [CI Actions](docs/project/ci.md)

## 准备环境

项目支持 Python 3.10–3.14，使用 `uv` 管理环境，以 `Makefile` 作为开发入口：

```bash
make prepare
```

涉及本地 Chromium 行为时再安装浏览器：

```bash
make install-browser
```

## 提交前验证

代码改动至少运行：

```bash
make ruff-format
make ruff-format-check
make ruff-check
make typecheck
make ty
make test-ci
uvx prek run --all-files
```

根据变更范围追加：

```bash
make docs-build          # 文档、配置或文档工具链变更；必须 strict build
make build-artifacts     # 包结构、依赖、元数据或发布逻辑变更
make test-local          # 本地浏览器行为变更
make remote-smoke        # 远程 Playwright / Docker 跨容器路径变更
uvx prek run -a actionlint --hook-stage=manual  # workflow 变更
```

CI 还会在 Python 3.10–3.14 上运行 pytest/coverage 与 `noneload` 插件加载矩阵。不要用跳过检查、放宽类型或屏蔽诊断来代替修复。

## Pull Request

1. 从最新 `master` 创建一个聚焦单一主题的短生命周期分支。
2. 同步提交实现、测试以及受到影响的用户或维护者文档。
3. 使用 [Angular 风格提交消息](docs/project/commit-messages.md)，并让 PR 标题可直接作为 squash commit subject。
4. 在 PR 描述中写明动机、方案、兼容性、风险和实际验证结果。
5. 处理 review，更新到最新 `master`，等待所有适用 checks 重新通过。
6. 默认使用 **Squash and merge**，合并后删除功能分支。

当前 `master` 未由 GitHub Ruleset 强制执行全部上述约定，维护者必须在合并前人工核对 checks 和 review 状态。详见 [Pull Request 生命周期](docs/project/pull-requests.md)。

## 文档预览与 TestPyPI

文档相关 PR 会先在只读的 `pull_request` workflow 中严格构建，再由受信任的 `workflow_run` 部署预览并评论链接。该流程支持 fork PR；部署 workflow 不会 checkout fork 分支，也不会把 artifact 当作 workflow script 执行，但预览中的 HTML/JavaScript 会在 reviewer 的浏览器中执行。预览只是正式站点同一 GitHub Pages origin 下的路径，必须视为不可信内容，不能依赖该 origin 中的 secret 或可信 `localStorage`。PR 关闭后，预览会自动清理。

正式发布由合并后的 `master` push 检测 `project.version` 前后差异；只有版本实际变化才创建 tag。因此 fork PR 可以正常成为版本 PR，而普通依赖配置变更不会误发布。

TestPyPI 发布仅由维护者手动触发，不会为每个 PR 自动上传，也不是 required check。

## 行为准则与安全

- 参与协作即表示同意遵守 [Code of Conduct](CODE_OF_CONDUCT.md)。
- 安全问题请按 [Security Policy](SECURITY.md) 私下报告，不要先公开漏洞细节。
