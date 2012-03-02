# ***** BEGIN LICENSE BLOCK *****
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
# ***** END LICENSE BLOCK *****
"""
Utility functions to instantiate the metrics logger from the sync
server configuration, as well as a decorator to time arbitrary
functions.
"""

from cornice import Service
from metlog.config import client_from_dict_config
from metlog.decorators import timeit, incr_count
from metlog.decorators.base import CLIENT_WRAPPER, MetlogDecorator
from zope.interface import Interface, implements
import functools
import threading
import thread
from contextlib import contextmanager


class IMetlogHelper(Interface):
    """An empty interface for the MetlogHelper."""
    pass


class MetlogHelperPlugin(object):
    '''
    Exposes a Metlog plugin for mozservices.

    This class acts as a transparent proxy to a MetlogHelper instance
    via the __getattr__ method call
    '''
    implements(IMetlogHelper)

    def __init__(self, **kwargs):
        # Disable metrics by default

        if not kwargs['enabled']:
            # Metrics are disabled
            self._client = None
            return

        disabled_decorators = dict([(k.replace("disable_", ''), v) \
                        for (k, v) in kwargs.items() \
                        if (k.startswith('disable_') and v)])

        metlog_config =  dict([(k.replace('sender_', ''), w) \
                for k, w in kwargs.items() if k.startswith("sender_")])

        self._client = client_from_dict_config({'sender': metlog_config})
        CLIENT_WRAPPER.activate(self._client, disabled_decorators)

    def __getattr__(self, k):
        return getattr(CLIENT_WRAPPER, k)



_LOCAL_STORAGE = threading.local()


def has_tlocal():
    thread_id = str(thread.get_ident())
    return hasattr(_LOCAL_STORAGE, thread_id)


def set_tlocal(value):
    thread_id = str(thread.get_ident())
    setattr(_LOCAL_STORAGE, thread_id, value)


def clear_tlocal():
    thread_id = str(thread.get_ident())
    if hasattr(_LOCAL_STORAGE, thread_id):
        delattr(_LOCAL_STORAGE, thread_id)


def get_tlocal():
    thread_id = str(thread.get_ident())
    if not has_tlocal():
        set_tlocal({})
    return getattr(_LOCAL_STORAGE, thread_id)


@contextmanager
def thread_context(callback):
    """
    This is a context manager where thread local storage
    has been bound using the thread identity.

    Access to a local dictionary is provided by the variables yielded
    by the context manager.  When the context manager exits, the
    callback is invoked with a single argument - the local storage
    dictionary.

    Local storage is always cleaned up by the context manager.
    """

    if not has_tlocal():
        set_tlocal({})

    # This context manager yields a dictionary that is thread local
    # Upon contextblock exit, the dictionary will be passed into the
    # callback function and finally garbage collected
    yield get_tlocal()

    try:
        callback(get_tlocal())
    finally:
        clear_tlocal()


class apache_log(MetlogDecorator):

    def metlog_call(self, *args, **kwargs):
        req = args[0]
        headers = req.headers

        webserv_log = {}

        wheaders = {}

        wheaders['User-Agent'] = headers.get('User-Agent', '')
        wheaders['path'] = getattr(req, 'path', '_no_path_')
        wheaders['host'] = getattr(req, 'host', '_no_host_')

        webserv_log['headers'] = wheaders

        def send_logmsg(tl_data):
            # this stuff gets stuffed into a callback
            # Fetch back any threadlocal variables and
            if has_tlocal():
                webserv_log['threadlocal'] = get_tlocal()
            else:
                webserv_log['threadlocal'] = None
            CLIENT_WRAPPER.client.metlog('wsgi', fields=webserv_log)

        result = None

        with thread_context(send_logmsg):  # NOQA
            return self._fn(*args, **kwargs)


class _DecoratorWrapper(object):
    # This class wraps the output of of a decorator
    # with a timer.  The output of a decorator call
    # is a decorated method
    def __init__(self, fn):
        self._underlying_decorator = fn

    def __call__(self, fn, *args, **kwargs):
        # Wrap the underlying callable with the timeit and incr_count
        # decorators

        # standard decorators for pegging timings and increment counts
        @apache_log
        @timeit
        @incr_count
        @functools.wraps(fn)
        def timed_fn(*fn_args, **fn_kwargs):
            return fn(*fn_args, **fn_kwargs)

        new_args = tuple([timed_fn] + list(args))
        return self._underlying_decorator(*new_args, **kwargs)


class MetricsService(Service):
    def __init__(self, **kw):
        Service.__init__(self, **kw)

    def get(self, **kw):
        return _DecoratorWrapper(Service.get(self, **kw))

    def put(self, **kw):
        return _DecoratorWrapper(Service.put(self, **kw))

    def post(self, **kw):
        return _DecoratorWrapper(Service.post(self, **kw))

    def delete(self, **kw):
        return _DecoratorWrapper(Service.delete(self, **kw))

