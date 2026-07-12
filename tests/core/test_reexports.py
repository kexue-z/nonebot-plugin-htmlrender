from nonebot_plugin_htmlrender.utils import signal as html_signal
from nonebot_plugin_htmlrender.utils.signal import (
    HANDLED_SIGNALS,
    install_signal_handler,
    register_signal_handler,
    remove_signal_handler,
    shield_signals,
)


def test_signal_module_reexports_utils_symbols() -> None:
    assert html_signal.HANDLED_SIGNALS == HANDLED_SIGNALS
    assert html_signal.install_signal_handler is install_signal_handler
    assert html_signal.register_signal_handler is register_signal_handler
    assert html_signal.remove_signal_handler is remove_signal_handler
    assert html_signal.shield_signals is shield_signals
    assert set(html_signal.__all__) == {
        "HANDLED_SIGNALS",
        "install_signal_handler",
        "register_signal_handler",
        "remove_signal_handler",
        "shield_signals",
    }
