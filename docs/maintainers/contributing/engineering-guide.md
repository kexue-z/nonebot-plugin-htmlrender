---
title: 工程协作与规范
description: 仓库结构、测试组件、代码规范与提交门禁
icon: lucide/folder-git-2
status: new
tags:
  - Maintainers
  - Engineering
---

# 工程协作与规范

!!! info "建议先阅读"
    - [贡献指南](contributing.md)
    - [提交消息指南](commit-message.md)
    - [编码规范](coding-standards.md)

## 仓库结构（核心）

```text
nonebot_plugin_htmlrender/
├─ nonebot_plugin_htmlrender/        # 插件实现
│  ├─ __init__.py                    # 插件入口与公开 API 导出
│  ├─ _bootstrap.py                  # 启动期补丁与可选插件 bootstrap
│  ├─ _compat.py                     # 兼容层主入口
│  ├─ browser.py                     # legacy shell：旧 browser 导入面
│  ├─ data_source.py                 # legacy shell：旧 data_source 导入面
│  ├─ render.py                      # Render 门面、默认实例、生命周期
│  ├─ backend/                       # 后端抽象层
│  │  ├─ base.py                     # Backend 协议与类型定义
│  │  ├─ factory.py                  # 后端注册、发现与状态查询
│  │  └─ playwright/                 # Playwright 后端实现
│  │     ├─ _page.py                 # 页面上下文管理与路由拦截
│  │     ├─ config.py                # Playwright 专属配置
│  │     ├─ data_source.py           # 兼容层入口（旧 API 转发）
│  │     ├─ install.py               # 浏览器自动安装
│  │     ├─ models.py                # 请求/配置 Pydantic 模型
│  │     ├─ operations.py            # 渲染动作（render_html/text/md/template）
│  │     ├─ render.py                # PlaywrightBackend 类
│  │     ├─ runtime.py               # 运行时生命周期（启动/停止/环境变量）
│  │     └─ telemetry.py             # 页面级遥测采集
│  ├─ resources/                     # 资源解析层
│  │  ├─ resolve.py                  # 资源解析引擎（policy/路径/URL 判断）
│  │  ├─ template.py                 # 模板变量与 HTML/CSS 资源替换
│  │  ├─ config.py                   # 资源配置
│  │  └─ filehost/                   # Filehost 基础设施
│  │     ├─ cache.py                 # URL 生成与 LRU 缓存
│  │     ├─ guard.py                 # 请求鉴权与中间件
│  │     └─ warmup.py                # 预热与启动编排
│  └─ utils/                         # 公共工具
│     ├─ install.py                  # 通用安装辅助
│     ├─ process.py                  # 进程管理
│     ├─ signal.py                   # 信号处理
│     └─ telemetry/                  # 遥测基础设施
│        ├─ common.py                # 通用遥测工具
│        ├─ sentry.py                # Sentry 集成
│        └─ prometheus.py            # Prometheus 指标
├─ tests/                            # 单测与远程 smoke
├─ docs/                             # 文档内容
├─ Makefile                          # 统一任务入口
└─ pyproject.toml                    # 依赖、lint/typecheck/test 配置
```

## 目录对账要点

- 顶层旧模块已经收敛为兼容壳，维护时不要再把新逻辑堆回 `browser.py` 或 `data_source.py`
- backend 主线是 `render.py -> backend/* -> backend/playwright/*`
- 资源解析主线是 `resources/*`
- 遥测主线是 `utils/telemetry/*`
- 如果目录结构与旧版本资料不一致，以当前仓库 tree 为准，不以历史顶层平铺模块为准

## Makefile 任务入口

本仓库用 `Makefile` 作为本地开发入口，详细 CI workflow 见 [CI Actions](../quality/ci-actions.md)，测试覆盖维度见 [测试矩阵](../quality/testing-matrix.md)。

常用任务：

- `make prepare`：同步完整开发环境并安装 git hooks；
- `make sync-all` / `make sync`：同步全部可选依赖与全部 dependency groups；
- `make sync-build`：同步构建/发布环境（`--no-sources`）；
- `make install-prek`：安装 `prek`、pre-commit hook 与 `commit-msg` hook；
- `make test-ci`：并发跑 CI profile（跳过 `requires_browser`）
- `make test-local`：本地串行跑真实浏览器用例
- `make install-browser`：安装本地测试浏览器
- `make remote-smoke`：复用已有镜像与依赖缓存，执行远程浏览器 smoke
- `make remote-smoke-build`：重建远程 smoke 镜像后执行，用于依赖或基础镜像变更
- `make remote-smoke-down`：停止远程 smoke 服务并清理卷
- `make ruff-format`：运行 `ruff format`
- `make ruff-format-check`：以非修改模式运行 `ruff format --check`
- `make ruff-check` / `make lint`：运行 `ruff check`
- `make typecheck`：`basedpyright`
- `make ty`：运行 `ty check`
- `make check`：按非修改的 `ruff-format-check -> ruff-check -> basedpyright -> ty -> test-ci` 顺序运行本地门禁
- `make build-artifacts`：以 `--no-sources` 构建发布产物，用 pinned `twine` 校验 metadata，并输出校验和
- `make docs-serve` / `make docs-build`：zensical 文档预览/严格构建；
- `make docs-deploy VERSION=x.y.z` / `make docs-list`：文档版本管理，详见 [文档版本管理](../quality/versioning.md)。

## 代码规范与格式要求

本项目以 `pyproject.toml` 为准，核心规则：

- 格式：`ruff format` 风格约束（双引号、空格缩进等），CI 使用 `--check`
- Lint：`ruff check`（包含 `F/E/W/I/UP/.../RUF` 等规则集）
- 类型检查：`basedpyright` 与 `ty`
- 测试：`pytest`（含 `pytest-xdist`、`pytest-cov`）

!!! tip "提交前建议"
    先用 `make ruff-format` 格式化有意修改的代码，再执行一次 `make check`，保证非修改格式检查、lint、类型检查和测试同步通过。

## 提交门禁（Commit Gate）

本项目提交检查统一使用 **`prek`**。

- `prek` 可以直接复用仓库内的 `.pre-commit-config.yaml` 配置。
- 也就是说，现有 pre-commit hooks 配置无需迁移，使用 `prek` 执行即可。

### 快速上手

```bash
uv tool install prek
prek install
prek install --hook-type commit-msg
```

### 常用命令

```bash
prek run --all-files
prek run --all-files --hook-stage=manual
prek run
```

- `prek run --all-files`：全量检查，适合提交前兜底。
- `prek run --all-files --hook-stage=manual`：包含默认禁用的慢速/手动 hook（如 `actionlint`）。
- `prek run`：仅检查当前变更，适合日常迭代。
- `commit-msg` hook 会检查提交消息是否符合 `type(scope): subject` 风格。
- 若团队在 CI/脚本中约定了额外参数，以团队约定为准。

## 本地提交流程 Checklist

### 开发前

- [ ] 安装/同步完整开发依赖（全部 extras 与全部 dependency groups）
- [ ] 确认本地工具可用：`uv`、`ruff`、`basedpyright`、`ty`、`pytest`
- [ ] 如需跑真实浏览器测试，先安装浏览器实例

```bash
make prepare
make install-browser   # 仅在需要 test-local 时执行
make test-ci           # 快速验证环境
```

### 提交前

- [ ] 代码格式化与 lint 通过（`ruff-format` / `ruff-check`）
- [ ] 类型检查通过（`basedpyright` / `ty`）
- [ ] 测试通过（至少 `test-ci`）
- [ ] 文档变更可本地预览（如本次包含 docs 变更）
- [ ] 运行 `prek` 门禁检查

```bash
make ruff-format
make ruff-format-check
make ruff-check
make typecheck
make ty
make test-ci
make docs-build        # 如涉及文档
prek run --all-files
```

### 发版前

- [ ] 版本号与变更日志一致（`pyproject.toml` / release notes）
- [ ] 全量检查通过（建议 `make check` + 必要的 `test-local`）
- [ ] 发布产物可正常构建（`wheel + sdist`）
- [ ] 文档站可正常构建
- [ ] 文档版本号与 `pyproject.toml` 一致（CI 自动从中读取版本部署）

```bash
make check
make test-local        # 如发布前要求真实浏览器回归
make docs-build
make build-artifacts
```

!!! note "文档版本发布"
    合并到 `master` 后的软件发布流程见 [发布流程](../quality/release-process.md)，文档部署见 [文档版本管理](../quality/versioning.md)；GitHub Actions job 视角见 [CI Actions](../quality/ci-actions.md)。
