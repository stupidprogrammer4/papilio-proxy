"""Native explicit HTTP schemas for writable node data and public results."""

from dataclasses import asdict

from rest_framework import serializers
from rest_framework.fields import empty

from ..domain import AgentRuntime, CertificatePolicy, NodeWorkKind
from ..schemas import AgentRuntimeSerializer, CertificatePolicySerializer


class NodeDefaultsSerializer(serializers.Serializer):
    runtime = AgentRuntimeSerializer()
    certificate_policy = CertificatePolicySerializer()


class AgentRuntimeUpdateSerializer(AgentRuntimeSerializer):
    def get_fields(self):
        fields = super().get_fields()
        for field in fields.values():
            field.default = empty
            field.required = True
        return fields


class CertificatePolicyUpdateSerializer(CertificatePolicySerializer):
    def get_fields(self):
        fields = super().get_fields()
        for field in fields.values():
            field.default = empty
            field.required = True
        return fields


class NodeInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    name = serializers.CharField(max_length=80)
    endpoint_url = serializers.URLField(max_length=500)
    runtime = AgentRuntimeSerializer(default=lambda: asdict(AgentRuntime()))
    certificate_policy = CertificatePolicySerializer(default=lambda: asdict(CertificatePolicy()))


class NodeSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    deployment_id = serializers.UUIDField()
    owner_id = serializers.IntegerField()
    name = serializers.CharField()
    endpoint_url = serializers.URLField()
    runtime = AgentRuntimeSerializer()
    certificate_policy = CertificatePolicySerializer()
    credentials_ready = serializers.BooleanField()
    certificate_expires_at = serializers.DateTimeField(allow_null=True)
    last_reachable = serializers.BooleanField(allow_null=True)
    last_checked_at = serializers.DateTimeField(allow_null=True)
    last_error_code = serializers.CharField(allow_null=True)
    uptime_seconds = serializers.IntegerField(allow_null=True)
    last_operation_id = serializers.UUIDField(allow_null=True)
    configuration_revision = serializers.IntegerField()


class NodeConfigurationInputSerializer(serializers.Serializer):
    expected_revision = serializers.IntegerField(min_value=1)
    runtime = AgentRuntimeUpdateSerializer()
    certificate_policy = CertificatePolicyUpdateSerializer()


class WorkInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=[item.value for item in NodeWorkKind])


class WorkSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    node_id = serializers.UUIDField()
    kind = serializers.CharField()
    status = serializers.CharField()
    attempts = serializers.IntegerField()
    error_code = serializers.CharField(allow_null=True)
    worker_pid = serializers.IntegerField(allow_null=True)


class CreationSerializer(serializers.Serializer):
    node = NodeSerializer()
    operation = WorkSerializer()


class NodeSearchSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, default="", max_length=200)
    page = serializers.IntegerField(default=1, min_value=1)
    page_size = serializers.IntegerField(default=20, min_value=1, max_value=200)


class NodePageSerializer(serializers.Serializer):
    items = NodeSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
