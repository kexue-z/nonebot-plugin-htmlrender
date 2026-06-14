# Web Screenshot Example

Demonstrates using `get_render_context` and `capture_html_element` to take web page screenshots.

## Commands

| Command | Description |
|---|---|
| `/screenshot [url]` | Take a full-page screenshot of a URL (defaults to `https://github.com`) |
| `/capture <selector>` | Capture a specific CSS selector element from GitHub |

## Setup

```bash
nb create  # Create a NoneBot project, select OneBot V11 adapter
nb plugin install nonebot-plugin-htmlrender
nb plugin install nonebot-plugin-alconna
```

Copy the `plugins/screenshot` directory into your project's plugin directory.

Add the following to your `.env` file:

```dotenv
RENDER_BACKEND=playwright
```
