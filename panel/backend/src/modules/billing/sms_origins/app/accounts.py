import asyncio
import hashlib
import json

from papilio.infra.db.tools.decorators import transactional

from src.config.pagination import ServicePage, service_page
from src.config.settings import PapilioSettings
from src.modules.billing.destinations.domain.results import DestinationDetails
from src.modules.billing.destinations.interfaces import (
    IPaymentDestinationService,
)
from src.modules.billing.sms_origins.app.services import (
    capacity,
    paging,
    sms_conflict,
    sms_not_found,
)
from src.modules.billing.sms_origins.domain.contracts import (
    DestinationBindingWrite,
    SmsOriginSearch,
)
from src.modules.billing.sms_origins.domain.models import ReceivingAliasModel
from src.modules.billing.sms_origins.infra.mysql import (
    ReceivingAliasRepository,
)
from src.modules.billing.sms_origins.interfaces import (
    IReceivingAliasService,
    IReceivingRealmService,
    ISmsOriginAdmissionService,
)


def account_digest(kind: str, account: str, bank_namespace: str | None) -> str:
    normalized = account.replace(" ", "").replace("-", "").upper()
    if kind == "bank_account":
        if (
            not bank_namespace
            or not normalized.isascii()
            or not normalized.isdigit()
        ):
            raise ValueError("sms_receiving_bank_namespace_required")
    payload = {
        "normalization_revision": 1,
        "kind": kind,
        "account": normalized,
        "bank_namespace": bank_namespace.strip().casefold()
        if kind == "bank_account" and bank_namespace
        else None,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


class ReceivingAliasService:
    def __init__(
        self, repo: ReceivingAliasRepository, settings: PapilioSettings
    ) -> None:
        self.repo, self.settings = repo, settings

    async def get(self, id: int) -> ReceivingAliasModel:
        row = await self.repo.get_by_id(id)
        if row is None:
            raise sms_not_found("sms_receiving_alias_not_found")
        return row

    async def resolve(
        self, realm_id: int, kind: str, digest: str, namespace: str | None
    ) -> ReceivingAliasModel:
        existing = await self.repo.by_account(digest)
        if existing is not None:
            if existing.realm_id != realm_id:
                raise sms_conflict("sms_receiving_alias_realm_conflict")
            return existing
        maximum = capacity(self.settings).max_aliases_per_realm
        ids = await self.repo.admission_ids(realm_id, maximum)
        if len(ids) >= maximum:
            raise sms_conflict("sms_receiving_alias_capacity")
        row = await self.repo.create(
            ReceivingAliasModel(
                realm_id=realm_id,
                kind=kind,
                account_sha256=digest,
                bank_namespace=namespace,
            )
        )
        return row

    async def search(
        self, realm_id: int, data: SmsOriginSearch
    ) -> ServicePage[ReceivingAliasModel]:
        limit = paging(self.settings, data)
        rows = await self.repo.page(realm_id, (data.page - 1) * limit, limit)
        return service_page(rows, limit)


class ReceivingBindingCommand:
    def __init__(
        self,
        admission: ISmsOriginAdmissionService,
        realms: IReceivingRealmService,
        aliases: IReceivingAliasService,
        destinations: IPaymentDestinationService,
        settings: PapilioSettings,
    ) -> None:
        (
            self.admission,
            self.realms,
            self.aliases,
            self.destinations,
            self.settings,
        ) = admission, realms, aliases, destinations, settings

    @transactional
    async def assign(
        self, id: int, data: DestinationBindingWrite
    ) -> DestinationDetails:
        capacity(self.settings)
        await self.admission.acquire()
        realm = await self.realms.locked(data.realm_id)
        if realm.revision != data.expected_realm_revision:
            raise sms_conflict("sms_receiving_realm_revision_conflict")
        destination = await self.destinations.locked(id)
        if destination.revision != data.expected_destination_revision:
            raise sms_conflict("payment_destination_revision_conflict")
        if not realm.is_active:
            raise sms_conflict("sms_receiving_realm_unavailable")
        namespace = (
            data.bank_namespace.strip().casefold()
            if data.bank_namespace is not None
            else None
        )
        try:
            digest = await asyncio.to_thread(
                account_digest,
                destination.kind,
                destination.account,
                namespace,
            )
        except ValueError as error:
            raise sms_conflict(str(error)) from error
        alias = await self.aliases.resolve(
            realm.id, destination.kind, digest, namespace
        )
        result = await self.destinations.assign_receiving_alias(
            id, destination.revision, alias.id
        )
        return result
