from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide

from papilio_proxy.config.settings import Settings
from papilio_proxy.modules.network.nodes.app.services import NodeReconciler
from papilio_proxy.modules.network.nodes.infra.client import XrayNodeClient
from papilio_proxy.modules.network.nodes.schedulers import NodeReconcileJob
from papilio_proxy.modules.network.subscriptions.app.services import AccessService
from papilio_proxy.modules.network.subscriptions.infra.repository import MysqlAccessRepository


class NodesProvider(Provider):
    scope = Scope.APP
    job = provide(NodeReconcileJob)

    @provide
    def reconciler(
        self, repository: MysqlAccessRepository, access: AccessService, node: XrayNodeClient | None
    ) -> NodeReconciler | None:
        return NodeReconciler(repository, access, node) if node else None

    @provide
    async def node(self, settings: Settings) -> AsyncIterator[XrayNodeClient | None]:
        node = XrayNodeClient(settings.node_socket_path) if settings.node_socket_path else None
        try:
            yield node
        finally:
            if node:
                await node.close()
