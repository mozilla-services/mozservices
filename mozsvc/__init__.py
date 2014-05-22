# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****

import logging
logger = logging.getLogger("mozsvc")


def includeme(config):
    """Include the mozsvc defaults into a Pyramid application config.

    This function allows you to include the following default behaviours
    into your Pyramid application config:

        * add a /__heartbeat__ route and default view implementation

    """
    if config.registry.get("mozsvc.has_been_included"):
        return
    config.registry["mozsvc.has_been_included"] = True
    config.add_route('heartbeat', '/__heartbeat__')
    config.include('mozsvc.tweens')
    config.include('mozsvc.metrics')
    config.scan('mozsvc.views')
