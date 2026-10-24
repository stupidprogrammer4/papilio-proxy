"""Public declarative node configuration schemas for native adapters."""

from dataclasses import asdict
from typing import Any

from rest_framework import serializers

from .domain import AgentRuntime, CertificatePolicy, NodeDefinition


class AgentRuntimeSerializer(serializers.Serializer):
    listen_address = serializers.CharField(default=AgentRuntime.listen_address, max_length=255)
    xray_api_address = serializers.CharField(default=AgentRuntime.xray_api_address, max_length=255)
    request_timeout_seconds = serializers.IntegerField(
        default=AgentRuntime.request_timeout_seconds, min_value=1, max_value=2147483647
    )
    read_header_timeout_seconds = serializers.IntegerField(
        default=AgentRuntime.read_header_timeout_seconds, min_value=1, max_value=2147483647
    )
    idle_timeout_seconds = serializers.IntegerField(
        default=AgentRuntime.idle_timeout_seconds, min_value=1, max_value=2147483647
    )
    shutdown_timeout_seconds = serializers.IntegerField(
        default=AgentRuntime.shutdown_timeout_seconds, min_value=1, max_value=2147483647
    )
    max_body_bytes = serializers.IntegerField(
        default=AgentRuntime.max_body_bytes, min_value=1, max_value=9223372036854775807
    )
    max_grpc_reply_bytes = serializers.IntegerField(
        default=AgentRuntime.max_grpc_reply_bytes, min_value=1, max_value=2147483647
    )


class CertificatePolicySerializer(serializers.Serializer):
    validity_seconds = serializers.IntegerField(
        default=CertificatePolicy.validity_seconds, min_value=1, max_value=2147483647
    )
    authority_validity_seconds = serializers.IntegerField(
        default=CertificatePolicy.authority_validity_seconds, min_value=1, max_value=2147483647
    )
    backdate_seconds = serializers.IntegerField(
        default=CertificatePolicy.backdate_seconds, min_value=0, max_value=2147483647
    )


class NodeDefinitionSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=80)
    endpoint_url = serializers.URLField(max_length=500)
    runtime = AgentRuntimeSerializer(default=lambda: asdict(AgentRuntime()))
    certificate_policy = CertificatePolicySerializer(default=lambda: asdict(CertificatePolicy()))

    def to_internal_value(self, data: Any) -> NodeDefinition:
        values = super().to_internal_value(data)
        return NodeDefinition(
            values["name"],
            values["endpoint_url"],
            AgentRuntime(**values["runtime"]),
            CertificatePolicy(**values["certificate_policy"]),
        )
