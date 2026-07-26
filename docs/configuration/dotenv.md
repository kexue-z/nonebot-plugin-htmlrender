---
title: .env 配置
description: 使用 NoneBot dotenv 配置渲染后端、Graphics Capability 与嵌套字段
icon: lucide/file-json-2
---

# `.env` 配置

NoneBot 支持从 dotenv 文件和进程环境变量读取配置。插件的所有配置都位于`render` 命名空间；在 dotenv 中使用双下划线 `__` 表示下一层字段：

```dotenv
RENDER__PROVIDER=playwright
RENDER__STARTUP=probe
RENDER__PROVIDER_CONFIG__ENGINE=chromium
```

以上配置等价于：

```yaml
render:
  provider: playwright
  startup: probe
  provider_config:
    engine: chromium
```

字段名大小写不敏感，本文统一使用大写环境变量。`RENDER_PROVIDER` 是旧版扁平配置键，不等价于 `RENDER__PROVIDER`，在 0.8 中会被拒绝。

## 配置文件与优先级

NoneBot 默认先读取项目目录中的 `.env`，再读取 `.env.{environment}`；默认环境为 `prod`，因此通常是 `.env` 与 `.env.prod`。可以在 `.env` 中选择其他环境：

```dotenv
ENVIRONMENT=dev
```

此时环境专属配置来自 `.env.dev`。同名值按以下顺序覆盖：

1. 传给 `nonebot.init()` 的参数；
2. 进程环境变量；
3. `.env.{environment}`；
4. `.env`；
5. 插件默认值。

部署密钥、远程 endpoint 与 filehost guard 不应提交到版本控制。将非敏感默认值放在 `.env`，环境差异放在 `.env.dev`、`.env.prod` 或部署平台的环境变量中。

## 值的写法

字符串、数字和布尔值可以直接填写。插件核心模型已知类型的列表与对象使用JSON：

```dotenv
RENDER__STARTUP=probe
RENDER__GRAPHICS__MAX_CONCURRENCY=2
RENDER__OBSERVABILITY__PROMETHEUS=true
RENDER__GRAPHICS__BACKENDS='["pillow", "skia"]'
RENDER__RESOURCES__LOCAL_ACCESS__ALLOWED_PATHS='["templates", "assets"]'
```

`render.provider_config` 是由所选 Provider 延后校验的开放字典。标量和嵌套对象仍可使用 `RENDER__PROVIDER_CONFIG__...`；Provider 专属的列表或对象应将整个`RENDER__PROVIDER_CONFIG` 写成 JSON：

```dotenv
RENDER__PROVIDER_CONFIG='{"load_default_fonts":false,"fonts":[{"path":"/app/fonts/NotoSansSC-Regular.otf","name":"Noto Sans SC"}],"font_families":["Noto Sans SC","sans-serif"]}'
```

也可以将完整对象写入单个 `RENDER` 变量：

```dotenv
RENDER='{"provider":"playwright","startup":"probe","provider_config":{"engine":"chromium"}}'
```

分层变量更易按部署环境覆盖，建议优先使用。两种写法同时存在时，`RENDER__...` 指定的叶子字段覆盖 `RENDER` JSON 中的对应字段。

!!! warning "JSON 必须使用双引号"

    dotenv 外层可以使用单引号，但 JSON 内的键名与字符串必须使用双引号。`["pillow"]` 是有效值，`['pillow']` 不是 JSON。

## 常见后端 { #common-backends }

安装对应 extra 后，从下列示例选择一个 HTML 后端。Pillow 与 Skia 是独立的Graphics 后端，可以单独启用，也可以附加到任意 HTML 后端。

=== "Playwright"

    ```dotenv
    RENDER__PROVIDER=playwright
    RENDER__STARTUP=probe
    RENDER__PROVIDER_CONFIG__ENGINE=chromium
    RENDER__PROVIDER_CONFIG__RESOURCE_RESOLVE_MODE=auto
    ```

    需要浏览器布局、JavaScript 或页面操作时使用。安装和远程连接字段见[Playwright 配置](../providers/playwright/)。

=== "HTMLKit"

    ```dotenv
    RENDER__PROVIDER=htmlkit
    RENDER__STARTUP=probe
    RENDER__PROVIDER_CONFIG__MAX_CONCURRENCY=2
    RENDER__PROVIDER_CONFIG__LANGUAGE=zh
    RENDER__PROVIDER_CONFIG__CULTURE=CN
    RENDER__PROVIDER_CONFIG__RESOURCE_RESOLVE_MODE=auto
    ```

    适合不需要 JavaScript 的进程内 HTML/CSS 排版。平台与输出限制见[HTMLKit 配置](../providers/htmlkit/)。

=== "Takumi"

    ```dotenv
    RENDER__PROVIDER=takumi
    RENDER__STARTUP=probe
    RENDER__PROVIDER_CONFIG='{"max_concurrency":4,"load_default_fonts":true,"font_families":["sans-serif"]}'
    ```

    适合受控静态内容以及 Takumi 专属的 node、SVG、measure 和 animation
    Capability。字体和缓存字段见 [Takumi 配置](../providers/takumi/)。

=== "Pillow"

    ```dotenv
    RENDER__GRAPHICS__BACKENDS='["pillow"]'
    RENDER__GRAPHICS__MAX_PIXELS=16777216
    RENDER__GRAPHICS__MAX_CONCURRENCY=2
    RENDER__GRAPHICS__MAX_COMMANDS=100000
    ```

    该配置只启用 Pillow `RasterScene` Capability，不选择 HTML 后端。安装与运行边界见 [Pillow 后端](../graphics/pillow/)。

=== "Skia"

    ```dotenv
    RENDER__GRAPHICS__BACKENDS='["skia"]'
    RENDER__GRAPHICS__MAX_PIXELS=16777216
    RENDER__GRAPHICS__MAX_CONCURRENCY=2
    RENDER__GRAPHICS__MAX_COMMANDS=100000
    ```

    该配置只启用 Skia `RasterScene` Capability。部署前检查[Skia 后端](../graphics/skia/)列出的 wheel、glibc 和系统图形库约束。

同时启用 Playwright、Pillow 与 Skia 时，将两类配置组合即可：

```dotenv
RENDER__PROVIDER=playwright
RENDER__STARTUP=probe
RENDER__PROVIDER_CONFIG__ENGINE=chromium
RENDER__GRAPHICS__BACKENDS='["pillow", "skia"]'
```

一次 composition 仍然只选择一个 HTML 后端；`backends` 列表可以包含两个Graphics 后端，但不能出现重复值。完整字段与默认值见[配置总览](../index.md)。
