import { chromium } from "playwright-core";

const port = Number.parseInt(process.env.BROWSER_PORT ?? "53333", 10);
const wsPath = process.env.BROWSER_WS_ENDPOINT ?? "/playwright";

const server = await chromium.launchServer({
  host: "0.0.0.0",
  port,
  wsPath,
});

console.log(server.wsEndpoint());
