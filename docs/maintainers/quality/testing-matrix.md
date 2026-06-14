---
title: 测试矩阵
description: CI / local 画像、并发策略与约束
icon: lucide/flask-conical
status: new
tags:
  - Maintainers
  - Testing
---

# 测试矩阵

测试矩阵只描述“哪些测试画像需要被覆盖”。具体 GitHub Actions job、触发条件和 artifact 排障入口见 [CI Actions](ci-actions.md)。

测试覆盖分为三层：

1. 本地 `Makefile` profile，帮助开发者快速复现 CI 或真实浏览器路径；
1. GitHub Actions 的版本矩阵，覆盖支持的 Python 版本；
1. GitHub Actions 的架构矩阵，覆盖 x64 与 arm64。

## Make 目标

- `make test` -> `make test-ci`
- `make test-ci`：并发运行，`HTMLRENDER_TEST_PROFILE=ci`
- `make test-local`：串行运行，`HTMLRENDER_TEST_PROFILE=local`
- `make install-browser`：安装到项目相对目录

## profile 对照

| 维度                    | ci   | local          |
| ----------------------- | ---- | -------------- |
| `requires_browser` 用例 | 跳过 | 执行           |
| 并发                    | 开启 | 关闭           |
| 浏览器安装要求          | 无   | 必须有本地安装 |

## 版本矩阵

测试用例由 `Coverage` workflow 统一覆盖，CI workflow 不再单独跑 pytest。当前 Python 版本覆盖：

| Python | Coverage | 说明                  |
| ------ | -------- | --------------------- |
| 3.10   | 是       | 项目最低支持版本      |
| 3.11   | 是       | 主流兼容版本          |
| 3.12   | 是       | 默认开发/文档构建版本 |
| 3.13   | 是       | 前向兼容验证          |

Lint、`ty`、`basedpyright`、`package`、文档构建固定在 Python 3.12 上运行，用于减少工具链差异；运行时版本兼容性由测试矩阵承担。

## 架构矩阵

Coverage workflow 额外覆盖架构维度：

| Runner             | 架构  | Python 版本               | 目的                 |
| ------------------ | ----- | ------------------------- | -------------------- |
| `ubuntu-latest`    | x64   | 3.10 / 3.11 / 3.12 / 3.13 | 主流 Linux 环境覆盖  |
| `ubuntu-24.04-arm` | arm64 | 3.10 / 3.11 / 3.12 / 3.13 | ARM Linux 兼容性覆盖 |

覆盖率任务会生成独立 XML，并用 Codecov flags 标记对应版本与架构。artifact 命名和下载入口见 [CI Actions](ci-actions.md)。

## 浏览器覆盖

CI profile 默认跳过 `requires_browser`，避免常规单测依赖本地浏览器安装。浏览器行为由两类任务覆盖：

- 本地开发：`make install-browser` 后运行 `make test-local`；
- CI 远程 smoke：`remote-browser-render` 通过 Docker Compose 启动远程浏览器服务并执行渲染验证。

## warning 策略

- 主路径默认测试新 API
- 兼容层只保留少量专测
- `ty` 会报告兼容层 deprecated warning；只要退出码为 0，这类 warning 视为兼容层预期噪音
