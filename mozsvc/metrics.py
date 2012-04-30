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

from contextlib import contextmanager
from cornice import Service
from metlog.config import client_from_dict_config
from metlog.decorators import timeit, incr_count
from metlog.decorators.base import MetlogDecorator
from metlog.holder import CLIENT_HOLDER
import threading


_LOCAL_STORAGE = threading.local()


def setup_metlog(config_dict, default=False):
    """
    Instantiate a Metlog client and add it to the client holder.

    :param config_dict: Dictionary object containing the metlog client
                        configuration.
    :param default: Should this be specified as CLIENT_HOLDER's default
                    client? Note that the first client to be added will
                    automatically be specified as the default, regardless
                    of the value of this argument.
    """
    name = config_dict.get('logger', '')
    client = CLIENT_HOLDER.get_client(name)
    client = client_from_dict_config(config_dict, client)
    if default:
        CLIENT_HOLDER.set_default_client_name(name)


def get_metlog_client(name=None):
    """
    Return the specified Metlog client from the CLIENT_HOLDER.

    :param name: Name of metlog client to fetch. If not provided the
                 holder's specified default client will be used.
    """
    if name is not None:
        client = CLIENT_HOLDER.get_client(name)
    else:
        client = CLIENT_HOLDER.default_client
    return client


class MetlogPlugin(object):
    def __init__(self, **kwargs):
        setup_metlog(kwargs)
        self.client = CLIENT_HOLDER.default_client


def get_tlocal():
    """
    Return the thread local metlog context dict, if it exists. This should only
    succeed from within a `thread_context` context manager. If we're not within
    such a context manager (and thus the metlog context dict doesn't exist)
    then an AttributeError will be raised.
    """
    if not hasattr(_LOCAL_STORAGE, 'metlog_context_dict'):
        raise AttributeError("No `metlog_context_dict`; are you in a "
                             "thread_context?")
    return _LOCAL_STORAGE.metlog_context_dict


@contextmanager
def thread_context(callback):
    """
    This is a context manager that accepts a callback function and returns a
    thread local dictionary object. Upon exit, the callback function will be
    called and passed that dictionary as the sole argument, after which the
    dictionary will be deleted.
    """
    _LOCAL_STORAGE.metlog_context_dict = dict()
    yield _LOCAL_STORAGE.metlog_context_dict
    try:
        callback(_LOCAL_STORAGE.metlog_context_dict)
    finally:
        del _LOCAL_STORAGE.metlog_context_dict


class apache_log(MetlogDecorator):
    """
    Decorator that can be wrapped around a view method which will extract some
    information from the WebOb request object and will send a metlog message w/
    this information when the view method completes.
    """
    def metlog_call(self, *args, **kwargs):
        req = args[0]
        headers = req.headers

        wheaders = {}
        wheaders['User-Agent'] = headers.get('User-Agent', '')
        wheaders['path'] = getattr(req, 'path', '_no_path_')
        wheaders['host'] = getattr(req, 'host', '_no_host_')
        webserv_log = {'headers': wheaders}

        def send_logmsg(tl_data):
            """
            Stuff the threadlocal data into the message and send it out.
            """
            webserv_log['threadlocal'] = tl_data
            self.client.metlog('wsgi', fields=webserv_log)

        with thread_context(send_logmsg):
            return self._fn(*args, **kwargs)


class MetricsService(Service):

    def __init__(self, **kw):
        self._decorators = kw.pop('decorators', [timeit, incr_count,
                                                 apache_log])
        Service.__init__(self, **kw)

    def get_view_wrapper(self, kw):
        """
        Returns a wrapper that will wrap the view callable w/ metlog decorators
        for timing and logging wsgi variables.
        """
        decorators = kw.pop('decorators', self._decorators)

        def wrapper(func):
            applied_set = set()
            if hasattr(func, '_metlog_decorators'):
                applied_set.update(func._metlog_decorators)
            for decorator in decorators:
                # Stacked api decorators may result in this being called more
                # than once for the same function, we need to make sure that
                # the original function isn't wrapped more than once by the
                # same decorator.
                if decorator not in applied_set:
                    func = decorator(func)
                    applied_set.add(decorator)
            func._metlog_decorators = applied_set
            return func
        return wrapper
