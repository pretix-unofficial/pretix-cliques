from django import forms
from django.contrib import messages
from django.db.transaction import atomic
from django.shortcuts import redirect
from django.utils.functional import cached_property
from django.utils.translation import pgettext_lazy, gettext_lazy as _

from pretix.base.models import SubEvent
from pretix.presale.checkoutflow import TemplateFlowStep
from pretix.presale.views import CartMixin, get_cart
from pretix.presale.views.cart import cart_session

from .models import Clique


class CliqueCreateForm(forms.Form):
    error_messages = {
        'duplicate_name': _(
            "There already is a clique with that name. If you want to join a clique already created "
            "by your friends, please choose to join a clique instead of creating a new one."
        ),
        'required': _('This field is required.'),
    }

    name = forms.CharField(
        max_length=190,
        label=_('Clique name'),
        required=False,
    )
    password = forms.CharField(
        max_length=190,
        label=_('Clique password'),
        min_length=3,
        required=False,
        help_text=_('Optional')
    )

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event')
        self.clique = kwargs.pop('current', None)
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if not name:
            raise forms.ValidationError(
                self.error_messages['required'],
                code='required'
            )

        if Clique.objects.filter(event=self.event, name=name).exclude(pk=(self.clique.pk if self.clique else 0)).exists():
            raise forms.ValidationError(
                self.error_messages['duplicate_name'],
                code='duplicate_name'
            )
        return name


class CliqueJoinForm(forms.Form):
    error_messages = {
        'clique_not_found': _(
            "This clique does not exist. Are you sure you entered the name correctly?"
        ),
        'required': _('This field is required.'),
        'pw_mismatch': _(
            "The password does not match. Please enter the password exactly as your friends send it."
        ),
    }

    name = forms.CharField(
        max_length=190,
        label=_('Clique name'),
        required=False,
    )
    password = forms.CharField(
        max_length=190,
        label=_('Clique password'),
        min_length=3,
        widget=forms.PasswordInput,
        required=False,
        help_text=_("Not all cliques require a password.")
    )

    def __init__(self, *args, **kwargs):
        self.event = kwargs.pop('event')
        super().__init__(*args, **kwargs)

    def clean(self):
        name = self.cleaned_data.get('name')
        password = self.cleaned_data.get('password')

        if not name:
            raise forms.ValidationError({
                'name': self.error_messages['required'],
            }, code='required')

        try:
            clique = Clique.objects.get(event=self.event, name=name)
        except Clique.DoesNotExist:
            raise forms.ValidationError({
                'name': self.error_messages['clique_not_found'],
            }, code='clique_not_found')
        else:
            if clique.password != password:
                raise forms.ValidationError({
                    'password': self.error_messages['pw_mismatch'],
                }, code='pw_mismatch')

        self.cleaned_data['clique'] = clique
        return self.cleaned_data


class CliqueStep(CartMixin, TemplateFlowStep):
    priority = 180
    identifier = "clique"
    template_name = "pretix_cliques/checkout_clique.html"
    icon = 'group'
    label = pgettext_lazy('checkoutflow', 'Clique')

    @atomic
    def post(self, request):
        self.request = request

        self.cart_session['clique_mode'] = request.POST.get('clique_mode', '')

        if self.cart_session['clique_mode'] == 'join':
            if self.join_form.is_valid():
                self.cart_session['clique_join'] = self.join_form.cleaned_data['clique'].pk
                return redirect(self.get_next_url(request))

        elif self.cart_session['clique_mode'] == 'create':
            if self.create_form.is_valid():
                clique = Clique(
                    event=self.event,
                )
                if self.cart_session.get('clique_create'):
                    try:
                        clique = Clique.objects.get(event=self.event, pk=self.cart_session['clique_create'])
                    except Clique.DoesNotExist:
                        pass

                clique.name = self.create_form.cleaned_data['name']
                clique.password = self.create_form.cleaned_data['password']
                clique.save()
                self.cart_session['clique_create'] = clique.pk
                return redirect(self.get_next_url(request))
        elif self.cart_session['clique_mode'] == 'none':
            return redirect(self.get_next_url(request))

        messages.error(self.request, _("We couldn't handle your input, please check below for errors."))
        return self.render()

    @cached_property
    def create_form(self):
        initial = {}
        current = None
        if self.cart_session.get('clique_mode') == 'create' and 'clique_create' in self.cart_session:
            try:
                current = Clique.objects.get(event=self.event, pk=self.cart_session['clique_create'])
            except Clique.DoesNotExist:
                pass
            else:
                initial['name'] = current.name
                initial['password'] = current.password

        return CliqueCreateForm(
            event=self.event,
            prefix='create',
            initial=initial,
            current=current,
            data=self.request.POST if self.request.method == "POST" and self.request.POST.get("clique_mode") == "create" else None
        )

    @cached_property
    def join_form(self):
        initial = {}
        if self.cart_session.get('clique_mode') == 'join' and 'clique_join' in self.cart_session:
            try:
                clique = Clique.objects.get(event=self.event, pk=self.cart_session['clique_join'])
            except Clique.DoesNotExist:
                pass
            else:
                initial['name'] = clique.name
                initial['password'] = clique.password

        return CliqueJoinForm(
            event=self.event,
            prefix='join',
            initial=initial,
            data=self.request.POST if self.request.method == "POST" and self.request.POST.get("clique_mode") == "join" else None
        )

    @cached_property
    def cart_session(self):
        return cart_session(self.request)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['create_form'] = self.create_form
        ctx['join_form'] = self.join_form
        ctx['cart'] = self.get_cart()
        ctx['selected'] = self.cart_session.get('clique_mode', '')
        return ctx

    def is_completed(self, request, warn=False):
        if request.event.has_subevents and cart_session(request).get('clique_mode') == 'join' and 'clique_join' in cart_session(request):
            try:
                clique = Clique.objects.get(event=self.event, pk=cart_session(request)['clique_join'])
                clique_subevents = set(c['order__all_positions__subevent'] for c in clique.ordercliques.filter(order__all_positions__canceled=False).values('order__all_positions__subevent').distinct())
                if clique_subevents:
                    cart_subevents = set(c['subevent'] for c in get_cart(request).values('subevent').distinct())
                    if any(c not in clique_subevents for c in cart_subevents):
                        if warn:
                            messages.warning(request, _('You requested to join a clique that participates in "{subevent_clique}", while you chose to participate in "{subevent_cart}". Please choose a different clique.').format(
                                subevent_clique=SubEvent.objects.get(pk=list(clique_subevents)[0]).name,
                                subevent_cart=SubEvent.objects.get(pk=list(cart_subevents)[0]).name,
                            ))
                        return False
            except Clique.DoesNotExist:
                pass


        return 'clique_mode' in cart_session(request)

    def is_applicable(self, request):
        return True
