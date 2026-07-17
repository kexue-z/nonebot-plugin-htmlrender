---
title: 依赖扩展与观测
description: filehost、Sentry、Prometheus 与稳定低基数遥测
icon: lucide/activity
---

# 依赖扩展与观测

## 可选 extras

| extra | 用途 |
| --- | --- |
| `htmlkit` | 实验性 HTMLKit/litehtml Provider |
| `playwright` | Playwright Provider |
| `takumi` | Takumi Provider |
| `pillow` | 独立 Pillow `RasterScene` Capability |
| `skia` | 独立 Skia `RasterScene` Capability |
| `filehost` | Playwright 的显式 HTTP asset publisher |
| `sentry` | Sentry spans 与 metrics |
| `prometheus` | Prometheus metrics |
| `all` | 安装上述全部能力，包括具有平台限制的 Skia |

```bash
uv add "nonebot-plugin-htmlrender[playwright,sentry,prometheus]>=0.8.0a1,<0.9"
```

HTMLKit/Playwright/Takumi 的引擎库缺失会形成可诊断的 Provider availability；插件
不会在 import 时无条件加载所有引擎。选择 HTMLKit 时，bootstrap 会在 NoneBot
startup 前只加载其对应插件，以注册上游 Fontconfig 初始化 hook。filehost transport
不同：为了在 ASGI 启动前
安装 guard，bootstrap 会立即 `require` 对应 NoneBot 插件；缺少 `filehost` extra
或加载失败会直接抛出 `ProviderUnavailable`。

Pillow/Skia 只在 `render.graphics.backends` 显式配置后加载，并形成独立 typed
Capability，不进入 Provider discovery。Skia 没有 sdist/musllinux wheel，并要求
manylinux_2_28、macOS 11+ 或受支持的 Windows wheel；Linux 还可能需要 OpenGL、
`libEGL` 与 fontconfig 运行库。Alpine/musl 或旧 glibc 镜像不要安装 `skia` 或
`all` extra；完整平台矩阵与配置见 [Pillow 与 Skia 位图场景](graphics.md)。

HTMLKit 当前精确锁定 `nonebot-plugin-htmlkit==0.1.0rc5`。它不引入 Playwright 或
Pillow，但属于 prerelease，平台 wheel、选项限制和 Fontconfig 生命周期见
[HTMLKit 配置](htmlkit.md)。

## 开启观测

```yaml
render:
  provider: playwright
  observability:
    sentry: true
    prometheus: true
```

完整路径为 `render.observability.sentry` 与
`render.observability.prometheus`，默认均为 `false`。开关启用后 bootstrap 会
自动尝试 `require` 对应 NoneBot 集成插件；未安装或加载失败只记录 warning，
不会让渲染运行时启动失败。

## 稳定指标

Prometheus：

- `nonebot_htmlrender_operations_total`
- `nonebot_htmlrender_duration_seconds`
- `nonebot_htmlrender_cache_events`
- `nonebot_htmlrender_cache_entries`
- `nonebot_htmlrender_cache_resident_bytes`

Sentry：

- `nonebot.htmlrender.count`
- `nonebot.htmlrender.duration`
- `nonebot.htmlrender.cache.events`
- `nonebot.htmlrender.cache.entries`
- `nonebot.htmlrender.cache.resident_bytes`

操作指标只使用稳定的 operation、provider identity 与 status 维度。当前导出
schema 中 provider identity 的 label 名保留为 `backend`；它是兼容性字段，
不是公共架构概念。路径、URL、HTML、模板变量、字体名、digest 和资源内容
都不会进入标签。

## 故障隔离

observer 由 composition 注入。Sentry/Prometheus 写入失败只降低观测质量，
不会替换成功的渲染结果，也不会覆盖原始业务异常。自定义 Provider 不应自行
创建 exporter；使用 `ProviderDependencies` 提供的 observer。
