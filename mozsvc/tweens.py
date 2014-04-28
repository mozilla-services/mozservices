# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import sys
import random
import traceback
import simplejson as json

from pyramid.httpexceptions import HTTPException, HTTPServiceUnavailable

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
        except HTTPException:
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


def fuzz_backoff_headers(handler, registry):
    """Add some random fuzzing to the value of various backoff headers.

    This can help to avoid a "dogpile" effect where all backed-off clients
    retry at the same time and overload the server.
    """

    HEADERS = ["Retry-After", "X-Backoff", "X-Weave-Backoff"]

    def fuzz_response(response):
        for header in HEADERS:
            value = response.headers.get(header)
            if value is not None:
                # The header value is a backoff duration in seconds.  Fuzz
                # it upward by up to 5% or 5 seconds, whichever is greater.
                value = int(value)
                max_fuzz = max(int(value * 0.05), 5)
                value += random.randint(0, max_fuzz)
                response.headers[header] = str(value)

    def fuzz_backoff_headers_tween(request):
        try:
            response = handler(request)
        except HTTPException, response:
            fuzz_response(response)
            raise
        else:
            fuzz_response(response)
            return response

    return fuzz_backoff_headers_tween


def send_backoff_responses(handler, registry):
    """Send backoff/unavailable responses to a percentage of clients.

    This tween allows the server to respond to a set percentage of traffic with
    an X-Backoff header and/or a "503 Service Unavilable" response.  The two
    probabilities are controlled by config options 'mozsvc.backoff_probability'
    and 'mozsvc.unavailable_probability' respectively.  If neither option is
    set then the tween is not activated, avoiding overhead in the (hopefully!)
    common case.
    """
    settings = registry.settings
    backoff_probability = settings.get("mozsvc.backoff_probability", 0)
    unavailable_probability = settings.get("mozsvc.unavailable_probability", 0)
    retry_after = settings.get("mozsvc.retry_after", 1800)

    if backoff_probability:

        backoff_probability = float(backoff_probability)

        def add_backoff_header(response):
            if "X-Backoff" not in response.headers:
                if "X-Weave-Backoff" not in response.headers:
                    response.headers["X-Backoff"] = str(retry_after)
                    response.headers["X-Weave-Backoff"] = str(retry_after)

        def send_backoff_header_tween(request, handler=handler):
            try:
                response = handler(request)
            except HTTPException, response:
                if random.random() < backoff_probability:
                    add_backoff_header(response)
                raise
            else:
                if random.random() < backoff_probability:
                    add_backoff_header(response)
                return response

        handler = send_backoff_header_tween

    if unavailable_probability:

        unavailable_probability = float(unavailable_probability)

        def send_unavailable_response_tween(request, handler=handler):
            if random.random() < unavailable_probability:
                return HTTPServiceUnavailable(body="0",
                                              retry_after=retry_after,
                                              content_type="application/json")
            return handler(request)

        handler = send_unavailable_response_tween

    return handler


def includeme(config):
    """Include all the mozsvc tweens into the given config."""
    config.add_tween("mozsvc.tweens.catch_backend_errors")
    config.add_tween("mozsvc.tweens.log_uncaught_exceptions")
    config.add_tween("mozsvc.tweens.fuzz_backoff_headers")
    config.add_tween("mozsvc.tweens.send_backoff_responses")
