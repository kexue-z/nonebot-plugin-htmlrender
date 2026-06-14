---
title: 最佳实践
description: 基于 examples 示例项目的上手建议与常见模式
icon: lucide/lightbulb
status: new
tags:
  - Users
  - Best Practices
---

# 最佳实践

这页面向刚接触本插件的同学，内容基于仓库 `examples/` 下的三个独立示例项目：

- `examples/screenshot/`：网页截图与元素截图；
- `examples/template_render/`：本地模板渲染与纯文本渲染；
- `examples/remote_browser/`：远程浏览器渲染。

如果你是第一次接入，建议按明确的接入顺序推进，而不是一开始就把远程浏览器、模板资源、外部字体和复杂交互全部堆进同一条链路。

## 从最小可用开始

推荐第一步先实现一个最简单命令，只调用一个 API（例如 `render_text`）：

```python
from nonebot import on_command, require
from nonebot.adapters.onebot.v11 import Bot, MessageEvent, MessageSegment
from nonebot_plugin_htmlrender import render_text

require("nonebot_plugin_htmlrender")

cmd = on_command("render_text")

@cmd.handle()
async def _(bot: Bot, event: MessageEvent) -> None:
    text = str(event.get_message()).strip() or "Hello, HTMLRender!"
    image = await render_text(text)
    await cmd.finish(MessageSegment.image(image))
```

先确保这条链路稳定，再扩展 Markdown、模板、资源解析等能力。

## 推荐的能力接入顺序

参考 `examples/template_render/` 与 `examples/screenshot/`，建议按这个顺序逐步添加：

1. `list_render_backend_statuses`：先确认后端状态可读（示例中包装为 `render_status` 命令）。
2. `render_text`：最快拿到第一张图。
3. `render_markdown`：引入样式和内容结构。
4. `get_render_context`：需要精细控制页面行为时再用。
5. `render_template`：适合业务页面和可复用布局。
6. `render_template + filters`：最后再引入模板过滤器。

这个顺序的好处是：每一步都可独立验证，定位问题时更容易。

## 目录与资源组织建议

模板示例给出了一个对初学者友好的结构：

- `examples/template_render/plugins/template_render/templates/`：模板与 CSS 放一起。
- `examples/template_render/plugins/template_render/__init__.py`：命令 handler 与渲染调用入口。
- `examples/screenshot/plugins/screenshot/__init__.py`：需要直接操作页面时的 `get_render_context` 示例。

实际项目里也建议保持同样思路：  
“模板/CSS/工具函数”分目录管理，尽量避免把所有逻辑写在一个 handler 里。

## 示例验证方式

当前示例项目更偏“可复制到 Bot 中运行”的集成示例。若要验证核心行为，请优先跑仓库测试：

```bash
make test-ci
```

涉及真实浏览器行为时，先安装项目本地浏览器，再跑 local profile：

```bash
make install-browser
make test-local
```

## 两条很实用的小技巧

### 1) 本地预览产物先落盘

调模板时建议先在业务代码里临时把渲染结果写成 `png`，这对排查样式问题非常有帮助。  
确认模板稳定后，再把结果直接发送到聊天消息里。

### 2) `get_render_context` 只在必要时使用

`get_render_context` 很强，但也更偏底层。  
如果你只是“输入文本/模板 -> 输出图片”，优先用 `render_*` API。  
只有在你需要自己控制 `page.goto`、`page.screenshot` 等步骤时，再切到 context 模式。

## 并发与会话复用

- 默认优先复用 `Render` 持有的 runtime 与 session，不要在业务层自己反复重建浏览器
- 高频调用时优先复用默认实例，避免手动在每次请求里显式 `startup_render()` / `shutdown_render()`
- 真正需要限制并发时，在业务层做任务队列或 semaphore，不要靠“每次都重启浏览器”来规避竞争

## 长文与长页面截图

- 长 Markdown 或长 HTML 页面优先保留 `full_page=True`
- 页面依赖异步资源时，优先用 `wait` 或自定义 page 行为补稳定等待，而不是单纯把 timeout 拉得很大
- 超长页面如果单张图不可读，应在业务层做分页或分段渲染，而不是强行输出一张极长截图

## 模板、字体与静态资源

- 模板目录、CSS、图片、字体尽量放在同一棵静态资源树下
- 本地模式可直接使用 `file://` 资源；远程模式优先走资源解析与 filehost，不要假定远端能直接访问本地路径
- 容器或远端浏览器环境中，CJK 字体和 emoji 字体要显式安装；不要把“本机能显示”当成可部署结论

## 远程模式的资源边界

- 远程浏览器只适合访问它自己网络环境里可达的 HTTP(S) 资源
- 只要模板里引用本地图片、CSS、字体或相对路径资源，就应评估 `resolve_resources=True` 与 filehost
- 非必要不要在远程模式下继续使用 `file://` base URL；优先 `about:blank` 或显式 HTTP(S) base URL

## 接入节奏示例

1. 先参考 `examples/template_render/` 中的纯文本渲染命令。
2. 把它改成你自己的命令名和业务文本。
3. 加入 `render_markdown` 命令并验证样式。
4. 再接入 `render_template`，把页面结构沉淀为模板。
5. 需要网页截图时参考 `examples/screenshot/`。
6. 最后视需求接入远程 Playwright / filehost，参考 `examples/remote_browser/`。

做到这一步，你的渲染层通常已经足够稳定，也便于团队继续维护。
