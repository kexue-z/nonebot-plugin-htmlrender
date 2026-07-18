# Takumi Capability 示例

展示如何从默认 `Application` 获取稳定的 `TAKUMI_CAPABILITIES` lookup key，并在
`extension()` 异步上下文中调用 Takumi 专属的 native API。该对象受一次 runtime
operation lease 保护，不能逃逸出上下文或保存为进程级单例。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/takumi_card [title]` | 通过 Takumi extension 渲染 PNG 卡片 |

## 安装与配置

```bash
nb create  # 创建 NoneBot 项目并选择 OneBot V11 adapter
uv add "nonebot-plugin-htmlrender[takumi]>=0.8.0a1,<0.9"
uv add nonebot-plugin-alconna
```

复制 `plugins/takumi_capability` 到项目插件目录，并写入：

```dotenv
RENDER={"provider":"takumi","startup":"probe","provider_config":{"max_concurrency":4}}
```

通用 HTML、Markdown 和模板渲染仍应优先使用顶层中立 API。只有 node、measure、
SVG、animation、动态字体或本例中的 Takumi 专属参数需要经过 typed Capability。
