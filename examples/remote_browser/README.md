# 远程 Playwright Provider 示例

展示如何通过 CDP 或 WebSocket endpoint 连接远程 Playwright 浏览器并执行渲染。

适用于 Bot 主机不安装浏览器，或由多个 Bot 共享独立浏览器服务的部署。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/render_status` | 探测当前 Provider 并列出 Capability |
| `/rshot [url]` | 通过远程浏览器截取完整网页，默认访问 `https://github.com` |
| `/rmd <markdown>` | 通过远程浏览器把 Markdown 渲染为图片 |

## 安装与配置

```bash
nb create  # 创建 NoneBot 项目并选择 OneBot V11 adapter
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0,<0.9"
uv add nonebot-plugin-alconna
```

复制 `plugins/remote_render` 到项目插件目录。

### 启动远程浏览器

#### 方案 A：Docker Compose（CDP，推荐）

```bash
docker compose up -d
cp .env.prod .env
```

该命令在 `9222` 端口启动 Chromium 容器；`.env.prod` 已配置对应 CDP endpoint。

#### 方案 B：Playwright Server（WebSocket）

```bash
npx playwright run-server --port 3000
```

```dotenv
RENDER={"provider":"playwright","startup":"probe","provider_config":{"engine":"chromium","connect_ws":{"endpoint":"ws://localhost:3000"}}}
```

!!! warning "CDP 与 WebSocket 只能选择一种"

    同时设置两个 endpoint 会在配置校验阶段失败。

完整配置模板见 `.env.prod`。示例中的 `/rshot` 直接接受调用方 URL，只适合受信任环境；生产部署必须限制导航目标和浏览器服务的网络可达范围。
