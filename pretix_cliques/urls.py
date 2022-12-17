from django.urls import path, re_path

from .views import (
    CliqueDelete, CliqueDetail, CliqueList, ControlCliqueChange, MetricsView,
    OrderCliqueChange, RaffleOverrideChange, RaffleView, RaffleRejectView, StatsView
)

urlpatterns = [
    re_path(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/orders/(?P<code>[0-9A-Z]+)/clique/chance$',
            RaffleOverrideChange.as_view(),
            name='control.order.raffle.override'),
    re_path(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/orders/(?P<code>[0-9A-Z]+)/clique$',
            ControlCliqueChange.as_view(),
            name='control.order.clique.modify'),
    path('control/event/<str:organizer>/<str:event>/cliques/stats/',
         StatsView.as_view(), name='event.stats'),
    path('control/event/<str:organizer>/<str:event>/cliques/raffle/',
         RaffleView.as_view(), name='event.raffle'),
    path('control/event/<str:organizer>/<str:event>/cliques/raffle/reject/',
         RaffleRejectView.as_view(), name='event.raffle.reject'),
    path('control/event/<str:organizer>/<str:event>/cliques/',
         CliqueList.as_view(), name='event.cliques.list'),
    path('control/event/<str:organizer>/<str:event>/cliques/<int:pk>/',
         CliqueDetail.as_view(), name='event.cliques.detail'),
    path('control/event/<str:organizer>/<str:event>/cliques/<int:pk>/delete',
         CliqueDelete.as_view(), name='event.cliques.delete'),
    path('metrics/cliques/<str:organizer>/<str:event>/',
         MetricsView.as_view(), name='metrics'),
]

event_patterns = [
    re_path(r'^order/(?P<order>[^/]+)/(?P<secret>[A-Za-z0-9]+)/clique/modify$',
            OrderCliqueChange.as_view(),
            name='event.order.clique.modify'),
]
