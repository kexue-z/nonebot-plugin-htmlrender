---
title: 自定义 Provider
description: EngineProvider 契约、discovery、配置与 bindings
icon: lucide/plug-zap
---

# 自定义 Provider

Provider 是一个独立、可发现的渲染引擎 composition factory。它不承载业务
API，也不拥有进程级全局状态。

## 契约

一个 Provider 实现类型化的 `EngineProvider[SettingsT]`：

- `id`：稳定、小写的 Provider ID；
- `parse_settings(raw)`：把 `render.provider_config` 变成 `SettingsT`；
- `availability(settings)`：无副作用检查依赖与平台；
- `bootstrap_requirements(settings)`：声明必须由 NoneBot 提前加载的插件；
- `resource_strategy(settings)`：在组装依赖前返回不可变资源策略；
- `compose(settings, dependencies)`：返回不可变 `EngineBindings`。

`compose()` 所需共享服务全部来自 `ProviderDependencies`：operation/cache
observer、worker executor、resource reader、local access policy、asset
publisher（可选）与 resource service。Provider 不得自己读取配置或创建 exporter。

第三方 distribution 从 `nonebot_plugin_htmlrender.providers` 导入
`EngineProvider`、`ProviderDependencies`、`EngineBindings` 与
`ResourceStrategy`；不要依赖核心包的内部配置模块。

## Bindings

`EngineBindings` 至少包含：

- lifecycle；
- 可选 `PreparedHtmlExecutor`；
- typed Capability catalog；
- 描述与低基数 observation attributes。

`ResourceStrategy` 只由 `resource_strategy(settings)` 提供。composition 必须先用它
决定 reader/publisher 接线，再调用 `compose()`；`EngineBindings` 不重复携带该值，
避免两个策略来源发生漂移。

没有通用位图能力的 Provider 可以省略 executor，但必须只声明真实存在的
Capability。不要创建“什么都支持”的大接口。

## Discovery

distribution 在 entry point group 中注册：

```toml
[project.entry-points."nonebot_plugin_htmlrender.providers"]
echo = "htmlrender_echo_provider:PROVIDER"
```

entry point 名必须等于 `provider.id`。`playwright`、`takumi` 为保留 ID；
重复 ID、保留 ID 覆盖、加载对象不满足协议都应在 composition 前失败。

## 配置

配置由 Provider 自己的严格模型校验，拒绝未知字段和互斥组合。解析完成后的
对象只在 composition 内传递，不写回全局状态。

## Capability

专属能力使用稳定的 `CapabilityKey[T]`：

```python
from nonebot_plugin_htmlrender.rendering import CapabilityKey

ECHO_DIAGNOSTICS = CapabilityKey("echo.diagnostics", EchoDiagnostics)
```

`CapabilityKey.interface` 必须是 concrete class、ABC，或使用
`@runtime_checkable` 标记的 `Protocol`，因为 composition 会在注册与读取时执行
运行时类型检查。

接口应表达业务动作，而不是暴露内部资源句柄。Capability 实现从自己的
lease provider 获取当前有效 lease；调用方不得跨 runtime 重建缓存租约产物。

## 参考实现

`examples/echo-provider` 展示最小第三方 distribution。新增 Provider 时先让
该示例的 discovery、settings、lifecycle、executor 与错误翻译测试通过，再
增加引擎专属能力。
