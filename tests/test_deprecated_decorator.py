from collections.abc import Generator
import warnings
from warnings import WarningMessage

import pytest


@pytest.fixture
def warning_catcher() -> Generator[list[WarningMessage], None, None]:
    """捕获警告的fixture"""
    with warnings.catch_warnings(record=True) as caught_warnings:
        warnings.simplefilter("always")
        yield caught_warnings
        warnings.resetwarnings()
        warnings.simplefilter("default")


def test_deprecated_basic(warning_catcher: list[WarningMessage]):
    """测试基础装饰器用法"""
    from nonebot_plugin_htmlrender.utils import deprecated

    @deprecated
    def old_function() -> str:
        return "test"

    result = old_function()
    assert result == "test"
    assert len(warning_catcher) == 1
    assert "已废弃。" in str(warning_catcher[0].message)


def test_deprecated_with_message(warning_catcher: list[WarningMessage]):
    """测试带消息的装饰器"""
    from nonebot_plugin_htmlrender.utils import deprecated

    test_message = "Use new_function instead"

    @deprecated(message=test_message)
    def old_function() -> str:
        return "test"

    result = old_function()
    assert result == "test"
    assert len(warning_catcher) == 1
    assert test_message in str(warning_catcher[0].message)


def test_deprecated_with_version(warning_catcher: list[WarningMessage]):
    """测试带版本号的装饰器"""
    from nonebot_plugin_htmlrender.utils import deprecated

    test_version = "2.0.0"

    @deprecated(version=test_version)
    def old_function() -> str:
        return "test"

    result = old_function()
    assert result == "test"
    assert len(warning_catcher) == 1
    assert test_version in str(warning_catcher[0].message)
