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
from metlog.client import MetlogClient
from metlog.client import SEVERITY
from mozsvc.util import resolve_name
from zope.interface import Interface, implements
import mozsvc.exceptions as exceptions
import functools
import threading
import thread
from contextlib import contextmanager


def return_fq_name(func, klass=None):
    """
    Resolve a fully qualified name for a function
    or method
    """
    # Forget checking the type via isinstance, just check for anything
    # that looks like it might be useful in constructing a usable name

    func_name = getattr(func, 'func_name', None)
    func_module = getattr(func, '__module__', None)

    if klass:
        name = "%s:%s.%s" % (klass.__module__, \
                             klass.__name__, \
                             'PyCallable')
    elif func_name:
        # This is some kind of function
        # Note that we can't determine the containing class
        # because return_fq_name is usually called by a decorator
        # and that means the function is not yet bound to an object
        # instance yet
        # Just grab the containing module and the function name
        name = "%s:%s" % (func_module, func_name)
    else:
        # This shouldn't happen, but we don't really want to throw
        # errors just because we can't get some fake arbitrary
        # name for an object
        name = str(func)
        if name.startswith('<') and name.endswith('>'):
            name = name[1:-1]
    return name


class MetlogHelper(object):
    """
    This is class acts as a kind of lazy proxy to the MetlogClient.
    We need this to provide late binding of the MetlogClient to the
    decorators that use Metlog.  We also need the set_client method
    exposed so that when configuration is changed (mostly during
    testing), we can dynamically repoint the metrics logging to a new
    output target
    """
    def __init__(self):
        self._reset()

    def _reset(self):
        """ Reset the MetlogClientHelper to it's initial state"""
        self._client = None
        self._registry = {}
        self._web_dispatcher = None

    def set_client(self, client):
        """ set the metlog client on the helper """
        if client is None:
            self._reset()
            return

        self._client = client


class IMetlogHelper(Interface):
    """An empty interface for the MetlogHelper."""
    pass


class MetlogHelperPlugin(object):
    '''
    Exposes a Metlog plugin for mozservices
    '''
    implements(IMetlogHelper)

    def __init__(self, **kwargs):
        # Disable metrics by default
        HELPER.set_client(None)
        if not kwargs.get('enabled', False):
            # Force set the client to disabled
            return
        del kwargs['enabled']

        HELPER.set_client(MetlogClient(None))

        # Strip out the keys prefixed with 'sender_'
        sender_keys = dict([(k.replace("sender_", ''), w) \
                        for (k, w) in kwargs.items() \
                        if k.startswith('sender_')])

        klass = resolve_name(sender_keys['backend'])
        del sender_keys['backend']
        HELPER._client.sender = klass(**sender_keys)

    def __getattr__(self, k):
        return getattr(HELPER, k)


def rebind_dispatcher(method_name):
    """
    Use this decorator to rebind a method to a class in the case that
    metrics is enabled.

    Currently, metrics are enabled for the world, or disabled for the
    world.
    """
    def wrapped(func):
        """
        This decorator is used to just rebind the dispatch method so that
        we do not incur overhead on execution of controller methods when
        the metrics logging is disabled.
        """
        @functools.wraps(func)
        def inner(*args, **kwargs):
            klass = args[0].__class__
            if not HELPER._client:
                # Get rid of the decorator
                setattr(klass, func.__name__, func)
                return func(*args, **kwargs)
            else:
                new_method = getattr(klass, method_name, None)
                if not new_method:
                    msg = 'No such method: [%s]' % method_name
                    raise exceptions.MethodNotFoundError(msg)
                setattr(klass, func.__name__, new_method)
                return new_method(*args, **kwargs)
        return inner
    return wrapped


class SimpleLogger(object):
    '''
    This class provides a simplified interface when you don't need
    access to a raw MetlogClient instance.
    '''

    def __init__(self, logger_name=None):
        if not logger_name:
            logger_name = 'anonymous'
        self._logger_name = logger_name

    @property
    def _client(self):
        return HELPER._client

    def metlog_log(self, msg, level):
        '''
        If metlog is enabled, we're going to send messages here
        '''
        self._client.metlog(type='oldstyle',
                logger=self._logger_name,
                severity=level, payload=msg)

    @rebind_dispatcher('metlog_log')
    def _log(self, msg, level):
        '''
        This is a no-op method in case metlog is disabled
        '''

    # TODO: would be nice to have a registration mechanism to 'attach'
    # the debug, info, warn, error, etc... methods through some kind
    # of callback mechanism at runtime

    def debug(self, msg):
        self._log(msg, SEVERITY.DEBUG)

    def info(self, msg):
        self._log(msg, SEVERITY.INFORMATIONAL)

    def warn(self, msg):
        self._log(msg, SEVERITY.WARNING)

    def error(self, msg):
        self._log(msg, SEVERITY.ERROR)

    def exception(self, msg):
        self._log(msg, SEVERITY.ALERT)

    def critical(self, msg):
        self._log(msg, SEVERITY.CRITICAL)


class MetricsDecorator(object):
    """
    This class is used to store some metadata about
    the decorated function.  This is needed since if you stack
    decorators, you'll lose the name of the underlying function that
    is being logged.  Mostly, we just care about the function name.
    """
    def __init__(self, fn):
        self._fn = fn

        if isinstance(fn, MetricsDecorator):
            if hasattr(fn, '_metrics_fn_code'):
                self._metrics_fn_code = fn._metrics_fn_code
            self._method_name = fn._method_name
        else:
            if hasattr(self._fn, 'func_code'):
                self._metrics_fn_code = getattr(self._fn, 'func_code')
            self._method_name = return_fq_name(self._fn)

    @property
    def __name__(self):
        # This is only here to support the use of functools.wraps
        return self._fn.__name__

    def _invoke(self, *args, **kwargs):
        return self._fn(*args, **kwargs)


class incr_count(MetricsDecorator):
    '''
    Decorate any callable for metrics timing.
    '''
    def __init__(self, fn):
        MetricsDecorator.__init__(self, fn)

    @rebind_dispatcher('metlog_call')
    def __call__(self, *args, **kwargs):
        return self._invoke(*args, **kwargs)

    def metlog_call(self, *args, **kwargs):
        try:
            result = self._invoke(*args, **kwargs)
        finally:
            HELPER._client.incr(self._method_name, count=1)
        return result


class timeit(MetricsDecorator):
    '''
    Decorate any callable for metrics timing.

    You must write you decorator in 'class'-style or else you won't be
    able to have your decorator disabled.
    '''
    def __init__(self, fn):
        MetricsDecorator.__init__(self, fn)

    @rebind_dispatcher('metlog_call')
    def __call__(self, *args, **kwargs):
        return self._invoke(*args, **kwargs)

    def metlog_call(self, *args, **kwargs):
        with HELPER._client.timer(self._method_name):
            return self._invoke(*args, **kwargs)


_LOCAL_STORAGE = threading.local()
_RLOCK = threading.RLock()


def has_tlocal():
    result = None
    with _RLOCK:
        thread_id = str(thread.get_ident())
        result = hasattr(_LOCAL_STORAGE, thread_id)
    return result


def set_tlocal(value):
    with _RLOCK:
        thread_id = str(thread.get_ident())
        setattr(_LOCAL_STORAGE, thread_id, value)


def clear_tlocal():
    with _RLOCK:
        thread_id = str(thread.get_ident())
        if hasattr(_LOCAL_STORAGE, thread_id):
            delattr(_LOCAL_STORAGE, thread_id)


def get_tlocal():
    result = None
    with _RLOCK:
        thread_id = str(thread.get_ident())
        if not has_tlocal():
            set_tlocal({})
        result = getattr(_LOCAL_STORAGE, thread_id)
    return result


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


def apache_log(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
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
            HELPER._client.metlog('wsgi', fields=webserv_log)

        result = None

        with thread_context(send_logmsg) as thread_dict:  # NOQA
            result = fn(*args, **kwargs)

        return result

    return wrapper


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


HELPER = MetlogHelper()


logger = SimpleLogger()
