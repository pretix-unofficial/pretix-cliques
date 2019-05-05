from django.apps import AppConfig
from django.utils.translation import ugettext_lazy


class PluginApp(AppConfig):
    name = 'pretix_cliques'
    verbose_name = 'pretix Cliques'

    class PretixPluginMeta:
        name = ugettext_lazy('pretix Cliques')
        author = 'Raphael Michel'
        description = ugettext_lazy('This pretix plugin adds the cliques feature.')
        visible = True
        version = '1.0.0'

    def ready(self):
        from . import signals  # NOQA


default_app_config = 'pretix_cliques.PluginApp'
