# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Contributor(s):
#   Victor Ng (vng@mozilla.com)
#   Rob Miller (rmiller@mozilla.com)
#
# ***** END LICENSE BLOCK *****
"""
Utility functions to instantiate the metrics logger from the sync
server configuration, as well as a decorator to time arbitrary
functions.
"""

import re
import json
import timeit
import logging
import functools

import pyramid.threadlocal
from pyramid.events import ContextFound


logger = logging.getLogger("mozsvc.metrics")

COMMA_SEPARATED = re.compile(r"\s*,\s*")


def initialize_request_metrics(request, defaults={}):
    """Request callback to add a "metrics" dict.

    This function should be invoked upon each new request.  It will create
    a request.metrics dict into which the application can store any runtime
    logging or metrics data, and will add response callbacks to log the
    contents of this dict once the request is complete.
    """
    # Create the request.metrics dict.
    request.metrics = defaults.copy()
    # Add in some basic information about the request
    # that should always be logged.
    request.metrics["method"] = request.method
    request.metrics["path"] = request.path_url
    request.metrics["agent"] = request.user_agent or ""
    xff = request.headers.get('X-Forwarded-For', '')
    xff = [ip for ip in COMMA_SEPARATED.split(xff) if ip]
    if request.remote_addr:
        xff.append(request.remote_addr)
    request.metrics["remoteAddressChain"] = xff
    request.metrics["request_start_time"] = timeit.default_timer()
    # Add hooks to log the metrics at the end of the request.
    request.add_response_callback(add_response_metrics)
    request.add_finished_callback(finalize_request_metrics)


def add_response_metrics(request, response):
    """Response callback to add metrics about a successfully-handled request.

    This function should be invoked when a request has been successfully
    handled and a response generated.  It will annotate the request.metrics
    dict with information about the total runtime and the resulting response.

    Note that this function is typically added to requests as a "response
    callback", which means that it will *not* be executed in case an unhandled
    exception occurs during request processing.
    """
    start_time = request.metrics.pop("request_start_time")
    request.metrics["request_time"] = timeit.default_timer() - start_time
    request.metrics["code"] = response.status_code


def finalize_request_metrics(request, message=None):
    """Finalize and log the collected request metrics.

    This function should be invoked once request handling is complete.
    It will finalize some details of the request.metrics dict and then
    emit a log line with its contents.

    By default the log line will be a simple JSON dump of all the metrics.
    This can be set to a custom message using the optional "message" argument.

    Note that this function is typically added to requests as a "finished
    callback" so that it will be invoked unconditionally at the end of
    request processing.
    """
    # If the add_response_metrics() callback did not get invoked, there
    # was probably any error in request processing.  Fill in some defaults
    # and a special status code.  The unhandled error will be logged by
    # other parts of the infrastructure.
    if "request_time" not in request.metrics:
        start_time = request.metrics.pop("request_start_time")
        request.metrics["request_time"] = timeit.default_timer() - start_time
        request.metrics["code"] = 999
    # Emit the a summary log line.
    if message is None:
        logger.info(json.dumps(request.metrics), extra=request.metrics)
    else:
        logger.info(message, extra=request.metrics)


def annotate_request(request, key, value):
    """Add or update an entry in the request.metrics dict.

    This is a helper function for storing data in the request.metrics dict.
    It provides some simple conveniences for the calling code:

        * If the request is None, then pyramid's threadlocals are used
          to find the current request object.
        * If the request has no metrics dict then it is silently ignored,
          so this is safe to call from contexts that may not metrics-enabled.
        * If the key already exists in the metrics dict, it is added to
          rather than being overwritten.

    """
    if request is None:
        request = pyramid.threadlocal.get_current_request()
    if request is not None:
        try:
            if key in request.metrics:
                request.metrics[key] += value
            else:
                request.metrics[key] = value
        except AttributeError:
            pass


class metrics_timer(object):
    """Decorator/context-manager to transparently time chunks of code.

    This class produces a timing decorator/context-manager that will place
    its result in the request.metrics dict upon completion.

    It uses pyramid threadlocals to get the current request object, which is
    a little bit icky but very convenient.  If you have the proper request
    object, you can pass it as an optional argument to the constructor.

    It can be used as a context-manager to time a chunk of code, like this:

        with metrics_timer("my.timer"):
            do_some_stuff()

    Or applied as a function decorator like this:

        @metrics_timer("my.timer")
        def do_some_stuff():
            do_more_stuff()

    """

    def __init__(self, key, request=None):
        self.key = key
        self._request = request

    def annotate_request(self, value, key=None, request=None):
        if key is None:
            key = self.key
        if request is None:
            request = self._request
        annotate_request(request, key, value)

    # When used as a context-manager, times the enclosed code.

    def __enter__(self):
        self.start_time = timeit.default_timer()
        return self

    def __exit__(self, exc_typ=None, exc_val=None, exc_tb=None):
        stop_time = timeit.default_timer()
        self.annotate_request(stop_time - self.start_time)

    # When called, applies itself as a function decorator.

    def __call__(self, func):

        @functools.wraps(func)
        def timed_func(*args, **kwds):
            # We can't use "with self" here since that stores state on
            # the object, and hence plays badly with threading or recursion.
            start_time = timeit.default_timer()
            try:
                return func(*args, **kwds)
            finally:
                stop_time = timeit.default_timer()
                self.annotate_request(stop_time - start_time)

        return timed_func


def new_request_listener(event):
    """NewRequest event-listener that adds request metrics."""
    initialize_request_metrics(event.request)


def includeme(config):
    """Include the mozsvc metrics hooks into the given config."""
    # The metrics-gathering code assumes a well-formed request,
    # so it's only safe to add it after pyramid has done a certain
    # amount of processing and view resolution.
    config.add_subscriber(new_request_listener, ContextFound)
