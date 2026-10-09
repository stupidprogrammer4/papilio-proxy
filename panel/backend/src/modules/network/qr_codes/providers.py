from dishka import Provider, Scope, provide

from src.modules.network.qr_codes.app.queries import SubscriptionQrQuery
from src.modules.network.qr_codes.interfaces import ISubscriptionQrQuery


class QrProvider(Provider):
    scope = Scope.REQUEST
    query = provide(SubscriptionQrQuery, provides=ISubscriptionQrQuery)
