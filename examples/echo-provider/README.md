# Echo Provider Example

This directory is a minimal third-party Provider distribution. It validates
the final 0.8 SDK without a browser or native renderer: every raster request
returns a 1×1 PNG in the configured color.

## Install

```bash
uv add --editable ./examples/echo-provider
```

## Configure

```yaml
render:
  provider: echo
  startup: probe
  provider_config:
    color: "#663399"
```

The distribution registers `PROVIDER` through the
`nonebot_plugin_htmlrender.providers` entry-point group. The implementation
shows typed settings, side-effect-free availability, lifecycle/executor
bindings, `ResourceStrategy`, and composition-provided dependencies.

It intentionally exposes no provider-specific Capability. Extend it only when
demonstrating a real typed boundary; do not add engine-specific parameters to
the neutral executor.
