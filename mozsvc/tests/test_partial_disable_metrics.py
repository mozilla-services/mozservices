from StringIO import StringIO
from mozsvc.config import Config
from mozsvc.metrics import timeit, incr_count
from mozsvc.metrics import MetricsDecorator, rebind_dispatcher, HELPER
from mozsvc.plugin import load_and_register
from pyramid.config import Configurator
from textwrap import dedent
import unittest


# This testcase is not obvious at all and is pretty subtle
# The 'enabled' setting of a decorator should be considered a SetOnce
# flag.  You cannot change the setting after the first invocation of
# a decorated method.  This is because the decorator rewrites the
# __call__ method depending on the enable state.  If the enabled state is
# changed, the class cannot be rewritten.
# 
# The only way to test that we can disable timers then is to write a
# decorator that is used *only* by this one test case so that we know
# that nobody else has modified the executable state

class tunable_timeit(MetricsDecorator):
    '''
    Decorate any callable for metrics timing.

    You must write you decorator in 'class'-style or else you won't be
    able to have your decorator disabled.
    '''
    def __init__(self, fn):
        MetricsDecorator.__init__(self, fn)

    @rebind_dispatcher('metlog_call', decorator_name='tunable_timeit')
    def __call__(self, *args, **kwargs):
        return self._invoke(*args, **kwargs)

    def metlog_call(self, *args, **kwargs):
        with HELPER.timer(self._method_name):
            return self._invoke(*args, **kwargs)

class TestDisabledTimers(unittest.TestCase):
    """
    We want the counter decorators to fire, but the timer decorators
    should not
    """
    def setUp(self):
        config = Config(StringIO(dedent("""
        [test1]
        enabled=true
        backend = mozsvc.metrics.MetlogHelperPlugin
        sender_backend=metlog.senders.DebugCaptureSender
        disable_tunable_timeit=true
        """)))
        settings = {"config": config}
        config = Configurator(settings=settings)
        self.plugin = load_and_register("test1", config)
        config.commit()

    def test_only_some_decorators(self):
        '''
        decorator ordering may matter when Ops goes to look at the
        logs. Make sure we capture stuff in the right order
        '''
        plugin = self.plugin

        plugin._client.sender.msgs.clear()
        assert len(plugin._client.sender.msgs) == 0

        @incr_count
        @tunable_timeit
        def no_timer(x, y):
            return x + y

        no_timer(5, 6)
        msgs = plugin._client.sender.msgs
        assert len(msgs) == 1

        for msg in msgs:
            expected = 'mozsvc.tests.test_partial_disable_metrics:no_timer'
            actual = msg['fields']['name']
            assert actual == expected

        # First msg should be counter, then timer as decorators are
        # applied inside to out, but execution is outside -> in
        assert msgs[0]['type'] == 'counter'

        plugin._client.sender.msgs.clear()
