---
title: 远程 Playwright 部署
description: WS/CDP 连接、本地资源传输、filehost 与健康检查
icon: lucide/cloud
---

# 远程 Playwright 部署

调用侧始终使用同一 Playwright Capability；本地、WS 与 CDP 的差异只存在于Provider 配置与资源 transport。

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

## 本地资源 transport

| 策略 | 适用场景 | 约束 |
| --- | --- | --- |
| `memory` | 默认远程部署 | asset 只活到单次操作结束，无共享磁盘要求 |
| `passthrough` | Bot 与浏览器有相同挂载点 | 两端路径必须完全一致 |
| `filehost` | 浏览器必须通过 HTTP 拉取资源 | 需要路由、请求头保护与 CORS 响应 |
| `error` | 禁止本地资源 | 发现本地引用立即失败 |

`memory` 读取受授权资源、按内容去重，并由 Page route 返回 bytes、媒体类型、cache
header 与 CORS 响应。`passthrough` 不上传文件；容器路径不一致时必然失败。

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

`startup: probe` 在 NoneBot 启动期验证连接；运行中可调用`await get_default_application().probe()`。部署还需确认：

- Provider extra 与远程服务 Playwright 版本兼容；
- endpoint 不向不可信网络开放，CDP 服务具备网络隔离和认证；
- local access 白名单最小化，默认使用 `memory`；
- 导航目标遵守 SSRF 策略；
- shutdown 能在有界时间内关闭连接并唤醒等待者。
