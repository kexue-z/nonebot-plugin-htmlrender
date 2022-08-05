from typing import Optional

from pydantic import Extra, BaseModel


class Config(BaseModel, extra=Extra.ignore):
    htmlrender_browser: Optional[str] = "chromium"
