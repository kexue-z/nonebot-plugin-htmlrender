---
title: v0.7.2 迁移说明
description: 从 v0.7.1 升级到 v0.7.2 时需要了解的远程 Markdown 修复
icon: lucide/bug-off
tags:
  - Users
  - Migration
  - Release
---

# v0.7.2 迁移说明

v0.7.2 是面向远程 Playwright 部署的兼容性修复版本，不包含公共 API 或配置项变更。

## 修复内容

使用远程 Playwright 渲染 Markdown 时，默认模板此前会让远端浏览器导航到 Bot
进程所在主机的 `file://` 地址。浏览器与 Bot 不共享文件系统时，该地址不可达，
渲染会以 `ERR_FILE_NOT_FOUND` 失败。

v0.7.2 在远程模式下直接通过 `page.set_content()` 注入默认 Markdown HTML，
不再导航到本地模板文件。自定义的 HTTP(S) 基址和显式传入的渲染配置保持原有行为。

## 是否需要修改配置

通常不需要。符合以下条件的部署可直接升级：

- 使用 Playwright WS 或 CDP 连接远端浏览器；
- 调用 `render_markdown` 或兼容入口 `md_to_pic`；
- 使用内置 Markdown 模板和样式。

若 Markdown 引用了本地图片、字体或其他静态资源，仍需确保远端浏览器能够访问这些
资源；本次修复只消除了默认模板文件本身的跨主机 `file://` 导航。

## 升级后验证

在实际远程浏览器环境执行一次最小渲染即可：

```python
from nonebot_plugin_htmlrender import render_markdown

image = await render_markdown("# remote markdown")
assert image
```

本地 Playwright、HTML 渲染和模板渲染行为不受影响。
