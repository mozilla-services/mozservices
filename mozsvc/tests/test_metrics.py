from StringIO import StringIO
from metlog.client import MetlogClient
from metlog.senders import ZmqPubSender
from mozsvc.config import Config

from mozsvc.metrics import MetlogPlugin
from mozsvc.metrics import apache_log
from mozsvc.metrics import MetricsService

from metlog.decorators import incr_count
from metlog.decorators import timeit

from mozsvc.metrics import get_tlocal
from mozsvc.plugin import load_from_config
from pyramid.config import Configurator
from textwrap import dedent
from webob.request import Request
import unittest
import json



class TestMetrics(unittest.TestCase):

    def test_loading_from_config(self):
        config = Config(StringIO(dedent("""
        [test1]
        enabled=true
        backend = mozsvc.metrics.MetlogPlugin
        sender_class=metlog.senders.ZmqPubSender
        sender_bindstrs=tcp://localhost:5585
                        tcp://localhost:5586

        [test2]
        dontusethis =  seriously
        """)))
        settings = {"config": config}
        plugin = load_from_config("test1", config)
        config = Configurator(settings=settings)
        config.commit()
        self.failUnless(isinstance(plugin, MetlogPlugin))
        self.failUnless(isinstance(plugin.client, MetlogClient))
        self.failUnless(isinstance(plugin.client.sender, ZmqPubSender))

        client = plugin.client
        sender = client.sender

        self.assertEquals(sender.bindstrs, \
                ['tcp://localhost:5585', 'tcp://localhost:5586'])


class TestConfigurationLoading(unittest.TestCase):
    '''
    make sure that DecoratorWrapper works on decorators with
    arguments and with out
    '''
    def setUp(self):
        config = Config(StringIO(dedent("""
        [test1]
        enabled=true
        backend = mozsvc.metrics.MetlogPlugin
        sender_class=metlog.senders.DebugCaptureSender
        """)))
        settings = {"config": config}
        self.plugin = load_from_config("test1", config)
        config = Configurator(settings=settings)
        config.commit()

    def test_loading_from_config(self):
        plugin = self.plugin
        assert len(plugin.client.sender.msgs) == 0

        @timeit
        def target_callable(x, y):
            return x + y

        result = target_callable(5, 6)
        assert result == 11
        assert len(plugin.client.sender.msgs) == 1

        obj = json.loads(plugin.client.sender.msgs[0])

        expected = 'mozsvc.tests.test_metrics:target_callable'
        actual = obj['fields']['name']
        assert actual == expected

        # Now test to make sure we can enque 2 messages using stacked
        # decorators
        plugin.client.sender.msgs.clear()
        assert len(plugin.client.sender.msgs) == 0

        @incr_count
        @timeit
        def new_target_callable(x, y):
            return x + y

        result = new_target_callable(5, 6)
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        assert len(msgs) == 2

        # Names should be preserved
        assert new_target_callable.__name__ == 'new_target_callable'

        for msg in msgs:
            expected = 'mozsvc.tests.test_metrics:target_callable'
            actual = obj['fields']['name']
            assert actual == expected

        # First msg should be timer then the counter
        # as decorators just wrap each other
        assert msgs[0]['type'] == 'timer'
        assert msgs[1]['type'] == 'counter'


class TestCannedDecorators(unittest.TestCase):
    def setUp(self):
        config = Config(StringIO(dedent("""
        [test1]
        enabled=true
        backend = mozsvc.metrics.MetlogPlugin
        sender_class=metlog.senders.DebugCaptureSender
        """)))
        settings = {"config": config}
        self.plugin = load_from_config("test1", config)
        config = Configurator(settings=settings)
        config.commit()

    def test_decorator_ordering(self):
        '''
        decorator ordering may matter when Ops goes to look at the
        logs. Make sure we capture stuff in the right order
        '''
        plugin = self.plugin

        plugin.client.sender.msgs.clear()
        assert len(plugin.client.sender.msgs) == 0

        @incr_count
        @timeit
        def ordering_1(x, y):
            return x + y

        ordering_1(5, 6)
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        assert len(msgs) == 2

        for msg in msgs:
            expected = 'mozsvc.tests.test_metrics:ordering_1'
            actual = msg['fields']['name']
            assert actual == expected

        # First msg should be counter, then timer as decorators are
        # applied inside to out, but execution is outside -> in
        assert msgs[0]['type'] == 'timer'
        assert msgs[1]['type'] == 'counter'

        plugin.client.sender.msgs.clear()
        assert len(plugin.client.sender.msgs) == 0

        @timeit
        @incr_count
        def ordering_2(x, y):
            return x + y

        ordering_2(5, 6)
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        assert len(msgs) == 2

        for msg in msgs:
            expected = 'mozsvc.tests.test_metrics:ordering_2'
            actual = msg['fields']['name']
            assert actual == expected

        # Ordering of log messages should occur in the in->out
        # ordering of decoration
        assert msgs[0]['type'] == 'counter'
        assert msgs[1]['type'] == 'timer'

    def test_apache_logger(self):

        plugin = self.plugin
        plugin.client.sender.msgs.clear()
        msgs = plugin.client.sender.msgs
        assert len(msgs) == 0

        @apache_log
        def some_method(request):
            data = get_tlocal()
            data['foo'] = 'bar'

        req = Request({'PATH_INFO': '/foo/bar',
                       'SERVER_NAME': 'somehost.com',
                       'SERVER_PORT': 80,
                       })
        some_method(req)
        msg = json.loads(plugin.client.sender.msgs[0])
        assert 'foo' in msg['fields']['threadlocal']
        assert msg['fields']['threadlocal']['foo'] == 'bar'


user_info = MetricsService(name='users', path='/{username}/info',
                    description='some_svc')

@user_info.get(decorators=[incr_count, timeit, apache_log])
def get_info(request):
    return 'foo'

decorate_all = MetricsService(name='users', path='/{username}/all',
                    description='some_svc',
                    decorators=[incr_count, timeit, apache_log])
@decorate_all.get()
def auto_decorate(request):
    return 'foo'

class TestMetricsService(unittest.TestCase):
    def setUp(self):
        config = Config(StringIO(dedent("""
        [test1]
        enabled=true
        backend = mozsvc.metrics.MetlogPlugin
        sender_class=metlog.senders.DebugCaptureSender
        """)))
        settings = {"config": config}
        self.plugin = load_from_config("test1", config)
        config = Configurator(settings=settings)
        config.commit()

    def test_metrics_service(self):
        '''
        Test the MetricsService class
        '''


        req = Request({'PATH_INFO': '/foo/info',
                       'SERVER_NAME': 'somehost.com',
                       'SERVER_PORT': 80,
                       })
        resp = get_info(req)

        plugin = self.plugin
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        assert len(msgs) == 3
        assert 'counter' in [m['type'] for m in msgs]
        assert 'timer' in [m['type'] for m in msgs]
        assert 'wsgi' in [m['type'] for m in msgs]

    def test_decorate_at_constructor(self):
        req = Request({'PATH_INFO': '/foo/all',
                       'SERVER_NAME': 'somehost.com',
                       'SERVER_PORT': 80,
                       })
        resp = auto_decorate(req)

        plugin = self.plugin
        msgs = [json.loads(m) for m in plugin.client.sender.msgs]
        assert len(msgs) == 3
        assert 'counter' in [m['type'] for m in msgs]
        assert 'timer' in [m['type'] for m in msgs]
        assert 'wsgi' in [m['type'] for m in msgs]
