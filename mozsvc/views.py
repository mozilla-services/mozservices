# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
""" Cornice default views.
"""
from pyramid.view import view_config


@view_config(route_name='heartbeat', renderer='string')
def heartbeat(request):
    return 'OK'
