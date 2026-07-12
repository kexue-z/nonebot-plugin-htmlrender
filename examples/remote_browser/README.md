# Remote Playwright Provider Example

Demonstrates connecting to a remote Playwright browser via CDP or WebSocket endpoint for rendering.

Useful for deploying the bot on a machine without a browser, or sharing a single browser instance across multiple bots.

## Commands

| Command | Description |
|---|---|
| `/render_status` | Probe the configured provider and list capabilities |
| `/rshot [url]` | Take a full-page screenshot via remote browser (defaults to `https://github.com`) |
| `/rmd <markdown>` | Render markdown text into an image via remote browser |

## Setup

```bash
nb create  # Create a NoneBot project, select OneBot V11 adapter
uv add "nonebot-plugin-htmlrender[playwright]>=0.8.0a1,<0.9"
uv add nonebot-plugin-alconna
```

Copy the `plugins/remote_render` directory into your project's plugin directory.

### Start a remote browser

#### Option A: Docker Compose (CDP) - Recommended

```bash
docker compose up -d
cp .env.prod .env
```

This starts a Chromium container on port 9222, `.env.prod` already configured to connect via CDP.

#### Option B: Playwright Server (WebSocket)

```bash
npx playwright run-server --port 3000
```

```dotenv
RENDER={"provider":"playwright","startup":"probe","provider_config":{"engine":"chromium","connect_ws":{"endpoint":"ws://localhost:3000"}}}
```

> **Note:** Only one remote mode can be active. Setting both CDP and WS endpoints will raise an error.

See `.env.prod` for a full configuration template.
