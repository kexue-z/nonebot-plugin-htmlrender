# Web Screenshot Example

Demonstrates resolving the typed Playwright capability and using `page()` and
`capture_element()` to take web page screenshots.

## Commands

| Command | Description |
|---|---|
| `/screenshot [url]` | Take a full-page screenshot of a URL (defaults to `https://github.com`) |
| `/capture <selector>` | Capture a specific CSS selector element from GitHub |

## Setup

```bash
nb create  # Create a NoneBot project, select OneBot V11 adapter
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0a1,<0.9"
uv add nonebot-plugin-alconna
```

Copy the `plugins/screenshot` directory into your project's plugin directory.

Add the following to your `.env` file:

```dotenv
RENDER={"provider":"playwright","startup":"probe"}
```
