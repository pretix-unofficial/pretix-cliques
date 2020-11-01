from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.generic import DeleteView, ListView, TemplateView
from pretix.base.models import Order
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
