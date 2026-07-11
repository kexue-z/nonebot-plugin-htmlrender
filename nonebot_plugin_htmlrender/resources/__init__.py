"""Resource resolution and template processing facade.

All external consumers import from here; implementation lives in
``resolve`` (resource resolution engine) and ``template`` (HTML/CSS/template
variable processing).
"""

from .cache import (
    FileCachePolicy as FileCachePolicy,
)
from .cache import (
    FileResourceCache as FileResourceCache,
)
from .cache import (
    FileRevision as FileRevision,
)
from .cache import (
    FileSnapshot as FileSnapshot,
)
from .cache import (
    ResourceCacheStats as ResourceCacheStats,
)
from .cache import (
    get_resource_cache as get_resource_cache,
)
from .cache import (
    read_resource_bytes as read_resource_bytes,
)
from .cache import (
    read_resource_text as read_resource_text,
)
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
    "FileCachePolicy",
    "FileResourceCache",
    "FileRevision",
    "FileSnapshot",
    "ResourceCacheStats",
    "ResourceResolveError",
    "ResourceResolver",
    "get_resource_cache",
    "is_remote_playwright_mode",
    "read_resource_bytes",
    "read_resource_text",
    "resolve_html_resources",
    "resolve_template_vars",
    "to_resource_url",
]
