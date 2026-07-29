# 网页截图示例

展示如何获取类型化 Playwright Capability，并直接使用 Playwright 原生 `Page` 与`Locator` API 截取网页或指定元素。`Page` 仅在 `page()` 异步上下文内有效，原生调用保留 Playwright 自身异常。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/screenshot [url]` | 截取完整网页，默认访问 `https://github.com` |
| `/capture <selector>` | 截取 GitHub 页面中的指定 CSS selector |

## 安装与配置

```bash
nb create  # 创建 NoneBot 项目并选择 OneBot V11 adapter
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0,<0.9"
uv add nonebot-plugin-alconna
```

复制 `plugins/screenshot` 到项目插件目录。

在 `.env` 中写入：

```dotenv
RENDER={"provider":"playwright","startup":"probe"}
```

示例直接接受调用方提供的 URL，只适合受信任环境。生产环境必须为 scheme、host 与port 建立 allowlist，并在容器或网络层限制 egress；`resource_policy` 不提供导航SSRF 防护。
