---
title: Application API
description: 默认对象图、生命周期、admission 与关闭语义
icon: lucide/orbit
---

# Application API

NoneBot bootstrap 负责默认 `Application` 的安装与关闭。手工组合或测试替身可使用：

```python
from nonebot_plugin_htmlrender import get_default_application

app = get_default_application()
await app.startup()
await app.probe()
await app.aclose()
```

只需要通用渲染 facade 时可调用 `get_default_renderer()`；它等价于读取默认`Application.renderer`，不会建立第二个 composition。Provider 专属或独立图形能力从 `Application.extensions.playwright`、`.takumi`、`.pillow` 与 `.skia` 获取；第三方自定义能力使用 `Application.extensions.require(KEY)`。

`set_default_application(application)` 只供宿主接线、独立 composition 与测试替身替换进程默认对象图，并返回先前的 `Application`。它不会隐式调用 `startup()` 或`aclose()`；安装者仍负责新旧对象的完整生命周期。常规 NoneBot 插件由 bootstrap管理默认对象，不应自行替换。

## 生命周期

`startup()` 与 `aclose()` 幂等。`aclose()` 先拒绝新的 Renderer、Preparation 与Resource Service 异步操作，等待已经获准的完整操作结束，再清理 Provider 与缓存。即使调用方事先保留了 facade 引用，关闭后也不能重新填充缓存。

关闭失败可重试，但一旦进入关闭流程便永久拒绝新操作；需要再次渲染时应创建新的composition。同步资源判断也检查同一个 admission gate。Provider 专属 Capability通过自己的 runtime lease 提供等价的拒绝、drain 与关闭后失效语义。

## 稳定生命周期错误

| 错误 | 含义 |
| --- | --- |
| `ProviderNotConfigured` | 默认 Application 尚未安装 |
| `ProviderNotFound` | 配置的 Provider ID 无法发现 |
| `ProviderUnavailable` | Provider 存在但当前环境不可运行 |
| `ProviderLifecycleError` | startup、probe 或关闭失败 |
| `CapabilityUnavailable` | 当前 composition 未绑定请求的能力 |

这些类型都继承 `RenderingError`，因此生命周期与 composition 失败同样提供`message`、`message_truncated`、`causes` 和 `causes_truncated`；底层异常仍保留在Python `__cause__` 链中。

启动策略见[启动与生命周期配置](../configuration/lifecycle.md)。
