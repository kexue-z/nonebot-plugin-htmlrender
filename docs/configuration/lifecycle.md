---
title: 启动与生命周期
description: Provider 选择、启动策略、持久化目录与配置加载
icon: lucide/sliders-horizontal
---

# 启动与生命周期

| 路径 | 默认值 | 说明 |
| --- | --- | --- |
| `render.provider` | `null` | `htmlkit`、`playwright`、`takumi` 或第三方 Provider ID |
| `render.startup` | `off` | `off`、`warmup`、`probe` |
| `render.provider_config` | `{}` | 交给所选 Provider 的严格配置对象 |

`off` 只延迟运行时创建，不改变 API；第一次依赖 Provider runtime 的 Renderer 或Playwright/Takumi Capability 操作会按需启动。`warmup` 在 NoneBot startup 创建运行时，`probe` 还执行最小真实探测。

不选择 Provider 时，插件仍可运行 Preparation 与 `render_template_html`；需要位图执行器的调用得到 `CapabilityUnavailable`。Pillow/Skia `RasterScene` Capability不依赖 `render.provider`，由[`render.graphics`](../graphics/) 单独启用。

## 持久化目录

Playwright 未显式设置 `render.provider_config.storage_path` 时，会在插件数据目录保存浏览器文件和运行时快照。部署时应确保目录可写；需要独立卷或固定路径时显式设置`storage_path`。

## 配置形式

```yaml
render:
  provider: playwright
  startup: probe
  resources:
    local_access:
      allowed_paths:
        - /app/assets
```

```dotenv
RENDER={"provider":"playwright","startup":"probe","resources":{"local_access":{"allowed_paths":["/app/assets"]}}}
```

资源限制见[资源、缓存与访问策略](resources.md)，从 0.7 升级时不要混用旧键，详见 [v0.8 迁移指南](../../guides/migration/v0.8.md)。
