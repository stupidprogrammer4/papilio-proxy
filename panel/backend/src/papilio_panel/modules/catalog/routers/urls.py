"""Product identity and immutable offer paths."""

from django.urls import path

from .products import ProductOfferView, ProductsView, ProductView

urlpatterns = [
    path("products", ProductsView.as_view()),
    path("products/<uuid:product_id>", ProductView.as_view()),
    path("product-offers/<uuid:offer_id>", ProductOfferView.as_view()),
]
