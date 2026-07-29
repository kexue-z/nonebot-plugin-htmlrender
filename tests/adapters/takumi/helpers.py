from nonebot_plugin_htmlrender.adapters.resources.reader import (
    AnyioWorkerExecutor,
    CompositeResourceReader,
    ConfiguredLocalAccessPolicy,
    RemoteTransportExecutor,
)
from nonebot_plugin_htmlrender.resources.config import ResourceStrategy
from nonebot_plugin_htmlrender.resources.service import ResourceService


def resource_service(*, strategy: ResourceStrategy | None = None) -> ResourceService:
    return ResourceService(
        reader=CompositeResourceReader(
            AnyioWorkerExecutor(),
            remote_transport=RemoteTransportExecutor(max_concurrent_fetches=2),
        ),
        local_access=ConfiguredLocalAccessPolicy(allowed_roots=(), allow_any=True),
        strategy=strategy or ResourceStrategy(),
    )


__all__ = ["resource_service"]
