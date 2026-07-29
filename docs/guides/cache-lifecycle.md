---
title: 缓存组件、失效与调优
description: 资源、Jinja、filehost 与 Takumi 缓存的边界和运维方法
icon: lucide/database-zap
---

# 缓存组件、失效与调优

通常不需要主动管理 htmlrender 缓存：默认容量有界，filesystem 与 HTTP validator 会自动复查，Application 关闭时会释放其拥有的状态。只有内容未按预期更新、工作集持续抖动、filehost 容量不足或 Takumi runtime 需要替换字体时，才需要介入。

## 先按现象选择操作 { #choose-an-action-by-symptom }

| 现象或目标 | 首选操作 | 不要做 |
| --- | --- | --- |
| 单个资源刚被外部程序覆盖，需要下一次读取立即看到 | 对同一路径调用 `app.resources.read_bytes(..., refresh=True)` 或 `read_text(..., refresh=True)` | 不要为了一个 key 重启整个 Bot |
| 批量生成任务开始前必须丢弃所有已读 resource bytes | 调用一次 `await app.resources.clear()` | 不要误以为它也会清理 Jinja、filehost 或 Takumi |
| 用户模板文件发生变化 | 直接再次渲染，默认 auto-reload 会检查模板 | 不要调用 adapter 内部 Jinja API |
| 自定义 filter 在高频调用中导致 Environment miss | 复用模块级函数或稳定 callable | 不要在循环内创建 lambda、`partial` 或 bound method |
| 远程 filehost 重复上传或容量耗尽 | 先检查 lease、TTL、预热范围与 `filehost` cache 指标，再调整容量 | 不要把 TTL 当作硬容量或删除计时器 |
| Takumi 重复编译相同 HTML/CSS | 读取 `api.compiled_cache_stats`，根据 hit/eviction 调整 compiled cache | 不要用 Resource Reader 的 clear 处理 native compiled object |
| Takumi 字体文件或注册选项已变化 | 关闭并重建 Application/runtime | 不要尝试在同一 native source 上热替换 |
| 希望释放当前 composition 的全部状态 | `await app.aclose()`，需要继续服务时构建新的 Application | 不要关闭后继续使用旧 facade 或 Capability |

处理问题时先用上表选择公共入口，再用下方组件拓扑解释为什么该操作只影响对应层。htmlrender 的缓存由 composition、Provider runtime 或进程级 hosted store 分别拥有，因此不存在一个能够清理所有缓存的全局按钮。

## 默认配置何时需要调整

保持默认值，直到指标或稳定复现表明工作集不匹配。容量调优遵循以下顺序：先确认缓存 key 是否稳定，再确认 source 是否频繁变化，最后才扩大 entries/bytes；不稳定的 filter identity、每次都不同的 HTML 或过宽的 filehost 预热目录无法通过单纯增加内存解决。

适合先调整条目数的场景是大量小对象；适合先调整 byte budget 的场景是少量大图片或字体。把任一支持 `0` 的驻留上限设为 `0` 适合验证缓存是否参与问题，也适合明确不需要跨调用复用的短命 worker，但会增加 source I/O 或 native 编译成本。

## 组件拓扑

| 组件 | 观测名称 | 缓存内容与 key | 容量与失效 | 公共控制面 |
| --- | --- | --- | --- | --- |
| Resource Reader | `resource` | `ResourceRef.cache_key` 对应的 bytes 与 revision | 条目数和驻留 bytes 双重 LRU；按 revalidation window 复查 | `read_bytes(..., refresh=True)`、`read_text(..., refresh=True)`、`app.resources.clear()` |
| Jinja Environment | `template_environment` | 模板源、immutable 模式、extensions、filter 名称与 callable 身份 | Environment LRU；每个 Environment 另有 compiled-template cache | 渲染调用自动使用；Application 关闭时清理 |
| Filehost publisher/store | `filehost` | 内容 SHA-256、suffix、Application namespace 与请求头能力 | publisher TTL 加 hosted store 条目/bytes LRU；活跃 lease 钉住资源 | 由 filehost transport 自动管理；Application 关闭时释放 namespace |
| Takumi compiled | `takumi_compiled` | HTML 与 HtmlOptions，或 CSS 与 strict/lossy 模式 | 条目数与输入 source UTF-8 bytes 双重 LRU | `api.compiled_cache_stats` 只读；重建 runtime 才能完整清理 |

`memory` transport 中的 `PreparedAsset` 和 Playwright Page route 只存活于当前 render lease，不是跨调用 cache。Playwright 的 browser storage 保存浏览器二进制和安装状态，也不属于上述运行时缓存；它的版本与目录约束见 [Playwright 浏览器运行环境](../configuration/providers/playwright.md#browser-runtime-requirements)。

## Resource Reader { #resource-reader }

Resource Reader 在每个 Application 内共享，filesystem、package、inline 和 HTTP(S) resource 都经过同一有界缓存。授权发生在读取和复用之前，因此 cache hit 不会绕过本地路径或远程网络策略。

在 `revalidate_seconds` 窗口内，resident value 可以直接复用。窗口到期后，带 revision 的 filesystem/package/HTTP resource 会执行 stat 或条件读取；资源未变化时复用原 bytes，变化时原子替换。没有 revision 的远程响应会重新读取正文。

需要立即绕过 resident value 时，从当前 Application 的 Resource Service 强制刷新：

```python
from nonebot_plugin_htmlrender import get_default_application

app = get_default_application()
payload = await app.resources.read_bytes(
    "assets/profile.png",
    refresh=True,
)
text = await app.resources.read_text(
    "templates/card.html",
    refresh=True,
)
```

`refresh=True` 只刷新该 resource key，并与同 key 的并发读取通过 singleflight 协调。需要丢弃整个 Resource Reader 的 resident entries 与 inflight generation 时使用：

```python
await app.resources.clear()
```

!!! warning "resources.clear 不是全局缓存清理"

    `app.resources.clear()` 只清理当前 Application 的 Resource Reader。它不会清理 Jinja Environment、filehost publisher/store、Takumi compiled/native 状态或 Playwright browser storage。需要释放整个 composition 时调用 `await app.aclose()`；关闭后的 Application 不能再次使用。

`max_entries=0` 或 `max_bytes=0` 会禁用 Resource Reader 的跨调用驻留，但同一时刻的并发冷读仍可共享 singleflight。大于 `max_bytes` 的单个成功读取会返回给调用方但不驻留；超过 `max_resource_bytes` 的资源会在读取或发布边界被拒绝。这三个值承担不同职责，不能互相替代。

## Jinja Environment 与自定义 filter { #jinja-environment-and-custom-filters }

Jinja 使用两层有界缓存：外层按 Environment key 维护 LRU，内层由每个 Environment 缓存已编译模板。`environment_cache_max_entries=0` 禁用外层驻留；`environment_compiled_cache_size=0` 禁用每个 Environment 的 compiled-template cache。

Environment key 包含模板源、immutable 模式、extensions，以及每个自定义 filter 的名称和 callable 身份。filter 在 `get_template()` 编译前注入，因此同名不同 callable 不会串用；`pass_context`、`pass_eval_context` 与 `pass_environment` 等调用约定也在对应 Environment 内编译。

为获得稳定命中，应复用模块级函数或长期存在的 callable：

```python
from nonebot_plugin_htmlrender import render_template

def format_percent(value: float) -> str:
    return f"{value:.1%}"

artifact = await render_template(
    "templates",
    "progress.html",
    {"progress": 0.625},
    filters={"percent": format_percent},
)
```

不要在每次调用时重新创建 lambda、`functools.partial` 或 bound method；即使行为相同，新 callable 身份也会产生新的 Environment key，造成 LRU churn。同步 filter 在事件循环线程执行，不应进行阻塞 I/O 或长时间 CPU 工作；Jinja 已启用 async，异步 filter 可以直接等待异步操作。

`render_template` 会先把变量树中的 `Path`/bytes 准备成资源 URL，再执行 filter；`render_template_html` 不进行资源物化，filter 接收原始变量。filter 若依赖这些类型，必须按所用入口设计，不能假设两个 API 的输入已经完成相同转换。

用户模板默认启用 Jinja auto-reload；模板文件变化后，后续加载会重新编译。公共 API 不暴露按模板源清理 Environment 的 adapter 内部接口；需要确定性地释放全部 Jinja 状态时关闭并重建 Application。

## Filehost publisher 与 hosted store { #filehost-publisher-and-hosted-store }

filehost 具有两个相互配合但职责不同的层次：每个 Application 的 publisher 维护 content-addressed URL mapping、TTL、lease 和 singleflight；进程级 hosted store 持有临时文件、请求头 guard、namespace 和硬容量台账。

`cache_ttl_seconds` 只决定无活跃 lease 时 URL mapping 可以复用多久，不是文件删除定时器。publisher 在 lease 释放时重新计算 TTL；过期 mapping 会在后续 publish 时淘汰。hosted store 由 `max_entries` 与 `max_bytes` 约束，通过 LRU 驱逐没有 lease 的资源；若超限且所有 resident asset 都被活跃 render lease 钉住，会返回稳定的 capacity error，而不是破坏在途渲染。

预热在 publisher startup 期间执行。`prewarm_paths` 仍受本地访问白名单约束，`prewarm_extensions` 用于筛选，`prewarm_max_files` 限制候选数量；单个预热文件失败只记录 warning，不阻止其他候选继续处理。预热适用于部署时已知且复用频繁的静态资源，不应扫描宽泛目录。

filehost 没有公共手工 clear API，`app.resources.clear()` 也不会影响它。Application 关闭会清理 publisher mapping 并释放自己的 hosted namespace；进程级 store 在 driver shutdown 时删除剩余临时文件。

## Takumi compiled、字体与图片缓存 { #takumi-compiled-font-and-image-caches }

Takumi runtime 缓存编译后的 HTML node 和 stylesheet。HTML key 包含源码与会改变编译结果的 HtmlOptions；CSS key区分 strict 与 lossy 编译。`compiled_cache_max_source_bytes` 统计输入 source 的 UTF-8 bytes，不代表 native object 的实际常驻内存，因此还必须用 `compiled_cache_max_entries` 约束 native 对象数量。

在受管理 lease 内读取只读统计快照：

```python
from nonebot_plugin_htmlrender import get_default_application

takumi = get_default_application().extensions.takumi
async with takumi.api() as api:
    await api.render_svg_html("<strong>cached</strong>", width=320)
    stats = api.compiled_cache_stats
    print(
        stats.entries,
        stats.resident_weight,
        stats.hits,
        stats.misses,
        stats.loads,
        stats.waits,
        stats.evictions,
    )
```

任一 compiled cache 上限为 `0` 都会禁用跨调用驻留，但并发相同 key 仍使用 singleflight。公共 API 不提供手工 clear；关闭并重建 Takumi runtime 才能同时释放 compiled native objects、字体注册和 renderer 状态。

`FileCachePolicy.REVALIDATE` 会在读取字体文件时强制刷新 Resource Reader，`IMMUTABLE` 仅适用于随镜像交付且运行期间不变化的字体。字体一旦以某个 source 注册到 native renderer，同 source 的 bytes 或选项发生变化会被拒绝，必须重建 runtime。`TakumiImageResource.cache` 的 `auto` / `none` 控制 Takumi native image cache，与 htmlrender 的 Resource Reader 和 compiled cache 是不同层次。

## 使用指标调优 { #tune-with-metrics }

开启 Prometheus 或 Sentry 后，缓存事件使用 `resource`、`template_environment`、`filehost` 与 `takumi_compiled` 四个固定名称。先观察 `hit`、`miss`、`load`、`wait` 和 `eviction`，再调整容量；不要只因为 resident entries 达到上限就扩大预算。

```promql
sum by (cache, event) (
  rate(nonebot_htmlrender_cache_events_total[5m])
)
```

持续 eviction 且随后立即 miss，通常表示工作集大于容量；大量 wait 表示 singleflight 正在合并同 key 并发冷读；miss 增长但 load 不增长可能来自失败或取消。`template_environment` 的 entries 只统计 Environment，不包含每个 Environment 内部已编译模板数量；`takumi_compiled` 的 resident bytes 表示 source weight，而非 native heap 精确值。

完整配置字段见[资源与访问策略](../configuration/resources.md)和[Takumi 配置](../configuration/providers/takumi.md)，指标 schema 与 exporter 设置见[可选依赖与可观测性](../configuration/observability.md)。
