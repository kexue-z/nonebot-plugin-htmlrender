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

`Application.resources` 的 `read_bytes()` / `read_text()` 接受 `refresh=True` 强制刷新单个 resource key，`await app.resources.clear()` 只清理当前 Application 的 Resource Reader。它不等价于 `aclose()`，不会清理 Jinja、filehost 或 Provider runtime cache；选择正确操作见[缓存组件、失效与调优](../guides/cache-lifecycle.md#choose-an-action-by-symptom)。

关闭失败可重试，但一旦进入关闭流程便永久拒绝新操作；需要再次渲染时应创建新的composition。同步资源判断也检查同一个 admission gate。Provider 专属 Capability通过自己的 runtime lease 提供等价的拒绝、drain 与关闭后失效语义。

## 稳定生命周期错误

| 错误 | 含义 |
| --- | --- |
| `ApplicationNotInitialized` | NoneBot 插件或其他宿主尚未安装进程默认 Application |
| `ProviderNotFound` | 配置的 Provider ID 无法发现 |
| `ProviderUnavailable` | Provider 存在但当前环境不可运行 |
| `ProviderLifecycleError` | startup、probe 或关闭失败 |
| `CapabilityUnavailable` | 当前 composition 未绑定请求的能力 |

`ApplicationNotInitialized` 与 `render.provider: null` 无关。插件已经加载但未选择 Provider 时，默认 Application 仍然存在，并保留 Preparation、Resource Service、`render_template_html` 与显式启用的 Graphics Capability；请求需要 HTML Provider 的位图渲染操作时才会抛出 `CapabilityUnavailable`。

这些类型都继承 `RenderingError`，因此生命周期与 composition 失败同样提供`message`、`message_truncated`、`causes` 和 `causes_truncated`；底层异常仍保留在Python `__cause__` 链中。

启动策略见[启动与生命周期配置](../configuration/lifecycle.md)。
