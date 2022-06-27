#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
@Author         : yanyongyu
@Date           : 2021-03-12 13:42:43
@LastEditors    : yanyongyu
@LastEditTime   : 2021-11-01 14:05:41
@Description    : None
@GitHub         : https://github.com/yanyongyu
"""
__author__ = "yanyongyu"

from typing import Optional, AsyncIterator
from contextlib import asynccontextmanager
from sys import platform

from nonebot.log import logger
from playwright.async_api import Page, Error, Browser, Playwright, async_playwright

_browser: Optional[Browser] = None
_playwright: Optional[Playwright] = None


async def init(**kwargs) -> Browser:
    global _browser
    global _playwright
    _playwright = await async_playwright().start()
    try:
        _browser = await launch_browser(**kwargs)
    except Error:
        await install_browser()
        _browser = await launch_browser(**kwargs)
    return _browser


async def launch_browser(**kwargs) -> Browser:
    assert _playwright is not None, "Playwright is not initialized"
    if "win" in platform.lower():
        return await _playwright.chromium.launch(**kwargs)
    else:
        return await _playwright.firefox.launch(**kwargs)


async def get_browser(**kwargs) -> Browser:
    return _browser or await init(**kwargs)


@asynccontextmanager
async def get_new_page(**kwargs) -> AsyncIterator[Page]:
    browser = await get_browser()
    page = await browser.new_page(**kwargs)
    try:
        yield page
    finally:
        await page.close()


async def shutdown_browser():
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()  # type: ignore


async def install_browser():
    import sys,os

    from playwright.__main__ import main
    if "win" in platform.lower():
        logger.info("正在安装 chromium")
        sys.argv = ["", "install", "chromium"]
    else:
        logger.info("正在安装 firefox")
        sys.argv = ["", "install", "firefox"]
    try:
        logger.info("正在安装依赖")
        os.system("playwright install-deps")
        main()
    except SystemExit:
        pass
