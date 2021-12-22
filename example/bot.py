import nonebot
from nonebot.adapters.cqhttp import Bot as CQHTTPBot

nonebot.init()


app = nonebot.get_asgi()

driver = nonebot.get_driver()
driver.register_adapter("cqhttp", CQHTTPBot)

nonebot.load_plugin("nonebot_plugin_htmlrender")
nonebot.load_plugin("nonebot_plugin_test")
nonebot.load_plugins("plugins")

if __name__ == "__main__":
    nonebot.run(app="bot:app")