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
- `ResourceReader.read(ref)`：异步读取，不决定暴露方式。
- `LocalAccessPolicy.authorize(path)`：本地读取前授权并返回正规化路径。
- `AssetPublisher.publish(value, *, lease_id, suffix)`：将路径或 bytes 映射为执行端 URL。
- `WorkerExecutor.run_sync(...)`：有界执行 filesystem/native 同步工作。
- `ResourceService`：递归模板变量、URL token 与 asset materialization。

## reader 组合

```text
CachingResourceReader(
    SingleflightResourceReader(
        CompositeResourceReader(
            filesystem,
            package,
            remote,
            inline,
        )
    )
)
```

`CachingResourceReader` 接收 composition 注入的 cache observer，并在边界隔离
observer 故障。授权发生在可复用内容发布前；不同 composition 不共享 cache、
budget、observer 或 inflight 状态。

## 缓存不变量

- entries 与 resident bytes 共用有界 budget；
- filesystem revision 按 revalidate window 复查；
- package/inline 可使用不可变 revision；
- 同一冷 key 由 singleflight 合并；
- owner 成功、失败或取消都唤醒所有 waiters；
- clear/invalidate 与 inflight 发布按 generation/epoch 隔离；
- 超过 byte 上限的单值旁路，不驱逐全部缓存；
- reader/publisher 在分配完整 payload 前执行单资源大小限制；
- LRU 与统计更新在同一同步边界内。

## LocalAccessPolicy

路径正规化、root containment 与 symlink 判定由同一策略实现。Provider、
filehost 和模板 loader 不得各自复制白名单逻辑。`allow_any_path` 是显式危险
开关，默认关闭。

## ResourceStrategy

Provider 用不可变策略描述执行端需求：

- 本地 Playwright：`file` 或显式 publisher；
- 远程 Playwright：`memory`、共享卷 passthrough、filehost 或 error；
- Takumi：直接消费已物化 bytes；
- 第三方 Provider：组合已有 transport，不修改核心 reader。

策略不执行 I/O；composition 根据策略组装 materializer/publisher。
每次调用的 `ResourcePolicy` 优先于 Provider 默认 `resolve_mode`；未提供覆盖时，
Playwright 与 Takumi executor 都必须执行同一个默认值。`off` 调用不得在
executor 中退回到 transport policy 后隐式物化；若 transport 需要 publisher，
composition 仍需组装它，以兑现后续单次调用的 `auto` / `strict` 覆盖。

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
generation 竞争、byte budget/LRU、observer 隔离和两个 composition 隔离。
