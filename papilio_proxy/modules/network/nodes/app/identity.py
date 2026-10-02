from hashlib import sha256


def node_email(subscription_id: str) -> str:
    """Opaque accounting key shared by every transport of one entitlement."""
    return "ent-" + sha256(subscription_id.encode()).hexdigest()[:48]
