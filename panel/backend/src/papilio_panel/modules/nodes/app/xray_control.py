"""Resolve current node ownership and credentials before background core control."""

from uuid import UUID

from papilio_panel.modules.identity.interfaces import AdminAccessCapability
from papilio_panel.shared.errors import Conflict

from ..domain import MutationObservation, NodeConnection, XrayApply, XrayRemove
from ..interfaces import AgentGateway, NodeStorage
from .xray_validation import validate_identity, validate_vless


class NodeXrayControl:
    def __init__(
        self, storage: NodeStorage, access: AdminAccessCapability, gateway: AgentGateway
    ) -> None:
        self.storage = storage
        self.access = access
        self.gateway = gateway

    def _connection(self, actor_id: int, node_id: UUID) -> NodeConnection:
        node = self.storage.read(node_id, actor_id)
        if not node.credentials_ready:
            raise Conflict("Wait for the node credentials to be issued.")
        credentials = self.storage.credentials(node_id, actor_id)
        return NodeConnection(
            node_id=node.id,
            deployment_id=node.deployment_id,
            endpoint_url=node.endpoint_url,
            runtime=node.runtime,
            credentials=credentials,
        )

    def apply(self, values: XrayApply) -> MutationObservation:
        self.access.authorize_owner(values.actor_id)
        validate_vless(values.user)
        connection = self._connection(values.actor_id, values.node_id)
        result = self.gateway.apply_vless(connection, values.user)
        return result

    def remove(self, values: XrayRemove) -> MutationObservation:
        self.access.authorize_owner(values.actor_id)
        validate_identity(values.identity)
        connection = self._connection(values.actor_id, values.node_id)
        result = self.gateway.remove_xray(connection, values.identity)
        return result
