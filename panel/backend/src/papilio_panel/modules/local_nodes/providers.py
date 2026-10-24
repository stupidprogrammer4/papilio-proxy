"""Bind local registration to public native module capabilities."""

from papilio_panel.modules.cores.providers import cores
from papilio_panel.modules.identity.providers import admin_access, owner_setup
from papilio_panel.modules.nodes.providers import connectivity, nodes

from .app.execution import LocalExecution
from .app.initialization import LocalOwnerInitialization
from .app.management import LocalNodeManagement
from .app.publications import LocalPublications
from .app.registration import LocalNodeRegistration
from .infra.broker import NativeLocalPublisher
from .infra.configuration import NativeLocalConfiguration
from .infra.files import NativeLocalFiles
from .infra.schedules import NativeLocalSchedule
from .infra.storage import DjangoLocalStorage
from .infra.work import DjangoLocalWorkStorage
from .interfaces import (
    LocalExecutionCapability,
    LocalNodeCapability,
    LocalOwnerInitializationCapability,
    LocalPublicationCapability,
    LocalRegistrationCapability,
)

storage = DjangoLocalStorage()
local_nodes: LocalNodeCapability = LocalNodeManagement(
    storage, admin_access, nodes, cores, NativeLocalConfiguration()
)
registration: LocalRegistrationCapability = LocalNodeRegistration(
    storage, admin_access, nodes, cores, local_nodes
)
owner_initialization: LocalOwnerInitializationCapability = LocalOwnerInitialization(
    owner_setup, local_nodes, registration
)
work_storage = DjangoLocalWorkStorage()
schedule = NativeLocalSchedule()
execution: LocalExecutionCapability = LocalExecution(
    work_storage, admin_access, local_nodes, nodes, connectivity, NativeLocalFiles(), schedule
)
publications: LocalPublicationCapability = LocalPublications(
    work_storage, NativeLocalPublisher(), schedule
)
