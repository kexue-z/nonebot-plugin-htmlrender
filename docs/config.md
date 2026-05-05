# 配置参考

本文档面向开发者，使用代码引用生成配置说明。

## 模块

::: nonebot_plugin_htmlrender.config
    options:
      show_source: true
      members:
        - Config
        - PlaywrightConfig
        - RemoteWSConfig
        - RemoteCDPConfig
        - SkiaConfig
        - PillowConfig
      show_if_no_docstring: true
      show_root_heading: true
      merge_init_into_class: true

## 配置入口

::: nonebot_plugin_htmlrender.config.Config
    options:
      show_source: true
      show_root_heading: false
      merge_init_into_class: true

## Playwright 配置

::: nonebot_plugin_htmlrender.config.PlaywrightConfig
    options:
      show_source: true
      show_root_heading: false
      merge_init_into_class: true

## 远程连接配置

::: nonebot_plugin_htmlrender.config.RemoteWSConfig
    options:
      show_source: true
      show_root_heading: false

::: nonebot_plugin_htmlrender.config.RemoteCDPConfig
    options:
      show_source: true
      show_root_heading: false

## 其他后端配置

::: nonebot_plugin_htmlrender.config.SkiaConfig
    options:
      show_source: true
      show_root_heading: false

::: nonebot_plugin_htmlrender.config.PillowConfig
    options:
      show_source: true
      show_root_heading: false
