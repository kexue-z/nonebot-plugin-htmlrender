---
title: 远程 Playwright 与资源传输
description: WS/CDP 连接、typed Capability 与本地资源 transport
icon: lucide/cloud
---

# 远程 Playwright 与资源传输

调用侧始终使用同一 Playwright Capability；本地、WS 与 CDP 的差异只存在于
Provider 配置与资源 transport。

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

    CDP 用于连接现有 Chromium 实例，不支持 Firefox 或 WebKit。

!!! warning "连接配置互斥"

    `render.provider_config.connect_ws.endpoint` 与
    `render.provider_config.connect_cdp.endpoint` 不能同时设置；CDP 仅支持 Chromium。

## 页面操作

```python
from nonebot_plugin_htmlrender import get_default_application
from nonebot_plugin_htmlrender.capabilities import PLAYWRIGHT_CAPABILITIES

capability = get_default_application().capabilities.require(PLAYWRIGHT_CAPABILITIES)
async with capability.page(viewport={"width": 1280, "height": 800}) as page:
    await page.goto("https://example.com", wait_until="networkidle", timeout=30_000)
    raw = await page.screenshot(full_page=True, type="png")
```

Page 属于当前 lease；离开上下文后不可使用。

## 本地资源 transport

| 策略 | 适用场景 | 约束 |
| --- | --- | --- |
| `memory` | 默认远程部署 | asset 只活到单次操作结束，无共享磁盘要求 |
| `passthrough` | Bot 与浏览器有相同挂载点 | 两端路径必须完全一致 |
| `filehost` | 浏览器必须通过 HTTP 拉取资源 | 需要 `filehost` extra、路由、请求头保护与 CORS 响应 |
| `error` | 禁止本地资源 | 发现本地引用立即失败 |

`memory` 会读取受授权资源、按内容去重，并由 Page route 返回 bytes、正确媒体类型、
cache header 与 `Access-Control-Allow-Origin: *`。`passthrough` 不会上传文件；容器
路径不一致时必然失败。

## filehost

``` { .yaml .annotate }
render:
  provider: playwright
  provider_config:
    remote_local_resource_policy: filehost # (1)!
  resources:
    local_access:
      allowed_paths:
        - /app/assets # (2)!
    filehost:
      cache_ttl_seconds: 300 # (3)!
```

1. 选择真实 HTTP URL transport；通常仍应优先使用 render-scoped `memory`。
2. 只授权文档确实需要读取的最小目录。
3. TTL 管理 URL mapping，render lease 会钉住在途内容；它不承诺逐文件物理删除。

!!! warning "CORS 不承担授权"

    默认请求头守卫必须保持开启。反向代理需要向 Bot 透传守卫请求头，并向浏览器
    保留 `Access-Control-Allow-Origin` 响应头。认证成功的资源响应会携带
    `Access-Control-Allow-Origin: *`，使 `set_content()` 页面可以加载跨源字体；
    未通过请求头守卫的请求仍返回 403，且不携带通配 CORS 响应头。不要把该路由
    暴露为任意文件下载服务。

## 健康检查

`startup: probe` 会在 NoneBot 启动期验证连接。运行中可调用：

```python
from nonebot_plugin_htmlrender import get_default_application

await get_default_application().probe()
```

探测失败会以 `ProviderUnavailable` 或 `ProviderLifecycleError` 报告，不会返回
模糊的状态对象。

## 部署检查表

- Provider extra 与远程服务 Playwright 版本兼容；
- endpoint 不对不可信网络开放；
- CDP 服务启用网络隔离和认证；
- local access 白名单最小化；
- 远程默认使用 `memory`，共享卷才使用 `passthrough`；
- `goto` 目标经过 SSRF 策略校验；
- shutdown 能在有界时间内关闭连接并唤醒等待者。
