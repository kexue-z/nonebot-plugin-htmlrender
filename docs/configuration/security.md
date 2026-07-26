---
title: 安全须知
description: 本地路径、远程导航、模板、filehost 与敏感数据边界
icon: lucide/shield-check
---

# 安全须知

HTML 渲染会连接网络、读取资源、执行模板或运行浏览器。Provider 不替调用方建立业务级信任边界。

## 本地文件

- 保持 `render.resources.local_access.allow_any_path: false`。
- `render.resources.local_access.allowed_paths` 只加入最小只读目录。
- 路径授权必须在读取前完成，并防止 `..` 与 symlink 越界。
- 不要把用户提供的任意路径传给模板、Markdown 或资源辅助函数。
- cache 命中不能绕过授权；策略变更后应创建新的 composition。

## 不可信 HTML 与模板 { #untrusted-html-and-templates }

Jinja autoescape 不能替代模板源码信任。模板源码、filters 与 extensions 只能来自受控代码；用户输入只能作为 `variables` 值。

`render_markdown` 会保留 Markdown 中的原始 HTML，并把转换结果作为 HTML 片段交给 Provider；它不提供 HTML 消毒边界。来自用户或模型的 Markdown 可能携带 `<script>`、事件处理属性和外链资源，其脚本执行与网络访问风险和 `render_html` 相同。若不需要富文本，使用会转义文本内容的 `render_text`；若需要 Markdown，应在渲染前按业务策略对白名单标签、属性和 URL 做清洗。

```python
artifact = await render_template(
    TRUSTED_TEMPLATE_DIR,
    "card.html",
    variables={"display_name": untrusted_text},
)
```

不要把用户输入拼成 `<script>`、event handler、CSS URL 或 Jinja 表达式。不要把“内容由模型生成”当作可信来源。

## 远程导航与 SSRF

Playwright Page 可访问 Bot 网络可达的任意目标。对用户提供的 URL：

- 建立 scheme/host/port allowlist；
- 解析 DNS 并阻止 loopback、link-local、metadata 与私网地址；
- 谨慎处理重定向和 DNS rebinding；
- 在容器/网络层限制 egress；
- 设置连接和完整操作超时。

`resource_policy` 只控制文档资源处理，不是 SSRF 防护。

## filehost

filehost 只应作为受控 asset publisher：

- 保持路径白名单最小；
- 保持请求头守卫并在代理中透传；
- 认证成功的响应会携带 `Access-Control-Allow-Origin: *`，以允许远程页面加载字体；
- 不向公网暴露通用文件读取路由；
- 不把 URL 视为永久地址；
- 了解 TTL 只释放映射，不承诺逐文件物理擦除。

对机密内容，优先使用 render-scoped `memory` transport。

!!! warning "通配 CORS 不是授权边界"

    未携带正确守卫请求头的 filehost 请求仍会返回 403，且不会获得通配 CORS响应头。反向代理必须分别保留入站守卫请求头和出站 CORS 响应头。

## Provider 配置与 Capability

endpoint、代理凭据、headers 和 storage state 都是敏感信息：

- 使用部署平台 secret，不写入仓库；
- 日志中不输出完整 `render.provider_config`；
- 不向不可信调用方暴露 raw Playwright Page 或 Browser；
- 不跨请求复用含认证状态的 Page/context；
- 只加载可信第三方 Provider distribution。

插件数据目录可能包含 Playwright 浏览器文件与运行时快照。部署时限制目录权限、备份范围和容器挂载；不要把它当作公开静态目录。其他 Provider 若在此保存状态，也必须遵循同一敏感数据生命周期。

Provider entry point 会在进程内执行代码，其权限与 Bot 相同。

## 资源与拒绝服务

- 保持 cache entry/byte 上限；
- 限制 HTML、Markdown、模板变量与 asset 大小；
- 设置 `timeout_seconds`；
- 限制 Playwright 页面、HTMLKit native thread、Takumi worker 和并发请求数；
- 对用户可控 URL 限制下载大小与重定向次数。

单个巨大资源不应挤占整个缓存预算；超限应作为资源错误报告。

## 遥测

不要记录 HTML、URL、路径、模板变量、header、字体名、digest 或 bytes。只使用低基数 operation、Provider identity、status 和聚合 cache 统计。observer异常必须与业务结果隔离。

## 发布前检查

- 本地路径和 symlink 越界测试；
- SSRF 与重定向策略测试；
- filehost 路由认证、CORS 和双向代理透传测试；
- cache/并发/取消上限测试；
- Provider extras 与第三方许可审查；
- secret 扫描和最小权限容器配置。
