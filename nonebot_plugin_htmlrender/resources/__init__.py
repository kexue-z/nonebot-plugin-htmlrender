"""Resource resolution and template processing facade.

All external consumers import from here; implementation lives in
``resolve`` (resource resolution engine) and ``template`` (HTML/CSS/template
variable processing).
"""

from .resolve import (
    ResourceResolveError as ResourceResolveError,
)
from .resolve import (
    ResourceResolver as ResourceResolver,
)
from .resolve import (
    is_remote_playwright_mode as is_remote_playwright_mode,
)
from .template import (
    resolve_html_resources as resolve_html_resources,
)
from .template import (
    resolve_template_vars as resolve_template_vars,
)
from .template import (
    to_resource_url as to_resource_url,
)

__all__ = [
    "ResourceResolveError",
    "ResourceResolver",
    "is_remote_playwright_mode",
    "resolve_html_resources",
    "resolve_template_vars",
    "to_resource_url",
]
