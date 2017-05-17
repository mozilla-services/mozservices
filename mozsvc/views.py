# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****

from pyramid.view import view_config
from pyramid.exceptions import URLDecodeError
from pyramid.httpexceptions import HTTPNotFound


@view_config(route_name='heartbeat', renderer='string')
def hearbeat(request):
    return 'OK'


@view_config(context=URLDecodeError)
def invalid_url_view(request):
    return HTTPNotFound()
