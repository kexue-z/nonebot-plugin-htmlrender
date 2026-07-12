# Local Template Render Example

Demonstrates using `render_template` and `render_text` to render local HTML/CSS templates into images.

## Commands

| Command | Description |
|---|---|
| `/profile [username]` | Render a user profile card from a Jinja2 template |
| `/textimg <content>` | Render plain text into an image |

## Setup

```bash
nb create  # Create a NoneBot project, select OneBot V11 adapter
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0a1,<0.9"
uv add nonebot-plugin-alconna
```

Copy the `plugins/template_render` directory (including `templates/`) into your project's plugin directory.

Add the following to your `.env` file:

```dotenv
RENDER={"provider":"playwright","startup":"probe","resources":{"local_access":{"allowed_paths":["plugins/template_render/templates"]}}}
```

## Template Structure

```text
plugins/template_render/
  __init__.py
  templates/
    profile.html    # Jinja2 template
    style.css       # Stylesheet loaded by the template
```

The template uses Jinja2 syntax. Variables are passed via the `variables`
parameter of `render_template`; the returned `RenderedImage` is converted with
`bytes(artifact)` before it is handed to the message adapter.
