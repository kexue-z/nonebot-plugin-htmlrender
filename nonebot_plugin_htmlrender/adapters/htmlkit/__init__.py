"""Optional HTMLKit HTML engine adapter.

The package intentionally exports no upstream objects.  Provider discovery
imports :mod:`provider` only when ``render.provider`` is ``"htmlkit"``.
"""

from .config import HtmlkitConfig as HtmlkitConfig

__all__ = ["HtmlkitConfig"]
