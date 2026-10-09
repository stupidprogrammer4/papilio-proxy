from dishka import Provider, Scope, provide

from src.modules.billing.sms.app.candidates import SmsCandidateQuery
from src.modules.billing.sms.app.services import SmsService
from src.modules.billing.sms.infra.mysql import SmsRepository
from src.modules.billing.sms.infra.readers import SmsCandidateReader
from src.modules.billing.sms.interfaces import ISmsCandidateQuery, ISmsService


class SmsProvider(Provider):
    scope = Scope.REQUEST
    repository = provide(SmsRepository)
    service = provide(SmsService, provides=ISmsService)
    candidate_reader = provide(SmsCandidateReader)
    candidates = provide(SmsCandidateQuery, provides=ISmsCandidateQuery)
