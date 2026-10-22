"""Native service request and read serializers with protected credential output."""

from rest_framework import serializers


class ServiceInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    name = serializers.CharField(max_length=80)
    core_id = serializers.UUIDField()
    inbound_id = serializers.UUIDField()
    user_level = serializers.IntegerField(
        min_value=0, max_value=4294967295, default=None, allow_null=True
    )
    identifier = serializers.UUIDField(default=None, allow_null=True, write_only=True)


class ServiceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    owner_id = serializers.IntegerField()
    core_id = serializers.UUIDField()
    inbound_id = serializers.UUIDField()
    name = serializers.CharField()
    status = serializers.CharField()
    attempts = serializers.IntegerField()
    error_code = serializers.CharField(allow_null=True)
    worker_pid = serializers.IntegerField(allow_null=True)
    lease_until = serializers.DateTimeField(allow_null=True)


class SearchSerializer(serializers.Serializer):
    q = serializers.CharField(default="", allow_blank=True)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, default=20)


class ServicePageSerializer(serializers.Serializer):
    items = ServiceSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class SubscriptionInputSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=1024, trim_whitespace=False)


class SubscriptionLinkSerializer(serializers.Serializer):
    url = serializers.URLField()
