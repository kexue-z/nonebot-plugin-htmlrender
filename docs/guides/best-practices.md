---
title: 最佳实践
description: 稳定 API、资源策略、错误与生命周期建议
icon: lucide/badge-check
---

# 最佳实践

## 优先使用通用 API

内容到图片优先使用 `render_*`；只有导航、selector、node、SVG 等确实依赖引擎的操作才获取 typed Capability。这样更换 Provider 时，Preparation 与业务代码保持不变。

## 在边界转换 typed artifact

```python
artifact = await render_markdown(text)
await matcher.finish(UniMessage(Image(raw=bytes(artifact))))
```

不要把 `RenderedImage` 当作 `bytes` 透传，也不要过早丢弃`media_type`、format 和尺寸。

## 明确资源策略

- 受控模板可使用 `ResourcePolicy.AUTO`。
- 构建期或安全敏感任务使用 `ResourcePolicy.STRICT`，让缺失资源直接失败。
- 确定无需本地物化时使用 `ResourcePolicy.OFF`。
- `allowed_paths` 只加入最小目录；生产环境保持 `allow_any_path: false`。
- 远程 Playwright 默认使用 `memory` transport，除非部署已显式共享卷。

## 对完整操作设置超时

```python
artifact = await render_html(html, timeout_seconds=15)
```

超时应覆盖 Preparation、lease 获取与执行，而不是只给某个页面步骤设置值。使用 raw Playwright Page 时，仍应给 `goto` 等外部网络操作设置独立超时。

## 按稳定错误分类

```python
from nonebot.log import logger

from nonebot_plugin_htmlrender import (
    CapabilityUnavailable,
    ProviderUnavailable,
    RenderingError,
    ResourceResolutionError,
)

try:
    artifact = await render_markdown(text)
except ResourceResolutionError:
    ...
except (ProviderUnavailable, CapabilityUnavailable):
    ...
except RenderingError as error:
    logger.warning("{}: {}", type(error).__name__, error.message)
    for cause in error.causes:
        logger.debug(
            "cause={} truncated={}",
            cause.exception_type,
            cause.truncated,
        )
```

不要依赖 HTMLKit/Playwright/Takumi 内部异常作为跨版本业务契约，也不要解析`str(error)` 做程序分支。`message` 和 `causes` 已有界裁剪，但不替代业务脱敏；`cause.message` 只应在完成过滤后进入外部日志。对无法由选定 Provider 准确表达的通用选项，捕获稳定的`UnsupportedRenderOption`，不要自行猜测降级后的尺寸或 DPR。

## 让 bootstrap 管理默认生命周期

常规 NoneBot 插件不要自行关闭默认 `Application`。独立 composition、测试或脚本应配对 `startup()` / `aclose()`；关闭后新建 composition，而不是复用。

## 保存 access，不保存 lease 产物

`app.extensions.playwright`、`.takumi`、`.pillow` 与 `.skia` access 可以按需重新获取；不要让 Playwright Page/Browser/BrowserContext、Takumi API、compiled 对象或原生 Renderer 逃逸出创建它们的异步上下文。Provider 重建后重新进入对应上下文。

## 不在日志中记录内容

只记录 operation、Provider ID、稳定错误类别与 request ID。不要记录 HTML、URL、路径、模板变量、headers、asset bytes 或资源 digest。
