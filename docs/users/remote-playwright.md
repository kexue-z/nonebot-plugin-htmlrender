---
title: 远程渲染与 Filehost
description: 远程连接模式、资源可达性与 filehost 的完整说明
icon: lucide/cloud-cog
status: new
tags:
  - Users
  - Remote
---

# 远程渲染与 Filehost

远程模式下，模板 HTML 仍在本地进程生成，但页面请求发生在远端浏览器所在的网络环境。  
这意味着“本地能读到的路径”与“远端浏览器能访问到的资源”是两回事。

最重要的结论：

- 远程模式下不要默认假设 `file://` 资源可用
- 模板里只要引用本地图片、CSS、字体或相对路径资源，就应评估资源解析与 filehost

## 三种部署形态怎么选

| 形态 | 浏览器位置 | 适用场景 | 本地资源处理 |
| --- | --- | --- | --- |
| 本地 Playwright | 与业务进程同机 | 单机部署、调试、简单接入 | 可直接走 `file://` |
| 远程 Playwright（WS） | Playwright Server | 需要完整 Playwright 能力、多 Bot 共用浏览器 | 本地资源通常需解析 |
| 远程浏览器（CDP）+ filehost | 远端 Chromium | 已有 CDP 基础设施、容器化部署 | 本地资源通常需解析 |

## 两种远程形式

### 远程 Playwright（WS）

=== "Dotenv"

    ```dotenv
    RENDER_PLAYWRIGHT={"connect_ws":{"endpoint":"ws://127.0.0.1:3000/"}}
    ```

=== "nonebot.init"

    ```python
    import nonebot

    nonebot.init(
        render_playwright={
            "connect_ws": {"endpoint": "ws://127.0.0.1:3000/"},
        }
    )
    ```

### 远程浏览器（CDP）

=== "Dotenv"

    ```dotenv
    RENDER_PLAYWRIGHT={"connect_cdp":{"endpoint":"http://127.0.0.1:9222/"}}
    ```

=== "nonebot.init"

    ```python
    import nonebot

    nonebot.init(
        render_playwright={
            "connect_cdp": {"endpoint": "http://127.0.0.1:9222/"},
        }
    )
    ```

## 差异与选型

| 维度 | 远程 Playwright（WS） | 远程浏览器（CDP） |
| --- | --- | --- |
| 连接方式 | `browser_type.connect()` | `browser_type.connect_over_cdp()` |
| 目标端 | Playwright Server | Chromium DevTools Endpoint |
| 引擎限制 | 跟随 Playwright 服务端能力 | 仅 Chromium 系 |
| 推荐场景 | 统一 Playwright 协议与能力 | 已有 CDP 基础设施/运维体系 |

## 为什么远程模式下 `file://` 经常失效

- 模板 HTML 是在本地渲染的
- 浏览器请求是在远端发出的
- 本地机器上的绝对路径，对远端机器通常不存在

因此远程模式下更稳的做法是：

- 页面 `base_url` 优先用 `about:blank` 或可访问的 HTTP(S) URL
- 本地静态资源通过资源解析转换为远端可访问 URL

## 资源解析推荐配置

无论 WS 还是 CDP，只要远端无法访问本地路径，都建议开启：

=== "Dotenv"

    ```dotenv
    RENDER_PLAYWRIGHT={"resource_resolve_mode":"auto","remote_local_resource_policy":"filehost"}
    ```

=== "nonebot.init"

    ```python
    import nonebot

    nonebot.init(
        render_playwright={
            "resource_resolve_mode": "auto",
            "remote_local_resource_policy": "filehost",
        }
    )
    ```

## 资源解析行为矩阵

### 全局开关

| 配置 | 含义 |
| --- | --- |
| `resource_resolve_mode=off` | 默认不解析资源 |
| `resource_resolve_mode=auto` | 按本地/远程策略自动解析 |
| `resource_resolve_mode=strict` | 行为同 auto，但失败默认按严格模式处理 |

### 远程模式下本地资源策略

| `remote_local_resource_policy` | 行为 |
| --- | --- |
| `passthrough` | 原值透传，远端是否能访问由部署环境自行决定 |
| `filehost` | 本地资源转 filehost URL，推荐远程主路径 |
| `error` | 发现本地资源直接报错 |

### 本地模式下本地资源策略

| `local_local_resource_policy` | 行为 |
| --- | --- |
| `file` | 把本地路径转为 `file://`，本地主路径默认选择 |
| `filehost` | 本地模式也强制走 filehost |
| `passthrough` | 原值透传 |

## 调用参数与全局配置的关系

- `resolve_resources=True`：本次调用显式开启资源解析
- `resolve_resources=False`：本次调用显式关闭资源解析
- `resolve_resources=None`：跟随全局 `resource_resolve_mode`
- `resource_resolver="filehost"`：本次调用强制使用 filehost 策略
- `resource_strict=True`：本次调用解析失败直接抛错

## 推荐调用

```python
img = await render_template(
    "templates",
    template_name="card.html",
    templates={"avatar": "assets/avatar.png"},
    resolve_resources=True,
    pages={"base_url": "about:blank"},
)
```

这里的 `about:blank` 不是装饰项，而是远程模式下的推荐默认值：  
它避免了把模板目录硬编码成远端通常不可达的 `file://` base URL。

## PNA 预检查

- `resource_strict=True`：预检查失败直接报错
- `resource_strict=False`：记录 warning 并继续

## 相关页面

- 资源安全边界见 [安全须知](security.md)
- 报错与排障见 [故障排查](troubleshooting.md)
- filehost 与请求头守卫的实现细节见维护者文档 [Filehost 资源解析方案](../maintainers/architecture/filehost-resource-resolution.md)
