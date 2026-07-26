---
title: Preparation 与资源 API
description: 中立文档准备、PreparedHtml 与资源辅助函数
icon: lucide/file-input
---

# Preparation 与资源 API

Preparation 不执行位图渲染，可用于检查或复用后端中立文档。

```python
from nonebot_plugin_htmlrender import RasterOptions, prepare_html, rasterize_html

prepared = prepare_html(
    "<img src='avatar.png'>",
    base_url="https://static.example/assets/",
)
artifact = await rasterize_html(
    prepared,
    RasterOptions(width=480, device_pixel_ratio=2),
)
```

`prepare_text`、`prepare_markdown`、`prepare_template` 是异步函数；`PreparedHtml` 由 HTML、stylesheets、assets、requirements、`document_base` 与`structure` 组成。`DocumentBase.declared_href` 为 `None` 表示未声明 `<base href>`，空字符串表示显式 `<base href="">`。0.8 起 `PreparedHtml` 只能经 `prepare_*`工厂构造，不接受手工拼装的不一致 IR。

其中 `PreparedStylesheet` 保存 CSS、独立的资源基址、嵌入状态与 media 条件；`PreparedAsset` 保存按文档 URL 精确寻址的不可变 bytes 与可选 media type。它们是`PreparedHtml` 的只读组成部分，不是另一组执行入口。

`prepare_markdown(markdown=..., resource_policy=...)` 与渲染 API 使用同一`ResourcePolicy` 语义。

## 资源辅助函数

`resolve_template_vars` 递归解析映射和序列中的路径或 bytes，`to_resource_url`处理单个值。两者均为异步函数，并返回 `ResourceResolution[T]`：`.value` 是解析后的值，`.request_headers_by_url` 按最终 URL 精确携带 filehost 请求授权。

```python
from nonebot_plugin_htmlrender import resolve_template_vars, to_resource_url

variables_result = await resolve_template_vars(
    {"avatar": "assets/avatar.png"},
    template_base="templates",
    strict=True,
)
variables = variables_result.value

logo_result = await to_resource_url(
    "assets/logo.svg",
    template_base="templates",
    strict=True,
)
logo_url = logo_result.value
logo_headers = logo_result.request_headers_by_url.get(logo_url, {})
```

非 filehost transport 的授权映射为空；调用方不得把一条 URL 的 header 扩大到同 host、同路径前缀或重定向目标。`template_base` 不扩张本地访问白名单。`strict=None` 继承组合策略，`False` 采用宽松解析，`True` 在任一资源失败时终止。

需要直接读取并立即刷新单个资源时，使用`get_default_application().resources.read_bytes(..., refresh=True)` 或 `.read_text(..., refresh=True)`；这与递归解析模板变量是不同操作。缓存驻留与 clear 边界见[缓存组件、失效与调优](../guides/cache-lifecycle.md#resource-reader)。

资源策略和部署配置见[资源、缓存与访问策略](../configuration/resources.md)。
