# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import traceback
import simplejson as json

from pyramid.httpexceptions import WSGIHTTPException, HTTPServiceUnavailable

import mozsvc
from mozsvc.exceptions import BackendError
from mozsvc.middlewares import create_hash


def get_logger(request):
    """Get the logger object to use for the given request.

    This will return a metlog client if one is attached to the request,
    or the default mozsvc.logger object if not.
    """
    logger = request.registry.get("metlog")
    if logger is None:
        logger = mozsvc.logger
    return logger


def catch_backend_errors(handler, registry):
    """Tween to turn BackendError into a 503 response.

    This is a pyramid tween factory for catching BackendError exceptions
    and translating them into a HTTP "503 Service Unavailable" response.
    """
    def catch_backend_errors_tween(request):
        try:
            return handler(request)
        except BackendError as err:
            logger = get_logger(request)
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


def log_uncaught_exceptions(handler, registry):
    """Tween to log all uncaught exceptions via metlog."""

    def log_uncaught_exceptions_tween(request):
        try:
            return handler(request)
        except WSGIHTTPException:
            raise
        except Exception:
            logger = get_logger(request)
            # We don't want to write arbitrary user-provided data into the
            # the logfiles.  For example, the sort of data that might show
            # up in the payload of a ValueError exception.
            # Format the traceback using standard printing, but use repr()
            # on the exception value itself to avoid this issue.
            exc_type, exc_val, exc_tb = sys.exc_info()
            lines = ["Uncaught exception while processing request:\n"]
            lines.append("%s %s\n" % (request.method, request.path_url))
            lines.extend(traceback.format_tb(exc_tb))
            lines.append("%r\n" % (exc_type,))
            lines.append("%r\n" % (exc_val,))
            logger.exception("".join(lines))
            raise

    return log_uncaught_exceptions_tween


def includeme(config):
    """Include all the mozsvc tweens into the given config."""
    config.add_tween("mozsvc.tweens.catch_backend_errors")
    config.add_tween("mozsvc.tweens.log_uncaught_exceptions")
