"""Public facade: typed-artifact render commands and the default application."""

from ._default import get_default_application as get_default_application
from ._default import get_default_renderer as get_default_renderer
from ._default import set_default_application as set_default_application
from .preparation import prepare_html as prepare_html
from .preparation import prepare_markdown as prepare_markdown
from .preparation import prepare_template as prepare_template
from .preparation import prepare_text as prepare_text
from .render import rasterize_html as rasterize_html
from .render import render_html as render_html
from .render import render_markdown as render_markdown
from .render import render_template as render_template
from .render import render_template_html as render_template_html
from .render import render_text as render_text
from .resources import resolve_template_vars as resolve_template_vars
from .resources import to_resource_url as to_resource_url

__all__ = [
    "get_default_application",
    "get_default_renderer",
    "prepare_html",
    "prepare_markdown",
    "prepare_template",
    "prepare_text",
    "rasterize_html",
    "render_html",
    "render_markdown",
    "render_template",
    "render_template_html",
    "render_text",
    "resolve_template_vars",
    "set_default_application",
    "to_resource_url",
]
