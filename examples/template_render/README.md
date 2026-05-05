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
nb plugin install nonebot-plugin-htmlrender
nb plugin install nonebot-plugin-alconna
```

Copy the `plugins/template_render` directory (including `templates/`) into your project's plugin directory.

Add the following to your `.env` file:

```dotenv
RENDER_BACKEND=playwright
```

## Template Structure

```
plugins/template_render/
  __init__.py
  templates/
    profile.html    # Jinja2 template
    style.css       # Stylesheet loaded by the template
```

The template uses Jinja2 syntax. Variables are passed via the `templates` parameter of `render_template`.
