from django.apps import AppConfig
from django.utils.translation import gettext_lazy
from . import __version__


class PluginApp(AppConfig):
    name = 'pretix_cliques'
    verbose_name = 'Cliques'

    class PretixPluginMeta:
        name = gettext_lazy('Cliques')
        author = 'Raphael Michel'
        description = gettext_lazy('This pretix plugin adds the cliques feature.')
        visible = True
        version = __version__
        category = 'FEATURE'

    def ready(self):
        from . import signals  # NOQA


