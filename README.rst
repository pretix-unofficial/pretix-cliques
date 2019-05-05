pretix Cliques
==============

This is a plugin for `pretix`_ allowing users to join a "clique" as part of their checkout experience. This clique
can be used for various purposes, such as having members of a clique participate in a ticket raffle as a whole.

This plugin has been written by the pretix team on commission by a client. Since it is specific to a certain
use case of pretix, it is not considered an "official pretix plugin" and therefore not guaranteed to receive updates
with every update of pretix.

Production install
------------------

1. Clone this repository

2. Activate the virtual environment you use for pretix development.

3. Run ``python setup.py install``

4. Run ``python -m pretix migrate`` and ``python -m pretix rebuild``


Development setup
-----------------

1. Make sure that you have a working `pretix development setup`_.

2. Clone this repository, eg to ``local/pretix-cliques``.

3. Activate the virtual environment you use for pretix development.

4. Execute ``python setup.py develop`` within this directory to register this application with pretix's plugin registry.

5. Execute ``make`` within this directory to compile translations.

6. Restart your local pretix server. You can now use the plugin from this repository for your events by enabling it in
   the 'plugins' tab in the settings.


License
-------

Copyright 2019 Raphael Michel.

Released under the terms of the Apache License 2.0


.. _pretix: https://github.com/pretix/pretix
.. _pretix development setup: https://docs.pretix.eu/en/latest/development/setup.html
