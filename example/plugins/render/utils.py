from nonebot.log import logger


def count_to_color(count: str) -> str:
    logger.debug(f"Filtering count: {count}")
    if count == "1":
        return "#facc15"
    elif count == "2":
        return "#f87171"
    elif count == "3":
        return "#c084fc"
    else:
        return "#60a5fa"
