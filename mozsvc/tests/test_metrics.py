from StringIO import StringIO
from mozsvc.config import Config, get_configurator
from mozsvc.plugin import load_from_config
from pyramid.config import Configurator
from textwrap import dedent
from webob.request import Request
import unittest2
import json

metlog = True
try:
    from metlog.client import MetlogClient
    from metlog.senders import ZmqPubSender
    from metlog.senders.logging import StdLibLoggingSender
    from metlog.decorators import incr_count
    from metlog.decorators import timeit
    from mozsvc.metrics import MetlogPlugin
    from mozsvc.metrics import MetricsService
    from mozsvc.metrics import load_metlog_client
    from mozsvc.metrics import send_mozsvc_data
    from mozsvc.metrics import update_mozsvc_data
except ImportError:
    metlog = False
    from cornice import Service as MetricsService  # NOQA
    timeit = send_mozsvc_data = incr_count = lambda fn: fn  # NOQA


class TestMetrics(unittest2.TestCase):
    def setUp(self):
        if not metlog:
            raise(unittest2.SkipTest('no metlog'))

    def test_loading_from_config(self):
        mozconfig = Config(StringIO(dedent("""
        [test1]
        backend = mozsvc.metrics.MetlogPlugin
        sender_class=metlog.senders.ZmqPubSender
        sender_bindstrs=tcp://localhost:5585
                        tcp://localhost:5586

        [test2]
        dontusethis =  seriously
        """)))
        settings = {"config": mozconfig}
        plugin = load_from_config("test1", mozconfig)
        config = Configurator(settings=settings)
        config.commit()
        self.failUnless(isinstance(plugin, MetlogPlugin))
        self.failUnless(isinstance(plugin.client, MetlogClient))
        self.failUnless(isinstance(plugin.client.sender, ZmqPubSender))

        client = plugin.client
        sender = client.sender
        bindstrs = sender.pool.socket().connect_bind

        self.assertEquals(bindstrs, \
                ['tcp://localhost:5585', 'tcp://localhost:5586'])

    def test_loading_from_configurator_with_default_sender(self):
        config = get_configurator({})
        client = load_metlog_client(config)
        self.failUnless(isinstance(client.sender, StdLibLoggingSender))

    def test_loading_from_configurator_with_explicit_sender(self):
        config = get_configurator({}, **{
            "metlog.backend": "mozsvc.metrics.MetlogPlugin",
            "metlog.sender_class": "metlog.senders.ZmqPubSender",
            "metlog.sender_bindstrs": "tcp://localhost:5585",
        })
        client = load_metlog_client(config)
        self.failUnless(isinstance(client.sender, ZmqPubSender))
        bindstrs = client.sender.pool.socket().connect_bind
        self.assertEquals(bindstrs, ['tcp://localhost:5585'])


class TestConfigurationLoading(unittest2.TestCase):
    """
    make sure that DecoratorWrapper works on decorators with arguments and with
    out
    """
    def setUp(self):
        if not metlog:
            raise(unittest2.SkipTest('no metlog'))
        mozconfig = Config(StringIO(dedent("""
        [test1]
        backend = mozsvc.metrics.MetlogPlugin
        sender_class=metlog.senders.DebugCaptureSender
        """)))
        settings = {"config": mozconfig}
        self.plugin = load_from_config("test1", mozconfig)
        config = Configurator(settings=settings)
        config.commit()

    def test_loading_from_config(self):
        plugin = self.plugin
        self.assertEqual(len(plugin.client.sender.msgs), 0)

        @timeit
        def target_callable(x, y):
            return x + y

        result = target_callable(5, 6)
        self.assertEqual(result, 11)
        self.assertEqual(len(plugin.client.sender.msgs), 1)

        obj = json.loads(plugin.client.sender.msgs[0])

        expected = 'mozsvc.tests.test_metrics.target_callable'
        actual = obj['fields']['name']
        self.assertEqual(actual, expected)

        # Now test to make sure we can enque 2 messages using stacked
        # decorators
        plugin.client.sender.msgs.clear()
        self.assertEqual(len(plugin.client.sender.msgs), 0)

        @incr_count
        @timeit
        def new_target_callable(x, y):
            return x + y

        result = new_target_callable(5, 6)
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        self.assertEqual(len(msgs), 2)

        # Names should be preserved
        self.assertEqual(new_target_callable.__name__, 'new_target_callable')

        for msg in msgs:
            expected = 'mozsvc.tests.test_metrics.target_callable'
            actual = obj['fields']['name']
            self.assertEqual(actual, expected)

        # First msg should be timer then the counter
        # as decorators just wrap each other
        self.assertEqual(msgs[0]['type'], 'timer')
        self.assertEqual(msgs[1]['type'], 'counter')


class TestCannedDecorators(unittest2.TestCase):
    def setUp(self):
        if not metlog:
            raise(unittest2.SkipTest('no metlog'))
        mozconfig = Config(StringIO(dedent("""
        [test1]
        backend = mozsvc.metrics.MetlogPlugin
        sender_class=metlog.senders.DebugCaptureSender
        """)))
        settings = {"config": mozconfig}
        self.plugin = load_from_config("test1", mozconfig)
        config = Configurator(settings=settings)
        config.commit()

    def test_decorator_ordering(self):
        plugin = self.plugin

        plugin.client.sender.msgs.clear()
        self.assertEqual(len(plugin.client.sender.msgs), 0)

        @incr_count
        @timeit
        def ordering_1(x, y):
            return x + y

        ordering_1(5, 6)
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        self.assertEqual(len(msgs), 2)

        for msg in msgs:
            expected = 'mozsvc.tests.test_metrics.ordering_1'
            actual = msg['fields']['name']
            self.assertEqual(actual, expected)

        # First msg should be counter, then timer as decorators are
        # applied inside to out, but execution is outside -> in
        self.assertEqual(msgs[0]['type'], 'timer')
        self.assertEqual(msgs[1]['type'], 'counter')

        plugin.client.sender.msgs.clear()
        self.assertEqual(len(plugin.client.sender.msgs), 0)

        @timeit
        @incr_count
        def ordering_2(x, y):
            return x + y

        ordering_2(5, 6)
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        self.assertEqual(len(msgs), 2)

        for msg in msgs:
            expected = 'mozsvc.tests.test_metrics.ordering_2'
            actual = msg['fields']['name']
            self.assertEqual(actual, expected)

        # Ordering of log messages should occur in the in->out
        # ordering of decoration
        self.assertEqual(msgs[0]['type'], 'counter')
        self.assertEqual(msgs[1]['type'], 'timer')

    def test_mozsvc_data(self):
        plugin = self.plugin
        plugin.client.sender.msgs.clear()
        msgs = plugin.client.sender.msgs
        self.assertEqual(len(msgs), 0)

        @send_mozsvc_data
        def some_method(request):
            update_mozsvc_data({'foo': 'bar'})

        req = Request({'PATH_INFO': '/foo/bar',
                       'SERVER_NAME': 'somehost.com',
                       'SERVER_PORT': 80,
                       })
        some_method(req)
        msg = json.loads(plugin.client.sender.msgs[0])
        self.assertTrue('foo' in msg['fields'])
        self.assertEqual(msg['fields']['foo'], 'bar')


user_info = MetricsService(name='users', path='/{username}/info',
                           description='some_svc')


@user_info.get(decorators=[timeit, send_mozsvc_data])
def get_info(request):
    return 'foo'


@user_info.get(decorators=[timeit, send_mozsvc_data])
def get_info_mozsvc_data(request):
    update_mozsvc_data({'moe': 'curly'})
    return 'foo'

decorate_all = MetricsService(name='users', path='/{username}/all',
                              description='some_svc')


@decorate_all.get()
def auto_decorate(request):
    update_mozsvc_data({'baz': 'bawlp'})
    return 'foo'


@decorate_all.get(decorators=[incr_count])
def decorator_override(request):
    return 'foo'


class TestMetricsService(unittest2.TestCase):
    def setUp(self):
        if not metlog:
            raise(unittest2.SkipTest('no metlog'))
        mozconfig = Config(StringIO(dedent("""
        [test1]
        backend = mozsvc.metrics.MetlogPlugin
        sender_class=metlog.senders.DebugCaptureSender
        """)))
        settings = {"config": mozconfig}
        self.plugin = load_from_config("test1", mozconfig)
        config = Configurator(settings=settings)
        config.commit()

    def test_metrics_service_get(self):
        req = Request({'PATH_INFO': '/foo/info',
                       'SERVER_NAME': 'somehost.com',
                       'SERVER_PORT': 80,
                       })
        resp = get_info(req)
        self.assertEqual(resp, 'foo')

        plugin = self.plugin
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        self.assertEqual(len(msgs), 1)
        self.assertTrue('timer' in [m['type'] for m in msgs])

    def test_metrics_service_get_mozsvc_data(self):
        req = Request({'PATH_INFO': '/foo/info',
                       'SERVER_NAME': 'somehost.com',
                       'SERVER_PORT': 80,
                       })
        resp = get_info_mozsvc_data(req)
        self.assertEqual(resp, 'foo')

        plugin = self.plugin
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        self.assertEqual(len(msgs), 2)
        self.assertTrue('timer' in [m['type'] for m in msgs])
        self.assertTrue('mozsvc' in [m['type'] for m in msgs])

    def test_decorate_at_constructor(self):
        req = Request({'PATH_INFO': '/foo/all',
                       'SERVER_NAME': 'somehost.com',
                       'SERVER_PORT': 80,
                       })
        resp = auto_decorate(req)
        self.assertEqual(resp, 'foo')

        plugin = self.plugin
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        msg_types = [m['type'] for m in msgs]
        self.assertEqual(len(msgs), 3)
        self.assertTrue('timer' in msg_types)
        self.assertTrue('counter' in msg_types)
        self.assertTrue('mozsvc' in msg_types)

    def test_decorator_override(self):
        req = Request({'PATH_INFO': '/foo/all',
                       'SERVER_NAME': 'somehost.com',
                       'SERVER_PORT': 80,
                       })
        resp = decorator_override(req)
        self.assertTrue(resp == 'foo')

        plugin = self.plugin
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        self.assertEqual(len(msgs), 1)
        self.assertTrue('counter' in [m['type'] for m in msgs])
