"""Scoped node read shapes and private credential decoding."""

import json
from typing import Any
from uuid import UUID

from cryptography.fernet import InvalidToken
from django.core.paginator import EmptyPage, Paginator

from papilio_panel.shared.credentials import credential_cipher
from papilio_panel.shared.errors import Conflict, Missing
from papilio_panel.shared.operations import OperationStatus

from ..domain import (
    AgentRuntime,
    CertificatePolicy,
    CredentialPrivateKeys,
    IssuedCredentials,
    NodeDefinition,
    NodePage,
    NodeRead,
    NodeSearch,
    NodeWorkKind,
    NodeWorkRead,
)
from ..models import AgentSettings, CredentialPolicy, Node, NodeCredentials, NodeOperation


def runtime_read(row: AgentSettings) -> AgentRuntime:
    return AgentRuntime(
        listen_address=row.listen_address,
        xray_api_address=row.xray_api_address,
        request_timeout_seconds=row.request_timeout_seconds,
        read_header_timeout_seconds=row.read_header_timeout_seconds,
        idle_timeout_seconds=row.idle_timeout_seconds,
        shutdown_timeout_seconds=row.shutdown_timeout_seconds,
        max_body_bytes=row.max_body_bytes,
        max_grpc_reply_bytes=row.max_grpc_reply_bytes,
    )


def policy_read(row: CredentialPolicy) -> CertificatePolicy:
    return CertificatePolicy(
        row.validity_seconds, row.authority_validity_seconds, row.backdate_seconds
    )


def definition_read(value: dict[str, Any]) -> NodeDefinition:
    return NodeDefinition(
        name=value["name"],
        endpoint_url=value["endpoint_url"],
        runtime=AgentRuntime(**value["runtime"]),
        certificate_policy=CertificatePolicy(**value["certificate_policy"]),
    )


def node_read(row: Node) -> NodeRead:
    try:
        credentials = row.credentials
    except NodeCredentials.DoesNotExist:
        credentials = None
    return NodeRead(
        id=row.id,
        deployment_id=row.deployment.deployment_id,
        owner_id=row.owner_id,
        name=row.name,
        endpoint_url=row.endpoint_url,
        runtime=runtime_read(row.runtime),
        certificate_policy=policy_read(row.certificate_policy),
        credentials_ready=credentials is not None,
        certificate_expires_at=credentials.expires_at if credentials else None,
        last_reachable=row.last_reachable,
        last_checked_at=row.last_checked_at,
        last_error_code=row.last_error_code,
        uptime_seconds=row.uptime_seconds,
        last_operation_id=row.last_operation_id,
        configuration_revision=row.configuration_revision,
    )


def work_read(row: NodeOperation) -> NodeWorkRead:
    return NodeWorkRead(
        id=row.id,
        node_id=row.node_id,
        actor_id=row.actor_id,
        kind=NodeWorkKind(row.kind),
        status=OperationStatus(row.status),
        attempts=row.attempts,
        error_code=row.error_code,
        worker_pid=row.worker_pid,
        lease_until=row.lease_until,
    )


class DjangoNodeReader:
    def read(self, node_id: UUID, actor_id: int) -> NodeRead:
        try:
            row = (
                Node.objects.select_related(
                    "deployment",
                    "runtime",
                    "certificate_policy",
                    "credentials",
                )
                .defer("credentials__secrets_ciphertext")
                .get(pk=node_id, owner_id=actor_id)
            )
        except Node.DoesNotExist as error:
            raise Missing("The node was not found.") from error
        return node_read(row)

    def search(self, values: NodeSearch) -> NodePage:
        rows = (
            Node.objects.filter(owner_id=values.actor_id, name__icontains=values.query)
            .select_related(
                "deployment",
                "runtime",
                "certificate_policy",
                "credentials",
            )
            .defer("credentials__secrets_ciphertext")
            .order_by("created_at", "id")
        )
        paginator = Paginator(rows, values.page_size)
        try:
            page = paginator.page(values.page)
        except EmptyPage as error:
            raise Missing("The requested node page does not exist.") from error
        return NodePage(
            items=tuple(node_read(row) for row in page.object_list),
            count=paginator.count,
            page=values.page,
            page_size=values.page_size,
        )

    def read_work(self, node_id: UUID, operation_id: UUID, actor_id: int) -> NodeWorkRead:
        try:
            row = NodeOperation.objects.get(pk=operation_id, node_id=node_id, actor_id=actor_id)
        except NodeOperation.DoesNotExist as error:
            raise Missing("The node operation was not found.") from error
        return work_read(row)

    def credentials(self, node_id: UUID, actor_id: int) -> IssuedCredentials:
        try:
            row = NodeCredentials.objects.get(node_id=node_id, node__owner_id=actor_id)
        except NodeCredentials.DoesNotExist as error:
            raise Missing("The node credentials were not found.") from error
        try:
            private = json.loads(credential_cipher().decrypt(bytes(row.secrets_ciphertext)))
            keys = CredentialPrivateKeys(**private)
        except (InvalidToken, ValueError, TypeError) as error:
            raise Conflict(
                "Stored node credentials could not be opened with this installation key."
            ) from error
        return IssuedCredentials(
            authority_certificate=row.authority_certificate,
            server_certificate=row.server_certificate,
            control_certificate=row.control_certificate,
            private_keys=keys,
            expires_at=row.expires_at,
        )
