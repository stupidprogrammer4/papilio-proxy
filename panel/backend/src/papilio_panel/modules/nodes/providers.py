"""Bind node application capabilities to native persistence, crypto and transport."""

from papilio_panel.modules.identity.providers import admin_access

from .app.connectivity import NodeConnectivity
from .app.execution import NodeExecution
from .app.management import NodeManagement
from .app.publications import NodePublications
from .app.xray_control import NodeXrayControl
from .infra.agent import NativeAgentGateway
from .infra.bootstrap import NativeBootstrapArchive
from .infra.broker import NativeNodePublisher
from .infra.certificates import NativeCertificateIssuer
from .infra.storage import DjangoNodeStorage
from .interfaces import (
    NodeCapability,
    NodeConnectivityCapability,
    NodeExecutionCapability,
    NodePublicationCapability,
    NodeXrayControlCapability,
)

storage = DjangoNodeStorage()
nodes: NodeCapability = NodeManagement(storage, admin_access, NativeBootstrapArchive())
execution: NodeExecutionCapability = NodeExecution(
    storage, admin_access, NativeCertificateIssuer(), NativeAgentGateway()
)
publications: NodePublicationCapability = NodePublications(storage, NativeNodePublisher())
xray_control: NodeXrayControlCapability = NodeXrayControl(
    storage, admin_access, NativeAgentGateway()
)
connectivity: NodeConnectivityCapability = NodeConnectivity(
    storage, admin_access, NativeAgentGateway()
)
