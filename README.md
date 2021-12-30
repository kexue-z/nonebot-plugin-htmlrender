# nonebot-plugin-htmlrender

* 通过浏览器渲染图片
* 可通过查看`example`参考使用实例

# ✨ 功能

* 通过html和浏览器生成图片
* 支持`纯文本` `markdown` 和 `jinja2` 模板输入 
* 通过 CSS 来控制样式



# 使用

参考[example/plugins/render/__init__.py](example/plugins/render/__init__.py)

## markdown 转 图片

- 使用 `GitHub-light` 样式
- 支持绝大部分 md 语法
- 代码高亮
- latex 数学公式 （感谢@[MeetWq](https://github.com/MeetWq)）
    - 使用 `$$...$$` 来输入独立公式
    - 使用 `$...$` 来输入行内公式

# 🌰 栗子

[example.md](docs/example.md)
## 文本转图片（同时文本里面可以包括html图片）
![](docs/text2pic.png)

## markdown转图片（同时文本里面可以包括html图片）
![](docs/md2pic.png)

## 纯html转图片
![](docs/html2pic.png)

## jinja2模板转图片
![](docs/template2pic2pic.png)


# 特别感谢

- [MeetWq](https://github.com/MeetWq) 提供数学公式支持代码和代码高亮