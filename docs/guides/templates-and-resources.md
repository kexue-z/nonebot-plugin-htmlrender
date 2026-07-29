---
title: 模板与资源
description: 组织 Jinja 模板、静态资源和可移植文档基址
icon: lucide/files
---

# 模板与资源

模板渲染分为 Preparation 与执行两个阶段。Preparation 读取模板及受策略允许的资源，生成中立 `PreparedHtml`；Provider 只负责执行已准备内容。

## 组织模板

把模板和它引用的静态资源放在同一受控目录，并将最小目录加入`render.resources.local_access.allowed_paths`。`template_base` 只负责相对路径定位，不会扩大本地访问白名单。

```python
from nonebot_plugin_htmlrender import render_template

image = await render_template(
    "templates",
    "profile.html",
    {"name": "Alice", "avatar": "assets/avatar.png"},
    width=720,
)
```

可运行项目见 `examples/template_render`。如果只需要 HTML，使用`render_template_html`，无需配置位图 Provider。

## 自定义 Jinja filter

通过 `filters` 为单次模板调用注入受信任的同步或异步 callable。filter 会在模板编译前进入对应 Jinja Environment；应复用模块级函数，使相同模板和 filter 组合能够命中 Environment cache：

```python
from nonebot_plugin_htmlrender import render_template

def format_percent(value: float) -> str:
    return f"{value:.1%}"

image = await render_template(
    "templates",
    "progress.html",
    {"progress": 0.625},
    filters={"percent": format_percent},
)
```

不要在循环中创建 lambda、`partial` 或临时 bound method；不同 callable 身份会生成不同 Environment key。同步 filter 在事件循环线程执行，不应包含阻塞 I/O。模板源码、filters 与 extensions 都是可执行的受信任代码，不能直接来自用户输入。

`render_template` 会先把变量中的 `Path`/bytes 准备成资源 URL，再调用 filter；`render_template_html` 不物化资源，filter 会看到原始变量。缓存 key、异步 filter 和失效边界见[缓存组件、失效与调优](cache-lifecycle.md#jinja-environment-and-custom-filters)。

## 预先解析变量

需要在模板外观察最终 URL 或 filehost 请求头时，使用`resolve_template_vars` 或 `to_resource_url`。它们返回 `ResourceResolution`；请求头只授权结果中对应的精确 URL，不得扩展到同 host、路径前缀或重定向目标。

```python
from nonebot_plugin_htmlrender import resolve_template_vars

result = await resolve_template_vars(
    {"avatar": "assets/avatar.png"},
    template_base="templates",
    strict=True,
)
variables = result.value
```

## 选择资源传输

本地 Provider 可直接读取受授权资源；远程 Playwright 默认使用单次操作内存桥。只有浏览器必须通过 HTTP 拉取资源时才选择 filehost，共享挂载路径完全一致时才选择passthrough。完整配置见[资源、缓存与访问策略](../configuration/resources.md)和[远程 Playwright 部署](../configuration/remote-playwright.md)。
