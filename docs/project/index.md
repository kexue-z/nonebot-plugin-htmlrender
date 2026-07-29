---
title: 项目维护
description: 协作流程、质量门禁、仓库治理与发布
icon: lucide/construction
---

# 项目维护

本区描述仓库协作和发布职责；运行时设计与第三方扩展统一放在[原理与扩展](../extensions/index.md)。

## 贡献流程

1. [贡献指南](contributing.md)
2. [工程协作流程](engineering-workflow.md)
3. [编码规范](coding-standards.md)
4. [提交消息指南](commit-messages.md)
5. [Pull Request 生命周期](pull-requests.md)

## 质量与发布

- [测试矩阵](testing.md)
- [CI Actions](ci.md)
- [仓库治理与保护](governance.md)
- [发布流程](release.md)
- [文档版本管理](documentation-versioning.md)

## 本地入口

```bash
make prepare
make check
make docs-build
```

涉及浏览器行为时增加 `make test-local`；涉及远程连接或资源 transport 时增加`make remote-smoke-build`。
