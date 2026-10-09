import asyncio
import hashlib
import hmac

from papilio.security.passwords import PasswordHasher

from src.config.settings import PapilioSettings


class Passwords:
    def __init__(self, settings: PapilioSettings) -> None:
        if settings.crypto is None:
            raise RuntimeError("Configure native Papilio password pepper")
        self.native = PasswordHasher(settings.crypto.password_salt)

    async def hash(self, password: str) -> str:
        result = await self.native.hash(password)
        return result

    async def verify(self, password: str, stored: str) -> bool:
        if not stored.startswith("scrypt$"):
            result = await self.native.verify(password, stored)
            return result
        try:
            algorithm, salt_hex, digest_hex = stored.split("$", 2)
            if algorithm != "scrypt":
                return False
            salt, digest = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
        except ValueError:
            return False
        candidate = await asyncio.to_thread(
            hashlib.scrypt, password.encode(), salt=salt, n=2**14, r=8, p=1
        )
        return hmac.compare_digest(candidate, digest)
