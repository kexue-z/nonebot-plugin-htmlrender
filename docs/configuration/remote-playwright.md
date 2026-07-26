---
title: 远程 Playwright 部署
description: WS/CDP 连接、本地资源传输、filehost 与健康检查
icon: lucide/cloud
---

# 远程 Playwright 部署

调用侧始终使用同一 Playwright Capability；本地、WS 与 CDP 的差异只存在于Provider 配置与资源 transport。

!!! tip "生产部署首选"

    首选在独立 Docker 容器中运行版本匹配的 Playwright WS 服务，再由 Bot 容器或宿主机通过私有容器网络连接。这样浏览器二进制、系统依赖和进程生命周期不会污染 Bot 宿主机。直接在 Bot 宿主机启动浏览器是第二选项，主要用于本地开发、单机环境或无法增加独立服务的部署。

## Docker 拓扑

推荐拓扑包含两个职责单一的服务：

| 服务 | 安装内容 | 网络职责 |
| --- | --- | --- |
| Bot | `nonebot-plugin-htmlrender[playwright]`，不安装本地浏览器 | 作为 Playwright client 主动连接 WS endpoint |
| Playwright | 与 Bot lockfile 版本匹配的浏览器、Playwright server 与系统依赖 | 只在私有容器网络暴露 WS 端口 |

Playwright 官方镜像包含浏览器和系统依赖，但不包含项目的 Python package。构建服务镜像时必须把镜像 tag 和 server package 固定到 Bot lockfile 解析出的同一 Playwright 版本；不要使用 `latest`。除非外部 client 必须访问，否则只使用 Compose `expose`，不要把 WS 端口发布到宿主机或公网。官方镜像内容与版本要求见 [Playwright Docker 说明](https://playwright.dev/python/docs/docker/)。

## 连接远程浏览器

=== "WS"

    ```yaml
    render:
      provider: playwright
      startup: probe
      provider_config:
        engine: chromium
        connect_ws:
          endpoint: ws://playwright:3000/
        remote_local_resource_policy: memory
    ```

    WS 使用 Playwright 协议，可连接 `playwright run-server` 或匹配版本的服务。

=== "CDP"

    ```yaml
    render:
      provider: playwright
      startup: probe
      provider_config:
        engine: chromium
        connect_cdp:
          endpoint: http://chromium:9222/
        remote_local_resource_policy: memory
    ```

    CDP 用于现有 Chromium 实例，不支持 Firefox 或 WebKit。

`connect_ws.endpoint` 与 `connect_cdp.endpoint` 互斥。页面导航和截图调用见[操作浏览器页面](../../guides/browser-automation.md)。

## WS 版本门禁与启动探测 { #ws-version-gate-and-startup-probe }

WS 模式会在建立 Playwright 协议连接前执行 client/server 版本门禁。门禁优先从 endpoint 的 `playwright_version`、`pw_version`、`version` 参数或路径提取版本；无法取得时，再以有界 HTTP 请求探测同源的 `/json/version` 与 `/`。

当前门禁是风险分级，不是版本强等于：

| client/server 差异 | 行为 |
| --- | --- |
| major 不同，或 minor 相差至少 2 | `BLOCK`，拒绝连接 |
| minor 相差 1 | `WARNING`，记录警告后继续 |
| minor 相同、patch 相差超过 10 | `WARNING`，记录警告后继续 |
| 其余可识别版本 | `SAFE`，继续连接 |
| 无法识别远端版本 | 记录警告并继续；版本门禁 fail-open |

门禁通过后仍需由 `BrowserType.connect()` 完成真实协议握手。配置 `startup: probe` 还会在启动期取得一个 Browser lease 并创建 Page，可以提前暴露连接成功但实际浏览器不可用的问题。三者共同提供早期诊断，但软门禁不能证明任意版本组合兼容，也不能替代部署时的精确锁定。

CDP 模式不执行 Playwright client/server 版本门禁；它只校验 endpoint、限制 `engine: chromium`，再通过实际 CDP 连接与 `startup: probe` 验证可用性。

因此 Docker WS 服务仍应把 server 镜像 tag、server package 与 Bot lockfile 解析出的 Playwright client 固定到同一版本。版本门禁是误配置保护，不是允许使用浮动 tag 或放宽版本约束的兼容性承诺。

## 本地资源 transport

| 策略 | 适用场景 | 约束 |
| --- | --- | --- |
| `memory` | 默认远程部署 | asset 只活到单次操作结束，无共享磁盘要求 |
| `passthrough` | Bot 与浏览器有相同挂载点 | 两端路径必须完全一致 |
| `filehost` | 浏览器必须通过 HTTP 拉取资源 | 需要路由、请求头保护与 CORS 响应 |
| `error` | 禁止本地资源 | 发现本地引用立即失败 |

`memory` 读取受授权资源、按内容去重，并由 Page route 返回 bytes、媒体类型、cache
header 与 CORS 响应。`passthrough` 不上传文件；容器路径不一致时必然失败。

`memory` asset 只存活于当前 render lease，不是跨调用 cache。filehost 的 content-addressed mapping、TTL、预热、hosted store LRU 与 lease 钉住语义见[缓存组件、失效与调优](../guides/cache-lifecycle.md#filehost-publisher-and-hosted-store)。

## Filehost

```yaml
render:
  provider: playwright
  provider_config:
    remote_local_resource_policy: filehost
  resources:
    local_access:
      allowed_paths:
        - /app/assets
    filehost:
      public_base_url: https://bot.example/
      cache_ttl_seconds: 300
```

请求头守卫必须保持开启。反向代理向 Bot 透传守卫请求头，并保留资源响应的 CORS
header；CORS 不承担授权。完整容量与访问策略见[资源、缓存与访问策略](resources.md)。

## 健康检查与部署检查表

`startup: probe` 在 NoneBot 启动期验证连接并创建 Page；运行中可调用`await get_default_application().probe()`。部署还需确认：

- Provider extra 与远程服务 Playwright 精确锁定到同一版本，不以软版本门禁代替依赖管理；
- endpoint 不向不可信网络开放，CDP 服务具备网络隔离和认证；
- local access 白名单最小化，默认使用 `memory`；
- 导航目标遵守 SSRF 策略；
- shutdown 能在有界时间内关闭连接并唤醒等待者。
