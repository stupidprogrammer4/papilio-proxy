"""The public connectivity capability observes actual mTLS/core facts within owner scope."""

import pytest
from django.contrib.auth.models import User
from django.db import connection
from test_node_user_control import native_control as native_control

from papilio_panel.modules.nodes.domain import XrayApply
from papilio_panel.modules.nodes.models import Node, NodeCredentials
from papilio_panel.shared.errors import AuthenticationRejected, Missing

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.runtime]


def test_connectivity_observation_keeps_credentials_and_denies_foreign_or_revoked_owners(
    native_control: tuple[XrayApply, int, str],
) -> None:
    from papilio_panel.modules.nodes.domain import NodeProbe
    from papilio_panel.modules.nodes.providers import connectivity

    values, _, _ = native_control
    secret = bytes(NodeCredentials.objects.get(node_id=values.node_id).secrets_ciphertext)
    observed = connectivity.probe(NodeProbe(values.actor_id, values.node_id))
    assert observed.reachable and observed.uptime_seconds is not None
    connection.close()
    row = Node.objects.get(pk=values.node_id)
    assert row.last_reachable is True and row.last_checked_at is not None
    assert row.uptime_seconds == observed.uptime_seconds
    before = row.last_checked_at
    foreign = User.objects.create_superuser(
        "other-probe-owner", password="isolated-probe-password-975!"
    )
    with pytest.raises(Missing):
        connectivity.probe(NodeProbe(foreign.pk, values.node_id))
    User.objects.filter(pk=values.actor_id).update(is_active=False)
    with pytest.raises(AuthenticationRejected):
        connectivity.probe(NodeProbe(values.actor_id, values.node_id))
    connection.close()
    row.refresh_from_db()
    assert row.last_checked_at == before
    assert bytes(NodeCredentials.objects.get(node_id=values.node_id).secrets_ciphertext) == secret
