from django import forms
from django.dispatch import receiver
from django.http import HttpRequest
from django.template.loader import get_template
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _
from pretix.base.models import Event, Order, OrderPosition
from pretix.base.signals import logentry_display, order_placed
from pretix.control.forms.filter import FilterForm
from pretix.control.signals import nav_event, order_info as control_order_info
from pretix.presale.signals import (
    checkout_confirm_page_content, checkout_flow_steps, order_info,
    order_meta_from_request,
)
from pretix.presale.views.cart import cart_session

from .checkoutflow import CliqueStep
from .models import Clique, OrderClique


@receiver(signal=checkout_flow_steps, dispatch_uid="clique_checkout_step")
def signal_checkout_flow_steps(sender, **kwargs):
    return CliqueStep


@receiver(order_meta_from_request, dispatch_uid="clique_order_meta")
def order_meta_signal(sender: Event, request: HttpRequest, **kwargs):
    cs = cart_session(request)
    return {
        'clique_mode': cs.get('clique_mode'),
        'clique_join': cs.get('clique_join'),
        'clique_create': cs.get('clique_create'),
    }


@receiver(order_placed, dispatch_uid="clique_order_placed")
def placed_order(sender: Event, order: Order, **kwargs):
    if order.meta_info_data and order.meta_info_data.get('clique_mode') == 'create':
        try:
            c = sender.cliques.get(pk=order.meta_info_data['clique_create'])
        except Clique.DoesNotExist:
            return
        else:
            c.ordercliques.create(order=order, is_admin=True)
    elif order.meta_info_data and order.meta_info_data.get('clique_mode') == 'join':
        try:
            c = sender.cliques.get(pk=order.meta_info_data['clique_join'])
        except Clique.DoesNotExist:
            return
        else:
            c.ordercliques.create(order=order, is_admin=False)


@receiver(checkout_confirm_page_content, dispatch_uid="clique_confirm")
def confirm_page(sender: Event, request: HttpRequest, **kwargs):
    cs = cart_session(request)

    template = get_template('pretix_cliques/checkout_confirm.html')
    ctx = {
        'mode': cs.get('clique_mode'),
        'request': request,
    }
    if cs.get('clique_mode') == 'join':
        try:
            ctx['clique'] = sender.cliques.get(pk=cs.get('clique_join'))
        except Clique.DoesNotExist:
            return
    elif cs.get('clique_mode') == 'create':
        try:
            ctx['clique'] = sender.cliques.get(pk=cs.get('clique_create'))
        except Clique.DoesNotExist:
            return
    return template.render(ctx)


@receiver(order_info, dispatch_uid="clique_order_info")
def order_info(sender: Event, order: Order, **kwargs):
    template = get_template('pretix_cliques/order_info.html')

    if not order.require_approval:
        return ""

    ctx = {
        'order': order,
        'event': sender,
    }
    try:
        c = order.orderclique
        ctx['clique'] = c.clique
        ctx['is_admin'] = c.is_admin
        ctx['fellows'] = OrderPosition.objects.filter(
            order__status__in=(Order.STATUS_PENDING, Order.STATUS_PAID),
            order__orderclique__clique=c.clique,
            item__admission=True
        ).exclude(order=order)
    except OrderClique.DoesNotExist:
        pass

    return template.render(ctx)


@receiver(control_order_info, dispatch_uid="clique_control_order_info")
def control_order_info(sender: Event, request, order: Order, **kwargs):
    template = get_template('pretix_cliques/control_order_info.html')

    ctx = {
        'order': order,
        'event': sender,
        'request': request,
    }
    try:
        c = order.orderclique
        ctx['clique'] = c.clique
        ctx['is_admin'] = c.is_admin
    except OrderClique.DoesNotExist:
        pass

    return template.render(ctx, request=request)


@receiver(signal=logentry_display, dispatch_uid="clique_logentry_display")
def shipping_logentry_display(sender, logentry, **kwargs):
    if not logentry.action_type.startswith('pretix_cliques'):
        return

    plains = {
        'pretix_cliques.order.left': _('The user left a clique.'),
        'pretix_cliques.order.joined': _('The user joined a clique.'),
        'pretix_cliques.order.created': _('The user created a new clique.'),
        'pretix_cliques.order.changed': _('The user changed a clique password.'),
        'pretix_cliques.order.deleted': _('The clique has been deleted.'),
        'pretix_cliques.clique.deleted': _('The clique has been changed.'),
        'pretix_cliques.clique.changed': _('The clique has been deleted.'),
    }

    if logentry.action_type in plains:
        return plains[logentry.action_type]


@receiver(nav_event, dispatch_uid="clique_nav")
def control_nav_event(sender, request=None, **kwargs):
    url = resolve(request.path_info)
    if not request.user.has_event_permission(request.organizer, request.event, 'can_view_orders', request=request):
        return []
    return [
        {
            'label': _('Cliques'),
            'url': reverse('plugins:pretix_cliques:event.cliques.list', kwargs={
                'event': request.event.slug,
                'organizer': request.event.organizer.slug,
            }),
            'active': (url.namespace == 'plugins:pretix_cliques' and 'cliques' in url.url_name),
            'icon': 'group',
        },
        {
            'label': _('Raffle'),
            'url': reverse('plugins:pretix_cliques:event.raffle', kwargs={
                'event': request.event.slug,
                'organizer': request.event.organizer.slug,
            }),
            'active': (url.namespace == 'plugins:pretix_cliques' and ('raffle' in url.url_name or 'stats' in url.url_name)),
            'icon': 'bullseye',
        }
    ]


class CliqueSearchForm(FilterForm):
    clique_name = forms.CharField(
        label=_('Clique name'),
        required=False,
        help_text=_('Exact matches only')
    )

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event')
        super().__init__(*args, **kwargs)
        del self.fields['ordering']

    def filter_qs(self, qs):
        fdata = self.cleaned_data
        qs = super().filter_qs(qs)
        if fdata.get('clique_name'):
            qs = qs.filter(orderclique__clique__name__iexact=fdata.get('clique_name'))
        return qs


try:
    from pretix.control.signals import order_search_forms

    @receiver(order_search_forms, dispatch_uid="clique_order_search")
    def control_order_search(sender, request, **kwargs):
        return CliqueSearchForm(
            data=request.GET,
            event=sender,
            prefix='cliques',
        )


except ImportError:
    pass
