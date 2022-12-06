from typing import Optional, Literal

from pydantic import Extra, BaseModel


class Config(BaseModel, extra=Extra.ignore):
    htmlrender_browser: Literal["chromium", "firefox"] = "chromium"
    htmlrender_download_host: Optional[str]
    htmlrender_proxy_host: Optional[str]
    htmlrender_pastebin_apikey: Optional[str]
