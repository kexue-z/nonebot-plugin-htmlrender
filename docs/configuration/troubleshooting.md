---
title: 故障排查
description: Provider discovery、启动、Capability、资源和渲染故障
icon: lucide/wrench
---

# 故障排查

先确定错误属于哪一层：

| 错误 | 首要检查 |
| --- | --- |
| `ApplicationNotInitialized` | NoneBot 插件是否加载，或独立宿主是否调用了 `set_default_application()` |
| `ProviderNotFound` | Provider ID、安装 distribution、entry point |
| `ProviderUnavailable` | extra、浏览器/native 库、endpoint |
| `ProviderLifecycleError` | startup/probe/shutdown 日志 |
| `CapabilityUnavailable` | 是否配置 Provider，以及当前 composition 是否绑定该操作/typed Capability |
| `UnsupportedRequirement` | 文档是否需要脚本、网络或不支持的样式 |
| `UnsupportedRenderOption` | 所选 Provider 是否能表达 DPR、显式高度等通用选项 |
| `ResourceResolutionError` | 路径、白名单、transport 与资源存在性 |
| `ProviderExecutionError` | Provider 运行时与输入最小复现 |

`ApplicationNotInitialized` 表示进程默认 Application 尚未由宿主安装，不表示`render.provider` 为空。未选择 Provider 是合法配置：Preparation、Resource Service、`render_template_html` 和显式启用的 Graphics Capability 仍可使用；此时调用需要 HTML Provider 的位图渲染 API 会抛出 `CapabilityUnavailable`。

## Provider 无法发现

1. 确认 `render.provider` 拼写。
2. 第一方 Provider 需要对应 extra。
3. 第三方 Provider 的 entry point group 必须是`nonebot_plugin_htmlrender.providers`，entry point 名必须等于 `provider.id`。
4. `htmlkit`、`playwright` 与 `takumi` 是保留 ID，第三方不可覆盖。

## Playwright 本地启动失败

先确认诊断命令运行在 Bot 项目的同一个虚拟环境内：

```bash
uv run python3 -c "import importlib.metadata; print(importlib.metadata.version('playwright'))"
```

Playwright Python client 要求精确匹配的 browser revision。若曾手工修改浏览器文件，或有其他虚拟环境对共享目录执行过安装、升级、卸载或缓存清理，不要继续复用该目录；给当前项目换用独占目录，并从当前虚拟环境重新安装：

```bash
PLAYWRIGHT_BROWSERS_PATH=/var/lib/htmlrender/playwright-project \
  uv run playwright install --with-deps chromium
```

将同一路径写入 `render.provider_config.storage_path`，然后用 `startup: probe` 重启验证。macOS/Windows 可去掉 `--with-deps`；Linux 上该参数还会补齐系统包。检查目录权限、`engine`、`executable_path`、channel 与系统依赖。设置 `skip_browser_install: true` 会禁止自动安装，不会让缺失或 revision 不匹配的浏览器变为可用。未设置 `storage_path` 时还需确认插件数据目录可写。

## WS/CDP 连接失败

- WS 使用 Playwright server endpoint；CDP 使用 Chromium endpoint。
- 两个 endpoint 不可同时设置。
- CDP 只支持 Chromium。
- WS 连接前会执行软版本门禁；major 不同或 minor 相差至少 2 会阻断，其余风险可能只记录警告。无法识别服务端版本时门禁会 fail-open。
- CDP 不执行 Playwright 版本门禁；检查 Chromium/CDP 自身兼容性。
- 检查容器 DNS、端口、TLS、认证、精确版本锁定和代理，不要把门禁通过视为兼容性证明。
- 使用 `startup: probe` 或 `await app.probe()` 完成真实连接并创建 Page，获取底层错误。

## typed Capability 缺失

确认 `render.provider` 与 `app.extensions.playwright` 或 `.takumi` 对应，并确认所需Graphics backend 已启用；不要用能力缺失作为 Provider 身份判断，业务应按真实所需能力访问。第三方自定义能力才通过其公共模块导出的 key 探测。

## 本地资源被拒绝

默认安全策略拒绝模板根之外的路径。把最小目录加入`render.resources.local_access.allowed_paths`，不要直接开启`render.resources.local_access.allow_any_path`。

路径存在仍失败时检查：

- 是否包含 `..`、symlink 越界或大小写不一致；
- Bot 与远程浏览器是否误用了 `passthrough`；
- `ResourcePolicy.STRICT` 是否暴露了先前被 AUTO 容忍的缺失资源；
- filehost 是否运行在插件初始化时可安装路由的 FastAPI ASGI host；
- filehost 守卫请求头是否在到达 Bot 前被反向代理移除。

??? info "资源返回 200，但字体或 CSS 仍未生效"

    检查浏览器的 `requestfailed` 事件和开发者工具 CORS 诊断。代理可能已经让资源请求成功到达 Bot，却在响应返回浏览器前移除了 `Access-Control-Allow-Origin`。HTTP 200 只说明传输成功，不表示浏览器已经允许页面使用该跨源资源。

## 缓存内容未更新或频繁驱逐

先识别发生问题的层，不要直接重启或清理所有状态：

1. 单个文件或 HTTP resource 未更新：用 `app.resources.read_bytes(..., refresh=True)` / `read_text(..., refresh=True)` 刷新同一个 key；批量任务需要干净的 Resource Reader 时才调用 `await app.resources.clear()`。
2. Jinja 模板未更新：用户模板默认 auto-reload；若 Environment miss 持续增长，检查是否在每次调用创建了新的 filter callable 或 extensions 组合。
3. filehost capacity error：检查是否有大量活跃 render lease 钉住资源、预热目录是否过宽，以及 `max_entries` / `max_bytes` 是否覆盖真实工作集。缩短 TTL 不能释放仍在 lease 中的 asset。
4. Takumi 重复编译或字体变化：读取 `api.compiled_cache_stats`；调整 compiled cache 上限，或关闭并重建 runtime 以替换字体/native 状态。

`app.resources.clear()` 不会清理 Jinja、filehost、Takumi 或 Playwright browser storage。完整清理矩阵与指标解释见[缓存组件、失效与调优](../guides/cache-lifecycle.md)。

## Takumi 拒绝文档

查看 `PreparedHtml.requirements`。JavaScript、网络、浏览器导航、无法物化的图片/字体或条件 stylesheet 不会被静默忽略。修改内容，或改用 Playwright。

## HTMLKit 拒绝选项或事件循环

HTMLKit rc5 只支持 asyncio，且不能表达通用 DPR/显式输出高度。调用时设置`device_pixel_ratio=1.0`、`height=None`；Trio 会得到 `ProviderUnavailable`。若超时或取消晚于预期，检查 native render 是否仍在执行：适配器必须先 drain
detached native thread，才能安全释放 Resource Service。

## 超时与取消

为通用操作设置 `timeout_seconds`。外部网络 Page 操作另外设置 Playwright
timeout。取消后退出当前异步上下文，不要继续使用其中取得的 Page、Takumi API 或原生对象；extension access 本身可以保留并重新进入新的上下文。

## 观测没有数据

依次确认：

1. 已安装 `sentry`/`prometheus` extra，并启用`render.observability.sentry` 或 `render.observability.prometheus`；
2. 对应 NoneBot 集成自身已经配置完成；htmlrender 不配置 Sentry transport，也不自行提供 Prometheus endpoint；
3. 集成在 NoneBot startup 前加载。修正安装或启动配置后需要重启进程，首次加载结果会在进程内缓存；
4. 已完成至少一次受观测操作。仅创建 `Application` 不会产生 operation 指标；
5. Sentry 项目的采样设置接受该 transaction，且所用 SDK 版本提供需要的 trace 或metrics surface；
6. Prometheus 实际抓取的是 `nonebot_plugin_prometheus` 暴露的 endpoint，并能看到`nonebot_htmlrender_operations_total`。

查看 `htmlrender.telemetry` warning 可以定位 SDK API、collector 注册与 exporter 写入失败；没有 Sentry trace 时，debug 日志会记录 operation、backend、status 与 duration。observer 故障被隔离，因此渲染成功并不证明 exporter 正常。完整的插装边界、指标schema 与 PromQL 示例见[可选依赖与可观测性](observability.md)。

## 最小诊断信息

捕获 `RenderingError` 时优先记录 `type(error).__name__`、`error.message`、`error.message_truncated`、`error.causes` 与 `error.causes_truncated`。若裁剪标记为`true`，说明快照并不完整；需要更深诊断时从受控错误追踪系统查看 `__cause__`，不要解析 `str(error)` 恢复结构。

报告问题时提供版本、Python/OS、Provider ID、脱敏后的嵌套配置、上述有界错误信息、startup/probe 日志和最小输入。原因消息来自底层引擎，虽然已经限制长度，仍可能带有URL、路径或输入片段；发送前必须脱敏。不要附带 token、headers、HTML 中的私密数据、本地绝对路径或 asset bytes。
