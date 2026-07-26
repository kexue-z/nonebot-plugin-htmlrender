---
title: 资源管线
description: Resource Service、reader decorators、安全策略与 AssetPublisher
icon: lucide/files
---

# 资源管线

资源层把“资源是什么”“能否读取”“如何读取/缓存”“如何交给执行端”分成独立端口，避免 Provider 内部重复实现路径和 cache 规则。

## 核心模型

- `ResourceRef`：`FileResourceRef`、`PackageResourceRef`、`RemoteResourceRef`、`InlineResourceRef`。
- `ResourceRevision`：用于缓存身份与 revalidation。
- `ResourceContent`：不可变 bytes、可选 media type 与 revision。
- `ResourceReader.read(ref, *, refresh=False)`：异步读取；强制 refresh 是一次原子cache 操作，不由 service 拼接 invalidate/read。
- `LocalAccessPolicy.authorize(path)`：本地读取前授权并返回正规化路径。
- `AssetPublisher.publish(value, *, lease_id, suffix) -> PublishedResource`：将路径或bytes 映射为执行端 URL。返回不可变 `PublishedResource(url, request_headers)`，授权随URL 一起下发；调用方按发布的精确 URL 匹配注入 header，不按 host / path 前缀 / 网络位置推断。
- `ResourceResolution[T]`：公共资源解析结果；`.value` 保持模板可直接消费的普通字符串/容器结构，`.request_headers_by_url` 汇总其中每个发布 URL 的不可变精确授权。相同 URL 若出现不同 header，整个解析操作失败，不能在宽松模式下猜测其中一组凭据。
- `WorkerExecutor.run_sync(...)`：completion-bound 执行 filesystem/native 同步工作。远程传输不复用该池：`RemoteTransportExecutor` 持有专用线程池，提交前获取实例级admission token，token 只在 future 的 done callback 中释放（worker 数与 token 数相等，池内不形成第二层 backlog）；完成事件经 AnyIO event-loop token 投递回原backend，等待方只 await `anyio.Event`，取消后立即恢复且不占用默认 AnyIO worker。`read_remote` 在单调 deadline（`request_timeout_seconds`）内编排DNS→policy→pinned request→redirect。传输由 bootstrap 显式创建并经 application
  lifecycle 的异步 `aclose()` 关闭（停止 admission → 按提交任务各自 deadline 排空 →关闭线程池，排空超时抛 `ProviderLifecycleError` 并保持可重试）；独立使用者经`open_resource_reader()` async context manager 获得 reader 与传输的所有权闭环。
- `ResourceService`：递归模板变量、URL token 与 asset materialization；公共`resolve_template_vars()`、`to_resource_url()`、`resolve_url_tokens()` 均返回`ResourceResolution`，不会把 `PublishedResource` 塞进模板变量树，也不会丢弃publisher 的请求授权。
- `ProviderResources`：收窄给 Provider 的策略绑定 façade，只公开本地授权、bytes读取与不可变 `ResourceStrategy`。

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

`CachingResourceReader` 在同一个 load slot 中完成 cache lookup、revision 复查、singleflight 与 writeback，避免 waiter 重复计作 source load。零驻留的零容量 `CachingResourceReader` 复用同一 singleflight 状态机。reader 接收 composition 注入的cache observer，并在边界隔离 observer 故障。授权发生在可复用内容发布前；不同 composition 不共享 cache、budget、observer 或 inflight 状态。

## 缓存不变量

- entries 与 resident bytes 共用有界 budget；
- filesystem revision 按 revalidate window 复查；
- package/inline 可使用不可变 revision；
- 同一冷 key 由 singleflight 合并；
- 同一 key 的并发强制 refresh 合并，refresh 开始后的普通读取等待新值；
- owner 成功或失败会向 waiters 发布同一结果；owner 自身被取消时只摘除 slot，waiters 重新竞争 load ownership，不继承其他调用方的取消；
- clear/invalidate 摘除旧 inflight，按 slot identity 隔离 writeback；新读取等待inner reset 完成，不消费 reset 前的内部状态；
- 超过 byte 上限的单值旁路，不驱逐全部缓存；
- reader/publisher 在分配完整 payload 前执行单资源大小限制；
- LRU 与统计更新在同一同步边界内。

cache event 采用操作语义：`miss` 只由无法复用 resident value 的 owner 产生；`load` 表示 source 成功返回 content（失败或取消的 attempt 不计 load）；`wait`表示一次调用加入既有 load slot；`eviction` 只表示容量策略驱逐，不包含显式invalidate/clear。

## 缓存边界

已实现的容量与复用契约：

- remote revalidation 走显式 conditional-read port：`ResourceReader.read_conditional`把缓存持有的 revision 传回 reader，remote adapter 将 `etag:` / `modified:`前缀的 revision token 映射到 `If-None-Match` / `If-Modified-Since`，`304`返回 typed `NotModified` 并复用缓存 bytes；reader 内不保存隐式 validator 状态。
- Jinja 内层 compiled-template cache 通过`render.resources.templates.environment_compiled_cache_size` 显式绑定到每个`Environment`（`0` 真正关闭缓存），与 `environment_cache_max_entries` 一起构成可计算的驻留上界。
- Takumi compiled cache 的 `compiled_cache_max_source_bytes` 明确以输入 source的 UTF-8 byte 长度作为容量单位，不是 compiled/native object 的实际 resident
  memory；native 对象数量的硬上限由 `compiled_cache_max_entries` 提供。

- hosted asset store（固定内部 mount `/_htmlrender/assets/`，由 bootstrap 在ASGI 启动前安装）拥有临时目录、精确 guard registry 与容量台账：写入前预留entry/byte admission，content-addressed LRU 只驱逐无 lease 资源并同步删除文件，全部被 lease 占用且超限时抛稳定 capacity error；publisher 只经自身namespace handle 发布/释放，TTL 只决定复用时效。`public_base_url` 是显式部署配置（禁止从 bind address、`Host`/`Forwarded` header 或 request context推导），filehost transport 选中而缺失时 composition 阶段即失败。hosted route 与 Playwright request route 共用同一 header merge 语义（`resources/headers.py`：相同值去重、冲突失败、capability 覆盖调用方预置值，不允许 `setdefault` 让错误值胜出）。

## LocalAccessPolicy

路径正规化、root containment 与 symlink 判定由同一策略实现。Provider、filehost 和模板 loader 不得各自复制白名单逻辑。`allow_any_path` 是显式危险开关，默认关闭。

## ResourceStrategy

Provider 用不可变策略描述执行端需求：

- 本地 Playwright：`file` 或显式 publisher；
- 远程 Playwright：`memory`、共享卷 passthrough、filehost 或 error；
- HTMLKit：本地与 prepared assets 先物化，远程资源 callback 只委托 composition注入的 `ProviderResources.read_bytes()`，不启用上游内置 filesystem/network
  fetcher；
- Takumi：直接消费已物化 bytes；
- 第三方 Provider：只组合 `ProviderResources` 与已有 transport，不依赖核心 reader或完整 `ResourceService`。

策略不执行 I/O；composition 根据策略组装 materializer/publisher。每次调用的 `ResourcePolicy` 优先于 Provider 默认 `resolve_mode`；未提供覆盖时，HTMLKit、Playwright 与 Takumi executor 都必须执行同一个默认值。`off` 调用不得在executor 中退回到 transport policy 后隐式物化；若 transport 需要 publisher，composition 仍需组装它，以兑现后续单次调用的 `auto` / `strict` 覆盖。

## 浏览器资产响应不变量

`memory` 与 filehost 是不同 transport，但都必须让远程浏览器安全消费受授权资产：

- 响应保留 asset bytes 与正确媒体类型；
- 跨源图片、CSS 与字体响应携带 `Access-Control-Allow-Origin: *`；
- `memory` route 同时返回 cache header，资源只在当前 render lease 内有效；
- filehost 先执行请求头守卫，仅为认证成功的资源响应添加通配 CORS；被拒绝的请求返回 403，且不携带该响应头。

!!! warning "CORS 不是授权机制"

    实现和代理不得用可访问 URL 或通配 CORS 替代 `LocalAccessPolicy` 与 filehost请求头守卫，也不得在代理层剥离守卫请求头或 CORS 响应头。

## filehost publisher

filehost 是 `AssetPublisher` adapter。htmlrender bootstrap 在 FastAPI ASGI host启动前安装固定路由与进程级 `HostedAssetStore`；预热和关闭仍属于bootstrap/adapter lifecycle，不需要 `require` 外部 filehost 插件。URL mapping 按digest singleflight 去重，TTL 只管理 mapping；render lease 钉住在途内容。物理临时文件、容量台账和最终清理由 `HostedAssetStore` 管理。

## 失败与取消

读取/授权/大小错误翻译为稳定 `ResourceResolutionError` 子类。取消不得留下未唤醒 waiter、未释放 lease 或半发布 mapping。关闭先拒绝新 publish，再在有界时间内 drain/取消已有任务。

## 测试

覆盖 ref dispatch、目录与 symlink 越界、immutable/revalidate revision、远程失败、strict/auto/off、并发冷读、owner/waiter 取消、异常广播、generation 竞争、byte budget/LRU、observer 隔离和两个 composition 隔离。真实远程Chromium 测试必须分别经过 `memory` 与 filehost transport，验证 Markdown 引用的CSS、图片和字体确实完成加载；filehost 还需验证守卫请求头、成功响应的 CORS、未认证 403，以及浏览器侧没有对应的 `requestfailed`。
