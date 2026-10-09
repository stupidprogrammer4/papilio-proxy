from dishka import Provider, Scope, provide

from src.modules.billing.sms_origins.app.accounts import (
    ReceivingAliasService,
    ReceivingBindingCommand,
)
from src.modules.billing.sms_origins.app.candidates import (
    SmsSettlementCandidateQuery,
)
from src.modules.billing.sms_origins.app.capabilities import (
    SmsOriginCapabilityQuery,
)
from src.modules.billing.sms_origins.app.commands import (
    ReceivingRealmCommand,
    SmsParserCommand,
)
from src.modules.billing.sms_origins.app.financial_commands import (
    SmsOriginSettlementCommand,
)
from src.modules.billing.sms_origins.app.financial_services import (
    SmsSettlementClaimService,
    SmsSettlementDecisionService,
    SmsSettlementService,
)
from src.modules.billing.sms_origins.app.intake import SmsOriginIntakeQuery
from src.modules.billing.sms_origins.app.manual_guard import (
    SmsManualPaymentGuard,
)
from src.modules.billing.sms_origins.app.queries import SmsOriginQuery
from src.modules.billing.sms_origins.app.review import (
    SmsApprovedFundingQuery,
    SmsSettlementReviewQuery,
)
from src.modules.billing.sms_origins.app.services import (
    ReceivingRealmService,
    SmsOriginAdmissionService,
    SmsParserProfileService,
    SmsParserRevisionService,
)
from src.modules.billing.sms_origins.infra.financial import SmsFinancialReader
from src.modules.billing.sms_origins.infra.intake import SmsIntakeReader
from src.modules.billing.sms_origins.infra.mysql import (
    ReceivingAliasRepository,
    ReceivingRealmRepository,
    SmsOriginAdmissionRepository,
    SmsParserProfileRepository,
    SmsParserRevisionRepository,
    SmsSettlementClaimRepository,
    SmsSettlementDecisionRepository,
    SmsSettlementRepository,
)
from src.modules.billing.sms_origins.infra.readers import (
    SmsParserProfileReader,
)
from src.modules.billing.sms_origins.interfaces import (
    IReceivingAliasService,
    IReceivingBindingCommand,
    IReceivingRealmCommand,
    IReceivingRealmService,
    ISmsApprovedFundingQuery,
    ISmsManualPaymentGuard,
    ISmsOriginAdmissionService,
    ISmsOriginCapabilityQuery,
    ISmsOriginIntakeQuery,
    ISmsOriginQuery,
    ISmsOriginSettlementCommand,
    ISmsParserCommand,
    ISmsParserProfileService,
    ISmsParserRevisionService,
    ISmsSettlementCandidateQuery,
    ISmsSettlementClaimService,
    ISmsSettlementDecisionService,
    ISmsSettlementReviewQuery,
    ISmsSettlementService,
)


class SmsOriginProvider(Provider):
    scope = Scope.REQUEST
    capability_query = provide(
        SmsOriginCapabilityQuery, provides=ISmsOriginCapabilityQuery
    )

    admission_repo = provide(SmsOriginAdmissionRepository)
    profiles_repo = provide(SmsParserProfileRepository)
    revisions_repo = provide(SmsParserRevisionRepository)
    realms_repo = provide(ReceivingRealmRepository)
    profiles_reader = provide(SmsParserProfileReader)
    admission = provide(
        SmsOriginAdmissionService, provides=ISmsOriginAdmissionService
    )
    profiles = provide(
        SmsParserProfileService, provides=ISmsParserProfileService
    )
    revisions = provide(
        SmsParserRevisionService, provides=ISmsParserRevisionService
    )
    realms = provide(ReceivingRealmService, provides=IReceivingRealmService)
    parser_command = provide(SmsParserCommand, provides=ISmsParserCommand)
    realm_command = provide(
        ReceivingRealmCommand, provides=IReceivingRealmCommand
    )
    query = provide(SmsOriginQuery, provides=ISmsOriginQuery)
    alias_repo = provide(ReceivingAliasRepository)
    alias_service = provide(
        ReceivingAliasService, provides=IReceivingAliasService
    )
    binding_command = provide(
        ReceivingBindingCommand, provides=IReceivingBindingCommand
    )
    intake_reader = provide(SmsIntakeReader)
    intake_query = provide(
        SmsOriginIntakeQuery, provides=ISmsOriginIntakeQuery
    )

    settlement_repo = provide(SmsSettlementRepository)
    claims_repo = provide(SmsSettlementClaimRepository)
    decisions_repo = provide(SmsSettlementDecisionRepository)
    financial_reader = provide(SmsFinancialReader)
    settlements = provide(SmsSettlementService, provides=ISmsSettlementService)
    claims = provide(
        SmsSettlementClaimService, provides=ISmsSettlementClaimService
    )
    decisions = provide(
        SmsSettlementDecisionService, provides=ISmsSettlementDecisionService
    )

    manual_guard = provide(
        SmsManualPaymentGuard, provides=ISmsManualPaymentGuard
    )

    financial_command = provide(
        SmsOriginSettlementCommand, provides=ISmsOriginSettlementCommand
    )
    review_query = provide(
        SmsSettlementReviewQuery, provides=ISmsSettlementReviewQuery
    )

    candidate_query = provide(
        SmsSettlementCandidateQuery, provides=ISmsSettlementCandidateQuery
    )

    funding_query = provide(
        SmsApprovedFundingQuery, provides=ISmsApprovedFundingQuery
    )
