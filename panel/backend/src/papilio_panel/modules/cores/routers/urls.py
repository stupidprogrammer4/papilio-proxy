"""Registered core resources and their owned Xray inbounds."""

from django.urls import path

from .cores import CoresView, CoreView, XrayCoresView, XrayInboundsView, XrayInboundView

urlpatterns = [
    path("cores", CoresView.as_view()),
    path("cores/xray", XrayCoresView.as_view()),
    path("cores/<uuid:core_id>", CoreView.as_view()),
    path("cores/<uuid:core_id>/xray/inbounds", XrayInboundsView.as_view()),
    path("cores/<uuid:core_id>/xray/inbounds/<uuid:inbound_id>", XrayInboundView.as_view()),
]
