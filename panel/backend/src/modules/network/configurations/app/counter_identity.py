import hashlib


def profile_counter_identity(profile_id: int, generation: int) -> str:
    value = f"papilio-profile:{profile_id}:{generation}".encode("ascii")
    return "papilio-" + hashlib.sha256(value).hexdigest()
