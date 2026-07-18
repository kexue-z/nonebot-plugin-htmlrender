---
title: 资源解析与传输
description: Resource Service、reader decorators、安全策略与 AssetPublisher
icon: lucide/files
---

# 资源解析与传输

资源层把“资源是什么”“能否读取”“如何读取/缓存”“如何交给执行端”分成独立
端口，避免 Provider 内部重复实现路径和 cache 规则。

## 核心模型

- `ResourceRef`：`FileResourceRef`、`PackageResourceRef`、
  `RemoteResourceRef`、`InlineResourceRef`。
- `ResourceRevision`：用于缓存身份与 revalidation。
- `ResourceContent`：不可变 bytes、可选 media type 与 revision。
- `ResourceReader.read(ref, *, refresh=False)`：异步读取；强制 refresh 是一次原子
  cache 操作，不由 service 拼接 invalidate/read。
- `LocalAccessPolicy.authorize(path)`：本地读取前授权并返回正规化路径。
- `AssetPublisher.publish(value, *, lease_id, suffix)`：将路径或 bytes 映射为执行端 URL。
- `WorkerExecutor.run_sync(...)`：有界执行 filesystem/native 同步工作。
- `ResourceService`：递归模板变量、URL token 与 asset materialization。
- `ProviderResources`：收窄给 Provider 的策略绑定 façade，只公开本地授权、bytes
  读取与不可变 `ResourceStrategy`。

## reader 组合

```text
CachingResourceReader(
    CompositeResourceReader(
        filesystem,
        package,
        remote,
        inline,
    )
)
```

`CachingResourceReader` 在同一个 load slot 中完成 cache lookup、revision 复查、
singleflight 与 writeback，避免 waiter 重复计作 source load。零驻留的
零容量 `CachingResourceReader` 复用同一 singleflight 状态机。reader 接收 composition 注入的
cache observer，并在边界隔离 observer 故障。授权发生在可复用内容发布前；
不同 composition 不共享 cache、budget、observer 或 inflight 状态。

## 缓存不变量

- entries 与 resident bytes 共用有界 budget；
- filesystem revision 按 revalidate window 复查；
- package/inline 可使用不可变 revision；
- 同一冷 key 由 singleflight 合并；
- 同一 key 的并发强制 refresh 合并，refresh 开始后的普通读取等待新值；
- owner 成功或失败会向 waiters 发布同一结果；owner 自身被取消时只摘除 slot，
  waiters 重新竞争 load ownership，不继承其他调用方的取消；
- clear/invalidate 摘除旧 inflight，按 slot identity 隔离 writeback；新读取等待
  inner reset 完成，不消费 reset 前的内部状态；
- 超过 byte 上限的单值旁路，不驱逐全部缓存；
- reader/publisher 在分配完整 payload 前执行单资源大小限制；
- LRU 与统计更新在同一同步边界内。

cache event 采用操作语义：`miss` 只由无法复用 resident value 的 owner 产生；
`load` 表示 source 成功返回 content（失败或取消的 attempt 不计 load）；`wait`
表示一次调用加入既有 load slot；`eviction` 只表示容量策略驱逐，不包含显式
invalidate/clear。

## 已知缓存边界（尚未实现）

下列行为不属于当前缓存契约，不能从现有配置项推断它们已经存在：

- remote reader 会在首次 GET 后保存响应的 `ETag` 或 `Last-Modified` revision，
  但 `revision(RemoteResourceRef)` 目前返回 `None`；revalidate window 到期时执行
  完整、无条件 GET，尚未发送 `If-None-Match` / `If-Modified-Since` 条件请求；
- filehost publisher 只有 opportunistic TTL 清理和 render lease pinning，没有
  `max_entries` / `max_bytes` 容量预算；持续发布大量不同资源时，mapping 可能在
  下一次 publish 触发过期清理前增长，活跃 lease 也会延长驻留；
- Takumi compiled cache 的 `compiled_cache_max_bytes` 使用输入 source 的 UTF-8
  byte 长度作为 weight proxy，不是 compiled/native object 的实际 resident memory；
- `environment_cache_max_entries` 只限制外层 Jinja `Environment` LRU。每个
  environment 仍保留 Jinja 自身默认最多 400 条的 template cache，因此总驻留上界
  是外层环境数与各环境内部 cache 的组合，而不是单一全局 template 条目预算。

这些边界需要分别通过 conditional HTTP reader、filehost 容量策略、可观测的
native weight/disposer，以及显式 Jinja 内层 cache 配置解决；在实现前不应把
`max_bytes` 或 `environment_cache_max_entries` 描述为覆盖这些对象的总内存上限。

## LocalAccessPolicy

路径正规化、root containment 与 symlink 判定由同一策略实现。Provider、
filehost 和模板 loader 不得各自复制白名单逻辑。`allow_any_path` 是显式危险
开关，默认关闭。

## ResourceStrategy

Provider 用不可变策略描述执行端需求：

- 本地 Playwright：`file` 或显式 publisher；
- 远程 Playwright：`memory`、共享卷 passthrough、filehost 或 error；
- HTMLKit：本地与 prepared assets 先物化，远程资源 callback 只委托 composition
  注入的 `ProviderResources.read_bytes()`，不启用上游内置 filesystem/network
  fetcher；
- Takumi：直接消费已物化 bytes；
- 第三方 Provider：只组合 `ProviderResources` 与已有 transport，不依赖核心 reader
  或完整 `ResourceService`。

策略不执行 I/O；composition 根据策略组装 materializer/publisher。
每次调用的 `ResourcePolicy` 优先于 Provider 默认 `resolve_mode`；未提供覆盖时，
HTMLKit、Playwright 与 Takumi executor 都必须执行同一个默认值。`off` 调用不得在
executor 中退回到 transport policy 后隐式物化；若 transport 需要 publisher，
composition 仍需组装它，以兑现后续单次调用的 `auto` / `strict` 覆盖。

## 浏览器资产响应不变量

`memory` 与 filehost 是不同 transport，但都必须让远程浏览器安全消费受授权资产：

- 响应保留 asset bytes 与正确媒体类型；
- 跨源图片、CSS 与字体响应携带 `Access-Control-Allow-Origin: *`；
- `memory` route 同时返回 cache header，资源只在当前 render lease 内有效；
- filehost 先执行请求头守卫，仅为认证成功的资源响应添加通配 CORS；被拒绝的请求
  返回 403，且不携带该响应头。

!!! warning "CORS 不是授权机制"

    实现和代理不得用可访问 URL 或通配 CORS 替代 `LocalAccessPolicy` 与 filehost
    请求头守卫，也不得在代理层剥离守卫请求头或 CORS 响应头。

## filehost publisher

filehost 是 `AssetPublisher` adapter。NoneBot require、路由安装、预热和关闭都
属于 bootstrap/adaptor lifecycle。URL mapping 按 digest singleflight 去重，
TTL 只管理 mapping；render lease 钉住在途内容。物理临时文件生命周期由
filehost 插件管理。

## 失败与取消

读取/授权/大小错误翻译为稳定 `ResourceResolutionError` 子类。取消不得留下
未唤醒 waiter、未释放 lease 或半发布 mapping。关闭先拒绝新 publish，再在
有界时间内 drain/取消已有任务。

## 测试

覆盖 ref dispatch、目录与 symlink 越界、immutable/revalidate revision、
远程失败、strict/auto/off、并发冷读、owner/waiter 取消、异常广播、
generation 竞争、byte budget/LRU、observer 隔离和两个 composition 隔离。真实远程
Chromium 测试必须分别经过 `memory` 与 filehost transport，验证 Markdown 引用的
CSS、图片和字体确实完成加载；filehost 还需验证守卫请求头、成功响应的 CORS、
未认证 403，以及浏览器侧没有对应的 `requestfailed`。
