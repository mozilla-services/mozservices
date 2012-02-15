# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import traceback
import simplejson as json

from pyramid.httpexceptions import HTTPServiceUnavailable

from mozsvc import logger
from mozsvc.exceptions import BackendError
from mozsvc.middlewares import create_hash


def catch_backend_errors(handler, registry):
    """Tween to turn BackendError into a 503 response.

    This is a pyramid tween factory for catching BackendError exceptions
    and translating them into a HTTP "503 Service Unavailable" response.
    """
    def catch_backend_errors_tween(request):
        try:
            return handler(request)
        except BackendError as err:
            err_info = str(err)
            err_trace = traceback.format_exc()
            try:
                extra_info = "user: %s" % (request.user,)
            except Exception:
                extra_info = "user: -"
            error_log = "%s\n%s\n%s" % (err_info, err_trace, extra_info)
            hash = create_hash(error_log)
            logger.error(hash)
            logger.error(error_log)
            msg = json.dumps("application error: crash id %s" % hash)
            if err.retry_after is not None:
                if err.retry_after == 0:
                    retry_after = None
                else:
                    retry_after = err.retry_after
            else:
                settings = request.registry.settings
                retry_after = settings.get("mozsvc.retry_after", 1800)

            return HTTPServiceUnavailable(body=msg, retry_after=retry_after,
                                          content_type="application/json")

    return catch_backend_errors_tween


def includeme(config):
    """Include all the mozsvc tweens into the given config."""
    config.add_tween("mozsvc.tweens.catch_backend_errors")
