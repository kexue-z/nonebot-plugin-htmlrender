---
title: 基础配置与加载
description: Provider 选择、启动策略、资源缓存与本地访问
icon: lucide/sliders-horizontal
---

# 基础配置与加载

## Provider 与启动

| 路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.provider` | `null` | `htmlkit`、`playwright`、`takumi` 或第三方 Provider ID |
| `render.startup` | `off` | `off`、`warmup`、`probe` |
| `render.provider_config` | `{}` | 交给已选择 Provider 的配置对象 |

`off` 只延迟运行时创建，不会改变 API；第一次位图操作会按需启动。
`warmup` 在 NoneBot startup 创建运行时，`probe` 还会做最小真实探测。

不选择 Provider 时，插件仍可加载并运行 Preparation 与
`render_template_html`；需要位图执行器的调用会得到 `CapabilityUnavailable`。
独立的 Pillow/Skia `RasterScene` Capability 不依赖 `render.provider`，由
[`render.graphics`](graphics.md) 单独启用。

## 持久化目录

Playwright 未显式设置 `render.provider_config.storage_path` 时，会在插件数据目录中
保存浏览器文件和运行时快照。部署时应确保该目录可写；需要使用独立卷或固定路径时，
请显式设置 `storage_path`。

## 资源缓存

| 路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.resources.cache.max_entries` | `256` | 共享 byte cache 条目上限，`0` 禁用 |
| `render.resources.cache.max_bytes` | `67108864` | 共享 byte budget，`0` 禁用 |
| `render.resources.cache.max_resource_bytes` | `67108864` | 单个资源读取/发布上限，`0` 表示不限制 |
| `render.resources.cache.revalidate_seconds` | `1.0` | cached resource 的 revision 复查/重读窗口 |
| `render.resources.templates.environment_cache_max_entries` | `64` | Jinja environment LRU 上限 |

缓存按 composition 隔离，命中不会绕过路径授权。filesystem 按 stat revision
复查，package/inline 使用稳定 revision；remote ref 没有可用 revision 时会在
窗口到期后重新读取。

## 本地访问策略

| 路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.resources.local_access.allow_any_path` | `false` | 是否允许访问任意本地路径 |
| `render.resources.local_access.allowed_paths` | `[]` | 额外允许的目录根 |

默认拒绝所有本地路径；模板目录、Markdown/CSS 文件及其本地依赖都必须落在
`allowed_paths` 内。白名单应使用最小目录，不要把 `/`、用户主目录或容器根
加入生产配置。

## 远程访问策略

| 路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.resources.remote_access.allow_private_networks` | `false` | 是否放行 loopback / 链路本地 / 私网段目标 |
| `render.resources.remote_access.allow_hosts` | `[]` | 允许绕过私网封锁的 host 白名单（含子域） |
| `render.resources.remote_access.deny_hosts` | `[]` | 始终拒绝的 host 黑名单，优先级最高 |
| `render.resources.remote_access.max_redirects` | `5` | 远程抓取允许的最大重定向次数 |

远程资源默认拒绝解析到 loopback、链路本地（含云 metadata `169.254.169.254`）、
RFC1918 私网及保留网段的目标；DNS 每次解析与每一跳重定向都会重新校验，
连接固定在通过校验的地址上以抵御 DNS rebinding。仅 `http`/`https` scheme
可用。需要访问内网资源时把具体 host 加入 `allow_hosts`。

## Filehost publisher

这些核心字段仅在 ResourceStrategy 选择 filehost publisher 时生效：

| 路径 | 默认值 |
| --- | --- |
| `render.resources.filehost.cache_ttl_seconds` | `300.0` |
| `render.resources.filehost.prewarm_enabled` | `true` |
| `render.resources.filehost.prewarm_max_files` | `256` |
| `render.resources.filehost.prewarm_paths` | `[]` |
| `render.resources.filehost.prewarm_extensions` | `[]` |
| `render.resources.filehost.request_header_name` | `X-HTMLRender-Filehost-Request` |
| `render.resources.filehost.request_header_value` | `null` |
| `render.resources.filehost.request_header_salt` | 内置稳定值 |

Resource Service 拥有 publisher 配置，Provider 只返回不可变的 transport 策略。

## 配置形式

YAML：

```yaml
render:
  provider: playwright
  startup: probe
  resources:
    local_access:
      allowed_paths:
        - /app/assets
    filehost:
      prewarm_paths:
        - /app/assets
```

Dotenv：

```dotenv
RENDER={"provider":"playwright","startup":"probe","resources":{"local_access":{"allowed_paths":["/app/assets"]},"filehost":{"prewarm_paths":["/app/assets"]}}}
```

从 0.7 升级时不要混用旧键；详见 [v0.8 迁移指南](../migration-v080.md)。
