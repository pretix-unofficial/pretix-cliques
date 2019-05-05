from django.conf.urls import url
from .views import OrderCliqueChange, ControlCliqueChange, CliqueList, CliqueDetail, CliqueDelete


urlpatterns = [
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/orders/(?P<code>[0-9A-Z]+)/clique$',
        ControlCliqueChange.as_view(),
        name='control.order.clique.modify'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/cliques/$',
        CliqueList.as_view(), name='event.cliques.list'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/cliques/(?P<pk>\d+)/$',
        CliqueDetail.as_view(), name='event.cliques.detail'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/cliques/(?P<pk>\d+)/delete$',
        CliqueDelete.as_view(), name='event.cliques.delete'),
]

event_patterns = [
    url(r'^order/(?P<order>[^/]+)/(?P<secret>[A-Za-z0-9]+)/clique/modify$',
        OrderCliqueChange.as_view(),
        name='event.order.clique.modify'),
]

