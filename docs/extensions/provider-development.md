---
title: Provider 开发指南
description: 从契约、lease、错误翻译到发布验证的完整流程
icon: lucide/workflow
---

# Provider 开发指南

## 1. 定义能力边界

先列出跨引擎语义与专属语义：

- 能消费 `PreparedHtml` 并输出 `RenderedImage`，才提供`PreparedHtmlExecutor`；
- 页面、node、measure、animation 等放入 typed Capability；
- 无法满足的 `RenderRequirement` 抛 `UnsupportedRequirement`，不得静默忽略。

## 2. 建立严格设置模型

`parse_settings()` 应产生不可变/受验证的 `SettingsT`，检查 unknown fields、范围、互斥连接模式和路径格式。错误消息使用完整的`render.provider_config.*` 路径。

availability 必须轻量且无副作用：检查 import spec、distribution metadata、平台和显式可执行文件，不创建浏览器或 native renderer。

## 3. 实现 lease provider

Provider-local `ExecutionLeaseProvider[T]` 负责：

- lazy startup 与并发 acquire 合并；
- runtime 死亡检测后的单次重建；
- 新 lease 与 closing 互斥；
- owner 取消时唤醒 waiters；
- 有界 close 与部分创建失败清理。

Playwright lease 持有 driver/browser，单次操作创建 context/page；Takumi lease持有 native runtime state。不要把内部句柄放入通用 application 类型。

## 4. 实现 executor 与 Capability

executor 只接受 `PreparedHtml`、`RasterOptions`、资源策略和操作超时。检查requirements 后执行。Adapter 在收到引擎编码 bytes 的边界立即调用`RenderedImage.from_bytes(data, expected_format=options.format)`，由产物解析真实物理像素尺寸并拒绝格式不匹配；检查失败需按执行错误翻译。Application 层只透传同一`RenderedImage`，不得再根据请求参数拼装元数据。

Capability 与 executor 必须共享同一 lease provider，避免出现两份 runtime。输出对象不得让调用方绕过生命周期。

## 5. 使用注入依赖

从 `ProviderDependencies` 使用：

- observer：稳定 operation name，失败隔离；
- `ProviderResources`：读取 bytes、授权本地路径并取得当前不可变`ResourceStrategy`；
- 可选 publisher：实现执行端所需 transport。

`ProviderResources` 的完整 Provider 可见面只有：

- `strategy`；
- `authorize_local(path)`；
- `read_bytes(reference, *, refresh=False)`。

worker、底层 reader、local access policy 与完整 `ResourceService` 都是 composition内部设施，不进入 Provider SDK。不要 import bootstrap、调用 NoneBot config API或安装模块级 provider seam。

## 6. 翻译异常

在 adapter 边界转换：

- 环境/依赖问题 → `ProviderUnavailable`
- 生命周期问题 → `ProviderLifecycleError`
- 执行问题 → `ProviderExecutionError`
- 文档能力不匹配 → `UnsupportedRequirement`
- 资源问题 → `ResourceResolutionError` 子类

保留原异常为 cause，但不要让引擎异常成为公共契约。

稳定摘要只描述 adapter 正在执行的动作，不要把未经限制的 `str(error)` 拼入摘要；通过 `source=error` 生成有界的 `ErrorCause` 快照，并用 `raise ... from error` 保留Python traceback 链：

```python
try:
    data = await engine.render(document)
except EngineError as error:
    raise ProviderExecutionError(
        "Example provider render failed.",
        source=error,
    ) from error
```

`RenderingError.message`、`message_truncated`、`causes` 与 `causes_truncated` 是稳定可补全字段；重复包装已有原因快照的 `RenderingError` 时会直接复用该快照。不要额外保存 native 异常对象或建立另一套 detail 模型。

## 7. 注册与测试

entry point 名与 `provider.id` 一致；测试至少覆盖：

- discovery collision、保留 ID 与错误对象；
- settings 有效/无效/未知字段；
- availability 缺依赖与正常环境；
- 并发 startup/acquire、死亡重建、取消与有界 close；
- executor 的 requirements、timeout 与错误翻译；
- Capability 存在/缺失和 lease 失效；
- 两个 composition 的资源、cache、observer 完全隔离；
- 安装 wheel 后的真实 entry point smoke。

真实引擎还需端到端 smoke，不能用“构造出了 `RenderedImage`”替代渲染语义断言。

`nonebot_plugin_htmlrender.providers.testing` 提供安装 wheel 后可复用的生命周期一致性检查。该模块属于 NoneBot 宿主内的开发工具：测试进程必须先初始化 NoneBot并加载 `nonebot_plugin_htmlrender`，不支持在普通、未初始化的 Python 进程中独立导入。

## 8. 文档与发布

同步更新 Provider 配置、能力矩阵、故障排查与 migration guide。运行`make check`、`make docs-build`、`make build-artifacts`；浏览器 Provider 增加local 与 remote smoke，native Provider 在支持平台运行真实 smoke。
