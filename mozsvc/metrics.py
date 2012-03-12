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
from metlog.decorators import timeit
from metlog.decorators.base import CLIENT_WRAPPER, MetlogDecorator
import cornice
import threading


_LOCAL_STORAGE = threading.local()


def setup_metlog(config_dict):
    """
    Instantiate the Metlog client and set up the client wrapper.

    :param config_dict: Dictionary object containing the metlog client
                        configuration.
    """
    CLIENT_WRAPPER.activate(config_dict)


def teardown_metlog():
    """
    Reset the client wrapper. Usually only needed for tests.
    """
    CLIENT_WRAPPER.reset()


def get_metlog_client():
    """
    Return the currently configured Metlog client. Will not work until
    `setup_metlog` has been called to initialize the client wrapper.
    """
    return CLIENT_WRAPPER.client


class MetlogPlugin(object):
    def __init__(self, **kwargs):
        setup_metlog(kwargs)
        self.client = CLIENT_WRAPPER.client


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
            CLIENT_WRAPPER.client.metlog('wsgi', fields=webserv_log)

        with thread_context(send_logmsg):
            return self._fn(*args, **kwargs)


def monkey_service_class(un=False):
    Service = cornice.Service
    for method_name in ['get', 'put', 'post', 'delete']:
        inner_name = '_metlog_orig_%s' % method_name
        if not un:
            orig_method = getattr(Service, method_name)
            wrapped = apache_log(timeit(orig_method))
            setattr(Service, inner_name, orig_method)
            setattr(Service, method_name, wrapped)
            Service._metlog_monkeyed = True
        else:
            orig_method = getattr(Service, inner_name)
            setattr(Service, method_name, orig_method)
            Service._metlog_monkeyed = False
