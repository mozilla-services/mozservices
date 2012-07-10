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
from metlog.logging import hook_logger
from metlog.senders.logging import StdLibLoggingSender
import threading

from mozsvc.plugin import load_from_settings


_LOCAL_STORAGE = threading.local()


# Default settings to use when there is no "metlog" section in the config file.
DEFAULT_METLOG_SETTINGS = {
    "metlog.backend": "mozsvc.metrics.MetlogPlugin",
    "metlog.sender_class": "metlog.senders.logging.StdLibLoggingSender",
    "metlog.sender_json_types": [],
}


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


def teardown_metlog():
    pass


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


def load_metlog_client(config):
    """Load and return a metlog client for the given Pyramid Configurator.

    This is a shortcut function to load and return the metlog client specified
    by the given Pyramid Configurator object.  If the configuration does not
    specify any metlog settings, a default client is constructed that routes
    all messages into the stdlib logging routines.

    The metlog client is cached in the Configurator's registry, so multiple
    calls to this function will return a single instance.
    """
    settings = config.registry.settings
    client = config.registry.get("metlog")
    if client is None:
        if "metlog.backend" not in settings:
            settings.update(DEFAULT_METLOG_SETTINGS)
        client = load_from_settings('metlog', settings).client
        config.registry['metlog'] = client
        if not isinstance(client.sender, StdLibLoggingSender):
            hook_logger("mozsvc", client)
    return client


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


class send_mozsvc_data(MetlogDecorator):
    """
    Decorator that can be wrapped around a view method which will check the
    `metlog_context_dict` threadlocal and, if not empty, generate a metlog
    message of type `mozsvc` with the contained data.
    """
    def metlog_call(self, *args, **kwargs):
        def send_logmsg(mozsvc_data):
            """
            Stuff the threadlocal data into the message and send it out.
            """
            if mozsvc_data:
                self.client.metlog('mozsvc', fields=mozsvc_data)

        with thread_context(send_logmsg):
            return self._fn(*args, **kwargs)


def update_mozsvc_data(update_data):
    """
    Update the `metlog_context_dict` with data that will be sent out via metlog
    after request processing.
    """
    get_tlocal().update(update_data)


class MetricsService(Service):

    def __init__(self, **kw):
        self._decorators = kw.pop('decorators', [timeit, incr_count,
                                                 send_mozsvc_data])
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
