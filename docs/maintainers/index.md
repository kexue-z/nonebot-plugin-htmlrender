---
title: 维护者文档
description: 0.8 架构、Provider SDK、资源服务与质量门禁
icon: lucide/construction
---

# 维护者文档

0.8 以 composition root 为唯一接线位置。核心层只依赖协议和值对象；NoneBot、
Playwright、Takumi、Jinja、filehost 与 telemetry 都属于外部适配器。

## 架构

1. [分层架构](architecture/architecture.md)
2. [自定义 Provider](architecture/custom-providers.md)
3. [Provider 开发指南](architecture/provider-development.md)
4. [资源解析与传输](architecture/resource-resolution.md)

## 质量与发布

- [测试矩阵](quality/testing-matrix.md)
- [CI Actions](quality/ci-actions.md)
- [发布流程](quality/release-process.md)
- [文档版本管理](quality/versioning.md)

## 核心不变量

- application/domain/preparation/resource contracts 不导入 NoneBot 或具体适配器。
- 业务路径不读取全局配置，不访问 registry/service locator。
- Provider 配置只在 composition root 解析一次。
- Preparation 生成中立 `PreparedHtml`；执行器只消费已准备内容。
- Capability 是类型化边界，不把专属参数加入通用 request。
- 资源读取必须先授权；cache 不得绕过策略。
- lifecycle、lease、singleflight 与取消路径都必须有界并可测试。
- observer 失败不改变业务结果，标签保持低基数。

## 开始贡献

先运行：

```bash
make prepare
make check
make docs-build
```

涉及浏览器行为时增加 `make test-local`；涉及远程连接或资源 transport 时增加
`make remote-smoke-build`。
