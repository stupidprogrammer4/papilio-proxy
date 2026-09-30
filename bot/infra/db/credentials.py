from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from bot.infra.db.models import EncryptedCredentialModel
from bot.infra.db.pool import create_mysql_engine
from bot.models.credentials import CredentialStorageError, KpayCredentials

KPAY_USERNAME_NAME = "kpay.username"
KPAY_PASSWORD_NAME = "kpay.password"
KPAY_ACCESS_TOKEN_NAME = "kpay.access_token"
KPAY_REFRESH_TOKEN_NAME = "kpay.refresh_token"


class MysqlCredentialVault:
    """Stores encrypted credential values; the Fernet key is never placed in MySQL."""

    def __init__(self, database_url: str, encryption_key: str) -> None:
        try:
            self._fernet = Fernet(encryption_key.encode())
        except ValueError as exc:
            raise CredentialStorageError("کلید رمزگذاری credential معتبر نیست.") from exc
        self._engine = create_mysql_engine(database_url)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def close(self) -> None:
        await self._engine.dispose()

    async def put(self, name: str, value: str) -> None:
        if not name or not value:
            raise CredentialStorageError("نام و مقدار credential نباید خالی باشند.")
        ciphertext = self._fernet.encrypt(value.encode()).decode()
        statement = insert(EncryptedCredentialModel).values(name=name, ciphertext=ciphertext)
        statement = statement.on_duplicate_key_update(ciphertext=statement.inserted.ciphertext)
        async with self._session_factory() as session, session.begin():
            await session.execute(statement)

    async def get(self, name: str) -> str | None:
        statement = select(EncryptedCredentialModel.ciphertext).where(
            EncryptedCredentialModel.name == name
        )
        async with self._session_factory() as session:
            ciphertext = await session.scalar(statement)
        if ciphertext is None:
            return None
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise CredentialStorageError("credential رمزگشایی نشد.") from exc

    async def save_kpay_credentials(self, credentials: KpayCredentials) -> None:
        await self.put(KPAY_USERNAME_NAME, credentials.username)
        await self.put(KPAY_PASSWORD_NAME, credentials.password)

    async def load_kpay_credentials(self) -> KpayCredentials | None:
        username = await self.get(KPAY_USERNAME_NAME)
        password = await self.get(KPAY_PASSWORD_NAME)
        if username is None and password is None:
            return None
        if username is None or password is None:
            raise CredentialStorageError("credentialهای KPay ناقص هستند.")
        return KpayCredentials(username=username, password=password)

    async def save_kpay_tokens(self, access_token: str, refresh_token: str | None) -> None:
        await self.put(KPAY_ACCESS_TOKEN_NAME, access_token)
        if refresh_token:
            await self.put(KPAY_REFRESH_TOKEN_NAME, refresh_token)
