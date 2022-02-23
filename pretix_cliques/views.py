import base64
import hmac
from collections import defaultdict

from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Exists, OuterRef
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _, pgettext_lazy
from django.views import View
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.generic import DeleteView, ListView, TemplateView, FormView
from django_scopes import scopes_disabled
from pretix_cliques.tasks import run_raffle, run_rejection

from pretix import settings
from pretix.base.models import Order, SubEvent, OrderPosition, OrderRefund, Event
from pretix.base.views.metrics import unauthed_response
from pretix.base.views.tasks import AsyncAction
from pretix.control.forms.widgets import Select2
from pretix.control.permissions import EventPermissionRequiredMixin
from pretix.control.views import UpdateView
from pretix.control.views.orders import OrderView
from pretix.multidomain.urlreverse import eventreverse
from pretix.presale.views import EventViewMixin
from pretix.presale.views.order import OrderDetailMixin
from .checkoutflow import CliqueCreateForm, CliqueJoinForm
from .models import Clique, OrderClique, OrderRaffleOverride


class CliqueChangePasswordForm(forms.Form):
    password = forms.CharField(
        max_length=190,
        label=_('New clique password'),
        help_text=_("Optional"),
        min_length=3,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event')
        super().__init__(*args, **kwargs)


@method_decorator(xframe_options_exempt, 'dispatch')
class OrderCliqueChange(EventViewMixin, OrderDetailMixin, TemplateView):
    template_name = 'pretix_cliques/order_clique_change.html'

    def dispatch(self, request, *args, **kwargs):
        self.request = request

        if not self.order:
            raise Http404(_('Unknown order code or not authorized to access this order.'))

        if not self.order.can_modify_answers:
            messages.error(request, _('The clique for this order cannot be changed.'))
            return redirect(self.get_order_url())

        if self.order.status not in (Order.STATUS_PENDING, Order.STATUS_EXPIRED, Order.STATUS_PAID):
            messages.error(request, _('The clique for this order cannot be changed.'))
            return redirect(self.get_order_url())

        return super().dispatch(request, *args, **kwargs)

    @transaction.atomic
    def post(self, request, *args, **kwargs):
        self.request = request

        mode = request.POST.get("clique_mode")
        if mode == "leave":
            try:
                c = self.order.orderclique
                c.delete()
                self.order.log_action("pretix_cliques.order.left", data={
                    'clique': c.pk
                })
                messages.success(request, _('Okay, you left your clique successfully. How do you want to continue?'))
                return redirect(eventreverse(self.request.event, 'plugins:pretix_cliques:event.order.clique.modify',
                                             kwargs={
                                                 'order': self.order.code,
                                                 'secret': self.order.secret,
                                             }))
            except OrderClique.DoesNotExist:
                pass

        elif mode == "change":
            if self.change_form.is_valid():
                try:
                    c = self.order.orderclique
                    if c.is_admin:
                        c.clique.password = self.change_form.cleaned_data['password']
                        c.clique.save()
                    self.order.log_action("pretix_cliques.order.changed", data={
                        'clique': c.pk
                    })
                    messages.success(request, _('Okay, we changed the password. Make sure to tell your friends!'))
                    return redirect(self.get_order_url())
                except OrderClique.DoesNotExist:
                    pass

        elif mode == 'join':
            if self.join_form.is_valid():
                clique = self.join_form.cleaned_data['clique']
                OrderClique.objects.create(
                    clique=clique,
                    order=self.order
                )
                self.order.log_action("pretix_cliques.order.joined", data={
                    'clique': clique.pk
                })
                messages.success(request, _('Great, we saved your changes!'))
                return redirect(self.get_order_url())

        elif mode == 'create':
            if self.create_form.is_valid():
                clique = Clique(event=self.request.event)
                clique.name = self.create_form.cleaned_data['name']
                clique.password = self.create_form.cleaned_data['password']
                clique.save()
                OrderClique.objects.create(
                    clique=clique,
                    order=self.order,
                    is_admin=True
                )
                self.order.log_action("pretix_cliques.order.created", data={
                    'clique': clique.pk
                })
                messages.success(request, _('Great, we saved your changes!'))
                return redirect(self.get_order_url())
        elif mode == 'none':
            messages.success(request, _('Great, we saved your changes!'))
            return redirect(self.get_order_url())

        messages.error(self.request, _("We could not handle your input. See below for more information."))
        return self.get(request, *args, **kwargs)

    @cached_property
    def change_form(self):
        return CliqueChangePasswordForm(
            event=self.request.event,
            prefix='change',
            data=self.request.POST if self.request.method == "POST" and self.request.POST.get(
                "clique_mode") == "change" else None
        )

    @cached_property
    def create_form(self):
        return CliqueCreateForm(
            event=self.request.event,
            prefix='create',
            data=self.request.POST if self.request.method == "POST" and self.request.POST.get(
                "clique_mode") == "create" else None
        )

    @cached_property
    def join_form(self):
        return CliqueJoinForm(
            event=self.request.event,
            prefix='join',
            data=self.request.POST if self.request.method == "POST" and self.request.POST.get(
                "clique_mode") == "join" else None
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['order'] = self.order
        ctx['join_form'] = self.join_form
        ctx['create_form'] = self.create_form
        ctx['change_form'] = self.change_form

        try:
            c = self.order.orderclique
            ctx['clique'] = c.clique
            ctx['is_admin'] = c.is_admin
        except OrderClique.DoesNotExist:
            ctx['selected'] = self.request.POST.get("clique_mode", 'none')

        return ctx

    def dispatch(self, request, *args, **kwargs):
        self.request = request

        return super().dispatch(request, *args, **kwargs)


class ControlCliqueForm(forms.ModelForm):
    class Meta:
        model = OrderClique
        fields = ['clique', 'is_admin']

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event')
        super().__init__(*args, **kwargs)
        self.fields['clique'].queryset = self.event.cliques.all()


class RaffleOverrideChange(OrderView):
    permission = 'can_change_orders'

    def post(self, request, *args, **kwargs):
        mode = request.POST.get('mode')
        if mode not in dict(OrderRaffleOverride.MODE_CHOICES):
            mode = OrderRaffleOverride.MODE_NORMAL
        OrderRaffleOverride.objects.update_or_create(
            order=self.order,
            defaults={
                'mode': mode
            }
        )
        self.order.log_action('pretix_cliques.chance.changed', data={
            'mode': mode
        }, user=self.request.user)
        messages.success(request, _('Great, we saved your changes!'))
        return redirect(self.get_order_url())


class ControlCliqueChange(OrderView):
    permission = 'can_change_orders'
    template_name = 'pretix_cliques/control_order_clique_change.html'

    @cached_property
    def form(self):
        try:
            instance = self.order.orderclique
        except OrderClique.DoesNotExist:
            instance = OrderClique(order=self.order)
        return ControlCliqueForm(
            data=self.request.POST if self.request.method == "POST" else None,
            instance=instance,
            event=self.request.event
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()
        ctx['form'] = self.form
        return ctx

    def post(self, request, *args, **kwargs):
        if self.form.is_valid():
            self.form.save()
            messages.success(request, _('Great, we saved your changes!'))
            return redirect(self.get_order_url())
        messages.error(self.request, _("We could not handle your input. See below for more information."))
        return self.get(request, *args, **kwargs)


class CliqueList(EventPermissionRequiredMixin, ListView):
    permission = 'can_change_orders'
    template_name = 'pretix_cliques/control_list.html'
    context_object_name = 'cliques'
    paginate_by = 25

    def get_queryset(self):
        return self.request.event.cliques.all()


class CliqueForm(forms.ModelForm):
    class Meta:
        model = Clique
        fields = ['name', 'password']

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event')
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if Clique.objects.filter(event=self.event, name=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(
                _('Duplicate clique name'),
                code='duplicate_name'
            )
        return name


class CliqueDetail(EventPermissionRequiredMixin, UpdateView):
    permission = 'can_change_orders'
    template_name = 'pretix_cliques/control_detail.html'
    context_object_name = 'clique'
    form_class = CliqueForm

    def get_queryset(self):
        return self.request.event.cliques.all()

    def form_valid(self, form):
        form.save()
        form.instance.log_action("pretix_cliques.clique.changed", data=form.cleaned_data, user=self.request.user)
        messages.success(self.request, _('Great, we saved your changes!'))
        return redirect(reverse('plugins:pretix_cliques:event.cliques.list', kwargs={
            'organizer': self.request.organizer.slug,
            'event': self.request.event.slug,
        }))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['orders'] = self.object.ordercliques.select_related('order')
        return ctx


class CliqueDelete(EventPermissionRequiredMixin, DeleteView):
    permission = 'can_change_orders'
    template_name = 'pretix_cliques/control_delete.html'
    context_object_name = 'clique'

    def get_queryset(self):
        return self.request.event.cliques.all()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['orders'] = self.object.ordercliques.select_related('order')
        return ctx

    @transaction.atomic
    def delete(self, request, *args, **kwargs):
        o = self.object = self.get_object()
        o.log_action("pretix_cliques.clique.deleted", data={
            "name": o.name
        }, user=request.user)
        for oc in self.object.ordercliques.select_related('order'):
            oc.order.log_action("pretix_cliques.order.deleted", data={
                'clique': o.pk
            }, user=request.user)
            oc.delete()
        o.delete()
        messages.success(self.request, _('The clique has been deleted.'))
        return redirect(reverse('plugins:pretix_cliques:event.cliques.list', kwargs={
            'organizer': self.request.organizer.slug,
            'event': self.request.event.slug,
        }))


class RaffleForm(forms.Form):
    subevent = forms.ModelChoiceField(
        SubEvent.objects.none(),
        label=pgettext_lazy('subevent', 'Date'),
        required=True,
    )
    number = forms.IntegerField(
        label=_('Number of tickets to raffle'),
        help_text=_('The end result can differ by as much as the size of the largest clique'),
        required=True
    )
    max_addons = forms.IntegerField(
        label=_('Maximum number of add-on products to raffle'),
        help_text=_('Add-on tickets generally do not affect raffle results, but if this number of add-on products '
                    'was successful, additional tickets with add-on products will no longer win.'),
        required=True,
        initial=999999,
    )

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event')
        super().__init__(*args, **kwargs)

        if self.event.has_subevents:
            self.fields['subevent'].queryset = self.event.subevents.all()
            self.fields['subevent'].widget = Select2(
                attrs={
                    'data-inverse-dependency': '#id_all_subevents',
                    'data-model-select2': 'event',
                    'data-select2-url': reverse('control:event.subevents.select2', kwargs={
                        'event': self.event.slug,
                        'organizer': self.event.organizer.slug,
                    }),
                    'data-placeholder': pgettext_lazy('subevent', 'All dates')
                }
            )
            self.fields['subevent'].widget.choices = self.fields['subevent'].choices
        else:
            del self.fields['subevent']


class RejectForm(forms.Form):
    subevent = forms.ModelChoiceField(
        SubEvent.objects.none(),
        label=pgettext_lazy('subevent', 'Date'),
        required=True,
    )

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event')
        super().__init__(*args, **kwargs)

        if self.event.has_subevents:
            self.fields['subevent'].queryset = self.event.subevents.all()
            self.fields['subevent'].widget = Select2(
                attrs={
                    'data-inverse-dependency': '#id_all_subevents',
                    'data-model-select2': 'event',
                    'data-select2-url': reverse('control:event.subevents.select2', kwargs={
                        'event': self.event.slug,
                        'organizer': self.event.organizer.slug,
                    }),
                    'data-placeholder': pgettext_lazy('subevent', 'All dates')
                }
            )
            self.fields['subevent'].widget.choices = self.fields['subevent'].choices
        else:
            del self.fields['subevent']


class RaffleView(EventPermissionRequiredMixin, AsyncAction, FormView):
    template_name = 'pretix_cliques/control_raffle.html'
    permission = 'can_change_orders'
    form_class = RaffleForm
    task = run_raffle
    known_errortypes = ['OrderError']

    def get(self, request, *args, **kwargs):
        if 'async_id' in request.GET and settings.HAS_CELERY:
            return self.get_result(request)
        return FormView.get(self, request, *args, **kwargs)

    def get_form_kwargs(self):
        k = super().get_form_kwargs()
        k['event'] = self.request.event
        return k

    def form_valid(self, form):
        return self.do(
            self.request.event.pk,
            subevent_id=form.cleaned_data['subevent'].pk if form.cleaned_data.get('subevent') else None,
            user_id=self.request.user.pk,
            raffle_size=form.cleaned_data['number'],
            max_addons=form.cleaned_data['max_addons'],
        )

    def get_success_message(self, value):
        return _('The raffle has been performed, {count} orders have been approved.').format(count=value)

    def get_success_url(self, value):
        return reverse('plugins:pretix_cliques:event.raffle', kwargs={
            'organizer': self.request.organizer.slug,
            'event': self.request.event.slug,
        })

    def get_error_url(self):
        return reverse('plugins:pretix_cliques:event.raffle', kwargs={
            'organizer': self.request.organizer.slug,
            'event': self.request.event.slug,
        })

    def get_error_message(self, exception):
        if isinstance(exception, str):
            return exception
        return super().get_error_message(exception)

    def form_invalid(self, form):
        messages.error(self.request, _('Your input was not valid.'))
        return super().form_invalid(form)


class RaffleRejectView(EventPermissionRequiredMixin, AsyncAction, FormView):
    template_name = 'pretix_cliques/control_raffle_reject.html'
    permission = 'can_change_orders'
    form_class = RejectForm
    task = run_rejection
    known_errortypes = ['OrderError']

    def get(self, request, *args, **kwargs):
        if 'async_id' in request.GET and settings.HAS_CELERY:
            return self.get_result(request)
        return FormView.get(self, request, *args, **kwargs)

    def get_form_kwargs(self):
        k = super().get_form_kwargs()
        k['event'] = self.request.event
        return k

    def form_valid(self, form):
        return self.do(
            self.request.event.pk,
            subevent_id=form.cleaned_data['subevent'].pk if form.cleaned_data.get('subevent') else None,
            user_id=self.request.user.pk,
        )

    def get_success_message(self, value):
        return _('{count} orders have been rejected.').format(count=value)

    def get_success_url(self, value):
        return reverse('plugins:pretix_cliques:event.raffle.reject', kwargs={
            'organizer': self.request.organizer.slug,
            'event': self.request.event.slug,
        })

    def get_error_url(self):
        return reverse('plugins:pretix_cliques:event.raffle.reject', kwargs={
            'organizer': self.request.organizer.slug,
            'event': self.request.event.slug,
        })

    def get_error_message(self, exception):
        if isinstance(exception, str):
            return exception
        return super().get_error_message(exception)

    def form_invalid(self, form):
        messages.error(self.request, _('Your input was not valid.'))
        return super().form_invalid(form)


class StatsMixin:
    def get_ticket_stats(self, event):
        qs = OrderPosition.objects.filter(
            order__event=event,
        ).annotate(
            has_clique=Exists(OrderClique.objects.filter(order_id=OuterRef('order_id')))
        )
        return [
            {
                'id': 'tickets_total',
                'label': _('All tickets, total'),
                'qs': qs.filter(order__status=Order.STATUS_PENDING, order__require_approval=True),
                'qs_cliq': True
            },
            {
                'id': 'tickets_registered',
                'label': _('Tickets registered for raffle'),
                'qs': qs.filter(order__status=Order.STATUS_PENDING, order__require_approval=True),
                'qs_cliq': True
            },
            {
                'id': 'tickets_approved',
                'label': _('Tickets in approved orders (regardless of payment status)'),
                'qs': qs.filter(order__require_approval=False),
                'qs_cliq': True
            },
            {
                'id': 'tickets_paid',
                'label': _('Tickets in paid orders'),
                'qs': qs.filter(order__require_approval=False, order__status=Order.STATUS_PAID),
            },
            {
                'id': 'tickets_pending',
                'label': _('Tickets in pending orders'),
                'qs': qs.filter(order__require_approval=False, order__status=Order.STATUS_PENDING),
            },
            {
                'id': 'tickets_canceled',
                'label': _('Tickets in canceled orders (except the ones not chosen in raffle)'),
                'qs': qs.filter(order__require_approval=False, order__status=Order.STATUS_CANCELED),
            },
            {
                'id': 'tickets_canceled_refunded',
                'label': _('Tickets in canceled and at least partially refunded orders'),
                'qs': qs.annotate(
                    has_refund=Exists(OrderRefund.objects.filter(order_id=OuterRef('order_id'), state__in=[OrderRefund.REFUND_STATE_DONE]))
                ).filter(
                    price__gt=0, order__status=Order.STATUS_CANCELED, has_refund=True
                ),
            },
            {
                'id': 'tickets_denied',
                'label': _('Tickets denied (not chosen in raffle)'),
                'qs': qs.filter(order__require_approval=True, order__status=Order.STATUS_CANCELED),
                'qs_cliq': True
            },
        ]


class StatsView(StatsMixin, EventPermissionRequiredMixin, TemplateView):
    template_name = 'pretix_cliques/control_stats.html'
    permission = 'can_view_orders'

    def get_context_data(self, **kwargs):

        def qs_by_item(qs):
            d = defaultdict(lambda: defaultdict(lambda: 0))
            for r in qs:
                d[r['item']][r['subevent']] = r['c']
            return d

        def qs_by_clique(qs):
            d = defaultdict(lambda: defaultdict(lambda: 0))
            for r in qs:
                d[r['has_clique']][r['subevent']] = r['c']
            return d

        def qs_by_unique_clique(qs):
            d = defaultdict(lambda: defaultdict(lambda: 0))
            for r in qs:
                d[r['has_clique']][r['subevent']] = r['cc']
            return d

        def qs_by_subevent(qs):
            d = defaultdict(lambda: defaultdict(lambda: 0))
            for r in qs:
                d[r['subevent']][r['item']] = r['c']
            return d

        ctx = super().get_context_data()
        ctx['subevents'] = self.request.event.subevents.all()
        ctx['items'] = self.request.event.items.all()
        ctx['ticket_stats'] = []
        for d in self.get_ticket_stats(self.request.event):
            qs = list(d['qs'].order_by().values('subevent', 'item').annotate(c=Count('*')))
            if d.get('qs_cliq'):
                qsc = list(d['qs'].order_by().values('subevent', 'has_clique').annotate(c=Count('*'), cc=Count('order__orderclique__clique', distinct=True)))
                c1 = qs_by_clique(qsc)
                c2 = qs_by_unique_clique(qsc)
            else:
                c1 = c2 = None

            ctx['ticket_stats'].append((
                d['label'],
                qs_by_item(qs),
                qs_by_subevent(qs),
                c1,
                c2
            ))
        return ctx


class MetricsView(StatsMixin, View):

    @scopes_disabled()
    def get(self, request, organizer, event):
        event = get_object_or_404(Event, slug=event, organizer__slug=organizer)
        if not settings.METRICS_ENABLED:
            return unauthed_response()

        # check if the user is properly authorized:
        if "Authorization" not in request.headers:
            return unauthed_response()

        method, credentials = request.headers["Authorization"].split(" ", 1)
        if method.lower() != "basic":
            return unauthed_response()

        user, passphrase = base64.b64decode(credentials.strip()).decode().split(":", 1)

        if not hmac.compare_digest(user, settings.METRICS_USER):
            return unauthed_response()
        if not hmac.compare_digest(passphrase, settings.METRICS_PASSPHRASE):
            return unauthed_response()

        # ok, the request passed the authentication-barrier, let's hand out the metrics:
        m = defaultdict(dict)
        for d in self.get_ticket_stats(event):
            if d.get('qs_cliq'):
                qs = d['qs'].order_by().values('subevent', 'item', 'has_clique').annotate(c=Count('*'), cc=Count('order__orderclique__clique', distinct=True))
                for r in qs:
                    m[d['id']]['{item="%s",subevent="%s",hasclique="%s"}' % (r['item'], r['subevent'], r['has_clique'])] = r['c']
                    if r['cc']:
                        m[d['id'] + '_unique_cliques']['{item="%s",subevent="%s"}' % (r['item'], r['subevent'])] = r['cc']
            else:
                qs = d['qs'].order_by().values('subevent', 'item').annotate(c=Count('*'))
                for r in qs:
                    m[d['id']]['{item="%s",subevent="%s"}' % (r['item'], r['subevent'])] = r['c']

        output = []
        for metric, sub in m.items():
            for label, value in sub.items():
                output.append("{}{} {}".format(metric, label, str(value)))

        content = "\n".join(output) + "\n"

        return HttpResponse(content)
