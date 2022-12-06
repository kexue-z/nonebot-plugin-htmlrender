from httpx import AsyncClient
from nonebot import get_driver
from pyqrcode import create

from .config import Config

url = "https://pastebin.com/api/api_post.php"
api_key = Config.parse_obj(get_driver().config.dict()).htmlrender_pastebin_apikey

api_dev_key = api_key if api_key else ""


class PastebinAPIERROR(Exception):
    pass


async def get_msg_qrcode_b64(
    api_paste_code: str,
    api_dev_key: str = api_dev_key,
    api_paste_name: str = "htmlrender",
    api_option: str = "paste",
    api_paste_private: str = "0",
    api_paste_format: str = "",
    api_user_key: str = "",
    api_paste_expire_date: str = "10M",
) -> str:
    """get_msg_qrcode_b64

    >说明: `将长文本发送到 pastebin.com 获取返回的链接, 并且将生成二维码, 转换为base64 `

    :参数:
      * `api_paste_code: str`: 内容或代码

    :可选参数:
      * `api_dev_key: str`: 开发者KEY
      * `api_paste_name: str`: 标题 默认 htmlrender
      * `api_option: str`: 选项 默认 paste
      * `api_paste_private: str`: 是否私有, 默认 0 公开
      * `api_paste_format: str`: 内容格式, 默认 空
      * `api_user_key: str`: 用户KEY 如果不填则为匿名
      * `api_paste_expire_date`: str: 过期时间 默认 10M

    :Exceptions:
      * `PastebinAPIERROR`: API哪里错了

    :返回:
      - `str`: base64编码后的二维码
    """
    data = {
        "api_dev_key": api_dev_key,
        "api_paste_code": api_paste_code,
        "api_paste_name": api_paste_name,
        "api_option": api_option,
        "api_paste_private": api_paste_private,
        "api_paste_format": api_paste_format,
        "api_user_key": api_user_key,
        "api_paste_expire_date": api_paste_expire_date,
    }

    async with AsyncClient() as client:
        res = await client.post(url, data=data)
    if "https://" in res.text:
        b64 = create(url).png_as_base64_str()
        return b64
    else:
        raise PastebinAPIERROR(f"pastebin生成错误! 请检查参数! API返回: {res.text}")
