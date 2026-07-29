# 本地模板渲染示例

展示如何通过引擎中立的 `render_template` 与 `render_text` API，将本地 HTML/CSS模板渲染为图片。示例显式使用 `height=None` 与 `device_pixel_ratio=1.0`，因此可以在 Playwright、Takumi 和 HTMLKit 三个静态 HTML Provider 之间切换。

## 命令

| 命令 | 说明 |
|---|---|
| `/profile [username]` | 使用 Jinja2 模板渲染用户卡片 |
| `/textimg <content>` | 将纯文本渲染为图片 |

## 安装

```bash
nb create  # 创建 NoneBot 项目并选择 OneBot V11 adapter
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0,<0.9"
uv add nonebot-plugin-alconna
```

复制 `plugins/template_render` 目录及其 `templates/` 子目录到项目的插件目录。

默认使用 Playwright：

```dotenv
RENDER={"provider":"playwright","startup":"probe","resources":{"local_access":{"allowed_paths":["plugins/template_render/templates"]}}}
```

也可以安装并选择 Takumi：

```bash
uv add "nonebot-plugin-htmlrender[takumi]>=0.8.0,<0.9"
```

```dotenv
RENDER={"provider":"takumi","startup":"probe","resources":{"local_access":{"allowed_paths":["plugins/template_render/templates"]}}}
```

或选择实验性的 HTMLKit：

```bash
uv add "nonebot-plugin-htmlrender[htmlkit]>=0.8.0,<0.9"
```

```dotenv
RENDER={"provider":"htmlkit","startup":"probe","resources":{"local_access":{"allowed_paths":["plugins/template_render/templates"]}},"provider_config":{"resource_resolve_mode":"strict"}}
```

HTMLKit 不是浏览器的等价替代，只适合其支持范围内的静态 HTML/CSS；需要脚本、网页导航、selector 或精确浏览器布局语义时仍应使用 Playwright。

## 模板结构

```text
plugins/template_render/
  __init__.py
  templates/
    profile.html    # Jinja2 template
    style.css       # Template stylesheet
```

模板变量通过 `render_template(..., variables=...)` 传入。返回值是`RenderedImage`；交给消息 adapter 前使用 `bytes(artifact)` 显式取得编码后的图片。
