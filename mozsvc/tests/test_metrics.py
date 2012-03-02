from StringIO import StringIO
from metlog.client import MetlogClient
from metlog.client import SEVERITY
from metlog.senders import ZmqPubSender
from mozsvc.config import Config
from mozsvc.exceptions import MethodNotFoundError
from mozsvc.metrics import IMetlogHelper
from mozsvc.metrics import MetlogHelperPlugin

from mozsvc.metrics import apache_log

from mozsvc.metrics import clear_tlocal
from mozsvc.metrics import get_tlocal
from mozsvc.metrics import has_tlocal

from metlog.decorators import incr_count
from metlog.decorators import timeit

from metlog.decorators.base import CLIENT_WRAPPER

from mozsvc.metrics import set_tlocal
from mozsvc.metrics import thread_context
from mozsvc.metrics import MetricsService
from mozsvc.plugin import load_and_register
from pyramid.config import Configurator
from textwrap import dedent
from webob.request import Request
from zope.interface.verify import verifyObject
import exceptions
import unittest
import json


class TestMetrics(unittest.TestCase):

    def test_loading_from_config(self):
        config = Config(StringIO(dedent("""
        [test1]
        enabled=true
        backend = mozsvc.metrics.MetlogHelperPlugin
        sender_class=metlog.senders.ZmqPubSender
        sender_bindstrs=tcp://localhost:5585
                        tcp://localhost:5586

        [test2]
        dontusethis =  seriously
        """)))
        settings = {"config": config}
        config = Configurator(settings=settings)
        plugin = load_and_register("test1", config)
        config.commit()
        self.failUnless(verifyObject(IMetlogHelper, plugin))
        self.failUnless(isinstance(plugin, MetlogHelperPlugin))
        self.failUnless(isinstance(plugin._client, MetlogClient))
        self.failUnless(isinstance(plugin._client.sender, ZmqPubSender))

        client = plugin._client
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
        backend = mozsvc.metrics.MetlogHelperPlugin
        sender_class=metlog.senders.DebugCaptureSender
        """)))
        settings = {"config": config}
        config = Configurator(settings=settings)
        self.plugin = load_and_register("test1", config)
        config.commit()

    def test_loading_from_config(self):

        plugin = self.plugin

        assert len(plugin._client.sender.msgs) == 0

        @timeit
        def target_callable(x, y):
            return x + y

        result = target_callable(5, 6)
        assert result == 11
        assert len(plugin._client.sender.msgs) == 1

        obj = json.loads(plugin._client.sender.msgs[0])

        expected = 'mozsvc.tests.test_metrics:target_callable'
        actual = obj['fields']['name']
        assert actual == expected

        # Now test to make sure we can enque 2 messages using stacked
        # decorators
        plugin._client.sender.msgs.clear()
        assert len(plugin._client.sender.msgs) == 0

        @incr_count
        @timeit
        def new_target_callable(x, y):
            return x + y

        result = new_target_callable(5, 6)
        msgs = [json.loads(m) for m in plugin._client.sender.msgs]
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
        backend = mozsvc.metrics.MetlogHelperPlugin
        sender_class=metlog.senders.DebugCaptureSender
        """)))
        settings = {"config": config}
        config = Configurator(settings=settings)
        self.plugin = load_and_register("test1", config)
        config.commit()

    def test_decorator_ordering(self):
        '''
        decorator ordering may matter when Ops goes to look at the
        logs. Make sure we capture stuff in the right order
        '''
        plugin = self.plugin

        plugin._client.sender.msgs.clear()
        assert len(plugin._client.sender.msgs) == 0

        @incr_count
        @timeit
        def ordering_1(x, y):
            return x + y

        ordering_1(5, 6)
        msgs = [json.loads(m) for m in plugin._client.sender.msgs]
        assert len(msgs) == 2

        for msg in msgs:
            expected = 'mozsvc.tests.test_metrics:ordering_1'
            actual = msg['fields']['name']
            assert actual == expected

        # First msg should be counter, then timer as decorators are
        # applied inside to out, but execution is outside -> in
        assert msgs[0]['type'] == 'timer'
        assert msgs[1]['type'] == 'counter'

        plugin._client.sender.msgs.clear()
        assert len(plugin._client.sender.msgs) == 0

        @timeit
        @incr_count
        def ordering_2(x, y):
            return x + y

        ordering_2(5, 6)
        msgs = [json.loads(m) for m in plugin._client.sender.msgs]
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
        plugin._client.sender.msgs.clear()
        msgs = plugin._client.sender.msgs
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
        msg = json.loads(plugin._client.sender.msgs[0])
        assert 'foo' in msg['fields']['threadlocal']
        assert msg['fields']['threadlocal']['foo'] == 'bar'

    def test_metrics_service(self):
        '''
        Test the MetricsService class
        '''
        user_info = MetricsService(name='users', path='/{username}/info',
                            description='some_svc')

        @user_info.get()
        def get_info(request):
            return 'foo'

        req = Request({'PATH_INFO': '/foo/info',
                       'SERVER_NAME': 'somehost.com',
                       'SERVER_PORT': 80,
                       })
        get_info(req)

        plugin = self.plugin
        msgs = [json.loads(m) for m in plugin._client.sender.msgs]
        assert len(msgs) == 3
        assert 'counter' in [m['type'] for m in msgs]
        assert 'timer' in [m['type'] for m in msgs]
        assert 'wsgi' in [m['type'] for m in msgs]


class TestDisabledMetrics(unittest.TestCase):
    def setUp(self):
        config = Config(StringIO(dedent("""
        [test1]
        enabled=false
        backend = mozsvc.metrics.MetlogHelperPlugin
        """)))
        settings = {"config": config}
        config = Configurator(settings=settings)
        self.plugin = load_and_register("test1", config)
        config.commit()

    def test_verify_disabled(self):
        assert self.plugin._client == None





class TestThreadLocal(unittest.TestCase):
    def setUp(self):
        if has_tlocal():
            clear_tlocal()

    def test_set_tlocal(self):
        assert not has_tlocal()
        set_tlocal({'foo': 432432})
        value = get_tlocal()
        assert value['foo'] == 432432

    def test_threadlocal(self):
        assert not has_tlocal()
        tmp = get_tlocal()
        assert tmp == {}
        tmp['foo'] = 42

        callback_invoked = {'result': False}

        def cb(data):
            assert len(tmp_2) == 2
            assert tmp_2['bar'] == 43
            callback_invoked['result'] = True

        with thread_context(cb) as tmp_2:
            assert len(tmp_2) == 1
            assert tmp_2['foo'] == 42
            tmp_2['bar'] = 43

        assert callback_invoked['result']

        # The thead context should have cleaned up the
        assert not has_tlocal()

    def test_new_context(self):
        """
        Check that a thread_context context manager will automaticaly
        create the dictionary storage for thread local data
        """
        context_worked = {'result': False}

        def callback(data):
            assert data['foo'] == 'bar'
            context_worked['result'] = True

        with thread_context(callback) as data:
            assert len(data) == 0
            data['foo'] = 'bar'

        assert context_worked['result']
        assert not has_tlocal()
