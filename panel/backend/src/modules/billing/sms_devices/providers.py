from dishka import Provider, Scope, provide

from src.modules.billing.sms_devices.app.services import SmsDeviceService
from src.modules.billing.sms_devices.app.settlement import SmsSettlementCommand
from src.modules.billing.sms_devices.infra.mysql import SmsDeviceRepository
from src.modules.billing.sms_devices.infra.settlement import (
    SmsSettlementReader,
)
from src.modules.billing.sms_devices.interfaces import (
    ISmsDeviceService,
    ISmsSettlementCommand,
)


class SmsDeviceProvider(Provider):
    scope = Scope.REQUEST
    settlement_reader = provide(SmsSettlementReader)
    settlement_command = provide(
        SmsSettlementCommand, provides=ISmsSettlementCommand
    )
    repo = provide(SmsDeviceRepository)
    service = provide(SmsDeviceService, provides=ISmsDeviceService)
