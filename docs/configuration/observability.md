---
title: 可选依赖与可观测性
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
| `filehost` | 为内置 HTTP asset publisher 增加 `py-machineid` 守卫标识来源 |
| `sentry` | Sentry spans 与 metrics |
| `prometheus` | Prometheus metrics |
| `all` | 安装上述全部能力，包括具有平台限制的 Skia |

```bash
uv add "nonebot-plugin-htmlrender[playwright,sentry,prometheus]>=0.8.0,<0.9"
```

HTMLKit/Playwright/Takumi 的引擎库缺失会形成可诊断的 Provider availability；插件不会在 import 时无条件加载所有引擎。选择 HTMLKit 时，bootstrap 会在 NoneBot
startup 前只加载其对应插件，以注册上游 Fontconfig 初始化 hook。filehost transport由 htmlrender 自有的 `HostedAssetStore` 提供，bootstrap 会在 FastAPI ASGI host启动前安装固定路由和请求头守卫，不再加载第二个 NoneBot filehost 插件。`filehost`
extra 只提供 `py-machineid` 作为默认守卫值的机器标识来源；未安装时会使用内置回退，也可以显式配置 `request_header_value`。

Pillow/Skia 只在 `render.graphics.backends` 显式配置后加载，并形成独立 typed
Capability，不进入 Provider discovery。Skia 没有 sdist/musllinux wheel，并要求manylinux_2_28、macOS 11+ 或受支持的 Windows wheel；Linux 还必须提供`libEGL.so.1`、`libGL.so.1` 与 `libexpat.so.1` 等运行库。Alpine/musl 或旧 glibc 镜像不要安装 `skia` 或 `all` extra；完整平台矩阵与安装命令见 [Skia 后端](graphics/skia.md)。

HTMLKit 当前精确锁定 `nonebot-plugin-htmlkit==0.1.0rc5`。它不引入 Playwright 或Pillow，但属于 prerelease，平台 wheel、选项限制和 Fontconfig 生命周期见[HTMLKit 配置](providers/htmlkit.md)。

## 开启观测

```yaml
render:
  provider: playwright
  observability:
    sentry: true
    prometheus: true
```

完整路径为 `render.observability.sentry` 与`render.observability.prometheus`，默认均为 `false`。开关启用后 bootstrap 会自动尝试 `require` 对应 NoneBot 集成插件；未安装或加载失败只记录 warning，不会让渲染运行时启动失败。

htmlrender 只负责产生 span 与指标，不负责重复配置 exporter：Sentry 的 DSN、采样、transport 和 release 等设置仍由 `nonebot_plugin_sentry`/Sentry SDK 管理；Prometheus
registry 与 HTTP endpoint 仍由 `nonebot_plugin_prometheus` 管理。两个 NoneBot 插件会在 htmlrender 导入阶段按开关提前加载，使它们来得及注册 startup hook；不要等到第一次渲染后才动态加载集成。

## 插装边界

composition 为每个 `Application` 创建 observer，并注入 Provider、Graphics backend、Resource Service、template compiler 与 Capability。Sentry 和 Prometheus 同时开启时，同一个 observer 将一次操作扇出到两个 exporter，不引入第二套渲染生命周期或参数契约；两者都关闭时 composition 直接注入 no-op observer。

| 调用面 | 观测范围 | operation |
| --- | --- | --- |
| 通用渲染 | Provider executor 的完整调用 | `playwright.html_render.rasterize_html`、`takumi.rasterize_html`、`htmlkit.rasterize_html` |
| Provider 生命周期 | runtime acquisition、启动与关闭 | acquisition 使用内部兼容名称；启动与关闭为 `render.startup`、`render.shutdown` |
| Provider runtime | 引擎创建、连接与释放子步骤 | `playwright.open_runtime`、`playwright.open_session`、`takumi.open_runtime`、`takumi.close_runtime` |
| Graphics | draw 与 encode 的完整调用 | `graphics.pillow.render_scene`、`graphics.skia.render_scene` |
| Playwright 原生访问 | `async with app.extensions.playwright.page()` 或 `.browser()` 的完整租约 | `playwright.native.page`、`playwright.native.browser` |
| Takumi 托管 API | `app.extensions.takumi.api()` 返回对象的每个异步方法 | `takumi.api.*` |
| Takumi 原生访问 | `async with app.extensions.takumi.renderer()` 的完整租约 | `takumi.native.renderer` |

Playwright 的 `Page.goto()`、`Locator.screenshot()` 等调用位于`playwright.native.page` span 内，但 htmlrender 不代理 Playwright 对象，也不会为每个上游方法再建立一层 operation。若 Playwright 自身另有 tracing，它可以在同一调用中独立工作。Takumi 的托管 API 可以在不牺牲上游类型的情况下按方法插装；直接取得原生`Renderer` 时则与 Playwright 相同，只观测整个租约，不猜测或拦截其内部调用。原生上下文内未被调用方捕获的上游异常会把该上下文标记为失败，但异常类型本身保持不变；调用方在上下文内部捕获并吞掉的异常不会被 observer 推断为失败。

生成的 operation span 总会包含 `render.backend`，结束时补充 `render.status`（`ok` 或`error`）与 `render.duration_seconds`。具体调用还可能提供稳定的低基数属性，例如`render.format`、`render.access` 与 `render.cache_hit`。

## Sentry 插装

存在当前 Sentry span 时，htmlrender 创建 child span；否则创建以 operation 为 `op`和 name 的 root transaction，并把 transaction source 设为 `task`。是否实际采样、如何上传完全遵循 Sentry SDK 配置。Sentry SDK 没有可用 metrics surface 时，trace仍可工作，指标则安全跳过。

生成的失败 span 总会附加 `error.type`。若异常属于 `RenderingError`，还会附加`error.message`、`error.message_truncated`、`error.cause_types` 与`error.causes_truncated`；这些值来自有界错误快照，不包含 native 异常对象。这里仅标记 span，不额外把同一个异常捕获为 Sentry event。

## Prometheus 插装

Prometheus collector 在首次使用时按进程惰性创建并复用，避免重复注册。操作 counter与 duration histogram 使用相同的 `op`、`backend`、`status` 标签。当 Sentry span提供 trace ID 时，htmlrender 会尽力把 `trace_id` exemplar 同时写入 counter 与histogram；客户端版本或存储后端不支持 exemplar 时自动回退为普通观测。

`/metrics` 路由、registry 选择和抓取配置属于 `nonebot_plugin_prometheus`，不是htmlrender 的公共接口。启用 htmlrender 的 Prometheus 开关只表示向该集成注册并更新collector。

## 稳定指标 schema

| 含义 | Prometheus | 类型与 labels | Sentry | 类型与 tags |
| --- | --- | --- | --- | --- |
| 操作次数 | `nonebot_htmlrender_operations_total` | counter；`op`、`backend`、`status` | `nonebot.htmlrender.count` | count；`op`、`backend`、`status` |
| 操作耗时 | `nonebot_htmlrender_duration_seconds` | histogram；`op`、`backend`、`status` | `nonebot.htmlrender.duration` | distribution（second）；`op`、`backend`、`status` |
| 缓存事件 | `nonebot_htmlrender_cache_events` | counter；`cache`、`event` | `nonebot.htmlrender.cache.events` | count；`cache`、`event` |
| 缓存条目 | `nonebot_htmlrender_cache_entries` | gauge；`cache` | `nonebot.htmlrender.cache.entries` | gauge；`cache` |
| 缓存驻留字节 | `nonebot_htmlrender_cache_resident_bytes` | gauge；`cache` | `nonebot.htmlrender.cache.resident_bytes` | gauge（byte）；`cache` |

当前 `cache` 值由 composition 固定为 `resource`、`template_environment`、`filehost`或 `takumi_compiled`；`event` 使用 `hit`、`miss`、`load`、`wait` 与 `eviction` 中适用于该缓存的子集。仅 byte-weighted cache 会更新 `resident_bytes`。

指标表示的具体缓存层并不相同：`template_environment` entries 是 Environment 数量，不包含内层 compiled templates；`filehost` entries 是 publisher mapping；`takumi_compiled` 的 resident bytes 是输入 source weight，不是 native heap 精确值。按现象选择指标和调优动作见[缓存组件、失效与调优](../guides/cache-lifecycle.md#tune-with-metrics)。

操作指标只使用稳定的 operation、provider identity 与 status 维度。当前导出schema 中 provider identity 的 label 名保留为 `backend`；它是兼容性字段，不是公共架构概念。路径、URL、HTML、模板变量、字体名、digest、资源内容、错误消息和 cause
type 都不会进入指标标签。

常用 PromQL 示例：

```promql
sum by (op, backend, status) (
  rate(nonebot_htmlrender_operations_total[5m])
)
```

```promql
histogram_quantile(
  0.95,
  sum by (le, op, backend) (
    rate(nonebot_htmlrender_duration_seconds_bucket[5m])
  )
)
```

多进程部署会由每个 worker 持有自己的 registry、cache gauge 与运行时；聚合规则应以 Prometheus 抓取到的实例标签区分进程，不能把单进程 cache gauge 当作集群总量。

## 故障隔离

observer 由 composition 注入。Sentry/Prometheus 写入失败只降低观测质量，不会替换成功的渲染结果，也不会覆盖原始业务异常。自定义 Provider 不应自行创建 exporter；使用 `ProviderDependencies` 提供的 operation/cache observer，并为operation 与属性选择固定、低基数的值。

bootstrap 发现已启用的集成缺失或加载失败时会记录 warning；SDK API 不兼容、collector 注册或写入失败会记录 `htmlrender.telemetry` warning。无可用 Sentry trace时还会输出 operation、backend、status 与 duration 的 debug 日志作为本地诊断回退。可选插件的首次加载结果会在进程内缓存；修复安装或启动配置后需要重启进程。
