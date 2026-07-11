"""Public facade: typed-artifact render commands and the default application."""

from ._default import get_default_application as get_default_application
from ._default import get_default_renderer as get_default_renderer
from ._default import set_default_application as set_default_application
from .render import rasterize_html as rasterize_html
from .render import render_html as render_html
from .render import render_markdown as render_markdown
from .render import render_template as render_template
from .render import render_template_html as render_template_html
from .render import render_text as render_text

__all__ = [
    "get_default_application",
    "get_default_renderer",
    "rasterize_html",
    "render_html",
    "render_markdown",
    "render_template",
    "render_template_html",
    "render_text",
    "set_default_application",
]
