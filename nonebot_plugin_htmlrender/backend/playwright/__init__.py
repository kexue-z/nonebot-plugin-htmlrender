"""Playwright backend package.

Import concrete symbols from their owning submodules, for example
``backend.playwright.render`` or ``backend.playwright.operations``. The package
initializer intentionally stays side-effect free so importing unrelated
Playwright submodules does not register or warm up the backend.
"""

__all__: list[str] = []
