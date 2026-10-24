"""Observe live node/core readiness through its authorized native transport."""

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import Conflict

from ..domain import NodeConnection, NodeProbe, ProbeObservation
from ..interfaces import AgentGateway, NodeStorage


class NodeConnectivity:
    def __init__(
        self, storage: NodeStorage, access: AdminAccessCapability, gateway: AgentGateway
    ) -> None:
        self.storage, self.access, self.gateway = storage, access, gateway

    def probe(self, values: NodeProbe) -> ProbeObservation:
        self.access.authorize_owner(values.actor_id)
        node = self.storage.read(values.node_id, values.actor_id)
        if not node.credentials_ready:
            raise Conflict("Wait for the node credentials to be issued.")
        credentials = self.storage.credentials(node.id, values.actor_id)
        result = self.gateway.check(
            NodeConnection(
                node.id,
                node.deployment_id,
                node.endpoint_url,
                node.runtime,
                credentials,
            )
        )
        self.storage.record_probe(node.id, values.actor_id, result)
        return result
