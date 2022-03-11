# nonebot-plugin-htmlrender

- 通过浏览器渲染图片
- 可通过查看`example`参考使用实例

# ✨ 功能

- 通过 html 和浏览器生成图片
- 支持`纯文本` `markdown` 和 `jinja2` 模板输入
- 通过 CSS 来控制样式

# 使用

参考[example/plugins/render/**init**.py](example/plugins/render/__init__.py)

## markdown 转 图片

- 使用 `GitHub-light` 样式
- 支持绝大部分 md 语法
- 代码高亮
- latex 数学公式 （感谢@[MeetWq](https://github.com/MeetWq)）
  - 使用 `$$...$$` 来输入独立公式
  - 使用 `$...$` 来输入行内公式
- 图片需要使用外部连接并使用`html`格式 否则文末会超出截图范围
- 图片可使用 md 语法 路径可为 `绝对路径`(建议), 或 `相对于template_path` 的路径

## 模板 转 图片

- 使用 jinja2 模板引擎
- 页面参数可自定义

# 🌰 栗子

[example.md](docs/example.md)

## 文本转图片（同时文本里面可以包括 html 图片）

![](docs/text2pic.png)

## markdown 转图片（同时文本里面可以包括 html 图片）

![](docs/md2pic.png)

## 纯 html 转图片

![](docs/html2pic.png)

## jinja2 模板转图片

![](docs/template2pic.png)

# 特别感谢

- [MeetWq](https://github.com/MeetWq) 提供数学公式支持代码和代码高亮

# 常见疑难杂症

## `playwright._impl._api_types.Error:` 初次运行时报错

- 一般为缺少必要的运行环境，如中文字体等

### Ubuntu 使用 `apt`

- 参考[Dao-bot Dockerfile](https://github.com/kexue-z/Dao-bot/blob/a7b35d6877b24b2bbd72039195bd1b3afebb5cf6/Dockerfile#L12-L15)

```sh
apt update && apt install -y locales locales-all fonts-noto \
    ibnss3-dev libxss1 libasound2 libxrandr2 \
    libatk1.0-0 libgtk-3-0 libgbm-dev libxshmfence1
```

### CentOS 使用 `yum`

- ~~小心 CentOS~~
- 参考[CentOS Dockerfile](https://github.com/kumaraditya303/playwright-centos/blob/master/Dockerfile)
- 添加中文字体库
- 最佳解决办法
  - 使用 Docker 然后用 Python 镜像 安装上面 Ubuntu 的写 `dockerfile`
