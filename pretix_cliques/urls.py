from django.conf.urls import url

from .views import (
    CliqueDelete, CliqueDetail, CliqueList, ControlCliqueChange, MetricsView,
    OrderCliqueChange, RaffleOverrideChange, RaffleView, RaffleRejectView, StatsView
)

urlpatterns = [
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/orders/(?P<code>[0-9A-Z]+)/clique/chance$',
        RaffleOverrideChange.as_view(),
        name='control.order.raffle.override'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/orders/(?P<code>[0-9A-Z]+)/clique$',
        ControlCliqueChange.as_view(),
        name='control.order.clique.modify'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/cliques/stats/$',
        StatsView.as_view(), name='event.stats'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/cliques/raffle/$',
        RaffleView.as_view(), name='event.raffle'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/cliques/raffle/reject/$',
        RaffleRejectView.as_view(), name='event.raffle.reject'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/cliques/$',
        CliqueList.as_view(), name='event.cliques.list'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/cliques/(?P<pk>\d+)/$',
        CliqueDetail.as_view(), name='event.cliques.detail'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/cliques/(?P<pk>\d+)/delete$',
        CliqueDelete.as_view(), name='event.cliques.delete'),
    url(r'^metrics/cliques/(?P<organizer>[^/]+)/(?P<event>[^/]+)/$',
        MetricsView.as_view(), name='metrics'),
]

event_patterns = [
    url(r'^order/(?P<order>[^/]+)/(?P<secret>[A-Za-z0-9]+)/clique/modify$',
        OrderCliqueChange.as_view(),
        name='event.order.clique.modify'),
]
