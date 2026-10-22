"""Native declarative registered-core API fields."""

from rest_framework import serializers


class CoreInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    node_id = serializers.UUIDField()
    name = serializers.CharField(max_length=80)
    default_user_level = serializers.IntegerField(min_value=0, max_value=4294967295, default=0)


class XraySettingsSerializer(serializers.Serializer):
    default_user_level = serializers.IntegerField()


class CoreSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    owner_id = serializers.IntegerField()
    node_id = serializers.UUIDField()
    kind = serializers.CharField()
    name = serializers.CharField()
    xray = XraySettingsSerializer()


class InboundInputSerializer(serializers.Serializer):
    request_key = serializers.UUIDField()
    tag = serializers.CharField(max_length=255, trim_whitespace=False)
    public_host = serializers.CharField(max_length=255, trim_whitespace=False)
    port = serializers.IntegerField(min_value=1, max_value=65535)


class InboundSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    core_id = serializers.UUIDField()
    tag = serializers.CharField()
    public_host = serializers.CharField()
    port = serializers.IntegerField()


class SearchSerializer(serializers.Serializer):
    q = serializers.CharField(default="", allow_blank=True)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, default=20)


class CorePageSerializer(serializers.Serializer):
    items = CoreSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class InboundPageSerializer(serializers.Serializer):
    items = InboundSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
