from dishka import Provider, Scope, provide

from src.modules.billing.reviews.app.commands import PaymentReviewCommand
from src.modules.billing.reviews.app.queries import PaymentReviewQuery
from src.modules.billing.reviews.infra.mysql import PaymentReviewRepository
from src.modules.billing.reviews.infra.readers import PaymentReviewReader
from src.modules.billing.reviews.interfaces import (
    IPaymentReviewCommand,
    IPaymentReviewQuery,
)
from src.modules.billing.reviews.tasks.schedulers.checks import (
    CheckPaymentReview,
    ScanPaymentReview,
)


class PaymentReviewProvider(Provider):
    scope = Scope.REQUEST
    repository = provide(PaymentReviewRepository)
    reader = provide(PaymentReviewReader)
    command = provide(PaymentReviewCommand, provides=IPaymentReviewCommand)
    query = provide(PaymentReviewQuery, provides=IPaymentReviewQuery)
    check_task = provide(CheckPaymentReview)
    scan_task = provide(ScanPaymentReview)
