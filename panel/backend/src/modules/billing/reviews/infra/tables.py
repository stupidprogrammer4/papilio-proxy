from papilio.infra.db.table import BaseTable

from src.modules.billing.reviews.domain.models import PaymentReviewModel


class PaymentReviewTable(PaymentReviewModel, BaseTable, table=True):
    table_name = "tbl_payment_reviews"
