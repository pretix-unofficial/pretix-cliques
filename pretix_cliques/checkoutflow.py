from django import forms
from django.contrib import messages
from django.db.transaction import atomic
from django.shortcuts import redirect
from django.utils.functional import cached_property
from django.utils.translation import pgettext_lazy, ugettext_lazy as _

from pretix.presale.checkoutflow import TemplateFlowStep
from pretix.presale.views import CartMixin
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

    def clean(self):
        password1 = self.cleaned_data.get('password', '')

        if not password1:
            raise forms.ValidationError({
                'password': self.error_messages['required'],
            }, code='required')

        return self.cleaned_data


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
        return 'clique_mode' in cart_session(request)

    def is_applicable(self, request):
        return True
