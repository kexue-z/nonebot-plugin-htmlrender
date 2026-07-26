---
title: 资源、缓存与访问策略
description: 共享缓存、本地与远程访问策略及 filehost publisher
icon: lucide/database
---

# 资源、缓存与访问策略

资源配置属于 composition，由 Resource Service 统一实施；Provider 只能看到收窄的资源 façade 和不可变 transport 策略。缓存命中不会绕过授权。

## 资源缓存

| 路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.resources.cache.max_entries` | `256` | 共享 byte cache 条目上限，`0` 禁用 |
| `render.resources.cache.max_bytes` | `67108864` | 共享 byte budget，`0` 禁用 |
| `render.resources.cache.max_resource_bytes` | `67108864` | 单资源读取/发布上限，`0` 不限制 |
| `render.resources.cache.revalidate_seconds` | `1.0` | revision 复查与重读窗口 |
| `render.resources.templates.environment_cache_max_entries` | `64` | Jinja environment LRU 上限 |
| `render.resources.templates.environment_compiled_cache_size` | `256` | 单 environment 编译缓存上限 |
| `render.resources.traversal.max_nodes` | `10000` | 单次模板变量树的节点上限 |
| `render.resources.traversal.max_depth` | `64` | 单次模板变量树的容器嵌套上限 |
| `render.resources.traversal.max_concurrency` | `16` | composition 共享的资源叶节点 I/O 并发上限 |

缓存按 composition 隔离。filesystem 按 stat revision 复查，package/inline 使用稳定revision；remote ref 没有 revision 时会在窗口到期后重新读取。

公共 Resource Service 支持用 `read_bytes(..., refresh=True)` / `read_text(..., refresh=True)` 强制刷新单个 key，以及用 `await app.resources.clear()` 清空当前 Application 的 Resource Reader。后者不会清理 Jinja、filehost、Takumi 或 Playwright browser storage；完整操作示例和清理矩阵见[缓存组件、失效与调优](../guides/cache-lifecycle.md)。

模板变量会先经过有界、迭代式结构规划，再由固定数量 worker 解析其中的资源叶节点。循环引用、超深或超宽变量树会在执行资源 I/O 前以 `ResourceResolutionError` 拒绝；扩大限制时应同时评估模板输入可信度与 publisher 容量。

## 本地访问

默认拒绝所有本地路径。模板目录、Markdown/CSS 文件及本地依赖必须位于`render.resources.local_access.allowed_paths`；生产配置不得把 `/`、用户主目录或容器根加入白名单。`allow_any_path` 只适用于明确受控的环境。

## 远程访问

远程资源默认拒绝 loopback、链路本地、RFC1918 私网和保留网段；DNS 每次解析及每跳重定向都会重新校验，连接固定到已校验地址以抵御 DNS rebinding。仅支持 HTTP(S)。

`render.resources.remote_access` 可设置 host allow/deny list、最大重定向次数、端到端截止时间与独立抓取并发。deny list 优先；超时覆盖 DNS、全部重定向和正文读取，不会在每一跳重置。

## Filehost publisher

filehost transport 使用 `render.resources.filehost` 配置公开基址、容量、TTL、预热路径与请求头守卫。固定内部 mount 为 `/_htmlrender/assets/`；`public_base_url` 必须是执行端可访问的 HTTP(S) 集合基址，部署方负责反向代理映射。

路由由 htmlrender 自有的 `HostedAssetStore` 在插件初始化时安装，要求 NoneBot 使用FastAPI ASGI host。非 ASGI driver 或插件初始化后才选择 filehost 时无法补装路由，publisher startup 会以稳定的 `ProviderLifecycleError` 失败。

默认请求头守卫必须保持开启。CORS 只允许浏览器加载已授权资源，不承担认证职责。容量由 `max_entries` 与 `max_bytes` 约束；在途 lease 会钉住内容，全部条目被占用且超限时抛稳定 capacity error。

完整字段和值见[配置总览](../index.md)，远程浏览器 transport 选择见[远程 Playwright 部署](../remote-playwright/)，TTL、lease、预热和容量调优见[缓存组件、失效与调优](../guides/cache-lifecycle.md#filehost-publisher-and-hosted-store)。
