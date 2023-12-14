from typing import Optional

from pydantic import Extra, BaseModel


class Config(BaseModel, extra=Extra.ignore):
    htmlrender_browser: Optional[str] = "chromium"
    htmlrender_download_host: Optional[str]
    htmlrender_proxy_host: Optional[str]
    htmlrender_browser_channel: Optional[str]
