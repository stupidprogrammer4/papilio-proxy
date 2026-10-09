from papilio.infra.db.table import BaseTable

from src.modules.billing.sms_devices.domain.models import SmsDeviceModel


class SmsDeviceTable(SmsDeviceModel, BaseTable, table=True):
    pass
