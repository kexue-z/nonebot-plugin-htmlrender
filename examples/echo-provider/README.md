# Echo Provider 示例

本目录是最小第三方 Provider distribution，不依赖浏览器或 native renderer，用于验证最终的 0.8 SDK：每个 raster request 都返回指定颜色的 1×1 PNG。

## 安装

```bash
uv add --editable ./examples/echo-provider
```

## 配置

```yaml
render:
  provider: echo
  startup: probe
  provider_config:
    color: "#663399"
```

distribution 通过 `nonebot_plugin_htmlrender.providers` entry-point group 注册`PROVIDER`。实现展示类型化 settings、无副作用 availability、lifecycle/executor
bindings、`ResourceStrategy`，以及 composition 注入的收窄 `ProviderResources`边界。

示例刻意不暴露 Provider 专属 Capability。只有需要展示真实 typed boundary 时才扩展它；不要向中立 executor 增加引擎专属参数。
