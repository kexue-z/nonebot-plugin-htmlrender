from typing import Optional

from pydantic import BaseModel, Extra


class Config(BaseModel, extra=Extra.ignore):
    htmlrender_browser: Optional[str] = "chromium"
    htmlrender_download_host: Optional[str] = None
    htmlrender_proxy_host: Optional[str] = None
    htmlrender_browser_channel: Optional[str] = None
